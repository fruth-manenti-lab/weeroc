"""Per-channel input DAC and TQ mask configuration, shared by CLI and GUI.

Unlike a threshold scan's temporary mask/Ctest/gain settings, these are
configuration-state writes meant to persist (like `apply_default_config`/
`initialize_fpga`) -- callers that want a bounded validation run instead of a
persistent change must pass `restore=True`.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from radioroc_client import DEFAULT_CONFIG, I2CRow, N_CHANNELS, RadiorocDevice


@dataclass(frozen=True)
class ChannelConfigOperation:
    """One channel-configuration request.

    **Attributes**
    - `tq_mask_channels` (`tuple[int, ...]`): Channels to set the TQ mask bit
      for.
    - `tq_mask_value` (`bool`): TQ mask bit to write.
    - `input_dac_enable_channels` (`tuple[int, ...]`): Channels to set the
      input DAC enable bit for.
    - `input_dac_enable_value` (`bool`): Input DAC enable bit to write.
    - `input_dac_value_channels` (`tuple[int, ...]`): Channels to set the
      input DAC raw value for.
    - `input_dac_value` (`int | None`): Raw 8-bit input DAC code, 0..255.
    - `input_dac_impedance` (`bool | None`): Set the shared impedance switch
      (all channels) to low (~150 Ohm) when true, high when false; leave
      unset when `None`.
    - `verify` (`bool`): Independently read back every touched register after
      writing.
    - `restore` (`bool`): Snapshot every touched register before writing and
      restore it afterward (bounded validation mode) instead of persisting.
    - `config_path` (`Path | None`): ASIC I2C config CSV. When `None` and the
      device already has rows loaded (for example, from an earlier job on the
      same connected session), those existing rows are kept; otherwise the
      packaged default config is loaded, mirroring
      `ThresholdJobConfig.load_rows`'s convention.
    """

    tq_mask_channels: tuple[int, ...] = ()
    tq_mask_value: bool = True
    input_dac_enable_channels: tuple[int, ...] = ()
    input_dac_enable_value: bool = True
    input_dac_value_channels: tuple[int, ...] = ()
    input_dac_value: int | None = None
    input_dac_impedance: bool | None = None
    verify: bool = True
    restore: bool = False
    config_path: Path | None = None

    def load_rows(self, existing=()) -> list[I2CRow]:
        """Load ASIC config rows, reusing already-loaded rows when possible.

        **Inputs**
        - `existing` (`Iterable[I2CRow]`): Rows already loaded on the device.

        **Returns**
        - `list[I2CRow]`: Rows to assign to `device.i2c_rows`.
        """

        if self.config_path is None and existing:
            return deepcopy(list(existing))
        with Path(self.config_path or DEFAULT_CONFIG).open(newline="") as stream:
            return [I2CRow(int(row["add"]), int(row["subadd"]), row["data"].strip())
                    for row in csv.DictReader(stream)]

    def validate(self) -> None:
        """Validate this operation before any hardware access.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        if self.input_dac_value_channels and self.input_dac_value is None:
            raise ValueError("input_dac_value_channels requires input_dac_value")
        if self.input_dac_value is not None and not 0 <= self.input_dac_value <= 255:
            raise ValueError("input_dac_value must be in range 0..255")
        for channels in (self.tq_mask_channels, self.input_dac_enable_channels,
                        self.input_dac_value_channels):
            for channel in channels:
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
        if not any([self.tq_mask_channels, self.input_dac_enable_channels,
                   self.input_dac_value_channels, self.input_dac_impedance is not None]):
            raise ValueError("at least one channel-configuration field is required")


@dataclass(frozen=True)
class RegisterMismatch:
    add: int
    subadd: int
    expected: str
    observed: str


@dataclass(frozen=True)
class ChannelConfigResult:
    """Outcome of one applied `ChannelConfigOperation`.

    **Attributes**
    - `applied` (`tuple[str, ...]`): Human-readable description of each write.
    - `touched_rows` (`int`): Distinct `(add, subadd)` registers written.
    - `verify_mismatches` (`tuple[RegisterMismatch, ...]`): Post-write
      readback mismatches, if `verify` was requested.
    - `restored` (`bool`): Whether touched registers were restored.
    - `restore_mismatches` (`tuple[RegisterMismatch, ...]`): Post-restore
      readback mismatches, if `restore` and `verify` were both requested.
    """

    applied: tuple[str, ...] = field(default_factory=tuple)
    touched_rows: int = 0
    verify_mismatches: tuple[RegisterMismatch, ...] = field(default_factory=tuple)
    restored: bool = False
    restore_mismatches: tuple[RegisterMismatch, ...] = field(default_factory=tuple)


def apply_channel_config(device: RadiorocDevice, operation: ChannelConfigOperation) -> ChannelConfigResult:
    """Apply one channel-configuration operation on an already-open device.

    **Inputs**
    - `device` (`RadiorocDevice`): Open device. ASIC config rows are loaded
      (or reused, see `ChannelConfigOperation.load_rows`) if not already
      present.
    - `operation` (`ChannelConfigOperation`): Validated configuration request.

    **Returns**
    - `ChannelConfigResult`: What was written and, if requested, verified and
      restored.

    **Hardware side effects**
    - May load the ASIC config table into `device.i2c_rows`.
    - Writes the requested channel-6/channel-0 ASIC registers, and reads them
      back when `verify` is requested.
    """

    operation.validate()
    device.i2c_rows = operation.load_rows(device.i2c_rows)
    touched: set[tuple[int, int]] = set()
    touched.update((ch, 6) for ch in operation.tq_mask_channels)
    touched.update((ch, 6) for ch in operation.input_dac_enable_channels)
    touched.update((ch, 0) for ch in operation.input_dac_value_channels)
    if operation.input_dac_impedance is not None:
        touched.update((ch, 6) for ch in range(N_CHANNELS))

    snapshot: dict[tuple[int, int], str] = {}
    if operation.restore:
        snapshot = {(add, subadd): device.read_register_bits(add, subadd) for add, subadd in touched}

    applied: list[str] = []
    for channel in operation.tq_mask_channels:
        device.set_tq_mask_for_channel(channel, enabled=operation.tq_mask_value)
        applied.append(f"tq_mask channel={channel} -> {int(operation.tq_mask_value)}")
    for channel in operation.input_dac_enable_channels:
        device.set_input_dac_enable_for_channel(channel, enabled=operation.input_dac_enable_value)
        applied.append(f"input_dac_enable channel={channel} -> {int(operation.input_dac_enable_value)}")
    for channel in operation.input_dac_value_channels:
        device.set_input_dac_value(channel, operation.input_dac_value)
        applied.append(f"input_dac_value channel={channel} -> {operation.input_dac_value}")
    if operation.input_dac_impedance is not None:
        device.set_input_dac_impedance(operation.input_dac_impedance)
        applied.append(f"input_dac_impedance -> {'low' if operation.input_dac_impedance else 'high'}")

    verify_mismatches: list[RegisterMismatch] = []
    if operation.verify:
        for add, subadd in sorted(touched):
            expected = device.find_i2c_row(add, subadd).data
            observed = device.read_register_bits(add, subadd)
            if observed != expected:
                verify_mismatches.append(RegisterMismatch(add, subadd, expected, observed))

    restore_mismatches: list[RegisterMismatch] = []
    if operation.restore:
        for (add, subadd), data in snapshot.items():
            device.write_register(add, subadd, data)
        if operation.verify:
            for (add, subadd), data in snapshot.items():
                observed = device.read_register_bits(add, subadd)
                if observed != data:
                    restore_mismatches.append(RegisterMismatch(add, subadd, data, observed))

    return ChannelConfigResult(
        applied=tuple(applied),
        touched_rows=len(touched),
        verify_mismatches=tuple(verify_mismatches),
        restored=operation.restore,
        restore_mismatches=tuple(restore_mismatches),
    )
