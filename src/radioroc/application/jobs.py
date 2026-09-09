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
    dac: int | None = None
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
