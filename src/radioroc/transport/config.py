"""Connection defaults preserved during the transport extraction."""

from dataclasses import dataclass
import math

from radioroc.protocol.frames import validate_integer

DEFAULT_PORT = "/dev/cu.usbserial-RD3_320"
DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_SECONDS = 0.5


@dataclass
class RadiorocConnectionConfig:
    """Connection settings for a RADIOROC 2 USB serial session.

    **Attributes**
    - `port` (`str`): Explicit serial device path, for example
      `"/dev/cu.usbserial-RD3_320"`.
    - `baud` (`int`): Serial baud rate. The tested board uses `115200`.
    - `timeout_s` (`float`): Read and write timeout in seconds.
    """

    port: str = DEFAULT_PORT
    baud: int = DEFAULT_BAUD
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS

    def validate(self) -> None:
        """Validate settings without constructing or discovering a transport."""
        if not isinstance(self.port, str) or not self.port.strip():
            raise ValueError("port must be a nonempty device path")
        validate_integer(self.baud, 1, 100_000_000, "baud")
        if (isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float))
                or not math.isfinite(self.timeout_s) or self.timeout_s <= 0):
            raise ValueError("timeout must be finite and greater than zero")

