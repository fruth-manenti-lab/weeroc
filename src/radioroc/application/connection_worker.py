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

from radioroc.transport.config import RadiorocConnectionConfig
from radioroc.transport.discovery import BoardPort, list_board_ports
from radioroc.transport.serial import RadiorocSerial

from .jobs import JobBusyError


@dataclass(frozen=True)
class ConnectionSnapshot:
    state: str
    ports: tuple[BoardPort, ...]
    port: str | None
    status_word: int | None
    error: str | None
    close_error: str | None


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
        self._session = None  # Owned and touched only by _run.
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
                                      self._status_word, self._error, self._close_error)

    def refresh(self):
        self._submit("refresh", None, "discovering", {"idle", "error"})

    def connect(self, config: RadiorocConnectionConfig):
        config = deepcopy(config)
        config.validate()
        self._submit("connect", config, "connecting", {"idle", "error"})

    def read_status(self):
        self._submit("read_status", None, "reading", {"connected"})

    def disconnect(self):
        self._submit("disconnect", None, "disconnecting", {"connected", "close_failed"})

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
            self._commands.put(("shutdown", None))

    def _submit(self, command, argument, busy_state, allowed_states):
        with self._lock:
            if not self._started:
                raise RuntimeError("connection worker has not been started")
            if (self._shutdown_queued or self._pending
                    or self._state not in allowed_states):
                raise JobBusyError(f"cannot {command} while connection is {self._state}")
            was_close_failed = self._state == "close_failed"
            self._pending = True
            # Publish before enqueueing so a UI cannot submit a second operation
            # during the interval before the worker wakes up.
            self._state = busy_state
            # A successful retry must leave an earlier failure reviewable until
            # the user starts a new connect/refresh operation.
            if not (command == "disconnect" and was_close_failed):
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
            return None
        try:
            session.close()
        except Exception as exc:
            return self._describe(exc)
        with self._lock:
            self._session = None
        return None

    def _run(self):
        while True:
            command, argument = self._commands.get()
            if command == "refresh":
                self._refresh()
            elif command == "connect":
                self._connect(argument)
            elif command == "read_status":
                self._read_status()
            elif command == "disconnect":
                self._disconnect(stop=False)
            elif command == "shutdown":
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
        self._publish("connected")

    def _read_status(self):
        try:
            status_word = int(self._session.read_word(100), 2)
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

    def _disconnect(self, *, stop: bool) -> bool:
        close_error = self._close_session()
        if close_error:
            with self._lock:
                primary_error = self._error
            self._publish("close_failed", error=primary_error, close_error=close_error)
            return False
        with self._lock:
            self._port = None
            self._status_word = None
        if not stop:
            with self._lock:
                error, close_error = self._error, self._close_error
            self._publish("idle", error=error, close_error=close_error)
        return True
