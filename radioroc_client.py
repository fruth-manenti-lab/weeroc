"""Reusable RADIOROC 2 helpers for scripts and future GUI code.

This module is the library layer for local RADIOROC 2 work. Command-line
scripts should parse user arguments, call functions/classes from this file, and
handle terminal output or file presentation only.

The library owns stable defaults, serial frame encoding, channel parsing, and
low-level USB serial transport. Higher-level scan operations will be migrated
here incrementally while keeping the proven prototype scripts working.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.resources import files
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
# Prefer this checkout's package when running legacy scripts without installation.
_source_package = Path(__file__).resolve().parent / "src"
if (_source_package / "radioroc").is_dir():
    sys.path.insert(0, str(_source_package))

from radioroc.protocol import bits, parse_bits, encode_read_request, encode_write_request
from radioroc.transport import (
    DEFAULT_PORT, DEFAULT_BAUD, DEFAULT_TIMEOUT_SECONDS,
    RadiorocConnectionConfig, RadiorocSerial, RadiorocMemoryTransport,
)
from radioroc.transport.errors import TransportProtocolError


DEFAULT_CONFIG: Path = Path(__file__).resolve().parent / "configs" / "radio_default_i2c.csv"
if not DEFAULT_CONFIG.is_file():
    DEFAULT_CONFIG = Path(str(files("radioroc.resources").joinpath("radio_default_i2c.csv")))
DEFAULT_RUNS_DIR: Path = Path("radioroc_runs")
N_CHANNELS: int = 64
FPGA_IO_NAMES: tuple[str, ...] = ("io0", "io1", "io2", "io3", "io4")

# Vendor/control constants proven from Radioroc2UI 2.2.0.5 disassembly and
# board tests. Names are deliberately explicit so callers do not need to
# interpret opaque FPGA bit strings.
RADIOROC_CHIP_ID: int = 1
ASIC_ADDRESS_BITS: int = 8
ASIC_SUBADDRESS_BITS: int = 8
FPGA_FIRMWARE_STATUS_WORD: int = 100
FPGA_I2C_FIFO_WRITE_WORD: int = 56
FPGA_I2C_FIFO_READ_WORD: int = 55
FPGA_I2C_CONTROL_WORD: int = 60
FPGA_STATUS_WORD: int = 4
FPGA_ADC_FRAME_WORD: int = 20
FPGA_ADC_ACQUISITION_COUNT_WORD: int = 21
FPGA_SYNCHRO_TRIGGER_WORD: int = 22
FPGA_IO_MUX_LOW_WORD: int = 77
FPGA_IO_MUX_HIGH_WORD: int = 78
ASIC_SHAPER_GAIN_SUBADDRESS: int = 2

INTERNAL_HOLD_ADC_CONTROL_WORD: str = "01110100"
EXTERNAL_HOLD_TRACK_ADC_CONTROL_WORD: str = "01111000"
EXTERNAL_HOLD_PEAK_ADC_CONTROL_WORD: str = "01111100"
INTERNAL_HOLD_CONVERSION_WORD: str = "11111111"
EXTERNAL_HOLD_VENDOR_CONVERSION_WORD: str = "00000100"


@dataclass
class I2CRow:
    """One ASIC I2C configuration row.

    **Attributes**
    - `add` (`int`): ASIC register address.
    - `subadd` (`int`): ASIC register subaddress.
    - `data` (`str`): Eight-bit binary data string, such as `"00010000"`.
    """

    add: int
    subadd: int
    data: str


@dataclass
class RadiorocRunMetadata:
    """Metadata recorded beside hardware run outputs.

    **Attributes**
    - `created_at` (`str`): UTC ISO-8601 timestamp for the run.
    - `command` (`list[str]`): Command-line invocation or GUI action tokens.
    - `settings` (`dict[str, object]`): User-facing run settings.
    - `git_commit` (`str | None`): Current git commit hash, if available.
    - `port` (`str`): Serial port used for the run.
    - `baud` (`int`): Serial baud rate used for the run.
    - `firmware_status_word` (`str | None`): FPGA firmware/status word read
      from the board, if available.
    """

    created_at: str
    command: list[str]
    settings: dict[str, object]
    git_commit: str | None
    port: str
    baud: int
    firmware_status_word: str | None = None

    @classmethod
    def create(
        cls,
        *,
        connection: RadiorocConnectionConfig,
        settings: dict[str, object] | None = None,
        command: list[str] | None = None,
        firmware_status_word: str | None = None,
        repo: Path = Path("."),
    ) -> "RadiorocRunMetadata":
        """Create metadata for a hardware run.

        **Inputs**
        - `connection` (`RadiorocConnectionConfig`): Serial connection used.
        - `settings` (`dict[str, object] | None`): Run settings to persist.
        - `command` (`list[str] | None`): Command tokens. Defaults to
          `sys.argv`.
        - `firmware_status_word` (`str | None`): Firmware/status word, if read.
        - `repo` (`Path`): Repository path used for git commit lookup.

        **Returns**
        - `RadiorocRunMetadata`: JSON-friendly run metadata.
        """

        return cls(
            created_at=datetime.now(timezone.utc).isoformat(),
            command=list(command if command is not None else sys.argv),
            settings=dict(settings or {}),
            git_commit=current_git_commit(repo),
            port=connection.port,
            baud=connection.baud,
            firmware_status_word=firmware_status_word,
        )

    def as_dict(self) -> dict[str, object]:
        """Return metadata as a JSON-friendly dictionary.

        **Inputs**
        - None

        **Returns**
        - `dict[str, object]`: Metadata fields suitable for JSON output.
        """

        return {
            "created_at": self.created_at,
            "command": self.command,
            "settings": self.settings,
            "git_commit": self.git_commit,
            "port": self.port,
            "baud": self.baud,
            "firmware_status_word": self.firmware_status_word,
        }


@dataclass
class ScurveConfig:
    """Configuration for an S-curve scan.

    **Attributes**
    - `channels` (`list[int]`): ASIC channels to scan.
    - `dac_min` (`int`): First threshold DAC code.
    - `dac_max` (`int`): Last threshold DAC code.
    - `dac_step` (`int`): DAC step size.
    - `t1` (`bool`): Use T1 when true, T2 when false.
    - `use_mask` (`bool`): Mask all but the measured channel.
    - `use_ctest` (`bool`): Enable Ctest for selected channels.
    - `clock_index` (`int`): Vendor S-curve clock index `0..3`.
    - `trigger_level` (`bool`): Count trigger level instead of rising edge.
    - `trigger_preamp_gain` (`int | None`): Optional paT gain code `1..63`.
    - `out_dir` (`Path`): Run output directory.
    """

    channels: list[int]
    dac_min: int = 0
    dac_max: int = 1023
    dac_step: int = 50
    t1: bool = True
    use_mask: bool = True
    use_ctest: bool = False
    clock_index: int = 3
    trigger_level: bool = False
    trigger_preamp_gain: int | None = None
    out_dir: Path = DEFAULT_RUNS_DIR

    def validate(self) -> None:
        """Validate this S-curve configuration before hardware writes.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        validate_channels(self.channels)
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be unique")
        validate_scan_range(self.dac_min, self.dac_max, self.dac_step, name="DAC")
        if not 0 <= self.clock_index <= 3:
            raise ValueError("clock_index must be in range 0..3")
        if self.trigger_preamp_gain is not None and not 1 <= self.trigger_preamp_gain <= 63:
            raise ValueError("trigger_preamp_gain must be in range 1..63")


@dataclass
class ThresholdScanConfig:
    """Configuration for a trigger-rate threshold scan.

    **Attributes**
    - `channels` (`list[int]`): ASIC channels to scan.
    - `dac_min` (`int`): First threshold DAC code.
    - `dac_max` (`int`): Last threshold DAC code.
    - `dac_step` (`int`): DAC step size.
    - `trigger_window_ms` (`float`): Counter gate duration per point.
    - `averages` (`int`): Number of repeated windows averaged per point.
    - `t1` (`bool`): Use T1 when true, T2 when false.
    - `use_mask` (`bool`): Mask all but the measured channel.
    - `use_ctest` (`bool`): Enable Ctest for selected channels.
    - `trigger_preamp_gain` (`int | None`): Optional paT gain code `1..63`.
    - `out_dir` (`Path`): Run output directory.
    """

    channels: list[int]
    dac_min: int = 0
    dac_max: int = 1023
    dac_step: int = 50
    trigger_window_ms: float = 100.0
    averages: int = 1
    t1: bool = True
    use_mask: bool = True
    use_ctest: bool = False
    trigger_preamp_gain: int | None = None
    out_dir: Path = DEFAULT_RUNS_DIR

    def validate(self) -> None:
        """Validate this threshold-scan configuration before hardware writes.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        from radioroc.protocol.frames import validate_integer
        if not self.channels:
            raise ValueError("at least one channel is required")
        for channel in self.channels:
            validate_integer(channel, 0, 63, "channel")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be unique")
        validate_integer(self.dac_min, 0, 1023, "dac_min")
        validate_integer(self.dac_max, 0, 1023, "dac_max")
        validate_integer(self.dac_step, 1, 1024, "dac_step")
        validate_scan_range(self.dac_min, self.dac_max, self.dac_step, name="DAC")
        if (isinstance(self.trigger_window_ms, bool)
                or not isinstance(self.trigger_window_ms, (int, float))
                or not math.isfinite(self.trigger_window_ms) or self.trigger_window_ms <= 0):
            raise ValueError("trigger_window_ms must be finite and positive")
        validate_integer(self.averages, 1, 2**31 - 1, "averages")
        for name in ("t1", "use_mask", "use_ctest"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.trigger_preamp_gain is not None:
            validate_integer(self.trigger_preamp_gain, 1, 63, "trigger_preamp_gain")


@dataclass
class HoldScanConfig:
    """Configuration for an internal or external hold scan.

    **Attributes**
    - `mode` (`str`): `"internal"` for ASIC delay-cell codes or `"external"`
      for FPGA-generated hold delays in ns.
    - `channels` (`list[int]`): ADC channels to summarize.
    - `trigger_channel` (`int`): Channel used for the ADC trigger setup.
    - `hold_min` (`int`): First hold code or external hold delay in ns.
    - `hold_max` (`int`): Last hold code or external hold delay in ns.
    - `hold_step` (`int`): Hold code or delay step.
    - `threshold_dac` (`int | None`): Optional T1/T2 threshold DAC setting.
    - `acquisitions` (`int`): ADC acquisitions per hold point.
    - `conversion_delay_ns` (`int`): ADC conversion delay, divisible by 40 ns.
    - `trigger_type` (`int`): Vendor ADC trigger type code.
    - `trigger_source` (`int`): Vendor ADC trigger source code.
    - `rstn_manual` (`bool`): Vendor ADC reset-n manual bit.
    - `external_trigger` (`bool`): Use external ASIC acquisition trigger bit.
    - `peak_sensing` (`bool`): Use vendor external-hold peak-sensing path.
    - `adc_window_ns` (`int`): ADC coincidence/window width, divisible by 5 ns.
    - `adc_nb_trig` (`int`): ADC time-window trigger count.
    - `timeout_s` (`float`): Per-batch ADC timeout.
    - `synchro_trigger` (`bool`): Pulse FPGA synchro trigger per ADC batch.
    - `sync_io` (`str`): FPGA IO name used for sync diagnostics.
    - `sync_io_mux_index` (`int | None`): Optional FPGA IO mux index.
    - `t1` (`bool`): Use T1 threshold when true, T2 when false.
    - `use_mask` (`bool`): Mask all but the trigger channel.
    - `use_ctest` (`bool`): Enable Ctest on the trigger channel.
    - `trigger_preamp_gain` (`int | None`): Optional paT gain code `1..63`.
    - `high_gain_code` (`int | None`): Optional high-gain shaper code `1..15`.
    - `low_gain_code` (`int | None`): Optional low-gain shaper code `1..15`.
    - `out_dir` (`Path`): Run output directory.
    """

    mode: str
    channels: list[int]
    trigger_channel: int
    hold_min: int = 0
    hold_max: int = 255
    hold_step: int = 5
    threshold_dac: int | None = None
    acquisitions: int = 10
    conversion_delay_ns: int = 400
    trigger_type: int = 0
    trigger_source: int = 3
    rstn_manual: bool = False
    external_trigger: bool = False
    peak_sensing: bool = False
    adc_window_ns: int = 50
    adc_nb_trig: int = 1
    timeout_s: float = 5.0
    synchro_trigger: bool = False
    sync_io: str = "io1"
    sync_io_mux_index: int | None = None
    t1: bool = True
    use_mask: bool = True
    use_ctest: bool = False
    trigger_preamp_gain: int | None = None
    high_gain_code: int | None = None
    low_gain_code: int | None = None
    out_dir: Path = DEFAULT_RUNS_DIR

    def validate(self) -> None:
        """Validate this hold-scan configuration before hardware writes.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        if self.mode not in {"internal", "external"}:
            raise ValueError("hold mode must be 'internal' or 'external'")
        validate_channels(self.channels)
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be unique")
        validate_channel(self.trigger_channel)
        validate_scan_range(self.hold_min, self.hold_max, self.hold_step, name="hold")
        if self.mode == "internal" and not (0 <= self.hold_min <= 255 and 0 <= self.hold_max <= 255):
            raise ValueError("internal hold code range must be within 0..255")
        if self.mode == "external" and (self.hold_min % 5 != 0 or self.hold_max % 5 != 0 or self.hold_step % 5 != 0):
            raise ValueError("external hold delays must be divisible by 5 ns")
        if self.threshold_dac is not None and not 0 <= self.threshold_dac <= 1023:
            raise ValueError("threshold_dac must be in range 0..1023")
        if not 1 <= self.acquisitions <= 255:
            raise ValueError("acquisitions must be in range 1..255")
        if self.conversion_delay_ns < 0 or self.conversion_delay_ns % 40 != 0:
            raise ValueError("conversion_delay_ns must be non-negative and divisible by 40")
        if not 0 <= self.trigger_type <= 3:
            raise ValueError("trigger_type must be in range 0..3")
        if not 0 <= self.trigger_source <= 7:
            raise ValueError("trigger_source must be in range 0..7")
        if self.adc_window_ns < 0 or self.adc_window_ns % 5 != 0:
            raise ValueError("adc_window_ns must be non-negative and divisible by 5")
        if not 0 <= self.adc_nb_trig <= 63:
            raise ValueError("adc_nb_trig must be in range 0..63")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.sync_io not in FPGA_IO_NAMES:
            raise ValueError(f"sync_io must be one of {FPGA_IO_NAMES}")
        if self.sync_io_mux_index is not None and not 0 <= self.sync_io_mux_index <= 7:
            raise ValueError("sync_io_mux_index must be in range 0..7")
        if self.trigger_preamp_gain is not None and not 1 <= self.trigger_preamp_gain <= 63:
            raise ValueError("trigger_preamp_gain must be in range 1..63")
        for name, value in (("high_gain_code", self.high_gain_code), ("low_gain_code", self.low_gain_code)):
            if value is not None and not 1 <= value <= 15:
                raise ValueError(f"{name} must be in range 1..15")


@dataclass
class SyncPulseConfig:
    """Configuration for a standalone FPGA synchro pulse test.

    **Attributes**
    - `sync_io` (`str`): FPGA IO name used for sync diagnostics.
    - `sync_io_mux_index` (`int | None`): Optional FPGA IO mux index.
    - `pulses` (`int`): Number of pulses to emit.
    - `period_ms` (`float`): Time between pulses in milliseconds.
    """

    sync_io: str = "io1"
    sync_io_mux_index: int | None = None
    pulses: int = 1000
    period_ms: float = 10.0

    def validate(self) -> None:
        """Validate this sync-pulse configuration before hardware writes.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        if self.sync_io not in FPGA_IO_NAMES:
            raise ValueError(f"sync_io must be one of {FPGA_IO_NAMES}")
        if self.sync_io_mux_index is not None and not 0 <= self.sync_io_mux_index <= 7:
            raise ValueError("sync_io_mux_index must be in range 0..7")
        if self.pulses < 1:
            raise ValueError("pulses must be at least 1")
        if self.period_ms < 0:
            raise ValueError("period_ms must be non-negative")


@dataclass
class IoMuxScanConfig:
    """Configuration for scanning FPGA IO mux indices.

    **Attributes**
    - `sync_io` (`str`): FPGA IO name to scan.
    - `scan_all_ios` (`bool`): Set all configurable IO outputs to each index.
    - `pulses_per_index` (`int`): Pulses emitted at each mux index.
    - `period_ms` (`float`): Pulse period in milliseconds.
    """

    sync_io: str = "io1"
    scan_all_ios: bool = False
    pulses_per_index: int = 100
    period_ms: float = 10.0

    def validate(self) -> None:
        """Validate this IO mux scan configuration before hardware writes.

        **Inputs**
        - None

        **Returns**
        - `None`
        """

        if self.sync_io not in FPGA_IO_NAMES:
            raise ValueError(f"sync_io must be one of {FPGA_IO_NAMES}")
        if self.pulses_per_index < 1:
            raise ValueError("pulses_per_index must be at least 1")
        if self.period_ms < 0:
            raise ValueError("period_ms must be non-negative")


@dataclass
class ScurveResult:
    """Result metadata for an S-curve scan.

    **Attributes**
    - `csv_path` (`Path`): Output CSV path.
    - `metadata_path` (`Path | None`): Output metadata JSON path.
    - `metadata` (`RadiorocRunMetadata | None`): Run metadata.
    - `points` (`int`): Number of DAC points written.
    - `channels` (`list[int]`): Channels included in the scan.
    - `warnings` (`list[str]`): Non-fatal warnings.
    - `verification` (`dict | None`): Optional independent restoration report.
    """

    csv_path: Path
    metadata_path: Path | None = None
    metadata: RadiorocRunMetadata | None = None
    points: int = 0
    channels: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "completed"
    cleanup_status: str = "not_required"
    cleanup_errors: list[str] = field(default_factory=list)
    persistence_errors: list[str] = field(default_factory=list)
    error: BaseException | None = None
    execution_mode: str = "hardware"
    verification: dict | None = None


@dataclass
class ThresholdScanResult:
    """Result metadata for a threshold scan.

    **Attributes**
    - `csv_path` (`Path`): Output CSV path.
    - `attempts_csv_path` (`Path | None`): Per-window attempt CSV path.
    - `metadata_path` (`Path | None`): Output metadata JSON path.
    - `metadata` (`RadiorocRunMetadata | None`): Run metadata.
    - `points` (`int`): Number of DAC points written.
    - `channels` (`list[int]`): Channels included in the scan.
    - `warnings` (`list[str]`): Non-fatal warnings.
    - `verification` (`dict | None`): Optional independent restoration report.
    """

    csv_path: Path
    attempts_csv_path: Path | None = None
    metadata_path: Path | None = None
    metadata: RadiorocRunMetadata | None = None
    points: int = 0
    channels: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "completed"
    cleanup_status: str = "not_required"
    cleanup_errors: list[str] = field(default_factory=list)
    persistence_errors: list[str] = field(default_factory=list)
    error: BaseException | None = None
    attempts: int = 0
    execution_mode: str = "hardware"
    verification: dict | None = None


@dataclass
class HoldScanResult:
    """Result metadata for a hold scan.

    **Attributes**
    - `csv_path` (`Path`): Output CSV path.
    - `metadata_path` (`Path | None`): Output metadata JSON path.
    - `metadata` (`RadiorocRunMetadata | None`): Run metadata.
    - `points` (`int`): Number of hold points written.
    - `channels` (`list[int]`): Channels summarized in the scan.
    - `mode` (`str`): Hold mode used for the scan.
    - `warnings` (`list[str]`): Non-fatal warnings.
    - `verification` (`dict | None`): Optional independent restoration report.
    """

    csv_path: Path
    metadata_path: Path | None = None
    metadata: RadiorocRunMetadata | None = None
    points: int = 0
    channels: list[int] = field(default_factory=list)
    mode: str = "internal"
    warnings: list[str] = field(default_factory=list)
    status: str = "completed"
    cleanup_status: str = "not_required"
    cleanup_errors: list[str] = field(default_factory=list)
    persistence_errors: list[str] = field(default_factory=list)
    error: BaseException | None = None
    execution_mode: str = "hardware"
    verification: dict | None = None


@dataclass
class SyncPulseResult:
    """Result metadata for a sync pulse test.

    **Attributes**
    - `pulses` (`int`): Number of pulses requested.
    - `period_ms` (`float`): Pulse period in milliseconds.
    - `sync_io` (`str`): FPGA IO name used.
    - `sync_io_mux_index` (`int | None`): FPGA IO mux index used.
    - `metadata` (`RadiorocRunMetadata | None`): Run metadata.
    """

    pulses: int
    period_ms: float
    sync_io: str
    sync_io_mux_index: int | None = None
    metadata: RadiorocRunMetadata | None = None


@dataclass
class IoMuxScanResult:
    """Result metadata for an IO mux scan.

    **Attributes**
    - `sync_io` (`str`): FPGA IO name scanned.
    - `scan_all_ios` (`bool`): Whether all FPGA IO outputs were scanned.
    - `indices` (`list[int]`): Mux indices tested.
    - `metadata` (`RadiorocRunMetadata | None`): Run metadata.
    """

    sync_io: str
    scan_all_ios: bool
    indices: list[int] = field(default_factory=lambda: list(range(8)))
    metadata: RadiorocRunMetadata | None = None


@dataclass
class FpgaWordSnapshot:
    """Saved FPGA word values for later restoration.

    **Attributes**
    - `words` (`dict[int, str]`): Mapping of FPGA word address to saved binary
      word value.
    """

    words: dict[int, str]


@dataclass
class AsicRegisterSnapshot:
    """Saved ASIC register values for later restoration.

    **Attributes**
    - `registers` (`dict[tuple[int, int], str]`): Mapping of
      `(add, subadd)` to saved binary register value.
    """

    registers: dict[tuple[int, int], str]


def current_git_commit(repo: Path = Path(".")) -> str | None:
    """Read the current repository commit hash.

    **Inputs**
    - `repo` (`Path`): Repository working tree path.

    **Returns**
    - `str | None`: Current commit hash, or `None` if git lookup fails.
    """

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    commit: str = result.stdout.strip()
    return commit or None


def timestamp_slug() -> str:
    """Create a filesystem-friendly local timestamp.

    **Inputs**
    - None

    **Returns**
    - `str`: Timestamp string in `YYYYMMDD_HHMMSS` format.
    """

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_channels_for_path(channels: list[int] | None) -> str:
    """Format a channel list for use in output directory names.

    **Inputs**
    - `channels` (`list[int] | None`): Channel indices, or `None` for a
      scan that is not channel-specific.

    **Returns**
    - `str`: Compact channel label such as `"ch4"`, `"ch0_1_2_3_etc"`,
      or `"all"`.
    """

    if not channels:
        return "all"
    validate_channels(channels)
    if len(channels) == 1:
        return f"ch{channels[0]}"
    shown: list[int] = channels[:4]
    suffix: str = "_etc" if len(channels) > len(shown) else ""
    return "ch" + "_".join(str(channel) for channel in shown) + suffix


def default_run_dir(
    scan_name: str,
    *,
    channels: list[int] | None = None,
    root: Path = DEFAULT_RUNS_DIR,
    timestamp: str | None = None,
) -> Path:
    """Build a standard output directory path for a scan.

    **Inputs**
    - `scan_name` (`str`): Human-readable scan name.
    - `channels` (`list[int] | None`): Channel list for the path label.
    - `root` (`Path`): Parent output directory.
    - `timestamp` (`str | None`): Optional timestamp override for tests.

    **Returns**
    - `Path`: Standard output path under `root`.
    """

    safe_scan: str = scan_name.lower().strip().replace(" ", "_").replace("-", "_")
    safe_scan = "".join(char for char in safe_scan if char.isalnum() or char == "_").strip("_")
    if not safe_scan:
        raise ValueError("scan_name must contain at least one letter or number")
    stamp: str = timestamp or timestamp_slug()
    return root / f"{safe_scan}_{format_channels_for_path(channels)}_{stamp}"


def write_metadata_json(
    metadata: RadiorocRunMetadata,
    out_dir: Path,
    filename: str = "metadata.json",
) -> Path:
    """Write run metadata beside scan output files.

    **Inputs**
    - `metadata` (`RadiorocRunMetadata`): Metadata object to serialize.
    - `out_dir` (`Path`): Output directory to create if needed.
    - `filename` (`str`): Metadata filename.

    **Returns**
    - `Path`: Written metadata JSON path.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    path: Path = out_dir / filename
    path.write_text(json.dumps(metadata.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_csv_rows(
    rows: list[dict[str, object]],
    out_dir: Path,
    filename: str,
    fieldnames: list[str] | None = None,
) -> Path:
    """Write scan rows to CSV with a stable header.

    **Inputs**
    - `rows` (`list[dict[str, object]]`): Rows to write.
    - `out_dir` (`Path`): Output directory to create if needed.
    - `filename` (`str`): CSV filename.
    - `fieldnames` (`list[str] | None`): Optional explicit column order. When
      omitted, the first row's keys are used.

    **Returns**
    - `Path`: Written CSV path.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    path: Path = out_dir / filename
    columns: list[str] = list(fieldnames or (list(rows[0].keys()) if rows else []))
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def validate_channel(channel: int, *, n_channels: int = N_CHANNELS) -> None:
    """Validate one ASIC channel index.

    **Inputs**
    - `channel` (`int`): Channel index to validate.
    - `n_channels` (`int`): Number of available ASIC channels.

    **Returns**
    - `None`
    """

    if not 0 <= channel < n_channels:
        raise ValueError(f"channel must be in range 0..{n_channels - 1}")


def validate_channels(channels: list[int], *, n_channels: int = N_CHANNELS) -> None:
    """Validate a non-empty ASIC channel list.

    **Inputs**
    - `channels` (`list[int]`): Channel indices to validate.
    - `n_channels` (`int`): Number of available ASIC channels.

    **Returns**
    - `None`
    """

    if not channels:
        raise ValueError("at least one channel is required")
    for channel in channels:
        validate_channel(channel, n_channels=n_channels)


def validate_scan_range(min_value: int, max_value: int, step: int, *, name: str) -> None:
    """Validate an inclusive integer scan range.

    **Inputs**
    - `min_value` (`int`): First scan point.
    - `max_value` (`int`): Last scan point.
    - `step` (`int`): Positive point spacing.
    - `name` (`str`): User-facing range name for error messages.

    **Returns**
    - `None`
    """

    if step <= 0:
        raise ValueError(f"{name} step must be positive")
    if max_value < min_value:
        raise ValueError(f"{name} max must be greater than or equal to min")


def scan_values(min_value: int, max_value: int, step: int, *, name: str = "scan") -> list[int]:
    """Return inclusive integer scan points.

    **Inputs**
    - `min_value` (`int`): First scan point.
    - `max_value` (`int`): Last scan point.
    - `step` (`int`): Positive point spacing.
    - `name` (`str`): User-facing range name for validation errors.

    **Returns**
    - `list[int]`: Inclusive scan point values.
    """

    validate_scan_range(min_value, max_value, step, name=name)
    return list(range(min_value, max_value + 1, step))


def parse_channels(value: str, *, n_channels: int = N_CHANNELS) -> list[int]:
    """Parse a channel selection string.

    **Inputs**
    - `value` (`str`): Channel expression such as `"4"`, `"0,4,7"`,
      `"0-15"`, `"all"`, or `"*"`.
    - `n_channels` (`int`): Number of valid channels.

    **Returns**
    - `list[int]`: Sorted unique channel indices.
    """

    if value.lower() in {"all", "*"}:
        return list(range(n_channels))
    channels: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            lo: int = int(lo_text)
            hi: int = int(hi_text)
            if hi < lo:
                raise ValueError("channel ranges must be ascending")
            channels.update(range(lo, hi + 1))
        else:
            channels.add(int(part))
    result: list[int] = sorted(channels)
    if not all(0 <= channel < n_channels for channel in result):
        raise ValueError(f"channels must be in range 0..{n_channels - 1}")
    return result


class RadiorocDevice:
    """Low-level RADIOROC FPGA and ASIC control API.

    This class wraps `RadiorocSerial` with FPGA word helpers, ASIC I2C FIFO
    transactions, default configuration loading, and default configuration
    verification, and typed scan workflows. CLI scripts and future GUI code
    should call this class instead of duplicating FPGA/ASIC register sequences.

    **Attributes**
    - `transport` (`RadiorocSerial`): Open serial transport.
    - `dry_run` (`bool`): When true, write-capable methods print intended
      operations instead of writing hardware.
    - `i2c_rows` (`list[I2CRow]`): Loaded default ASIC I2C configuration rows.
    - `chip_id` (`int`): ASIC chip ID used by the vendor I2C FIFO protocol.
    - `address_bits` (`int`): ASIC address field width.
    - `subaddress_bits` (`int`): ASIC subaddress field width.
    """

    def __init__(self, transport: RadiorocSerial, *, dry_run: bool = False):
        """Create a low-level RADIOROC device wrapper.

        **Inputs**
        - `transport` (`RadiorocSerial`): Open serial transport.
        - `dry_run` (`bool`): When true, suppress hardware writes.

        **Returns**
        - `None`
        """

        self.transport: RadiorocSerial = transport
        self.dry_run: bool = dry_run
        self.i2c_rows: list[I2CRow] = []
        self.chip_id: int = RADIOROC_CHIP_ID
        self.address_bits: int = ASIC_ADDRESS_BITS
        self.subaddress_bits: int = ASIC_SUBADDRESS_BITS
        self._job_checkpoint = None

    def _checkpoint(self) -> None:
        if self._job_checkpoint is not None:
            self._job_checkpoint()

    def read_word(self, address: int) -> str:
        """Read one FPGA word.

        **Inputs**
        - `address` (`int`): FPGA word address.

        **Returns**
        - `str`: Eight-bit binary word.
        """

        self._checkpoint()
        return self.transport.read_word(address)

    def write_word(self, address: int, word_bits: str) -> None:
        """Write one FPGA word, respecting dry-run mode.

        **Inputs**
        - `address` (`int`): FPGA word address.
        - `word_bits` (`str`): Binary word string.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one FPGA control/data word unless `dry_run` is true.
        """

        self._checkpoint()
        if self.dry_run:
            print(f"DRY write_word address={address} data={word_bits}")
            return
        self.transport.write_word(address, word_bits)

    def load_default_config(self, path: Path = DEFAULT_CONFIG) -> None:
        """Load the default ASIC I2C CSV table.

        **Inputs**
        - `path` (`Path`): CSV file with `add`, `subadd`, and `data` columns.

        **Returns**
        - `None`
        """

        with path.open(newline="") as fp:
            self.i2c_rows = [
                I2CRow(int(row["add"]), int(row["subadd"]), str(row["data"]).strip())
                for row in csv.DictReader(fp)
            ]

    def full_i2c_address(self, add: int, subadd: int) -> bytes:
        """Encode an ASIC register address/subaddress pair.

        **Inputs**
        - `add` (`int`): ASIC register address.
        - `subadd` (`int`): ASIC register subaddress.

        **Returns**
        - `bytes`: Two-byte big-endian full address field.
        """

        full: str = f"{add:0{self.address_bits}b}{subadd:0{self.subaddress_bits}b}"
        return int(full, 2).to_bytes(2, "big")

    def write_register(self, add: int, subadd: int, data: str) -> None:
        """Write one ASIC I2C register.

        **Inputs**
        - `add` (`int`): ASIC register address.
        - `subadd` (`int`): ASIC register subaddress.
        - `data` (`str`): Eight-bit binary data.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one ASIC slow-control register through the FPGA I2C FIFO
          unless `dry_run` is true.
        """

        row: I2CRow | None = self.find_i2c_row(add, subadd)
        if row is not None:
            row.data = data
        payload: bytes = (
            self.chip_id.to_bytes(1, "big")
            + self.full_i2c_address(add, subadd)
            + parse_bits(data).to_bytes(1, "little")
        )
        self.i2c_fifo_transaction(payload, read=False)

    def write_fifo(self, rows: list[I2CRow]) -> None:
        """Write multiple ASIC I2C rows through the vendor FIFO path.

        **Inputs**
        - `rows` (`list[I2CRow]`): Register rows to write.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC slow-control rows through the FPGA I2C FIFO unless
          `dry_run` is true.
        """

        payload: bytes = b"".join(
            self.chip_id.to_bytes(1, "little")
            + self.full_i2c_address(row.add, row.subadd)
            + parse_bits(row.data).to_bytes(1, "little")
            for row in rows
        )
        self.i2c_fifo_transaction(payload, read=False)

    def read_fifo(self, rows: list[I2CRow]) -> bytes:
        """Read multiple ASIC I2C rows through the vendor FIFO path.

        **Inputs**
        - `rows` (`list[I2CRow]`): Register addresses to read. The `data` field
          is ignored; missing readback is never replaced by a default.

        **Returns**
        - `bytes`: One data byte per requested row.

        **Hardware side effects**
        - Performs ASIC slow-control read transactions through the FPGA I2C
          FIFO unless `dry_run` is true.
        """

        payload: bytes = b"".join(
            (128 + self.chip_id).to_bytes(1, "little")
            + self.full_i2c_address(row.add, row.subadd)
            + b"\x00"
            for row in rows
        )
        return self.i2c_fifo_transaction(payload, read=True) or b""

    def i2c_fifo_transaction(self, payload: bytes, *, read: bool) -> bytes | None:
        """Run a vendor-style ASIC I2C FIFO transaction.

        **Inputs**
        - `payload` (`bytes`): FIFO payload in four-byte I2C operation chunks.
        - `read` (`bool`): Whether to read back data from the FIFO read word.

        **Returns**
        - `bytes | None`: Readback bytes for read transactions, otherwise
          `None`.

        **Hardware side effects**
        - Temporarily enables the FPGA I2C bus-active bit, writes the FIFO
          payload, triggers the FPGA I2C transaction, and restores the
          bus-active bit afterward unless `dry_run` is true.
        """

        self._checkpoint()
        if self.dry_run:
            kind: str = "read" if read else "write"
            print(f"DRY i2c_{kind}_fifo {len(payload)} bytes")
            return b"" if read else None

        word0: str = self.transport.read_word(0)
        primary_error = None
        try:
            self.transport.write_word(FPGA_I2C_CONTROL_WORD, "00000000")
            self.transport.write_word(0, word0[0] + "1" + word0[2:8])
            for offset in range(0, len(payload), 256):
                self._checkpoint()
                chunk: bytes = payload[offset : offset + 256]
                self.transport.write_words(FPGA_I2C_FIFO_WRITE_WORD, chunk)
                self.transport.write_word(FPGA_I2C_CONTROL_WORD, "00000000")
                self.transport.write_word(FPGA_I2C_CONTROL_WORD, "00000010")
                for _ in range(1000):
                    self._checkpoint()
                    if self.transport.read_word(FPGA_STATUS_WORD)[7] == "1":
                        break
                else:
                    raise TimeoutError("i2c FIFO transaction timed out")
                self.transport.write_word(FPGA_I2C_CONTROL_WORD, "00000100")
            if read:
                return self.transport.read_words(FPGA_I2C_FIFO_READ_WORD, len(payload) // 4)
            return None
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                self.transport.write_word(0, word0[0] + "0" + word0[2:8])
            except BaseException as cleanup_error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"I2C bus cleanup also failed: {cleanup_error}")

    def find_i2c_row(self, add: int, subadd: int) -> I2CRow | None:
        """Find a loaded default I2C row.

        **Inputs**
        - `add` (`int`): ASIC register address.
        - `subadd` (`int`): ASIC register subaddress.

        **Returns**
        - `I2CRow | None`: Matching row, or `None` if absent.
        """

        for row in self.i2c_rows:
            if row.add == add and row.subadd == subadd:
                return row
        return None

    def select_i2c_rows(self, *, add_lt: int | None = None, subadd: int | None = None) -> list[I2CRow]:
        """Select loaded I2C rows by simple filters.

        **Inputs**
        - `add_lt` (`int | None`): Keep rows with address lower than this value.
        - `subadd` (`int | None`): Keep rows with this subaddress.

        **Returns**
        - `list[I2CRow]`: Copies of matching rows.
        """

        selected: list[I2CRow] = self.i2c_rows
        if add_lt is not None:
            selected = [row for row in selected if row.add < add_lt]
        if subadd is not None:
            selected = [row for row in selected if row.subadd == subadd]
        return [I2CRow(row.add, row.subadd, row.data) for row in selected]

    def read_register_bits(self, add: int, subadd: int) -> str:
        """Read one ASIC register as an eight-bit binary string.

        **Inputs**
        - `add` (`int`): ASIC register address.
        - `subadd` (`int`): ASIC register subaddress.

        **Returns**
        - `str`: Verified eight-bit register value. Transport failures propagate.
          Only dry-run mode returns a configured fallback without hardware.

        **Hardware side effects**
        - Performs one ASIC slow-control read unless `dry_run` is true.
        """

        row: I2CRow | None = self.find_i2c_row(add, subadd)
        fallback: str = row.data if row is not None else "00000000"
        if self.dry_run:
            return fallback
        data: bytes = self.read_fifo([I2CRow(add, subadd, fallback)])
        if len(data) != 1:
            raise TransportProtocolError(f"expected one ASIC register byte, received {len(data)}")
        return bits(data[0], 8)

    def apply_default_config(self) -> None:
        """Write all loaded default ASIC I2C rows to the board.

        **Inputs**
        - None

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes the full loaded ASIC slow-control table unless `dry_run` is
          true.
        """

        if not self.i2c_rows:
            raise RuntimeError("default config not loaded")
        self.write_fifo(self.i2c_rows)

    def verify_default_config(self, *, limit: int | None = None) -> list[tuple[int, int, int, int]]:
        """Verify loaded default ASIC I2C rows against board readback.

        **Inputs**
        - `limit` (`int | None`): Number of rows to verify. Use `None` for all
          rows.

        **Returns**
        - `list[tuple[int, int, int, int]]`: Mismatches as
          `(add, subadd, expected, observed)`.

        **Hardware side effects**
        - Reads ASIC slow-control rows through the FPGA I2C FIFO unless
          `dry_run` is true.
        """

        if not self.i2c_rows:
            raise RuntimeError("default config not loaded")
        rows: list[I2CRow] = self.i2c_rows[:limit] if limit is not None else self.i2c_rows
        readback: bytes = self.read_fifo(rows)
        if self.dry_run:
            print(f"DRY verify_default_config rows={len(rows)}")
            return []
        mismatches: list[tuple[int, int, int, int]] = []
        for row, value in zip(rows, readback):
            expected: int = parse_bits(row.data)
            if value != expected:
                mismatches.append((row.add, row.subadd, expected, value))
        return mismatches

    def initialize_fpga(self) -> None:
        """Initialize FPGA control words like the vendor UI connection path.

        **Inputs**
        - None

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes FPGA control words `0` and `1` unless `dry_run` is true.
        """

        self.write_word(0, "00111111")
        self.write_word(1, "01000000")

    def configure_scurve_firmware(self, *, clock_index: int, trigger_level: bool) -> None:
        """Configure FPGA words used by S-curve and threshold scans.

        **Inputs**
        - `clock_index` (`int`): Vendor S-curve clock index `0..3`.
        - `trigger_level` (`bool`): Count trigger level when true.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes FPGA words `1` and `3` unless `dry_run` is true.
        """

        if not 0 <= clock_index <= 3:
            raise ValueError("clock_index must be in range 0..3")
        word1: str = self.read_word(1) if not self.dry_run else "00000000"
        self.write_word(1, word1[:4] + bits(clock_index, 2) + word1[6:])
        word3: str = self.read_word(3) if not self.dry_run else "00000000"
        self.write_word(3, word3[:-1] + str(int(trigger_level)))

    def set_threshold_dac(self, dac: int, *, t1: bool) -> None:
        """Set the T1 or T2 global threshold DAC.

        **Inputs**
        - `dac` (`int`): Threshold DAC code `0..1023`.
        - `t1` (`bool`): Write T1 when true, T2 when false.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC threshold slow-control registers.
        """

        if not 0 <= dac <= 1023:
            raise ValueError("dac must be in range 0..1023")
        dac_bits: str = bits(dac, 10)
        if t1:
            self.write_register(65, 2, "000000" + dac_bits[:2])
            self.write_register(65, 1, dac_bits[2:])
        else:
            self.write_register(65, 2, dac_bits[4:] + "00")
            self.write_register(65, 3, "0000" + dac_bits[:4])

    def set_trigger_preamp_gain(self, gain: int, *, channels: list[int]) -> None:
        """Set selected channels' trigger preamplifier paT gain code.

        **Inputs**
        - `gain` (`int`): paT gain code `1..63`; `1` is highest gain.
        - `channels` (`list[int]`): Channels to modify.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes selected channel gain rows through the ASIC I2C FIFO.
        """

        validate_channels(channels)
        if not 1 <= gain <= 63:
            raise ValueError("trigger preamp gain code must be in range 1..63; 1=max gain, 63=min gain")
        rows: list[I2CRow] = []
        for channel in channels:
            row: I2CRow | None = self.find_i2c_row(channel, 1)
            if row is None:
                continue
            current: int = parse_bits(row.data)
            compensation: int = current & 0xC0
            new_data: str = bits(compensation | gain, 8)
            row.data = new_data
            rows.append(I2CRow(channel, 1, new_data))
        if not rows:
            raise RuntimeError("no trigger preamp gain rows found for selected channels")
        self.write_fifo(rows)

    def set_energy_shaper_gain(
        self,
        *,
        channels: list[int],
        high_gain_code: int | None = None,
        low_gain_code: int | None = None,
    ) -> None:
        """Set selected channels' ADC energy-path shaper gain codes.

        **Inputs**
        - `channels` (`list[int]`): Channels to modify.
        - `high_gain_code` (`int | None`): High-gain shaper code `1..15`.
        - `low_gain_code` (`int | None`): Low-gain shaper code `1..15`.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes selected channel energy gain rows through the ASIC I2C FIFO.

        **Mapping note**
        - The user guide defines 4-bit high-gain and low-gain shaper codes.
          The default table stores `10001000` at per-channel subaddress 2,
          consistent with two default code-8 nibbles. We use the upper nibble
          for high gain and the lower nibble for low gain.
        """

        validate_channels(channels)
        if high_gain_code is None and low_gain_code is None:
            return
        if high_gain_code is not None and not 1 <= high_gain_code <= 15:
            raise ValueError("high_gain_code must be in range 1..15")
        if low_gain_code is not None and not 1 <= low_gain_code <= 15:
            raise ValueError("low_gain_code must be in range 1..15")

        rows: list[I2CRow] = []
        for channel in channels:
            row: I2CRow | None = self.find_i2c_row(channel, ASIC_SHAPER_GAIN_SUBADDRESS)
            if row is None:
                continue
            current: int = parse_bits(row.data)
            current_hg: int = (current >> 4) & 0xF
            current_lg: int = current & 0xF
            new_hg: int = high_gain_code if high_gain_code is not None else current_hg
            new_lg: int = low_gain_code if low_gain_code is not None else current_lg
            new_data = bits((new_hg << 4) | new_lg, 8)
            row.data = new_data
            rows.append(I2CRow(channel, ASIC_SHAPER_GAIN_SUBADDRESS, new_data))
        if not rows:
            raise RuntimeError("no energy shaper gain rows found for selected channels")
        self.write_fifo(rows)

    def set_mask_for_channel(self, channel: int, *, t1: bool, enabled: bool) -> None:
        """Enable or disable one channel trigger mask bit.

        **Inputs**
        - `channel` (`int`): Channel index.
        - `t1` (`bool`): Modify the T1 mask when true, T2 when false.
        - `enabled` (`bool`): Mask bit value.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one channel mask register if present in the loaded defaults.
        """

        validate_channel(channel)
        row: I2CRow | None = self.find_i2c_row(channel, 6)
        if row is None:
            return
        data: list[str] = list(row.data)
        data[3 if t1 else 4] = "1" if enabled else "0"
        self.write_register(channel, 6, "".join(data))

    def set_ctest_for_channel(self, channel: int, enabled: bool) -> None:
        """Enable or disable Ctest injection on one channel.

        **Inputs**
        - `channel` (`int`): Channel index.
        - `enabled` (`bool`): Ctest bit value.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one channel Ctest register if present in the loaded defaults.
        """

        validate_channel(channel)
        row: I2CRow | None = self.find_i2c_row(channel, 7)
        if row is None:
            return
        data: list[str] = list(row.data)
        data[3] = "1" if enabled else "0"
        self.write_register(channel, 7, "".join(data))

    def set_tq_mask_for_channel(self, channel: int, enabled: bool) -> None:
        """Enable or disable one channel's TQ trigger mask bit.

        **Inputs**
        - `channel` (`int`): Channel index.
        - `enabled` (`bool`): Mask bit value.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one channel mask register if present in the loaded defaults.

        Bit position recovered from the vendor GUI's compiled widget
        properties (`checkBox_maskTQ_NN`: add=channel, subadd=6, position=2,
        LSB-numbered per `i2c.set_value`'s documented convention -> string
        index 5 in this codebase's MSB-first row string), cross-checked
        against `set_mask_for_channel`'s already hardware-validated T1
        (position 4 -> index 3) and T2 (position 3 -> index 4) bits from the
        same register. Not yet independently verified against real hardware.
        """

        validate_channel(channel)
        row: I2CRow | None = self.find_i2c_row(channel, 6)
        if row is None:
            return
        data: list[str] = list(row.data)
        data[5] = "1" if enabled else "0"
        self.write_register(channel, 6, "".join(data))

    def set_input_dac_enable_for_channel(self, channel: int, enabled: bool) -> None:
        """Enable or disable one channel's input DAC.

        **Inputs**
        - `channel` (`int`): Channel index.
        - `enabled` (`bool`): Enable bit value.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one channel mask register if present in the loaded defaults.

        Bit position recovered from the vendor GUI's compiled widget
        properties (`checkBox_indacNN`: add=channel, subadd=6, position=6 ->
        string index 1 in this codebase's row string). Not yet independently
        verified against real hardware.
        """

        validate_channel(channel)
        row: I2CRow | None = self.find_i2c_row(channel, 6)
        if row is None:
            return
        data: list[str] = list(row.data)
        data[1] = "1" if enabled else "0"
        self.write_register(channel, 6, "".join(data))

    def set_input_dac_impedance(self, low_impedance: bool) -> None:
        """Select high- or low-impedance (~150 Ohm) input DAC termination.

        **Inputs**
        - `low_impedance` (`bool`): Select the ~150 Ohm input when true, high
          impedance when false.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes the same bit across every loaded channel-6 register (0..63)
          present in the loaded defaults.

        This is a single physical switch shared by all channels, not a
        per-channel setting (vendor guide 3.1.2). Bit position recovered from
        the vendor GUI's compiled widget properties
        (`checkBox_indac_impedance`: subadd=6, position=7, `all_channels_add`
        true -> string index 0, written identically to every channel's row 6).
        Not yet independently verified against real hardware.
        """

        value = "1" if low_impedance else "0"
        for channel in range(N_CHANNELS):
            row: I2CRow | None = self.find_i2c_row(channel, 6)
            if row is None:
                continue
            data: list[str] = list(row.data)
            data[0] = value
            self.write_register(channel, 6, "".join(data))

    def set_input_dac_value(self, channel: int, value: int) -> None:
        """Set one channel's input DAC DC value.

        **Inputs**
        - `channel` (`int`): Channel index.
        - `value` (`int`): Raw 8-bit input DAC code, 0..255 (vendor guide
          3.1.2: approximately 50-600 mV, ~2 mV per step).

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes one channel input-DAC register if present in the loaded
          defaults.

        Register recovered from the vendor GUI's compiled widget properties
        (`lineEdit_indacNN`: add=channel, subadd=0, position=0, nbbits=8 ->
        the entire row byte). Not yet independently verified against real
        hardware.
        """

        from radioroc.protocol.frames import validate_integer

        validate_channel(channel)
        validate_integer(value, 0, 255, "value")
        row: I2CRow | None = self.find_i2c_row(channel, 0)
        if row is None:
            return
        self.write_register(channel, 0, bits(value, 8))

    def prepare_trigger_masks(self, *, t1: bool, use_mask: bool, use_ctest: bool) -> None:
        """Prepare trigger path masks and Ctest bits for scan loops.

        **Inputs**
        - `t1` (`bool`): Use T1 when true, T2 when false.
        - `use_mask` (`bool`): Clear per-channel trigger masks before scan.
        - `use_ctest` (`bool`): Clear per-channel Ctest enables before scan.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC slow-control rows for discriminator selection, masks,
          and Ctest enables.
        """

        clps_t: str = "00010000" if t1 else "00100000"
        self.write_fifo([I2CRow(66, channel, clps_t) for channel in range(N_CHANNELS)])
        if use_mask:
            rows: list[I2CRow] = self.select_i2c_rows(add_lt=N_CHANNELS, subadd=6)
            for row in rows:
                data: list[str] = list(row.data)
                data[3 if t1 else 4] = "0"
                row.data = "".join(data)
            self.write_fifo(rows)
        if use_ctest:
            rows = self.select_i2c_rows(add_lt=N_CHANNELS, subadd=7)
            for row in rows:
                data = list(row.data)
                data[3] = "0"
                row.data = "".join(data)
            self.write_fifo(rows)

    @staticmethod
    def accurate_delay_ms(delay_ms: float) -> None:
        """Delay with millisecond-scale timing for threshold counters.

        **Inputs**
        - `delay_ms` (`float`): Delay duration in milliseconds.

        **Returns**
        - `None`
        """

        if delay_ms <= 0:
            return
        deadline: float = time.perf_counter() + delay_ms / 1000.0
        while True:
            remaining: float = deadline - time.perf_counter()
            if remaining <= 0:
                return
            if remaining > 0.003:
                time.sleep(remaining - 0.001)

    def run_scurve(
        self,
        config: ScurveConfig,
        *,
        metadata: RadiorocRunMetadata | None = None,
        cancellation=None,
        on_event=None,
    ) -> ScurveResult:
        """Compatibility entry point for the shared S-curve job.

        Failures raise ScurveJobError carrying a durable partial ``result``.
        The application runner returns that result directly for UI consumers.
        """
        from radioroc.application.scurve import ScurveJob, ScurveJobConfig, ScurveJobError
        result = ScurveJob().run(self, ScurveJobConfig(config), metadata=metadata,
                                 cancellation=cancellation, on_event=on_event)
        if result.status not in ("completed", "cancelled") or result.cleanup_errors or result.persistence_errors:
            raise ScurveJobError(result) from result.error
        return result

    def run_threshold_scan(
        self,
        config: ThresholdScanConfig,
        *,
        metadata: RadiorocRunMetadata | None = None,
        cancellation=None,
        on_event=None,
    ) -> ThresholdScanResult:
        """Compatibility entry point for the shared threshold job.

        Failures raise ThresholdJobError carrying a durable partial ``result``.
        The application runner returns that result directly for UI consumers.
        """
        from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig, ThresholdJobError
        result = ThresholdJob().run(self, ThresholdJobConfig(config), metadata=metadata,
                                    cancellation=cancellation, on_event=on_event)
        if result.status not in ("completed", "cancelled") or result.cleanup_errors or result.persistence_errors:
            raise ThresholdJobError(result) from result.error
        return result

    def configure_adc_external_hold(
        self,
        *,
        trigger_channel: int,
        hold_delay_ns: int,
        conversion_delay_ns: int,
        nb_acq: int,
        trigger_type: int,
        trigger_source: int,
        rstn_manual: bool,
        ext_trig: bool,
        peak_sensing: bool,
        adc_window_ns: int,
        adc_nb_trig: int,
    ) -> None:
        """Configure FPGA/ASIC registers for external hold acquisition.

        **Inputs**
        - `trigger_channel` (`int`): Channel used for ADC trigger setup.
        - `hold_delay_ns` (`int`): External hold delay in ns, divisible by 5.
        - `conversion_delay_ns` (`int`): ADC conversion delay, divisible by 40.
        - `nb_acq` (`int`): Number of ADC acquisitions.
        - `trigger_type` (`int`): Vendor ADC trigger type code.
        - `trigger_source` (`int`): Vendor ADC trigger source code.
        - `rstn_manual` (`bool`): Vendor ADC reset-n manual bit.
        - `ext_trig` (`bool`): Use external acquisition trigger bit.
        - `peak_sensing` (`bool`): Use external peak-sensing control path.
        - `adc_window_ns` (`int`): ADC trigger window in ns, divisible by 5.
        - `adc_nb_trig` (`int`): ADC time-window trigger count.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC hold-source register and FPGA ADC timing/control words.
        """

        validate_channel(trigger_channel)
        if hold_delay_ns < 0 or hold_delay_ns % 5 != 0:
            raise ValueError("hold_delay_ns must be non-negative and divisible by 5")
        if conversion_delay_ns < 0 or conversion_delay_ns % 40 != 0:
            raise ValueError("conversion_delay_ns must be non-negative and divisible by 40")
        if not 1 <= nb_acq <= 255:
            raise ValueError("nb_acq must be in range 1..255")
        if not 0 <= trigger_type <= 3:
            raise ValueError("trigger_type must be in range 0..3")
        if not 0 <= trigger_source <= 7:
            raise ValueError("trigger_source must be in range 0..7")
        if adc_window_ns < 0 or adc_window_ns % 5 != 0:
            raise ValueError("adc_window_ns must be non-negative and divisible by 5")
        if not 0 <= adc_nb_trig <= 63:
            raise ValueError("adc_nb_trig must be in range 0..63")

        ext_hold_code: int = hold_delay_ns // 5
        if ext_hold_code > 0xFFF:
            raise ValueError("external hold delay code must fit in 12 bits; max delay is 20475 ns")

        i2c65_12_bits: str = self.read_register_bits(65, 12)
        if peak_sensing:
            self.write_register(65, 12, i2c65_12_bits[:2] + "01" + "0000")
        else:
            self.write_register(65, 12, i2c65_12_bits[:3] + "1" + i2c65_12_bits[4:])

        ext_hold_bits: str = bits(ext_hold_code, 12)
        saved_w23: str = self.read_word(23) if (peak_sensing and not self.dry_run) else "00000000"
        peak_or_ext_trig: bool = peak_sensing or ext_trig
        self.write_word(22, "00" + bits(trigger_channel, 6))
        self.write_word(23, "01" + saved_w23[2:] if peak_sensing else "00000000")
        self.write_word(24, bits(adc_window_ns // 5, 8))
        self.write_word(
            25,
            bits(trigger_source, 3) + str(int(rstn_manual)) + "1" + str(int(peak_or_ext_trig)) + bits(trigger_type, 2),
        )
        self.write_word(26, ext_hold_bits[4:])
        self.write_word(27, "00" + bits(adc_nb_trig, 6))
        self.write_word(30, ext_hold_bits[:4] + bits(0, 3))
        self.write_word(31, bits(conversion_delay_ns // 40, 8))
        self.write_word(21, bits(nb_acq))

    def configure_adc_internal_hold(self, *, trigger_channel: int, hold_code: int, nb_acq: int) -> None:
        """Configure FPGA/ASIC registers for internal delay-cell hold.

        **Inputs**
        - `trigger_channel` (`int`): Channel used for ADC trigger setup.
        - `hold_code` (`int`): ASIC internal hold delay code `0..255`.
        - `nb_acq` (`int`): Number of ADC acquisitions.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC internal hold code and FPGA ADC control words.
        """

        validate_channel(trigger_channel)
        if not 0 <= hold_code <= 255:
            raise ValueError("internal hold code must be in range 0..255")
        if not 1 <= nb_acq <= 255:
            raise ValueError("nb_acq must be in range 1..255")
        i2c65_12: str = self.read_register_bits(65, 12)
        self.write_register(65, 12, i2c65_12[:2] + "10" + i2c65_12[4:])
        self.write_register(65, 8, bits(hold_code))
        saved_w23: str = self.read_word(23) if not self.dry_run else "00000000"
        self.write_word(31, INTERNAL_HOLD_CONVERSION_WORD)
        self.write_word(25, INTERNAL_HOLD_ADC_CONTROL_WORD)
        self.write_word(22, "00" + bits(trigger_channel, 6))
        self.write_word(23, "00" + saved_w23[2:])
        self.write_word(21, bits(nb_acq))

    def acquire_adc_batch(
        self,
        *,
        nb_acq: int,
        timeout_s: float = 5.0,
        synchro_trigger: bool = False,
    ) -> tuple[list[list[float]], list[list[float]]]:
        """Acquire one ADC batch and return high-gain and low-gain samples.

        **Inputs**
        - `nb_acq` (`int`): Number of requested ADC acquisitions.
        - `timeout_s` (`float`): Timeout waiting for the ADC-ready bit.
        - `synchro_trigger` (`bool`): Pulse the FPGA synchro trigger after
          arming acquisition.

        **Returns**
        - `tuple[list[list[float]], list[list[float]]]`: High-gain and low-gain
          samples indexed by channel.

        **Hardware side effects**
        - Arms FPGA ADC acquisition and reads ADC FIFO payload.
        """

        if not 1 <= nb_acq <= 255:
            raise ValueError("nb_acq must be in range 1..255")
        if self.dry_run:
            return [[math.nan] * nb_acq for _ in range(N_CHANNELS)], [[math.nan] * nb_acq for _ in range(N_CHANNELS)]

        saved_w2: str = self.read_word(2)
        self.write_word(21, bits(nb_acq))
        self.write_word(2, saved_w2[:1] + "1" + saved_w2[3:])
        self.write_word(2, saved_w2[:1] + "0" + saved_w2[3:])
        self.write_word(2, saved_w2[0] + "1" + saved_w2[2:])
        self.write_word(2, saved_w2[0] + "0" + saved_w2[2:])
        if synchro_trigger:
            self.pulse_synchro_trigger(count=nb_acq + 1, period_ms=1.0)

        deadline: float = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.read_word(4)[5] == "1":
                break
            time.sleep(0.01)
        else:
            raise TimeoutError("ADC acquisition timed out waiting for FPGA word 4 bit 5")

        count_words: str = self.read_word(29) + self.read_word(28)
        total_nb_acq: int = int(int(count_words, 2) / 256)
        if total_nb_acq <= 0:
            return [[] for _ in range(N_CHANNELS)], [[] for _ in range(N_CHANNELS)]

        payload: bytes = self.transport.read_words(20, total_nb_acq * N_CHANNELS * 4)
        low_gain: list[list[float]] = [[] for _ in range(N_CHANNELS)]
        high_gain: list[list[float]] = [[] for _ in range(N_CHANNELS)]
        channel: int = 0
        for index in range(0, len(payload) - 3, 4):
            low_gain[channel].append(0.25 * int.from_bytes(payload[index : index + 2], "big"))
            high_gain[channel].append(0.25 * int.from_bytes(payload[index + 2 : index + 4], "big"))
            channel = 0 if channel == N_CHANNELS - 1 else channel + 1
        return high_gain, low_gain

    @staticmethod
    def mean_stdev(values: list[float]) -> tuple[float, float]:
        """Return mean and sample standard deviation.

        **Inputs**
        - `values` (`list[float]`): Numeric samples.

        **Returns**
        - `tuple[float, float]`: Mean and standard deviation, or `nan` for an
          empty sample list.
        """

        if not values:
            return math.nan, math.nan
        if len(values) == 1:
            return values[0], 0.0
        return statistics.mean(values), statistics.stdev(values)

    def run_hold_scan(
        self,
        config: HoldScanConfig,
        *,
        metadata: RadiorocRunMetadata | None = None,
        cancellation=None,
        on_event=None,
    ) -> HoldScanResult:
        """Compatibility entry point for the shared hold-scan job.

        Failures raise HoldScanJobError carrying a durable partial ``result``.
        The application runner returns that result directly for UI consumers.
        """
        from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig, HoldScanJobError
        result = HoldScanJob().run(self, HoldScanJobConfig(config), metadata=metadata,
                                   cancellation=cancellation, on_event=on_event)
        if result.status not in ("completed", "cancelled") or result.cleanup_errors or result.persistence_errors:
            raise HoldScanJobError(result) from result.error
        return result

    def pulse_synchro_trigger(self, *, count: int, period_ms: float) -> None:
        """Pulse the FPGA synchro-trigger output.

        **Inputs**
        - `count` (`int`): Number of pulses to emit.
        - `period_ms` (`float`): Delay between pulses in milliseconds.

        **Returns**
        - `None`

        **Hardware side effects**
        - Toggles FPGA word `22` bit 0 repeatedly.
        """

        if count < 1:
            raise ValueError("sync pulse count must be at least 1")
        if period_ms < 0:
            raise ValueError("sync pulse period must be non-negative")
        saved_w22: str = self.read_word(22) if not self.dry_run else "00000000"
        for index in range(count):
            self.write_word(22, "1" + saved_w22[1:])
            self.write_word(22, "0" + saved_w22[1:])
            if period_ms > 0 and index != count - 1:
                time.sleep(period_ms / 1000.0)

    def read_fpga_io_mux(self) -> dict[str, int]:
        """Read the FPGA IO mux settings.

        **Inputs**
        - None

        **Returns**
        - `dict[str, int]`: Current mux index for `io0` through `io4`.

        **Hardware side effects**
        - Reads FPGA words `77` and `78` unless `dry_run` is true.
        """

        if self.dry_run:
            return {name: 0 for name in FPGA_IO_NAMES}
        word77: str = self.read_word(77)
        word78: str = self.read_word(78)
        packed: str = word78[-7:] + word77
        return {
            "io4": int(packed[0:3], 2),
            "io3": int(packed[3:6], 2),
            "io2": int(packed[6:9], 2),
            "io1": int(packed[9:12], 2),
            "io0": int(packed[12:15], 2),
        }

    def write_fpga_io_mux(self, **updates: int) -> dict[str, int]:
        """Write selected FPGA IO mux settings.

        **Inputs**
        - `**updates` (`int`): Mapping such as `io1=5`.

        **Returns**
        - `dict[str, int]`: Full mux state after applying updates.

        **Hardware side effects**
        - Writes FPGA words `77` and `78`.
        """

        mux: dict[str, int] = self.read_fpga_io_mux()
        for name, index in updates.items():
            if name not in FPGA_IO_NAMES:
                raise ValueError(f"unknown FPGA IO name {name!r}; expected one of {', '.join(FPGA_IO_NAMES)}")
            if not 0 <= index <= 7:
                raise ValueError("FPGA IO mux index must be in range 0..7")
            mux[name] = index
        packed: str = (
            bits(mux["io4"], 3)
            + bits(mux["io3"], 3)
            + bits(mux["io2"], 3)
            + bits(mux["io1"], 3)
            + bits(mux["io0"], 3)
        )
        self.write_word(77, packed[7:15])
        self.write_word(78, packed[0:7])
        return mux

    def run_sync_pulse(
        self,
        config: SyncPulseConfig,
        *,
        metadata: RadiorocRunMetadata | None = None,
    ) -> SyncPulseResult:
        """Run a standalone FPGA synchro pulse test.

        **Inputs**
        - `config` (`SyncPulseConfig`): Pulse settings.
        - `metadata` (`RadiorocRunMetadata | None`): Optional run metadata.

        **Returns**
        - `SyncPulseResult`: Pulse settings and metadata.

        **Hardware side effects**
        - Optionally writes IO mux settings, then toggles the synchro trigger.
        """

        config.validate()
        if config.sync_io_mux_index is not None:
            self.write_fpga_io_mux(**{config.sync_io: config.sync_io_mux_index})
        self.pulse_synchro_trigger(count=config.pulses, period_ms=config.period_ms)
        return SyncPulseResult(
            pulses=config.pulses,
            period_ms=config.period_ms,
            sync_io=config.sync_io,
            sync_io_mux_index=config.sync_io_mux_index,
            metadata=metadata,
        )

    def run_io_mux_scan(
        self,
        config: IoMuxScanConfig,
        *,
        metadata: RadiorocRunMetadata | None = None,
    ) -> IoMuxScanResult:
        """Scan FPGA IO mux indices while pulsing the synchro trigger.

        **Inputs**
        - `config` (`IoMuxScanConfig`): Mux scan settings.
        - `metadata` (`RadiorocRunMetadata | None`): Optional run metadata.

        **Returns**
        - `IoMuxScanResult`: IO name, scan mode, tested indices, and metadata.

        **Hardware side effects**
        - Cycles IO mux settings and toggles the synchro trigger.
        """

        config.validate()
        original: dict[str, int] = self.read_fpga_io_mux()
        indices: list[int] = list(range(8))
        try:
            for index in indices:
                updates: dict[str, int] = (
                    {name: index for name in FPGA_IO_NAMES}
                    if config.scan_all_ios
                    else {config.sync_io: index}
                )
                mux: dict[str, int] = self.write_fpga_io_mux(**updates)
                print(f"Testing mux index {index}; mux={mux}", flush=True)
                self.pulse_synchro_trigger(count=config.pulses_per_index, period_ms=config.period_ms)
        finally:
            self.write_fpga_io_mux(**original)
        return IoMuxScanResult(
            sync_io=config.sync_io,
            scan_all_ios=config.scan_all_ios,
            indices=indices,
            metadata=metadata,
        )

    def snapshot_fpga_words(self, addresses: list[int]) -> FpgaWordSnapshot:
        """Read FPGA words for later restoration.

        **Inputs**
        - `addresses` (`list[int]`): FPGA word addresses to save.

        **Returns**
        - `FpgaWordSnapshot`: Saved word values by address.

        **Hardware side effects**
        - Reads the requested FPGA words over USB serial.
        """

        return FpgaWordSnapshot({address: self.read_word(address) for address in addresses})

    def restore_fpga_words(self, snapshot: FpgaWordSnapshot) -> None:
        """Restore FPGA words from a snapshot.

        **Inputs**
        - `snapshot` (`FpgaWordSnapshot`): Saved FPGA word values.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes the saved FPGA words unless `dry_run` is true.
        """

        for address, word in snapshot.words.items():
            self.write_word(address, word)

    def snapshot_asic_registers(self, registers: list[tuple[int, int]]) -> AsicRegisterSnapshot:
        """Read ASIC registers for later restoration.

        **Inputs**
        - `registers` (`list[tuple[int, int]]`): `(add, subadd)` pairs to save.

        **Returns**
        - `AsicRegisterSnapshot`: Saved register values by `(add, subadd)`.

        **Hardware side effects**
        - Reads ASIC slow-control registers through the FPGA I2C FIFO unless
          `dry_run` is true.
        """

        return AsicRegisterSnapshot(
            {register: self.read_register_bits(register[0], register[1]) for register in registers}
        )

    def restore_asic_registers(self, snapshot: AsicRegisterSnapshot) -> None:
        """Restore ASIC registers from a snapshot.

        **Inputs**
        - `snapshot` (`AsicRegisterSnapshot`): Saved ASIC register values.

        **Returns**
        - `None`

        **Hardware side effects**
        - Writes ASIC slow-control registers through the FPGA I2C FIFO unless
          `dry_run` is true.
        """

        for (add, subadd), data in snapshot.registers.items():
            self.write_register(add, subadd, data)
