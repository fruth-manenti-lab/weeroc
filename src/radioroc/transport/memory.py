"""Deterministic memory backend; not a timing or FIFO simulator."""

class RadiorocMemoryTransport:
    """In-memory FPGA word transport for non-hardware tests.

    This class implements the small transport surface used by `RadiorocDevice`.
    It is not a serial emulator for timing-sensitive scan behavior, but it is
    sufficient for unit tests that need deterministic FPGA word reads/writes.

    **Attributes**
    - `words` (`dict[int, str]`): FPGA word storage by address.
    - `payloads` (`dict[int, bytes]`): Multi-byte payload storage by address.
    """

    def __init__(self, words: dict[int, str] | None = None, payloads: dict[int, bytes] | None = None):
        """Create a memory-backed transport.

        **Inputs**
        - `words` (`dict[int, str] | None`): Initial FPGA word values.
        - `payloads` (`dict[int, bytes] | None`): Initial multi-byte payloads.

        **Returns**
        - `None`
        """

        self.words: dict[int, str] = dict(words or {})
        self.payloads: dict[int, bytes] = dict(payloads or {})

    def read_word(self, address: int) -> str:
        """Read one memory-backed FPGA word.

        **Inputs**
        - `address` (`int`): FPGA word address.

        **Returns**
        - `str`: Eight-bit binary word.
        """

        return self.words.get(address, "00000000")

    def write_word(self, address: int, word_bits: str) -> None:
        """Write one memory-backed FPGA word.

        **Inputs**
        - `address` (`int`): FPGA word address.
        - `word_bits` (`str`): Eight-bit binary word.

        **Returns**
        - `None`
        """

        self.words[address] = word_bits

    def read_words(self, address: int, length: int) -> bytes:
        """Read bytes from memory-backed payload storage.

        **Inputs**
        - `address` (`int`): Payload address.
        - `length` (`int`): Number of bytes requested.

        **Returns**
        - `bytes`: Stored bytes padded with zeros as needed.
        """

        payload: bytes = self.payloads.get(address, b"")
        return payload[:length].ljust(length, b"\x00")

    def write_words(self, address: int, payload: bytes) -> None:
        """Write bytes to memory-backed payload storage.

        **Inputs**
        - `address` (`int`): Payload address.
        - `payload` (`bytes`): Bytes to store.

        **Returns**
        - `None`
        """

        self.payloads[address] = payload


