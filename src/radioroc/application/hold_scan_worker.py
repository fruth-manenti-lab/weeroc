"""Owned hold-scan session with a coalesced, bounded display mailbox.

No Qt dependency: a GUI timer polls snapshots on its own thread. The job writes
every sample to disk; at most 1024 completed hold points are retained for
display. This mirrors ``radioroc.application.threshold_worker.ThresholdWorker``
exactly; see that module for the design rationale.
"""

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock, Thread

from radioroc_client import HoldScanResult, RadiorocDevice
from .hold_scan import HoldScanJob, HoldScanJobConfig
from .jobs import CancellationToken, JobBusyError, JobEvent
from radioroc.transport.hold_scan_simulator import (
    HoldSimulationConfig, create_hold_simulator,
)


@dataclass(frozen=True)
class WorkerOutcome:
    result: HoldScanResult | None
    error: str | None = None
    close_error: str | None = None


@dataclass(frozen=True)
class WorkerSnapshot:
    event: JobEvent | None
    rows: tuple[tuple[tuple[str, object], ...], ...]
    coalesced_events: int
    outcome: WorkerOutcome | None


class HoldScanWorker:
    """One-shot worker. The worker thread creates and releases its session.

    session_factory is an offline fault-injection seam, called with the validated
    operation and simulation settings. Hardware execution is deliberately absent
    from this simulation delivery.
    """

    def __init__(self, operation: HoldScanJobConfig,
                 simulation: HoldSimulationConfig | None = None, *,
                 session_factory=create_hold_simulator):
        self.operation = deepcopy(operation)
        self.simulation = simulation or HoldSimulationConfig()
        HoldScanJob.preview(self.operation)
        self.simulation.validate()
        self._factory = session_factory
        self._token = CancellationToken()
        self._lock = Lock()
        self._event = None
        self._rows = []
        self._unread = False
        self._coalesced = 0
        self._outcome = None
        self._thread = Thread(target=self._run, name="radioroc-holdscan", daemon=False)
        self._started = False

    @property
    def is_alive(self):
        return self._thread.is_alive()

    def start(self):
        if self._started:
            raise JobBusyError("this worker has already been started")
        self._started = True
        self._thread.start()

    def cancel(self):
        self._token.cancel()

    def join(self, timeout=None):
        if self._started:
            self._thread.join(timeout)

    def snapshot(self):
        with self._lock:
            self._unread = False
            return WorkerSnapshot(self._event, tuple(self._rows), self._coalesced, self._outcome)

    def _publish(self, event):
        with self._lock:
            if self._unread:
                self._coalesced += 1
            self._event = event
            self._unread = True
            if event.kind == "point":
                if len(self._rows) >= 1024:
                    raise RuntimeError("hold scan display exceeds the 1024-point hold range")
                self._rows.append(event.values)

    def _run(self):
        result = None
        error = close_error = None
        session = None
        entered = False
        try:
            session = self._factory(self.operation, self.simulation)
            transport = session.__enter__()
            entered = True
            result = HoldScanJob().run(RadiorocDevice(transport), self.operation,
                                       cancellation=self._token, on_event=self._publish)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if entered:
                try:
                    session.__exit__(None, None, None)
                except Exception as exc:
                    close_error = f"{type(exc).__name__}: {exc}"
            # Terminal delivery follows session cleanup, never just the final job event.
            with self._lock:
                self._outcome = WorkerOutcome(result, error, close_error)
