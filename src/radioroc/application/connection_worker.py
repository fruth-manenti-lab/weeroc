"""Persistent, UI-polled ownership of one desktop hardware session.

The worker has no GUI dependency.  Callers submit one operation and poll its
immutable snapshot; serial discovery and every session operation stay on the
worker thread.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread

from radioroc_client import RadiorocDevice
from radioroc.transport.config import RadiorocConnectionConfig
from radioroc.transport.discovery import BoardPort, list_board_ports
from radioroc.transport.serial import RadiorocSerial

from .channel_config import ChannelConfigOperation, apply_channel_config
from .hold_scan import HoldScanJob, HoldScanJobConfig
from .jobs import CancellationToken, JobBusyError, JobCancelled
from .threshold import ThresholdJob, ThresholdJobConfig
from .threshold_worker import WorkerOutcome, WorkerSnapshot


@dataclass(frozen=True)
class ConnectionSnapshot:
    state: str
    ports: tuple[BoardPort, ...]
    port: str | None
    status_word: int | None
    error: str | None
    close_error: str | None
    fault: str | None = None


class ConnectionWorker:
    """A persistent command worker for discovery and one selected session."""

    def __init__(self, *, discovery=list_board_ports,
                 session_factory=RadiorocSerial.from_config):
        self._discovery = discovery
        self._factory = session_factory
        self._commands: Queue[tuple[str, object | None]] = Queue(maxsize=2)
        self._lock = Lock()
        self._state = "idle"
        self._ports: tuple[BoardPort, ...] = ()
        self._port: str | None = None
        self._status_word: int | None = None
        self._error: str | None = None
        self._close_error: str | None = None
        self._fault: str | None = None
        self._session = None  # Owned and touched only by _run.
        self._device = None  # Constructed and touched only by _run.
        self._threshold_token: CancellationToken | None = None
        self._threshold_event = None
        self._threshold_rows = []
        self._threshold_unread = False
        self._threshold_coalesced = 0
        self._threshold_outcome = None
        self._hold_token: CancellationToken | None = None
        self._hold_event = None
        self._hold_rows = []
        self._hold_unread = False
        self._hold_coalesced = 0
        self._hold_outcome = None
        self._channel_config_outcome = None
        self._hold_shutdown_for_job_fault = False
        self._pending = False
        self._shutdown_queued = False
        self._started = False
        self._thread = Thread(target=self._run, name="radioroc-connection", daemon=False)

    @property
    def is_alive(self):
        return self._thread.is_alive()

    def start(self):
        with self._lock:
            if self._started:
                raise JobBusyError("this connection worker has already been started")
            self._started = True
        self._thread.start()

    def join(self, timeout=None):
        if self._started:
            self._thread.join(timeout)

    def snapshot(self):
        with self._lock:
            return ConnectionSnapshot(self._state, self._ports, self._port,
                                      self._status_word, self._error, self._close_error,
                                      self._fault)

    def threshold_snapshot(self):
        with self._lock:
            self._threshold_unread = False
            return deepcopy(WorkerSnapshot(self._threshold_event,
                                           tuple(self._threshold_rows),
                                           self._threshold_coalesced,
                                           self._threshold_outcome))

    def hold_scan_snapshot(self):
        with self._lock:
            self._hold_unread = False
            return deepcopy(WorkerSnapshot(self._hold_event,
                                           tuple(self._hold_rows),
                                           self._hold_coalesced,
                                           self._hold_outcome))

    def channel_config_snapshot(self):
        with self._lock:
            return deepcopy(self._channel_config_outcome)

    def refresh(self):
        self._submit("refresh", None, "discovering", {"idle", "error"})

    def connect(self, config: RadiorocConnectionConfig):
        config = deepcopy(config)
        config.validate()
        self._submit("connect", config, "connecting", {"idle", "error"})

    def read_status(self):
        self._submit("read_status", None, "reading", {"connected"})

    def apply_channel_config(self, operation: ChannelConfigOperation):
        """Apply one input DAC / TQ mask configuration on the owned session."""
        operation.validate()
        self._submit("apply_channel_config", operation, "configuring", {"connected"})

    def disconnect(self):
        self._submit("disconnect", None, "disconnecting",
                     {"connected", "faulted", "close_failed"})

    def run_threshold(self, operation: ThresholdJobConfig):
        """Run one verified threshold job on the persistent owned session."""
        operation = deepcopy(operation)
        ThresholdJob.preview(operation)
        with self._lock:
            if not self._started:
                raise RuntimeError("connection worker has not been started")
            if (self._shutdown_queued or self._pending or self._state != "connected"
                    or self._fault is not None or self._device is None):
                raise JobBusyError(f"cannot run_threshold while connection is {self._state}")
            self._pending = True
            self._state = "scanning"
            self._error = None
            self._close_error = None
            self._threshold_token = CancellationToken()
            self._threshold_event = None
            self._threshold_rows = []
            self._threshold_unread = False
            self._threshold_coalesced = 0
            self._threshold_outcome = None
            self._commands.put(("run_threshold", operation))

    def cancel_threshold(self):
        """Request cooperative cancellation without touching the transport."""
        with self._lock:
            if self._state != "scanning" or self._threshold_token is None:
                raise JobBusyError(f"cannot cancel_threshold while connection is {self._state}")
            self._threshold_token.cancel()

    def run_hold_scan(self, operation: HoldScanJobConfig):
        """Run one verified hold-scan job on the persistent owned session."""
        operation = deepcopy(operation)
        HoldScanJob.preview(operation)
        with self._lock:
            if not self._started:
                raise RuntimeError("connection worker has not been started")
            if (self._shutdown_queued or self._pending or self._state != "connected"
                    or self._fault is not None or self._device is None):
                raise JobBusyError(f"cannot run_hold_scan while connection is {self._state}")
            self._pending = True
            self._state = "scanning"
            self._error = None
            self._close_error = None
            self._hold_token = CancellationToken()
            self._hold_event = None
            self._hold_rows = []
            self._hold_unread = False
            self._hold_coalesced = 0
            self._hold_outcome = None
            self._commands.put(("run_hold_scan", operation))

    def cancel_hold_scan(self):
        """Request cooperative cancellation without touching the transport."""
        with self._lock:
            if self._state != "scanning" or self._hold_token is None:
                raise JobBusyError(f"cannot cancel_hold_scan while connection is {self._state}")
            self._hold_token.cancel()

    def review_fault(self):
        """Clear a visible fault after the session has been released."""
        with self._lock:
            if (not self._started or self._pending or self._shutdown_queued
                    or self._session is not None or self._state not in {"idle", "error"}):
                raise JobBusyError(f"cannot review_fault while connection is {self._state}")
            if self._fault is None:
                raise JobBusyError("there is no connection fault to review")
            self._fault = None

    def shutdown(self):
        """Request session release then stop; a failed close remains retryable."""
        with self._lock:
            if not self._started:
                raise RuntimeError("connection worker has not been started")
            if self._state == "stopped":
                raise JobBusyError("connection worker has stopped")
            if self._shutdown_queued:
                raise JobBusyError("shutdown is already pending")
            self._shutdown_queued = True
            # Shutdown is the sole command permitted behind a running operation:
            # it lets a window close while connect is still in progress.
            if not self._pending:
                self._state = "disconnecting"
            if self._threshold_token is not None:
                self._threshold_token.cancel()
            if self._hold_token is not None:
                self._hold_token.cancel()
            self._commands.put(("shutdown", None))

    def _submit(self, command, argument, busy_state, allowed_states):
        with self._lock:
            if not self._started:
                raise RuntimeError("connection worker has not been started")
            if (self._shutdown_queued or self._pending
                    or self._state not in allowed_states
                    or (command in {"refresh", "connect"} and self._fault is not None)):
                raise JobBusyError(f"cannot {command} while connection is {self._state}")
            preserve_failure = (command == "disconnect"
                                and self._state in {"faulted", "close_failed"})
            self._pending = True
            # Publish before enqueueing so a UI cannot submit a second operation
            # during the interval before the worker wakes up.
            self._state = busy_state
            # A successful retry must leave an earlier failure reviewable until
            # the user starts a new connect/refresh operation.
            if not preserve_failure:
                self._error = None
                self._close_error = None
            self._commands.put((command, argument))

    def _publish(self, state, *, error=None, close_error=None):
        with self._lock:
            self._state = state
            self._error = error
            self._close_error = close_error
            self._pending = False

    @staticmethod
    def _describe(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"

    def _close_session(self) -> str | None:
        """Try one close.  Keep the object for a later retry if it fails."""
        with self._lock:
            session = self._session
        if session is None:
            return None
        # RadiorocSerial cleans up its own partially-entered session.  Calling
        # close again is harmless but obscures that the failed enter already
        # released its lease; a still-held lease remains retryable below.
        if (isinstance(session, RadiorocSerial)
                and session.ser is None and session._lease is None):
            with self._lock:
                self._session = None
                self._device = None
            return None
        try:
            session.close()
        except Exception as exc:
            error = self._describe(exc)
            self._latch_fault(error)
            return error
        with self._lock:
            self._session = None
            self._device = None
        return None

    def _latch_fault(self, message: str):
        with self._lock:
            if self._fault is None:
                self._fault = message
            elif message not in self._fault:
                self._fault = f"{self._fault}; {message}"

    def _publish_threshold(self, event):
        with self._lock:
            if self._threshold_unread:
                self._threshold_coalesced += 1
            self._threshold_event = event
            self._threshold_unread = True
            if event.kind == "point":
                if len(self._threshold_rows) < 1024:
                    self._threshold_rows.append(event.values)
                else:
                    self._threshold_coalesced += 1

    def _publish_hold(self, event):
        with self._lock:
            if self._hold_unread:
                self._hold_coalesced += 1
            self._hold_event = event
            self._hold_unread = True
            if event.kind == "point":
                if len(self._hold_rows) < 1024:
                    self._hold_rows.append(event.values)
                else:
                    self._hold_coalesced += 1

    def _run(self):
        while True:
            command, argument = self._commands.get()
            if command == "refresh":
                self._refresh()
            elif command == "connect":
                self._connect(argument)
            elif command == "read_status":
                self._read_status()
            elif command == "apply_channel_config":
                self._apply_channel_config(argument)
            elif command == "disconnect":
                self._disconnect(stop=False)
            elif command == "run_threshold":
                self._run_threshold(argument)
            elif command == "run_hold_scan":
                self._run_hold_scan(argument)
            elif command == "shutdown":
                with self._lock:
                    hold = self._hold_shutdown_for_job_fault
                    self._hold_shutdown_for_job_fault = False
                if hold:
                    with self._lock:
                        self._shutdown_queued = False
                    continue
                if self._disconnect(stop=True):
                    with self._lock:
                        error, close_error = self._error, self._close_error
                    self._publish("stopped", error=error, close_error=close_error)
                    return
                with self._lock:
                    self._shutdown_queued = False

    def _refresh(self):
        try:
            ports = tuple(self._discovery())
        except Exception as exc:
            self._publish("error", error=self._describe(exc))
            return
        with self._lock:
            self._ports = ports
        self._publish("connected" if self._session is not None else "idle")

    def _connect(self, config):
        session = None
        primary_error = None
        entered = False
        try:
            with self._lock:
                self._port = config.port
                self._status_word = None
            session = self._factory(config)
            # Retain before __enter__: it may have acquired a lease before failing.
            with self._lock:
                self._session = session
            transport = session.__enter__()
            entered = True
            status_word = int(transport.read_word(100), 2)
        except Exception as exc:
            primary_error = self._describe(exc)
            # RadiorocSerial.__enter__ cleans up itself.  If that cleanup retained
            # the lease, its close failed; do not make a hidden second attempt.
            if (not entered and isinstance(session, RadiorocSerial)
                    and session._lease is not None):
                close_error = primary_error
            else:
                close_error = self._close_session()
            if close_error:
                self._latch_fault(close_error)
            if not close_error:
                with self._lock:
                    self._port = None
                    self._status_word = None
            self._publish("close_failed" if close_error else "error",
                          error=primary_error, close_error=close_error)
            return
        with self._lock:
            self._port = config.port
            self._status_word = status_word
            self._device = RadiorocDevice(transport)
        self._publish("connected")

    @staticmethod
    def _threshold_fault(result, error):
        problems = []
        if error:
            problems.append(error)
        if result is None:
            if not problems:
                problems.append("threshold job returned no result")
            return "; ".join(problems)
        expected_cancel = (result.status == "cancelled"
                           and isinstance(result.error, JobCancelled))
        if result.error is not None and not expected_cancel:
            problems.append(f"{type(result.error).__name__}: {result.error}")
        if result.status in {"failed", "disconnected"}:
            problems.append(f"threshold status: {result.status}")
        if result.cleanup_status not in {"restored", "not_required"}:
            problems.append(f"cleanup status: {result.cleanup_status}")
        problems.extend(f"cleanup: {item}" for item in result.cleanup_errors)
        problems.extend(f"persistence: {item}" for item in result.persistence_errors)
        verification = result.verification
        if not verification:
            problems.append("restoration verification is absent")
        elif verification.get("status") != "passed":
            problems.append(
                f"restoration verification {verification.get('status', 'absent')}"
            )
        return "; ".join(problems) or None

    @staticmethod
    def _hold_fault(result, error):
        problems = []
        if error:
            problems.append(error)
        if result is None:
            if not problems:
                problems.append("hold scan job returned no result")
            return "; ".join(problems)
        expected_cancel = (result.status == "cancelled"
                           and isinstance(result.error, JobCancelled))
        if result.error is not None and not expected_cancel:
            problems.append(f"{type(result.error).__name__}: {result.error}")
        if result.status in {"failed", "disconnected"}:
            problems.append(f"hold scan status: {result.status}")
        if result.cleanup_status not in {"restored", "not_required"}:
            problems.append(f"cleanup status: {result.cleanup_status}")
        problems.extend(f"cleanup: {item}" for item in result.cleanup_errors)
        problems.extend(f"persistence: {item}" for item in result.persistence_errors)
        verification = result.verification
        if not verification:
            problems.append("restoration verification is absent")
        elif verification.get("status") != "passed":
            problems.append(
                f"restoration verification {verification.get('status', 'absent')}"
            )
        return "; ".join(problems) or None

    def _run_hold_scan(self, operation):
        result = None
        error = None
        with self._lock:
            token = self._hold_token
            device = self._device
        try:
            result = HoldScanJob().run(
                device, operation, cancellation=token,
                on_event=self._publish_hold, verify_restoration=True,
            )
        except Exception as exc:
            error = self._describe(exc)
        outcome = WorkerOutcome(result, error, None)
        fault = self._hold_fault(result, error)
        with self._lock:
            self._hold_outcome = outcome
            self._hold_token = None
            if fault:
                if self._fault is None:
                    self._fault = fault
                elif fault not in self._fault:
                    self._fault = f"{self._fault}; {fault}"
                self._state = "faulted"
                self._error = fault
                self._close_error = None
                if self._shutdown_queued:
                    self._hold_shutdown_for_job_fault = True
            else:
                self._state = "connected"
                self._error = None
                self._close_error = None
            self._pending = False

    def _run_threshold(self, operation):
        result = None
        error = None
        with self._lock:
            token = self._threshold_token
            device = self._device
        try:
            result = ThresholdJob().run(
                device, operation, cancellation=token,
                on_event=self._publish_threshold, verify_restoration=True,
            )
        except Exception as exc:
            error = self._describe(exc)
        outcome = WorkerOutcome(result, error, None)
        fault = self._threshold_fault(result, error)
        with self._lock:
            self._threshold_outcome = outcome
            self._threshold_token = None
            if fault:
                if self._fault is None:
                    self._fault = fault
                elif fault not in self._fault:
                    self._fault = f"{self._fault}; {fault}"
                self._state = "faulted"
                self._error = fault
                self._close_error = None
                if self._shutdown_queued:
                    self._hold_shutdown_for_job_fault = True
            else:
                self._state = "connected"
                self._error = None
                self._close_error = None
            self._pending = False

    def _read_status(self):
        try:
            status_word = int(self._device.read_word(100), 2)
        except Exception as exc:
            primary_error = self._describe(exc)
            close_error = self._close_session()
            if not close_error:
                with self._lock:
                    self._port = None
            with self._lock:
                self._status_word = None
            self._publish("close_failed" if close_error else "error",
                          error=primary_error, close_error=close_error)
            return
        with self._lock:
            self._status_word = status_word
        self._publish("connected")

    def _apply_channel_config(self, operation):
        try:
            result = apply_channel_config(self._device, operation)
        except Exception as exc:
            primary_error = self._describe(exc)
            close_error = self._close_session()
            if not close_error:
                with self._lock:
                    self._port = None
                    self._status_word = None
            with self._lock:
                self._channel_config_outcome = None
            self._publish("close_failed" if close_error else "error",
                          error=primary_error, close_error=close_error)
            return
        with self._lock:
            self._channel_config_outcome = result
        if result.verify_mismatches or result.restore_mismatches:
            fault = (f"channel config mismatch: verify={len(result.verify_mismatches)} "
                     f"restore={len(result.restore_mismatches)}")
            self._latch_fault(fault)
            self._publish("faulted", error=fault)
        else:
            self._publish("connected")

    def _disconnect(self, *, stop: bool) -> bool:
        close_error = self._close_session()
        if close_error:
            self._latch_fault(close_error)
            with self._lock:
                primary_error = self._error
            self._publish("close_failed", error=primary_error, close_error=close_error)
            return False
        with self._lock:
            self._port = None
            self._status_word = None
        if not stop:
            with self._lock:
                error, close_error, fault = self._error, self._close_error, self._fault
            self._publish("idle", error=error, close_error=close_error)
        return True
