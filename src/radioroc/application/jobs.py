"""Small job contracts independent of the CLI and GUI."""

from dataclasses import dataclass
from threading import Event, Lock
from weakref import WeakKeyDictionary


class JobCancelled(Exception):
    """Cooperative stop requested by a caller."""


class JobBusyError(RuntimeError):
    """A job already owns this transport session; jobs are never queued."""


class CancellationToken:
    def __init__(self):
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def checkpoint(self) -> None:
        if self._event.is_set():
            raise JobCancelled("job cancelled")


@dataclass(frozen=True)
class JobEvent:
    kind: str
    status: str
    completed_points: int
    total_points: int
    point: int | None = None
    values: tuple[tuple[str, object], ...] = ()
    message: str | None = None


_registry_guard = Lock()
_session_locks: WeakKeyDictionary = WeakKeyDictionary()


def session_lock(transport):
    """Share a non-reentrant job lock even across device wrappers of a session."""
    with _registry_guard:
        if transport not in _session_locks:
            _session_locks[transport] = Lock()
        return _session_locks[transport]


class CleanupRunner:
    """Run best-effort cleanup calls, recording failures instead of raising.

    After one call fails because the board stopped answering (timeout) the remaining calls are skipped: each would otherwise wait out
    its own full timeout, leaving the app stuck "cancelling" for minutes.
    """

    def __init__(self, errors: list, describe):
        self.errors = errors
        self.describe = describe
        self.dead = False
        self._skip_noted = False

    def __call__(self, label, call):
        if self.dead:
            if not self._skip_noted:
                self.errors.append("remaining cleanup skipped: the board is not responding")
                self._skip_noted = True
            return
        try:
            call()
        except BaseException as exc:
            self.errors.append(f"{label}: {self.describe(exc)}")
            if isinstance(exc, TimeoutError):  # TransportTimeoutError subclasses it; fast I/O errors don't count
                self.dead = True
