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
    - `tq_mask_states` (`dict[int, bool] | None`): Independent per-channel TQ
      mask bits (channel -> enabled), for a 64-channel toggle-grid UI where
      each cell may hold a different state. Channels here must not also
      appear in `tq_mask_channels`.
    - `t1_mask_states` (`dict[int, bool] | None`): Same as `tq_mask_states`,
      for the T1 mask; channels here must not also appear in
      `t1_mask_channels`.
    - `t2_mask_states` (`dict[int, bool] | None`): Same as `tq_mask_states`,
      for the T2 mask; channels here must not also appear in
      `t2_mask_channels`.
    - `input_dac_enable_channels` (`tuple[int, ...]`): Channels to set the
      input DAC enable bit for.
    - `input_dac_enable_value` (`bool`): Input DAC enable bit to write.
    - `input_dac_value_channels` (`tuple[int, ...]`): Channels to set the
      input DAC raw value for.
    - `input_dac_value` (`int | None`): Raw 8-bit input DAC code, 0..255.
    - `input_dac_values` (`dict[int, int] | None`): Independent per-channel
      raw 8-bit input DAC codes (channel -> value), for callers such as a
      64-channel grid UI where each cell may hold a different value.
      Channels here must not also appear in `input_dac_value_channels`.
    - `t1_mask_channels` (`tuple[int, ...]`): Channels to set the T1 trigger
      mask bit for.
    - `t1_mask_value` (`bool`): T1 mask bit to write.
    - `t2_mask_channels` (`tuple[int, ...]`): Channels to set the T2 trigger
      mask bit for.
    - `t2_mask_value` (`bool`): T2 mask bit to write.
    - `input_dac_impedance` (`bool | None`): Set the shared impedance switch
      (all channels) to low (~150 Ohm) when true, high when false; leave
      unset when `None`.
    - `t1_calibration_dac_values` (`dict[int, int] | None`): Independent
      per-channel T1 threshold-calibration trim codes (channel -> 0..63),
      for a 64-channel grid UI.
    - `t2_calibration_dac_values` (`dict[int, int] | None`): Same as
      `t1_calibration_dac_values`, for the T2 trim DAC.
    - `trigger_preamp_gain_values` (`dict[int, int] | None`): Per-channel
      trigger-preamplifier (paT) gain codes (channel -> 0..63).
    - `trigger_preamp_compensation_values` (`dict[int, int] | None`):
      Per-channel trigger-preamplifier feedback-compensation codes
      (channel -> 0..3).
    - `high_gain_values` (`dict[int, int] | None`): Per-channel high-gain
      (HG) energy-preamplifier gain codes (channel -> 0..15).
    - `low_gain_values` (`dict[int, int] | None`): Per-channel low-gain (LG)
      energy-preamplifier gain codes (channel -> 0..15).
    - `high_gain_shaping_values` (`dict[int, int] | None`): Per-channel
      high-gain CRRC shaper time codes (channel -> 0..15).
    - `low_gain_shaping_values` (`dict[int, int] | None`): Per-channel
      low-gain CRRC shaper time codes (channel -> 0..15).
    - `high_gain_shaping_slow_states` (`dict[int, bool] | None`): Per-channel
      high-gain shaper LSB scale (channel -> `True` for 120 ns/code, `False`
      for 20 ns/code).
    - `low_gain_shaping_slow_states` (`dict[int, bool] | None`): Same as
      `high_gain_shaping_slow_states`, for the low-gain shaper.
    - `t1_threshold_dac` (`int | None`): Common (ASIC-wide) T1
      trigger-threshold DAC code, 0..1023.
    - `t2_threshold_dac` (`int | None`): Common (ASIC-wide) T2
      trigger-threshold DAC code, 0..1023.
    - `tq_threshold_dac` (`int | None`): Common (ASIC-wide) TQ
      trigger-threshold DAC code, 0..1023.
    - `trigger_selection` (`str | None`): Common (ASIC-wide) trigger
      selection; must be a key of `RadiorocDevice.TRIGGER_SELECTION_CODES`
      when set.
    - `delay_code` (`int | None`): Common (ASIC-wide) peak-detector hold
      delay code, 0..255.
    - `delay_slope` (`int | None`): Common (ASIC-wide) delay-slope trim code,
      0..15.
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
    tq_mask_states: dict[int, bool] | None = None
    input_dac_enable_channels: tuple[int, ...] = ()
    input_dac_enable_value: bool = True
    input_dac_value_channels: tuple[int, ...] = ()
    input_dac_value: int | None = None
    input_dac_values: dict[int, int] | None = None
    t1_mask_channels: tuple[int, ...] = ()
    t1_mask_value: bool = True
    t1_mask_states: dict[int, bool] | None = None
    t2_mask_channels: tuple[int, ...] = ()
    t2_mask_value: bool = True
    t2_mask_states: dict[int, bool] | None = None
    input_dac_impedance: bool | None = None
    t1_calibration_dac_values: dict[int, int] | None = None
    t2_calibration_dac_values: dict[int, int] | None = None
    trigger_preamp_gain_values: dict[int, int] | None = None
    trigger_preamp_compensation_values: dict[int, int] | None = None
    high_gain_values: dict[int, int] | None = None
    low_gain_values: dict[int, int] | None = None
    high_gain_shaping_values: dict[int, int] | None = None
    low_gain_shaping_values: dict[int, int] | None = None
    high_gain_shaping_slow_states: dict[int, bool] | None = None
    low_gain_shaping_slow_states: dict[int, bool] | None = None
    t1_threshold_dac: int | None = None
    t2_threshold_dac: int | None = None
    tq_threshold_dac: int | None = None
    trigger_selection: str | None = None
    delay_code: int | None = None
    delay_slope: int | None = None
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
                        self.input_dac_value_channels, self.t1_mask_channels,
                        self.t2_mask_channels):
            for channel in channels:
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
        for states, channels, name in (
            (self.tq_mask_states, self.tq_mask_channels, "tq_mask"),
            (self.t1_mask_states, self.t1_mask_channels, "t1_mask"),
            (self.t2_mask_states, self.t2_mask_channels, "t2_mask"),
        ):
            self._validate_channel_dict(states, channels, name)
        if self.input_dac_values is not None:
            overlap = set(self.input_dac_values) & set(self.input_dac_value_channels)
            if overlap:
                raise ValueError(
                    f"channels {sorted(overlap)} appear in both input_dac_values and "
                    "input_dac_value_channels")
            for channel, value in self.input_dac_values.items():
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
                if not 0 <= value <= 255:
                    raise ValueError("input_dac_values values must be in range 0..255")
        for values, name in ((self.t1_calibration_dac_values, "t1_calibration_dac_values"),
                             (self.t2_calibration_dac_values, "t2_calibration_dac_values")):
            if values is None:
                continue
            for channel, value in values.items():
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
                if not 0 <= value <= 63:
                    raise ValueError(f"{name} values must be in range 0..63")
        for values, name, max_value in (
            (self.trigger_preamp_gain_values, "trigger_preamp_gain_values", 63),
            (self.trigger_preamp_compensation_values, "trigger_preamp_compensation_values", 3),
            (self.high_gain_values, "high_gain_values", 15),
            (self.low_gain_values, "low_gain_values", 15),
            (self.high_gain_shaping_values, "high_gain_shaping_values", 15),
            (self.low_gain_shaping_values, "low_gain_shaping_values", 15),
        ):
            if values is None:
                continue
            for channel, value in values.items():
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
                if not 0 <= value <= max_value:
                    raise ValueError(f"{name} values must be in range 0..{max_value}")
        for states, name in ((self.high_gain_shaping_slow_states, "high_gain_shaping_slow_states"),
                             (self.low_gain_shaping_slow_states, "low_gain_shaping_slow_states")):
            if states is None:
                continue
            for channel in states:
                if not 0 <= channel < N_CHANNELS:
                    raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")
        if self.t1_threshold_dac is not None and not 0 <= self.t1_threshold_dac <= 1023:
            raise ValueError("t1_threshold_dac must be in range 0..1023")
        if self.t2_threshold_dac is not None and not 0 <= self.t2_threshold_dac <= 1023:
            raise ValueError("t2_threshold_dac must be in range 0..1023")
        if self.tq_threshold_dac is not None and not 0 <= self.tq_threshold_dac <= 1023:
            raise ValueError("tq_threshold_dac must be in range 0..1023")
        if self.trigger_selection is not None and \
                self.trigger_selection not in RadiorocDevice.TRIGGER_SELECTION_CODES:
            raise ValueError(
                f"trigger_selection must be one of {sorted(RadiorocDevice.TRIGGER_SELECTION_CODES)}")
        if self.delay_code is not None and not 0 <= self.delay_code <= 255:
            raise ValueError("delay_code must be in range 0..255")
        if self.delay_slope is not None and not 0 <= self.delay_slope <= 15:
            raise ValueError("delay_slope must be in range 0..15")
        if not any([self.tq_mask_channels, self.input_dac_enable_channels,
                   self.input_dac_value_channels, self.input_dac_values,
                   self.t1_mask_channels, self.t2_mask_channels,
                   self.tq_mask_states, self.t1_mask_states, self.t2_mask_states,
                   self.t1_calibration_dac_values, self.t2_calibration_dac_values,
                   self.input_dac_impedance is not None,
                   self.trigger_preamp_gain_values, self.trigger_preamp_compensation_values,
                   self.high_gain_values, self.low_gain_values,
                   self.high_gain_shaping_values, self.low_gain_shaping_values,
                   self.high_gain_shaping_slow_states, self.low_gain_shaping_slow_states,
                   self.t1_threshold_dac is not None, self.t2_threshold_dac is not None,
                   self.tq_threshold_dac is not None, self.trigger_selection is not None,
                   self.delay_code is not None, self.delay_slope is not None]):
            raise ValueError("at least one channel-configuration field is required")

    @staticmethod
    def _validate_channel_dict(states: dict[int, bool] | None, channels: tuple[int, ...],
                               name: str) -> None:
        if states is None:
            return
        overlap = set(states) & set(channels)
        if overlap:
            raise ValueError(
                f"channels {sorted(overlap)} appear in both {name}_states and {name}_channels")
        for channel in states:
            if not 0 <= channel < N_CHANNELS:
                raise ValueError(f"channel must be in range 0..{N_CHANNELS - 1}")


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
    touched.update((ch, 0) for ch in (operation.input_dac_values or {}))
    touched.update((ch, 6) for ch in operation.t1_mask_channels)
    touched.update((ch, 6) for ch in operation.t2_mask_channels)
    touched.update((ch, 6) for ch in (operation.tq_mask_states or {}))
    touched.update((ch, 6) for ch in (operation.t1_mask_states or {}))
    touched.update((ch, 6) for ch in (operation.t2_mask_states or {}))
    touched.update((ch, 4) for ch in (operation.t1_calibration_dac_values or {}))
    touched.update((ch, 5) for ch in (operation.t2_calibration_dac_values or {}))
    if operation.input_dac_impedance is not None:
        touched.update((ch, 6) for ch in range(N_CHANNELS))
    touched.update((ch, 1) for ch in (operation.trigger_preamp_gain_values or {}))
    touched.update((ch, 1) for ch in (operation.trigger_preamp_compensation_values or {}))
    touched.update((ch, 2) for ch in (operation.high_gain_values or {}))
    touched.update((ch, 2) for ch in (operation.low_gain_values or {}))
    touched.update((ch, 3) for ch in (operation.high_gain_shaping_values or {}))
    touched.update((ch, 3) for ch in (operation.low_gain_shaping_values or {}))
    touched.update((ch, 7) for ch in (operation.high_gain_shaping_slow_states or {}))
    touched.update((ch, 7) for ch in (operation.low_gain_shaping_slow_states or {}))
    if operation.t1_threshold_dac is not None:
        touched.update({(65, 1), (65, 2)})
    if operation.t2_threshold_dac is not None:
        touched.update({(65, 2), (65, 3)})
    if operation.tq_threshold_dac is not None:
        touched.update({(65, 3), (65, 4)})
    if operation.trigger_selection is not None:
        touched.add((65, 12))
    if operation.delay_code is not None:
        touched.add((65, 8))
    if operation.delay_slope is not None:
        touched.add((65, 9))

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
    for channel, value in (operation.input_dac_values or {}).items():
        device.set_input_dac_value(channel, value)
        applied.append(f"input_dac_value channel={channel} -> {value}")
    for channel in operation.t1_mask_channels:
        device.set_mask_for_channel(channel, t1=True, enabled=operation.t1_mask_value)
        applied.append(f"t1_mask channel={channel} -> {int(operation.t1_mask_value)}")
    for channel in operation.t2_mask_channels:
        device.set_mask_for_channel(channel, t1=False, enabled=operation.t2_mask_value)
        applied.append(f"t2_mask channel={channel} -> {int(operation.t2_mask_value)}")
    for channel, enabled in (operation.tq_mask_states or {}).items():
        device.set_tq_mask_for_channel(channel, enabled=enabled)
        applied.append(f"tq_mask channel={channel} -> {int(enabled)}")
    for channel, enabled in (operation.t1_mask_states or {}).items():
        device.set_mask_for_channel(channel, t1=True, enabled=enabled)
        applied.append(f"t1_mask channel={channel} -> {int(enabled)}")
    for channel, enabled in (operation.t2_mask_states or {}).items():
        device.set_mask_for_channel(channel, t1=False, enabled=enabled)
        applied.append(f"t2_mask channel={channel} -> {int(enabled)}")
    for channel, value in (operation.t1_calibration_dac_values or {}).items():
        device.set_calibration_dac_for_channel(channel, t1=True, value=value)
        applied.append(f"t1_calibration_dac channel={channel} -> {value}")
    for channel, value in (operation.t2_calibration_dac_values or {}).items():
        device.set_calibration_dac_for_channel(channel, t1=False, value=value)
        applied.append(f"t2_calibration_dac channel={channel} -> {value}")
    if operation.input_dac_impedance is not None:
        device.set_input_dac_impedance(operation.input_dac_impedance)
        applied.append(f"input_dac_impedance -> {'low' if operation.input_dac_impedance else 'high'}")
    for channel, value in (operation.trigger_preamp_gain_values or {}).items():
        device.set_trigger_preamp_gain_for_channel(channel, value)
        applied.append(f"trigger_preamp_gain channel={channel} -> {value}")
    for channel, value in (operation.trigger_preamp_compensation_values or {}).items():
        device.set_trigger_preamp_compensation_for_channel(channel, value)
        applied.append(f"trigger_preamp_compensation channel={channel} -> {value}")
    for channel, value in (operation.high_gain_values or {}).items():
        device.set_high_gain_for_channel(channel, value)
        applied.append(f"high_gain channel={channel} -> {value}")
    for channel, value in (operation.low_gain_values or {}).items():
        device.set_low_gain_for_channel(channel, value)
        applied.append(f"low_gain channel={channel} -> {value}")
    for channel, value in (operation.high_gain_shaping_values or {}).items():
        device.set_high_gain_shaping_for_channel(channel, value)
        applied.append(f"high_gain_shaping channel={channel} -> {value}")
    for channel, value in (operation.low_gain_shaping_values or {}).items():
        device.set_low_gain_shaping_for_channel(channel, value)
        applied.append(f"low_gain_shaping channel={channel} -> {value}")
    for channel, slow in (operation.high_gain_shaping_slow_states or {}).items():
        device.set_high_gain_shaping_slow_for_channel(channel, slow)
        applied.append(f"high_gain_shaping_slow channel={channel} -> {int(slow)}")
    for channel, slow in (operation.low_gain_shaping_slow_states or {}).items():
        device.set_low_gain_shaping_slow_for_channel(channel, slow)
        applied.append(f"low_gain_shaping_slow channel={channel} -> {int(slow)}")
    if operation.t1_threshold_dac is not None:
        device.set_t1_threshold_dac(operation.t1_threshold_dac)
        applied.append(f"t1_threshold_dac -> {operation.t1_threshold_dac}")
    if operation.t2_threshold_dac is not None:
        device.set_t2_threshold_dac(operation.t2_threshold_dac)
        applied.append(f"t2_threshold_dac -> {operation.t2_threshold_dac}")
    if operation.tq_threshold_dac is not None:
        device.set_tq_threshold_dac(operation.tq_threshold_dac)
        applied.append(f"tq_threshold_dac -> {operation.tq_threshold_dac}")
    if operation.trigger_selection is not None:
        device.set_trigger_selection(operation.trigger_selection)
        applied.append(f"trigger_selection -> {operation.trigger_selection}")
    if operation.delay_code is not None:
        device.set_delay_code(operation.delay_code)
        applied.append(f"delay_code -> {operation.delay_code}")
    if operation.delay_slope is not None:
        device.set_delay_slope(operation.delay_slope)
        applied.append(f"delay_slope -> {operation.delay_slope}")

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
