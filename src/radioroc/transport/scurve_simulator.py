"""Deterministic offline transport for the shared S-curve workflow.

The simulator implements the FPGA word, I2C FIFO, and per-point count-pair
surface used by ``ScurveJob._run_locked``: FPGA words 1/3/6 for clock index,
trigger-level and channel select; the vendor I2C FIFO at words 55/56/60 for
ASIC register access; and a two-word read at address 8 (``device.transport.
read_words(8, 2)``) returning ``(pulse_data, fifo9)`` -- the fixed pulse count
issued per point and the number of those pulses that crossed the threshold.
This wire-protocol faking is workflow-specific and not shared with
``HoldSimulationTransport`` or ``ThresholdSimulationTransport``.

The turn-on-percentage-vs-threshold-DAC response itself, however, has a real
precedent in this codebase: it is the same physical shape as
``ThresholdSimulationTransport``'s physics-validated logistic trigger-rate
model (higher DAC code -> higher threshold -> fewer pulses cross it), so this
module reuses that logistic math rather than inventing a new curve shape. As
with the hold-scan simulator, only the wire protocol below is specific to this
workflow; the model parameters are not independently validated against a
measured RADIOROC S-curve.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import TYPE_CHECKING

from radioroc.protocol import bits

from .memory import RadiorocMemoryTransport

if TYPE_CHECKING:
    from radioroc.application.scurve import ScurveJobConfig


_FPGA_STATUS_WORD = 4
_FIFO_WRITE_ADDRESS = 56
_FIFO_READ_ADDRESS = 55
_I2C_CONTROL_ADDRESS = 60
_CHANNEL_SELECT_ADDRESS = 6
_COUNT_PAIR_ADDRESS = 8


def _sigmoid(z: float) -> float:
    # Stable logistic evaluation for arbitrarily valid finite inputs.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True)
class ScurveSimulationConfig:
    """Parameters for the labelled, deterministic S-curve turn-on model.

    ``midpoint`` is the channel-zero DAC code at half the plateau turn-on
    percentage. Each increasing configured channel shifts its midpoint by
    ``channel_spacing`` DAC codes. ``width`` controls the logistic transition
    width in DAC codes. ``pulse_count`` is the fixed per-point pulse count
    (the simulated ``pulse_data`` denominator); it is transmitted as a single
    byte, mirroring the real two-word count-pair readback, so it must fit in
    0..255.
    """

    midpoint: float = 500
    width: float = 30
    channel_spacing: float = 3
    pulse_count: int = 200

    def validate(self) -> None:
        """Reject non-finite parameters and physically invalid model scales."""

        for name in ("midpoint", "width", "channel_spacing"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.width <= 0:
            raise ValueError("width must be positive")
        if isinstance(self.pulse_count, bool) or not isinstance(self.pulse_count, int):
            raise ValueError("pulse_count must be an integer")
        if not 0 <= self.pulse_count <= 255:
            raise ValueError("pulse_count must be in range 0..255 (a single hardware byte)")

    def as_dict(self) -> dict[str, float | int]:
        """Return JSON-friendly model parameters."""

        self.validate()
        return asdict(self)


class ScurveSimulationTransport(RadiorocMemoryTransport):
    """Memory transport which serves a deterministic S-curve turn-on response."""

    def __init__(self, operation: "ScurveJobConfig", simulation: ScurveSimulationConfig, *,
                 asic: dict[tuple[int, int], int] | None = None):
        simulation.validate()
        self.operation = operation
        self.simulation = simulation
        self.simulation_metadata = {
            "model": "deterministic-logistic-v1",
            "warning": "wire protocol is faked for this workflow; the logistic shape is "
                      "borrowed from the physics-validated threshold model, not independently validated here",
            **simulation.as_dict(),
        }
        super().__init__({0: bits(0), 1: bits(0), 3: bits(0), 6: bits(0), 100: bits(5)})
        self.asic: dict[tuple[int, int], int] = dict(asic or {})
        self._pending_fifo = bytearray()
        self._fifo_replies = bytearray()
        self._selected_channel = 0
        self._t1 = operation.scan.t1
        self.closed = False

    def __enter__(self) -> "ScurveSimulationTransport":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        """Mark this synthetic session closed; no external resource exists."""

        self.closed = True

    def write_word(self, address: int, word_bits: str) -> None:
        super().write_word(address, word_bits)
        if address == _CHANNEL_SELECT_ADDRESS:
            self._selected_channel = int(word_bits, 2)
        elif address == _I2C_CONTROL_ADDRESS and word_bits == bits(2):
            self._execute_fifo()

    def read_word(self, address: int) -> str:
        # RadiorocDevice.i2c_fifo_transaction polls the FPGA I2C-FIFO-ready
        # bit (word 4, index 7) after each FIFO trigger; the synthetic
        # session always reports ready immediately.
        if address == _FPGA_STATUS_WORD:
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
        if address == _COUNT_PAIR_ADDRESS and length == 2:
            return self._count_pair()
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
        self._pending_fifo.clear()

    def _written_dac(self) -> int:
        if self._t1:
            return ((self.asic.get((65, 2), 0) & 0x03) << 8) | self.asic.get((65, 1), 0)
        return ((self.asic.get((65, 3), 0) & 0x0F) << 6) | ((self.asic.get((65, 2), 0) >> 2) & 0x3F)

    def _turn_on_fraction(self) -> float:
        dac = self._written_dac()
        midpoint = self.simulation.midpoint + self._selected_channel * self.simulation.channel_spacing
        exponent = (dac - midpoint) / self.simulation.width
        # Higher DAC (higher threshold) crosses fewer pulses, mirroring
        # ThresholdSimulationTransport's validated trigger-rate direction.
        return _sigmoid(-exponent)

    def _count_pair(self) -> bytes:
        pulse_count = self.simulation.pulse_count
        fifo9 = max(0, min(pulse_count, round(pulse_count * self._turn_on_fraction())))
        return bytes([pulse_count, fifo9])


def create_scurve_simulator(operation: "ScurveJobConfig",
                            simulation: ScurveSimulationConfig | None = None) -> ScurveSimulationTransport:
    """Create a context-manager transport for one validated S-curve operation.

    Initial ASIC values are seeded from the operation's effective table so the
    workflow's real snapshot and restoration commands have meaningful state to
    preserve.
    """

    operation.validate()
    operation = deepcopy(operation)
    model = simulation or ScurveSimulationConfig()
    model.validate()
    rows = operation.load_rows()
    initial_asic = {(row.add, row.subadd): int(row.data, 2) for row in rows}
    return ScurveSimulationTransport(operation, model, asic=initial_asic)
