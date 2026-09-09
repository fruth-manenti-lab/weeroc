"""USB candidate discovery and logical identities; no serial ports are opened."""

from dataclasses import dataclass
import os
from serial.tools.list_ports import comports


def canonical_port(port: str) -> str:
    """Resolve symlinks and merge macOS call-in/call-out aliases."""
    if os.name == "nt":
        return port.upper().removeprefix("\\\\.\\")
    return os.path.realpath(port).replace("/dev/tty.", "/dev/cu.", 1)


@dataclass(frozen=True)
class BoardPort:
    port: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    location: str | None
    interface: str | None

    @property
    def identity(self) -> str:
        """Share one key for all interfaces with the same USB identity."""
        if self.vid is not None and self.pid is not None:
            prefix = f"usb:{self.vid:04x}:{self.pid:04x}"
            if self.serial_number:
                return f"{prefix}:serial:{self.serial_number}"
            if self.location:
                # Linux appends interface information, e.g. 1-2.3:1.0.
                return f"{prefix}:location:{self.location.split(':')[0]}"
        return f"port:{canonical_port(self.port)}"


def list_board_ports() -> list[BoardPort]:
    """List FTDI 0403:6010 candidates; this alone does not verify RADIOROC firmware."""
    return sorted((
        BoardPort(p.device, p.description, p.vid, p.pid, p.serial_number, p.location, p.interface)
        for p in comports(include_links=True) if (p.vid, p.pid) == (0x0403, 0x6010)
    ), key=lambda p: p.port)


def board_identity(port: str) -> str:
    """Use discovered board identity, falling back to the explicit canonical port."""
    target = canonical_port(port)
    for item in list_board_ports():
        if canonical_port(item.port) == target:
            return item.identity
    return f"port:{target}"
