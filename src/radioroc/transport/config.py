"""Connection defaults preserved during the transport extraction."""

from dataclasses import dataclass

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


