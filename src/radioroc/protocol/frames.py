"""RADIOROC framing, without device access or workflow knowledge.

The recovered vendor code establishes response length and delimiters only.
Response bytes 1 and 2 remain opaque until their meaning is verified against
firmware; do not reject valid data based on an assumed echo format.
"""


class FrameError(ValueError):
    """A response does not satisfy the established wire format."""


def bits(value: int, width: int = 8) -> str:
    """Format a binary value, retaining the legacy minimum-width behavior."""
    return format(value, f"0{width}b")


def parse_bits(value: str) -> int:
    """Parse a binary string, retaining the legacy helper's behavior."""
    return int(str(value).strip(), 2)


def validate_integer(value: int, minimum: int, maximum: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in range {minimum}..{maximum}")


def encode_read_request(address: int, length: int = 1) -> bytes:
    """Encode a read of 1..65536 bytes from a 7-bit FPGA address."""
    validate_integer(address, 0, 127, "address")
    validate_integer(length, 1, 65536, "length")
    size = length - 1
    return bytes([0xAA, size & 0xFF, address | 0x80, size >> 8, 0x55])


def encode_write_request(address: int, payload: bytes) -> bytes:
    """Encode 1..256 bytes written to one FPGA address (including FIFO ports)."""
    validate_integer(address, 0, 127, "address")
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("payload must be bytes-like")
    payload = bytes(payload)
    validate_integer(len(payload), 1, 256, "payload length")
    return bytes([0xAA, len(payload) - 1, address]) + payload + b"\x55"


def decode_read_response(response: bytes, length: int) -> bytes:
    """Validate established framing and return the payload, never partial data."""
    validate_integer(length, 1, 65536, "length")
    if len(response) != length + 4:
        raise FrameError(f"expected {length + 4} response bytes, received {len(response)}")
    if response[0] != 0xAA or response[-1] != 0x55:
        raise FrameError("response must start with AA and end with 55")
    return response[3:-1]
