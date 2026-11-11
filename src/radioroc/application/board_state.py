"""Compare GUI settings with the ASIC register table the board holds.

The GUI colours each ASIC-config control by whether its value is already on
the board.  "On the board" means a register table the connection worker
trusts: one read back in full from hardware, or one this app wrote in full
(apply defaults / load config) and has kept in step with every later write.

Matching never re-implements register bit layouts.  `operation_matches`
replays a `ChannelConfigOperation` through the same `apply_channel_config`
path the Apply buttons use, against an in-memory copy of the table, and
reports whether any register would change.  If nothing would change, the
setting is already on the board.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from radioroc_client import I2CRow, RadiorocDevice

from .channel_config import ChannelConfigOperation, apply_channel_config

READ_BACK = "read_back"
WRITTEN = "written"


@dataclass(frozen=True)
class BoardRegisterState:
    """The ASIC register table the worker believes the board holds.

    **Attributes**
    - `rows` (`tuple[I2CRow, ...]`): One row per ASIC register.
    - `serial` (`int`): Increases every time the table changes; lets the GUI
      skip recolouring when nothing changed.
    - `source` (`str`): `READ_BACK` when the table was last read in full from
      hardware, `WRITTEN` when it is the app's own record of writes since a
      full read-back or full-table write.
    """

    rows: tuple[I2CRow, ...]
    serial: int
    source: str


class _OverlayDevice(RadiorocDevice):
    """A device with no transport whose writes land in an overlay dict."""

    def __init__(self, base: dict[tuple[int, int], str]):
        super().__init__(None, dry_run=True)
        self._base = base
        self.writes: dict[tuple[int, int], str] = {}
        # apply_channel_config keeps already-loaded rows instead of loading
        # the packaged defaults when this is non-empty.  Lookups go through
        # find_i2c_row below, so one placeholder is enough (and keeps the
        # deepcopy in ChannelConfigOperation.load_rows cheap).
        self.i2c_rows = [I2CRow(0, 0, "")]

    def find_i2c_row(self, add: int, subadd: int) -> I2CRow | None:
        key = (add, subadd)
        if key not in self._base:
            return None
        return I2CRow(add, subadd, self.writes.get(key, self._base[key]))

    def write_register(self, add: int, subadd: int, data: str) -> None:
        self.writes[(add, subadd)] = data

    def read_register_bits(self, add: int, subadd: int) -> str:  # probe "exclusive" reads
        return self.writes.get((add, subadd), self._base[(add, subadd)])


def rows_by_address(rows) -> dict[tuple[int, int], str]:
    """Index register rows by `(add, subadd)`."""

    return {(row.add, row.subadd): row.data for row in rows}


def operation_matches(rows, operation: ChannelConfigOperation) -> bool:
    """Whether applying `operation` would leave every register unchanged.

    **Inputs**
    - `rows` (`dict[tuple[int, int], str] | Iterable[I2CRow]`): The board's
      register table; pass a `rows_by_address` dict when comparing many
      operations against one table.
    - `operation` (`ChannelConfigOperation`): Settings to compare.  Only
      plain value settings make sense here (gains, trims, masks, thresholds,
      input DAC); probe routing is an action, not a stored setting.

    **Returns**
    - `bool`: `True` when every setting in `operation` is already on the
      board.  A register missing from `rows` counts as not matching.

    **Hardware side effects**
    - None.
    """

    base = rows if isinstance(rows, dict) else rows_by_address(rows)
    device = _OverlayDevice(base)
    apply_channel_config(device, replace(operation, verify=False, restore=False, config_path=None))
    return all(base[key] == data for key, data in device.writes.items()) and _all_found(base, operation)


def _all_found(base: dict[tuple[int, int], str], operation: ChannelConfigOperation) -> bool:
    """Setters silently skip registers absent from the table; treat that as unknown."""

    per_channel_subadd = {
        "trigger_preamp_gain_values": 1, "trigger_preamp_compensation_values": 1,
        "high_gain_values": 2, "low_gain_values": 2,
        "high_gain_shaping_values": 3, "low_gain_shaping_values": 3,
        "high_gain_shaping_slow_states": 7, "low_gain_shaping_slow_states": 7,
        "t1_calibration_dac_values": 4, "t2_calibration_dac_values": 5,
        "input_dac_values": 0, "tq_mask_states": 6, "t1_mask_states": 6, "t2_mask_states": 6,
    }
    for name, subadd in per_channel_subadd.items():
        for channel in getattr(operation, name) or {}:
            if (channel, subadd) not in base:
                return False
    return True


def board_value(rows, operation_field: str, candidates, channel: int | None = None):
    """The value of one setting that the board holds, or `None` if none fits.

    Found by trying each candidate through `operation_matches`, so it uses
    the same register encoding as Apply and never decodes bits by hand.

    **Inputs**
    - `rows` (`dict[tuple[int, int], str] | Iterable[I2CRow]`): Board table.
    - `operation_field` (`str`): A `ChannelConfigOperation` field, e.g.
      `"trigger_preamp_gain_values"` (per-channel, needs `channel`) or
      `"t1_threshold_dac"` (ASIC-wide).
    - `candidates` (`Iterable`): Values to try, e.g. `range(64)`.
    - `channel` (`int | None`): Channel for per-channel fields.

    **Returns**
    - The first matching candidate, or `None`.
    """

    base = rows if isinstance(rows, dict) else rows_by_address(rows)
    for value in candidates:
        setting = value if channel is None else {channel: value}
        if operation_matches(base, ChannelConfigOperation(**{operation_field: setting})):
            return value
    return None
