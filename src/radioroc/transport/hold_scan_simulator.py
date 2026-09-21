"""Deterministic offline transport for the shared hold-scan workflow.

The simulator implements the FPGA word, I2C FIFO, and ADC-batch surface used by
``RadiorocDevice.configure_adc_internal_hold``/``configure_adc_external_hold``/
``acquire_adc_batch``. It deliberately does not emulate serial timing.

Unlike ``ThresholdSimulationTransport`` (which models real, physics-validated
trigger-rate logistic behavior measured on the bench), the ADC response curve
generated here is a **synthetic shape built only to exercise the GUI's live
plot**. It is not derived from, or validated against, any physical
track-and-hold measurement. It produces a qualitatively similar single-peak
shape to a real captured RADIOROC hold scan -- a flat baseline, a rising edge,
a plateau near the peak, and a falling edge, centered somewhere within the
configured ``hold_min``..``hold_max`` range -- and nothing more should be read
into its exact numbers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import TYPE_CHECKING

from radioroc_client import N_CHANNELS
from radioroc.protocol import bits

from .memory import RadiorocMemoryTransport

if TYPE_CHECKING:
    from radioroc.application.hold_scan import HoldScanJobConfig


_FPGA_STATUS_WORD = 4
_FIFO_WRITE_ADDRESS = 56
_FIFO_READ_ADDRESS = 55
_I2C_CONTROL_ADDRESS = 60
_NB_ACQ_ADDRESS = 21
_COUNT_HIGH_ADDRESS = 29
_COUNT_LOW_ADDRESS = 28
_ADC_FRAME_ADDRESS = 20
_INTERNAL_HOLD_CODE_REGISTER = (65, 8)


def _sigmoid(z: float) -> float:
    # Stable logistic evaluation for arbitrarily valid finite inputs.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True)
class HoldSimulationConfig:
    """Parameters for the synthetic, qualitative track-and-hold response.

    ``peak_center`` is the hold code/delay (in the scan's own units) at the
    middle of the plateau; ``None`` centers it at the midpoint of the
    configured ``hold_min``..``hold_max`` range. The rising edge is centered
    ``plateau_half_width`` units before that midpoint and the falling edge
    the same distance after it, so the response is at its plateau in between;
    ``None`` derives a small default from the configured hold range.
    ``rise_width``/``fall_width`` control the transition widths of each edge,
    in the same units. ``low_gain_ratio`` scales the high-gain baseline/peak
    to produce a distinguishable low-gain curve. ``channel_spacing`` shifts
    each successive configured channel's center for visual variety only.
    """

    baseline_counts: float = 125.0
    peak_counts: float = 800.0
    peak_center: float | None = None
    plateau_half_width: float | None = None
    rise_width: float = 15.0
    fall_width: float = 20.0
    low_gain_ratio: float = 0.15
    channel_spacing: float = 0.0

    def validate(self) -> None:
        """Reject non-finite parameters and physically invalid model scales."""

        for name in ("baseline_counts", "peak_counts", "rise_width", "fall_width",
                     "low_gain_ratio", "channel_spacing"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in ("peak_center", "plateau_half_width"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite or None")
        if self.rise_width <= 0:
            raise ValueError("rise_width must be positive")
        if self.fall_width <= 0:
            raise ValueError("fall_width must be positive")
        if self.plateau_half_width is not None and self.plateau_half_width < 0:
            raise ValueError("plateau_half_width must be non-negative")
        if self.baseline_counts < 0:
            raise ValueError("baseline_counts must be non-negative")
        if self.peak_counts < 0:
            raise ValueError("peak_counts must be non-negative")
        if self.low_gain_ratio < 0:
            raise ValueError("low_gain_ratio must be non-negative")

    def as_dict(self) -> dict[str, float | None]:
        """Return JSON-friendly model parameters."""

        self.validate()
        return asdict(self)


class HoldSimulationTransport(RadiorocMemoryTransport):
    """Memory transport which serves a synthetic hold-scan ADC response."""

    def __init__(self, operation: "HoldScanJobConfig", simulation: HoldSimulationConfig, *,
                 asic: dict[tuple[int, int], int] | None = None):
        simulation.validate()
        self.operation = operation
        self.simulation = simulation
        self.simulation_metadata = {
            "model": "synthetic-track-and-hold-v1",
            "warning": "qualitative GUI-exercise shape, not a physics-validated ASIC model",
            **simulation.as_dict(),
        }
        scan = operation.scan
        span = scan.hold_max - scan.hold_min
        self._center = (simulation.peak_center if simulation.peak_center is not None
                        else (scan.hold_min + scan.hold_max) / 2.0)
        self._plateau_half_width = (simulation.plateau_half_width
                                    if simulation.plateau_half_width is not None
                                    else max(0.0, span * 0.05))
        super().__init__({0: bits(0), 1: bits(0), 4: bits(5), 100: bits(5)})
        self.asic: dict[tuple[int, int], int] = dict(asic or {})
        self._pending_fifo = bytearray()
        self._fifo_replies = bytearray()
        self._nb_acq = 1
        self.closed = False

    def __enter__(self) -> "HoldSimulationTransport":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        """Mark this synthetic session closed; no external resource exists."""

        self.closed = True

    def write_word(self, address: int, word_bits: str) -> None:
        super().write_word(address, word_bits)
        if address == _NB_ACQ_ADDRESS:
            self._nb_acq = int(word_bits, 2)
        elif address == _I2C_CONTROL_ADDRESS and word_bits == bits(2):
            self._execute_fifo()

    def read_word(self, address: int) -> str:
        # RadiorocDevice polls FPGA word 4 for both the I2C-FIFO-ready bit
        # (index 7) and the ADC-acquisition-ready bit (index 5). The
        # synthetic session always reports ready immediately.
        if address == _FPGA_STATUS_WORD:
            return bits(5)
        if address == _COUNT_HIGH_ADDRESS:
            return bits(self._nb_acq)
        if address == _COUNT_LOW_ADDRESS:
            return bits(0)
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
        if address == _ADC_FRAME_ADDRESS:
            return self._acquisition_payload(length)
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

    def _current_x(self) -> float:
        if self.operation.scan.mode == "internal":
            return float(self.asic.get(_INTERNAL_HOLD_CODE_REGISTER, 0))
        word26 = self.words.get(26, "00000000")
        word30 = self.words.get(30, "00000000")
        ext_hold_code = int(word30[:4] + word26, 2)
        return float(ext_hold_code * 5)

    def _shape_fraction(self, x: float, channel_index: int) -> float:
        center = self._center + channel_index * self.simulation.channel_spacing
        rise_center = center - self._plateau_half_width
        fall_center = center + self._plateau_half_width
        rising = _sigmoid((x - rise_center) / self.simulation.rise_width)
        falling = 1.0 - _sigmoid((x - fall_center) / self.simulation.fall_width)
        return rising * falling

    def _acquisition_payload(self, length: int) -> bytes:
        total_nb_acq = length // (N_CHANNELS * 4)
        x = self._current_x()
        payload = bytearray()
        for _acquisition in range(total_nb_acq):
            for channel in range(N_CHANNELS):
                fraction = self._shape_fraction(x, channel)
                high_gain = self.simulation.baseline_counts + \
                    (self.simulation.peak_counts - self.simulation.baseline_counts) * fraction
                low_baseline = self.simulation.baseline_counts * self.simulation.low_gain_ratio
                low_peak = self.simulation.peak_counts * self.simulation.low_gain_ratio
                low_gain = low_baseline + (low_peak - low_baseline) * fraction
                low_raw = max(0, min(65535, round(low_gain * 4)))
                high_raw = max(0, min(65535, round(high_gain * 4)))
                payload += low_raw.to_bytes(2, "big")
                payload += high_raw.to_bytes(2, "big")
        return bytes(payload[:length].ljust(length, b"\x00"))


def create_hold_simulator(operation: "HoldScanJobConfig",
                          simulation: HoldSimulationConfig | None = None) -> HoldSimulationTransport:
    """Create a context-manager transport for one validated hold-scan operation.

    Initial ASIC values are seeded from the operation's effective table so the
    workflow's real snapshot and restoration commands have meaningful state to
    preserve.
    """

    operation.validate()
    operation = deepcopy(operation)
    model = simulation or HoldSimulationConfig()
    model.validate()
    rows = operation.load_rows()
    initial_asic = {(row.add, row.subadd): int(row.data, 2) for row in rows}
    return HoldSimulationTransport(operation, model, asic=initial_asic)
