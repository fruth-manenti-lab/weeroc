"""Nonblocking, cooperative board ownership between programs of the same user."""

from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from filelock import FileLock, Timeout

from .errors import DeviceBusyError, TransportIOError


class BoardLease:
    """Hold an OS-backed file lock; never infer availability from a stale PID.

    The default directory is independent of working directory and TMPDIR.
    Directory overrides are for isolated tests. All real clients must use the
    same directory on a local filesystem. Other users/vendor programs do not
    participate in this cooperative lock.
    """

    def __init__(self, identity: str, port: str, *, directory: Path | None = None):
        self.identity = identity
        self.port = port
        self.directory = directory if directory is not None else Path.home() / ".radioroc" / "locks"
        basename = sha256(identity.encode()).hexdigest()
        self.path = self.directory / f"{basename}.lock"
        self.owner_path = self.directory / f"{basename}.json"
        self._lock = FileLock(str(self.path), timeout=0, thread_local=False)
        self._held = False

    def acquire(self) -> None:
        if self._held:
            raise DeviceBusyError(f"session already owns {self.port}")
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._lock.acquire(timeout=0)
        except Timeout as exc:
            try:
                owner = json.loads(self.owner_path.read_text())
                detail = f"process {owner['pid']} ({owner['program']}, port {owner['port']})"
            except (OSError, ValueError, KeyError, TypeError):
                detail = "another RADIOROC session"
            raise DeviceBusyError(f"board {self.identity} is in use by {detail}") from exc
        except OSError as exc:
            raise TransportIOError(f"cannot acquire board lock {self.path}: {exc}") from exc
        self._held = True
        try:
            # Informational only. Lock ownership is decided by the OS, not JSON.
            self.owner_path.write_text(json.dumps({
                "pid": os.getpid(), "program": Path(sys.argv[0]).name,
                "port": self.port, "identity": self.identity,
            }))
        except OSError as exc:
            self.release()
            raise TransportIOError(f"cannot record board owner: {exc}") from exc

    def release(self) -> None:
        if self._held:
            # Leave lock/metadata files in place. Deleting a locked Unix file can
            # split contenders across inodes. Stale JSON is never used as a lock.
            self._lock.release()
            self._held = False

    def __enter__(self) -> "BoardLease":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
