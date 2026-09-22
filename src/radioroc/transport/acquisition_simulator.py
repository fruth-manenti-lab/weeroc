"""Deterministic offline transport for the shared acquisition workflow.

The simulator implements the FPGA word, I2C FIFO, and ADC-batch surface used
by ``RadiorocDevice.configure_adc_external_hold``/``acquire_adc_batch``. It
deliberately does not emulate serial timing. The generic FIFO/status-word/
ADC-frame plumbing here (``write_word``/``read_word``/``write_words``/
``read_words``/``_execute_fifo``) duplicates the equivalent surface in
``HoldSimulationTransport`` (``hold_scan_simulator.py``) rather than sharing
it, so that file is never touched by this one.

Unlike ``HoldSimulationTransport`` (which sweeps a hold value across a curve
shape), an acquisition has **one fixed operating point**: every event's
high-gain/low-gain sample is a fixed mean plus Gaussian jitter
(``random.gauss(mean, stdev)``, clamped to ``[0, 65535/4]`` before the ``*4``
int16 pack), independent of batch number. This produces a plausible,
non-degenerate spectrum shape for tests and future GUI live-plot exercise --
it is a **synthetic shape built only to exercise offline code paths**, not
derived from, or validated against, any physical measurement, and nothing
should be read into its exact numbers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import random
from typing import TYPE_CHECKING

from radioroc_client import N_CHANNELS
from radioroc.protocol import bits

from .memory import RadiorocMemoryTransport

if TYPE_CHECKING:
    from radioroc.application.acquisition import AcquisitionJobConfig


_FPGA_STATUS_WORD = 4
_FIFO_WRITE_ADDRESS = 56
_FIFO_READ_ADDRESS = 55
_I2C_CONTROL_ADDRESS = 60
_NB_ACQ_ADDRESS = 21
_COUNT_HIGH_ADDRESS = 29
_COUNT_LOW_ADDRESS = 28
_ADC_FRAME_ADDRESS = 20
_MAX_ADC_VALUE = 65535 / 4


@dataclass(frozen=True)
class AcquisitionSimulationConfig:
    """Parameters for the synthetic, single-operating-point ADC response.

    ``hg_mean``/``hg_stdev`` and ``lg_mean``/``lg_stdev`` describe a fixed
    Gaussian high-gain/low-gain sample distribution, in the same 0.25-per-code
    vendor scale ``acquire_adc_batch`` returns. ``channel_spacing`` shifts
    each successive channel's mean for visual variety only.
    """

    hg_mean: float = 800.0
    hg_stdev: float = 40.0
    lg_mean: float = 120.0
    lg_stdev: float = 15.0
    channel_spacing: float = 0.0

    def validate(self) -> None:
        """Reject non-finite parameters and physically invalid model scales."""

        for name in ("hg_mean", "hg_stdev", "lg_mean", "lg_stdev", "channel_spacing"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.hg_stdev < 0:
            raise ValueError("hg_stdev must be non-negative")
        if self.lg_stdev < 0:
            raise ValueError("lg_stdev must be non-negative")
        if self.hg_mean < 0:
            raise ValueError("hg_mean must be non-negative")
        if self.lg_mean < 0:
            raise ValueError("lg_mean must be non-negative")

    def as_dict(self) -> dict[str, float]:
        """Return JSON-friendly model parameters."""

        self.validate()
        return asdict(self)


class AcquisitionSimulationTransport(RadiorocMemoryTransport):
    """Memory transport which serves a synthetic fixed-point ADC response."""

    def __init__(self, operation: "AcquisitionJobConfig", simulation: AcquisitionSimulationConfig, *,
                 asic: dict[tuple[int, int], int] | None = None, rng: random.Random | None = None):
        simulation.validate()
        self.operation = operation
        self.simulation = simulation
        self.simulation_metadata = {
            "model": "synthetic-fixed-point-acquisition-v1",
            "warning": "qualitative offline-exercise shape, not a physics-validated ASIC model",
            **simulation.as_dict(),
        }
        # Never rely on global random state: tests must be reproducible from
        # a caller-supplied Random instance or seed.
        self._rng = rng if rng is not None else random.Random()
        super().__init__({0: bits(0), 1: bits(0), 4: bits(5), 100: bits(5)})
        self.asic: dict[tuple[int, int], int] = dict(asic or {})
        self._pending_fifo = bytearray()
        self._fifo_replies = bytearray()
        self._nb_acq = 1
        self.closed = False

    def __enter__(self) -> "AcquisitionSimulationTransport":
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

    def _acquisition_payload(self, length: int) -> bytes:
        total_nb_acq = length // (N_CHANNELS * 4)
        payload = bytearray()
        for _acquisition in range(total_nb_acq):
            for channel in range(N_CHANNELS):
                offset = channel * self.simulation.channel_spacing
                high_gain = self._rng.gauss(self.simulation.hg_mean + offset, self.simulation.hg_stdev)
                low_gain = self._rng.gauss(self.simulation.lg_mean + offset, self.simulation.lg_stdev)
                high_gain = max(0.0, min(_MAX_ADC_VALUE, high_gain))
                low_gain = max(0.0, min(_MAX_ADC_VALUE, low_gain))
                high_raw = max(0, min(65535, round(high_gain * 4)))
                low_raw = max(0, min(65535, round(low_gain * 4)))
                payload += low_raw.to_bytes(2, "big")
                payload += high_raw.to_bytes(2, "big")
        return bytes(payload[:length].ljust(length, b"\x00"))


def create_acquisition_simulator(operation: "AcquisitionJobConfig",
                                 simulation: AcquisitionSimulationConfig | None = None,
                                 *, rng: random.Random | None = None) -> AcquisitionSimulationTransport:
    """Create a context-manager transport for one validated acquisition operation.

    Initial ASIC values are seeded from the operation's effective table so the
    workflow's real snapshot and restoration commands have meaningful state to
    preserve.
    """

    operation.validate()
    operation = deepcopy(operation)
    model = simulation or AcquisitionSimulationConfig()
    model.validate()
    rows = operation.load_rows()
    initial_asic = {(row.add, row.subadd): int(row.data, 2) for row in rows}
    return AcquisitionSimulationTransport(operation, model, asic=initial_asic, rng=rng)
