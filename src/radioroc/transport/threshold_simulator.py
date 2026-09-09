"""Deterministic offline transport for the shared threshold workflow.

The simulator implements the FPGA word, I2C FIFO, and counter surface used by
``RadiorocDevice``.  It deliberately does not emulate serial timing or analog
hardware.  Counter values follow a labelled logistic model so a caller can run
the real ``ThresholdJob`` without a board.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import TYPE_CHECKING

from radioroc.protocol import bits

from .memory import RadiorocMemoryTransport

if TYPE_CHECKING:
    from radioroc.application.threshold import ThresholdJobConfig


_COUNTER_ADDRESS = 96
_FIFO_WRITE_ADDRESS = 56
_FIFO_READ_ADDRESS = 55
_I2C_CONTROL_ADDRESS = 60


@dataclass(frozen=True)
class ThresholdSimulationConfig:
    """Parameters for the labelled, deterministic threshold-rate model.

    ``midpoint`` is the channel-zero DAC code at half the plateau rate.
    Each increasing channel shifts its midpoint by ``channel_spacing`` DAC
    codes.  ``width`` controls the logistic transition width in DAC codes.
    """

    midpoint: float = 500
    width: float = 30
    plateau_hz: float = 100000
    channel_spacing: float = 3

    def validate(self) -> None:
        """Reject non-finite parameters and physically invalid model scales."""

        for name in ("midpoint", "width", "plateau_hz", "channel_spacing"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.width <= 0:
            raise ValueError("width must be positive")
        if self.plateau_hz < 0:
            raise ValueError("plateau_hz must be non-negative")

    def as_dict(self) -> dict[str, float]:
        """Return JSON-friendly model parameters."""

        self.validate()
        return asdict(self)


class ThresholdSimulationTransport(RadiorocMemoryTransport):
    """Memory transport which serves deterministic threshold counter values."""

    def __init__(self, operation: "ThresholdJobConfig", simulation: ThresholdSimulationConfig, *,
                 asic: dict[tuple[int, int], int] | None = None):
        simulation.validate()
        self.operation = operation
        self.simulation = simulation
        self.simulation_metadata = {
            "model": "deterministic-logistic-v1",
            **simulation.as_dict(),
        }
        super().__init__({0: bits(0), 1: bits(0), 6: bits(0), 100: bits(5)})
        self.asic: dict[tuple[int, int], int] = dict(asic or {})
        self._pending_fifo = bytearray()
        self._fifo_replies = bytearray()
        self._selected_channel = 0
        self._threshold_kind = "t1" if operation.scan.t1 else "t2"
        self.closed = False

    def __enter__(self) -> "ThresholdSimulationTransport":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        """Mark this synthetic session closed; no external resource exists."""

        self.closed = True

    def write_word(self, address: int, word_bits: str) -> None:
        super().write_word(address, word_bits)
        if address == 6:
            self._selected_channel = int(word_bits, 2)
        elif address == _I2C_CONTROL_ADDRESS and word_bits == bits(2):
            self._execute_fifo()

    def read_word(self, address: int) -> str:
        # ``RadiorocDevice.i2c_fifo_transaction`` polls the ready bit after
        # each FIFO trigger.  The synthetic FIFO completes immediately.
        if address == 4:
            return bits(1)
        return super().read_word(address)

    def write_words(self, address: int, payload: bytes) -> None:
        if address == _FIFO_WRITE_ADDRESS:
            self._pending_fifo.extend(payload)
            return
        super().write_words(address, payload)

    def read_words(self, address: int, length: int) -> bytes:
        if address == _FIFO_READ_ADDRESS:
            response = bytes(self._fifo_replies[:length])
            del self._fifo_replies[:length]
            return response
        if address == _COUNTER_ADDRESS:
            if length != 4:
                return self._counter_count().to_bytes(4, "little")[:length]
            return self._counter_count().to_bytes(4, "little")
        return super().read_words(address, length)

    def _execute_fifo(self) -> None:
        if len(self._pending_fifo) % 4:
            raise ValueError("I2C FIFO payload must contain four-byte operations")
        for offset in range(0, len(self._pending_fifo), 4):
            chip, address, subaddress, data = self._pending_fifo[offset:offset + 4]
            key = (address, subaddress)
            if chip & 0x80:
                self._fifo_replies.append(self.asic.get(key, 0))
            else:
                self.asic[key] = data
                if key == (65, 1):
                    self._threshold_kind = "t1"
                elif key == (65, 3):
                    self._threshold_kind = "t2"
        self._pending_fifo.clear()

    def _written_dac(self) -> int:
        if self._threshold_kind == "t1":
            return ((self.asic.get((65, 2), 0) & 0x03) << 8) | self.asic.get((65, 1), 0)
        return ((self.asic.get((65, 3), 0) & 0x0F) << 6) | ((self.asic.get((65, 2), 0) >> 2) & 0x3F)

    def _counter_count(self) -> int:
        scan = self.operation.scan
        dac = self._written_dac()
        midpoint = self.simulation.midpoint + self._selected_channel * self.simulation.channel_spacing
        exponent = (dac - midpoint) / self.simulation.width
        # Stable logistic evaluation for arbitrarily valid finite inputs.
        if exponent >= 0:
            fraction = math.exp(-exponent) / (1.0 + math.exp(-exponent))
        else:
            fraction = 1.0 / (1.0 + math.exp(exponent))
        window_seconds = scan.trigger_window_ms / 1000.0
        maximum = 2**32 - 1
        rate = self.simulation.plateau_hz * fraction
        if rate >= maximum / window_seconds:
            return maximum
        return max(0, round(rate * window_seconds))


def create_threshold_simulator(operation: "ThresholdJobConfig",
                               simulation: ThresholdSimulationConfig | None = None) -> ThresholdSimulationTransport:
    """Create a context-manager transport for one validated threshold operation.

    Initial ASIC values are seeded from the operation's effective table so the
    workflow's real snapshot and restoration commands have meaningful state to
    preserve.
    """

    operation.validate()
    operation = deepcopy(operation)
    model = simulation or ThresholdSimulationConfig()
    model.validate()
    rows = operation.load_rows()
    initial_asic = {(row.add, row.subadd): int(row.data, 2) for row in rows}
    return ThresholdSimulationTransport(operation, model, asic=initial_asic)
