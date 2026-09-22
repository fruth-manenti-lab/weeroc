"""Owned acquisition session with a coalesced, bounded display mailbox.

No Qt dependency: a GUI timer polls snapshots on its own thread. The job
writes every raw sample to disk (``events.csv``); this worker never retains
raw per-event samples in memory for display. Unlike `ThresholdWorker`
(whose "point" events are one scalar rate per DAC code, capped at the
1024-code DAC range), `AcquisitionJob`'s "point" events fire once per
**batch** and carry that whole batch's raw `ch{N}_hg`/`ch{N}_lg` sample
lists (up to `acquisitions_per_batch` values each). Retaining those lists
verbatim would duplicate an effectively unbounded amount of already-durable
CSV data in memory, so what is kept here instead is a small per-channel
count/min/max/mean summary of each batch -- see `summarize_acquisition_event`.
"""

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock, Thread

from radioroc_client import AcquisitionResult, RadiorocDevice
from .acquisition import AcquisitionJob, AcquisitionJobConfig
from .jobs import CancellationToken, JobBusyError, JobEvent
from radioroc.transport.acquisition_simulator import (
    AcquisitionSimulationConfig, create_acquisition_simulator,
)

# How many per-batch summaries are retained for display. Threshold's
# equivalent cap (1024) is the DAC axis's own fixed size, so hitting it is a
# defensive assertion (a real bug) there. `batches` has no such fixed upper
# bound -- a long acquisition run can request far more than that -- so this
# cap is a deliberately much smaller "recent history" window instead: a
# rolling buffer of the most recently completed batches' summaries, which is
# what a live progress display actually wants to show (the newest data),
# rather than a hard ceiling that would freeze the display at the first N
# batches of a long run.
MAX_RETAINED_BATCHES = 255


@dataclass(frozen=True)
class AcquisitionWorkerOutcome:
    result: AcquisitionResult | None
    error: str | None = None
    close_error: str | None = None


@dataclass(frozen=True)
class AcquisitionWorkerSnapshot:
    event: JobEvent | None
    rows: tuple[tuple[tuple[str, object], ...], ...]
    coalesced_events: int
    outcome: AcquisitionWorkerOutcome | None


def summarize_acquisition_event(event: JobEvent) -> tuple[tuple[str, object], ...]:
    """Compact per-channel count/min/max/mean summary of one batch "point" event.

    `event.values` carries the whole batch's raw `ch{N}_hg`/`ch{N}_lg`
    sample lists (see `AcquisitionJob._run_locked`'s `emit("point", ...)`);
    this reduces each list to four numbers plus the batch number, which is
    what a bounded-memory live progress display needs -- the raw samples
    themselves are already durably written to `events.csv` by the job.
    """
    summary: dict[str, object] = {"batch": event.point}
    for name, samples in event.values:
        count = len(samples)
        summary[f"{name}_count"] = count
        if count:
            summary[f"{name}_min"] = min(samples)
            summary[f"{name}_max"] = max(samples)
            summary[f"{name}_mean"] = sum(samples) / count
    return tuple(summary.items())


class AcquisitionWorker:
    """One-shot worker. The worker thread creates and releases its session.

    session_factory is an offline fault-injection seam, called with the validated
    operation and simulation settings. Hardware execution is deliberately absent
    from this simulation delivery.
    """

    def __init__(self, operation: AcquisitionJobConfig,
                 simulation: AcquisitionSimulationConfig | None = None, *,
                 session_factory=create_acquisition_simulator):
        self.operation = deepcopy(operation)
        self.simulation = simulation or AcquisitionSimulationConfig()
        AcquisitionJob.preview(self.operation)
        self.simulation.validate()
        self._factory = session_factory
        self._token = CancellationToken()
        self._lock = Lock()
        self._event = None
        self._rows = []
        self._unread = False
        self._coalesced = 0
        self._outcome = None
        self._thread = Thread(target=self._run, name="radioroc-acquisition", daemon=False)
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
            return AcquisitionWorkerSnapshot(self._event, tuple(self._rows), self._coalesced, self._outcome)

    def _publish(self, event):
        with self._lock:
            if self._unread:
                self._coalesced += 1
            self._event = event
            self._unread = True
            if event.kind == "point":
                if len(self._rows) >= MAX_RETAINED_BATCHES:
                    self._rows.pop(0)
                self._rows.append(summarize_acquisition_event(event))

    def _run(self):
        result = None
        error = close_error = None
        session = None
        entered = False
        try:
            session = self._factory(self.operation, self.simulation)
            transport = session.__enter__()
            entered = True
            result = AcquisitionJob().run(RadiorocDevice(transport), self.operation,
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
                self._outcome = AcquisitionWorkerOutcome(result, error, close_error)
