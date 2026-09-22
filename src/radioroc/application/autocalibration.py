"""Automatic threshold (T1/T2) calibration, shared by the compatibility API,
CLI and future UI.

Ports `scripts/radioroc_standard_scurves.py`'s `RadiorocOps.autocalibrate_scurve`
onto the shared core instead of that script's own duplicated ASIC/FPGA
primitives. The algorithm itself is unchanged (see IMPLEMENTATION_STATUS.md's
F08 entry for the full design rationale):

1. Probe a reference channel (the first selected channel) at calibration trim
   0 and 63 with two coarse S-curves, to estimate `lsb_ratio` -- how many DAC
   codes one trim-DAC LSB shifts the threshold. The reference channel's trim
   is restored to its original value after probing, on every exit path.
2. Run one finer S-curve across every selected channel; estimate each
   channel's DAC crossing point and their mean.
3. Correct each channel's calibration trim DAC to align its crossing with the
   mean -- this is the job's one intentional, persistent write.
4. Run one final, narrow S-curve across every selected channel to verify
   alignment.

Each of the four sub-scans reuses `ScurveJob`'s own hardware-validated
per-point scan/restore logic directly (`ScurveJob()._run_locked(...)`, the
method `ScurveJob.run()` itself calls after acquiring the transport's session
lock) rather than reimplementing it. `session_lock` is explicitly
non-reentrant, so this job acquires it once for the whole four-step sequence
instead of letting each sub-scan acquire-and-release it independently, which
would let another job interleave mid-calibration.

Unlike the legacy script's `stop_after_all_low` early-exit, the final
verification scan here always runs its full configured range -- a bounded
simplification, not a functional gap; keep `final_window_before`/
`final_window_after`/`final_dac_step` narrow to control its length.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
import csv
import json
import os
import statistics
import tempfile

from radioroc_client import (
    DEFAULT_CONFIG, I2CRow, N_CHANNELS, RadiorocDevice, RadiorocRunMetadata,
    ScurveConfig, ScurveResult, parse_bits, scan_values, validate_scan_range,
)
from radioroc.data.scurve_reader import read_scurve_run
from radioroc.transport.errors import TransportClosedError, TransportIOError
from radioroc_analysis import estimate_scurve_crossings
from .jobs import CancellationToken, JobBusyError, JobCancelled, session_lock
from .scurve import ScurveJob, ScurveJobConfig


def _describe(error):
    return f"{type(error).__name__}: {error}" if error is not None else None


@dataclass(frozen=True)
class AutocalibrationJobConfig:
    """One automatic-threshold-calibration request.

    **Attributes**
    - `channels` (`list[int]`): Channels to calibrate together. The first
      channel is used as the reference channel for the LSB-ratio probe.
    - `t1` (`bool`): Calibrate the T1 calibration trim DAC when true, T2
      when false.
    - `use_mask` (`bool`): Mask all but the measured channel during each
      sub-scan, same as `ScurveConfig.use_mask`.
    - `use_ctest` (`bool`): Enable Ctest during each sub-scan.
    - `clock_index` (`int`): Vendor S-curve clock index `0..3`.
    - `trigger_level` (`bool`): Count trigger level instead of rising edge.
    - `trigger_preamp_gain` (`int | None`): Optional paT gain code override
      applied during every sub-scan.
    - `out_dir` (`Path`): Top-level run output directory. Each sub-scan gets
      its own subdirectory (`step1_zero`, `step1_full`, `step2`, `final`).
    - `config_path` (`Path | None`): ASIC I2C config CSV. `None` reuses
      already-loaded device rows, mirroring `ScurveJobConfig`'s convention.
    - `initialize_fpga` (`bool`): Re-initialize the FPGA before the first
      sub-scan. Persists, like `ScurveJobConfig.initialize_fpga`.
    - `apply_defaults` (`bool`): Apply the ASIC's packaged defaults before
      the first sub-scan. Persists, like `ScurveJobConfig.apply_defaults`.
    - `probe_dac_min`/`probe_dac_max`/`probe_dac_step` (`int`): DAC range for
      the two step-1 LSB-ratio probe scans (reference channel only).
    - `transition_dac_step` (`int`): DAC step for the step-2 scan across all
      selected channels.
    - `transition_margin` (`int`): Added past the higher of the two step-1
      crossing estimates to pick the step-2 scan's upper bound.
    - `transition_dac_floor`/`transition_dac_cap` (`int`): Bounds clamping the
      computed step-2 upper bound.
    - `final_window_before`/`final_window_after` (`int`): How far below/above
      the step-2 mean crossing the final verification scan covers.
    - `final_dac_step` (`int`): DAC step for the final verification scan.
    - `target_percent` (`float`): Trigger-rate percentage defining a
      "crossing" (see `radioroc_analysis.estimate_scurve_crossings`).
    """

    channels: list[int]
    t1: bool = True
    use_mask: bool = True
    use_ctest: bool = False
    clock_index: int = 3
    trigger_level: bool = False
    trigger_preamp_gain: int | None = None
    out_dir: Path = Path("radioroc_runs")
    config_path: Path | None = None
    initialize_fpga: bool = False
    apply_defaults: bool = False
    probe_dac_min: int = 0
    probe_dac_max: int = 1000
    probe_dac_step: int = 50
    transition_dac_step: int = 10
    transition_margin: int = 150
    transition_dac_floor: int = 300
    transition_dac_cap: int = 1023
    final_window_before: int = 50
    final_window_after: int = 120
    final_dac_step: int = 2
    target_percent: float = 50.0

    def validate(self) -> None:
        # Reuses ScurveConfig's own channel/clock-index/gain validation for
        # the fields this config shares with it, instead of duplicating it.
        ScurveConfig(channels=self.channels, dac_min=self.probe_dac_min,
                     dac_max=self.probe_dac_max, dac_step=self.probe_dac_step,
                     t1=self.t1, use_mask=self.use_mask, use_ctest=self.use_ctest,
                     clock_index=self.clock_index, trigger_level=self.trigger_level,
                     trigger_preamp_gain=self.trigger_preamp_gain, out_dir=self.out_dir).validate()
        validate_scan_range(0, self.transition_dac_cap, self.transition_dac_step,
                            name="transition_dac")
        if self.transition_margin < 0:
            raise ValueError("transition_margin must be >= 0")
        if not 0 <= self.transition_dac_floor <= self.transition_dac_cap <= 1023:
            raise ValueError("transition_dac_floor/cap must satisfy 0 <= floor <= cap <= 1023")
        if self.final_window_before < 0 or self.final_window_after < 0:
            raise ValueError("final_window_before/after must be >= 0")
        if self.final_dac_step <= 0:
            raise ValueError("final_dac_step must be positive")
        if not 0.0 < self.target_percent < 100.0:
            raise ValueError("target_percent must be in range 0..100 (exclusive)")
        for name in ("initialize_fpga", "apply_defaults"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")

    def registers(self):
        """Registers this operation reads/writes, for CSV completeness checks.

        The union of every sub-scan's own `ScurveJobConfig.registers()` (they
        differ only in which channels are included, so the all-channels case
        covers every one) plus each selected channel's calibration-DAC row.
        """

        widest = ScurveJobConfig(ScurveConfig(
            channels=self.channels, t1=self.t1, use_mask=self.use_mask,
            use_ctest=self.use_ctest, trigger_preamp_gain=self.trigger_preamp_gain))
        registers = set(widest.registers())
        subadd = 4 if self.t1 else 5
        registers.update((channel, subadd) for channel in self.channels)
        return sorted(registers)

    def load_rows(self, existing=()) -> list[I2CRow]:
        self.validate()
        if self.config_path is None and existing:
            rows = deepcopy(list(existing))
        else:
            with Path(self.config_path or DEFAULT_CONFIG).open(newline="") as stream:
                rows = [I2CRow(int(r["add"]), int(r["subadd"]), r["data"].strip())
                        for r in csv.DictReader(stream)]
        keys = set()
        for row in rows:
            if not (0 <= row.add <= 255 and 0 <= row.subadd <= 255):
                raise ValueError("ASIC address/subaddress must be in range 0..255")
            if len(row.data) != 8 or set(row.data) - {"0", "1"}:
                raise ValueError(f"invalid ASIC data at {(row.add, row.subadd)}")
            key = (row.add, row.subadd)
            if key in keys:
                raise ValueError(f"duplicate ASIC row: {key}")
            keys.add(key)
        required = set(self.registers()) - {(66, ch) for ch in range(N_CHANNELS)}
        missing = required - keys
        if missing:
            raise ValueError(f"configuration lacks calibration registers: {sorted(missing)}")
        return rows

    def as_dict(self):
        data = asdict(self)
        data["out_dir"] = str(self.out_dir)
        data["config_path"] = str(self.config_path) if self.config_path is not None else None
        return data


@dataclass
class AutocalibrationResult:
    """Outcome of one automatic-threshold-calibration run.

    **Attributes**
    - `out_dir` (`Path`): Top-level run directory.
    - `metadata_path` (`Path | None`): Top-level manifest path.
    - `status` (`str`): `"completed"`, `"cancelled"`, `"failed"` or
      `"disconnected"`.
    - `reference_channel` (`int | None`): Channel used for the LSB-ratio probe.
    - `lsb_ratio` (`float | None`): Estimated DAC codes per trim-DAC LSB.
    - `crossings` (`dict[int, float | None]`): Each channel's step-2 crossing.
    - `mean_position` (`float | None`): Mean of the valid step-2 crossings.
    - `calibration_before`/`calibration_after` (`dict[int, int]`): Each
      channel's calibration trim DAC before/after correction.
    - `sub_runs` (`dict[str, Path]`): Each sub-scan's own output directory.
    - `reference_restored` (`bool | None`): Whether the reference channel's
      probed-away calibration trim was confirmed restored (only checked when
      `verify_restoration` is requested).
    - `warnings` (`list[str]`): Non-fatal warnings.
    - `error` (`BaseException | None`): The exception that ended the run, if any.
    - `execution_mode` (`str`): `"hardware"`, `"simulation"` or `"dry-run"`.
    """

    out_dir: Path
    metadata_path: Path | None = None
    status: str = "completed"
    reference_channel: int | None = None
    lsb_ratio: float | None = None
    crossings: dict = field(default_factory=dict)
    mean_position: float | None = None
    calibration_before: dict = field(default_factory=dict)
    calibration_after: dict = field(default_factory=dict)
    sub_runs: dict = field(default_factory=dict)
    reference_restored: bool | None = None
    warnings: list = field(default_factory=list)
    error: BaseException | None = None
    execution_mode: str = "hardware"


class AutocalibrationJob:
    def run(self, device: RadiorocDevice, config: AutocalibrationJobConfig, *,
            metadata: RadiorocRunMetadata | None = None,
            cancellation: CancellationToken | None = None, on_event=None,
            verify_restoration: bool = False) -> AutocalibrationResult:
        """Run the four-step calibration sequence, or report a dry-run preview.

        Invalid input or an occupied session raises before any hardware
        operation. Callbacks run on the caller's thread and must be quick.
        """

        config = deepcopy(config)
        config.validate()
        if not isinstance(verify_restoration, bool):
            raise ValueError("verify_restoration must be boolean")
        result = AutocalibrationResult(out_dir=Path(config.out_dir))
        if device.dry_run:
            result.execution_mode = "dry-run"
            result.status = "completed"
            return result
        lock = session_lock(device.transport)
        if not lock.acquire(blocking=False):
            raise JobBusyError("another job is running on this transport session")
        try:
            return self._run_locked(device, config, result,
                                    cancellation or CancellationToken(), on_event,
                                    verify_restoration, metadata)
        finally:
            lock.release()

    def _run_sub_scan(self, device, *, out_dir, channels, dac_min, dac_max, dac_step,
                      config, metadata, cancellation, on_event) -> ScurveResult:
        scan = ScurveConfig(channels=list(channels), dac_min=dac_min, dac_max=dac_max,
                            dac_step=dac_step, t1=config.t1, use_mask=config.use_mask,
                            use_ctest=config.use_ctest, clock_index=config.clock_index,
                            trigger_level=config.trigger_level,
                            trigger_preamp_gain=config.trigger_preamp_gain, out_dir=out_dir)
        sub_config = ScurveJobConfig(scan)
        sub_config.validate()
        rows = sub_config.load_rows(device.i2c_rows)
        total = len(scan_values(scan.dac_min, scan.dac_max, scan.dac_step, name="DAC"))
        sub_result = ScurveResult(csv_path=Path(scan.out_dir) / "scurve.csv",
                                  metadata=metadata, channels=list(scan.channels))
        return ScurveJob()._run_locked(device, sub_config, rows, sub_result, total,
                                       cancellation, on_event, False)

    def _run_locked(self, device, config, result, token, on_event, verify_restoration,
                    metadata):
        started_dir = Path(config.out_dir)
        manifest = {"operation": config.as_dict(), "status": "preparing", "sub_runs": {}}
        writer = None
        subadd = 4 if config.t1 else 5
        reference_channel = config.channels[0]

        def persist():
            if writer is not None:
                manifest.update(status=result.status, error=_describe(result.error),
                                warnings=list(result.warnings))
                manifest["sub_runs"] = {name: str(path) for name, path in result.sub_runs.items()}
                writer.update(manifest)

        try:
            token.checkpoint()
            rows = config.load_rows(device.i2c_rows)
            device.i2c_rows = rows
            started_dir.mkdir(parents=True, exist_ok=True)
            writer = _TopLevelManifestWriter(started_dir, manifest)
            result.metadata_path = writer.metadata_path
            if config.initialize_fpga:
                device.initialize_fpga()
            if config.apply_defaults:
                device.apply_default_config()
            persist()

            original_calibration = {}
            for channel in config.channels:
                row = device.find_i2c_row(channel, subadd)
                if row is not None:
                    original_calibration[channel] = parse_bits(row.data) & 0x3F
            if reference_channel not in original_calibration:
                raise ValueError(
                    f"no calibration row found for reference channel {reference_channel}")
            result.calibration_before = dict(original_calibration)
            result.reference_channel = reference_channel

            # -- Step 1: 2-step LSB estimate on the reference channel -------
            zero_estimate = full_estimate = None
            reference_restored = True
            try:
                device.set_calibration_dac_for_channel(reference_channel, t1=config.t1, value=0)
                zero_out = started_dir / "step1_zero"
                zero_result = self._run_sub_scan(
                    device, out_dir=zero_out, channels=[reference_channel],
                    dac_min=config.probe_dac_min, dac_max=config.probe_dac_max,
                    dac_step=config.probe_dac_step, config=config, metadata=metadata,
                    cancellation=token, on_event=on_event)
                result.sub_runs["step1_zero"] = zero_out
                if zero_result.status != "completed":
                    return self._finish(result, zero_result.status, zero_result.error, persist)
                zero_estimate = estimate_scurve_crossings(
                    _read_run_rows(zero_out), [reference_channel],
                    target_percent=config.target_percent)[reference_channel]

                device.set_calibration_dac_for_channel(reference_channel, t1=config.t1, value=63)
                full_out = started_dir / "step1_full"
                full_result = self._run_sub_scan(
                    device, out_dir=full_out, channels=[reference_channel],
                    dac_min=config.probe_dac_min, dac_max=config.probe_dac_max,
                    dac_step=config.probe_dac_step, config=config, metadata=metadata,
                    cancellation=token, on_event=on_event)
                result.sub_runs["step1_full"] = full_out
                if full_result.status != "completed":
                    return self._finish(result, full_result.status, full_result.error, persist)
                full_estimate = estimate_scurve_crossings(
                    _read_run_rows(full_out), [reference_channel],
                    target_percent=config.target_percent)[reference_channel]
            finally:
                # A failed restore must never mask whatever the try block was
                # already returning/raising (mirrors ScurveJob's cleanup_call
                # convention: cleanup errors are recorded, never allowed to
                # replace the primary outcome).
                try:
                    device.set_calibration_dac_for_channel(
                        reference_channel, t1=config.t1,
                        value=original_calibration[reference_channel])
                except Exception as restore_error:
                    reference_restored = False
                    result.warnings.append(
                        f"failed to restore reference channel {reference_channel}'s "
                        f"calibration DAC: {_describe(restore_error)}")
                else:
                    if verify_restoration:
                        try:
                            restored_row = device.find_i2c_row(reference_channel, subadd)
                            reference_restored = (
                                restored_row is not None and
                                parse_bits(restored_row.data) & 0x3F ==
                                original_calibration[reference_channel])
                        except Exception as verify_error:
                            reference_restored = False
                            result.warnings.append(
                                "failed to verify reference-channel restoration: "
                                f"{_describe(verify_error)}")
            result.reference_restored = reference_restored if verify_restoration else None
            persist()

            if zero_estimate is None or full_estimate is None or full_estimate == zero_estimate:
                lsb_ratio = 1.0
                result.warnings.append(
                    "could not estimate an LSB ratio from the reference channel; using 1.0")
            else:
                lsb_ratio = max(abs(full_estimate - zero_estimate) / 63.0, 0.25)
            result.lsb_ratio = lsb_ratio

            # -- Step 2: transition window across every selected channel ---
            token.checkpoint()
            candidates = [p for p in (zero_estimate, full_estimate) if p is not None]
            transition_max = min(config.transition_dac_cap, max(
                config.transition_dac_floor, int(max(candidates or [150]) + config.transition_margin)))
            transition_out = started_dir / "step2"
            transition_result = self._run_sub_scan(
                device, out_dir=transition_out, channels=config.channels,
                dac_min=0, dac_max=transition_max, dac_step=config.transition_dac_step,
                config=config, metadata=metadata, cancellation=token, on_event=on_event)
            result.sub_runs["step2"] = transition_out
            if transition_result.status != "completed":
                return self._finish(result, transition_result.status, transition_result.error, persist)
            positions = estimate_scurve_crossings(
                _read_run_rows(transition_out), config.channels, target_percent=config.target_percent)
            result.crossings = positions
            valid_positions = [p for p in positions.values() if p is not None]
            mean_position = statistics.mean(valid_positions) if valid_positions else 500.0
            result.mean_position = mean_position
            persist()

            # -- Step 3: apply corrected calibration trim DACs --------------
            token.checkpoint()
            applied = {}
            for channel in config.channels:
                current = original_calibration.get(channel)
                if current is None:
                    continue
                position = positions.get(channel)
                correction = 0 if position is None else round((position - mean_position) / lsb_ratio)
                value = min(63, max(0, current - correction))
                device.set_calibration_dac_for_channel(channel, t1=config.t1, value=value)
                applied[channel] = value
            result.calibration_after = applied
            persist()

            # -- Step 5: final verification scan -----------------------------
            token.checkpoint()
            final_min = max(0, int(mean_position) - config.final_window_before)
            final_max = min(1023, int(mean_position) + config.final_window_after)
            final_out = started_dir / "final"
            final_result = self._run_sub_scan(
                device, out_dir=final_out, channels=config.channels,
                dac_min=final_min, dac_max=final_max, dac_step=config.final_dac_step,
                config=config, metadata=metadata, cancellation=token, on_event=on_event)
            result.sub_runs["final"] = final_out
            if final_result.status != "completed":
                return self._finish(result, final_result.status, final_result.error, persist)

            return self._finish(result, "completed", None, persist)
        except (JobCancelled, KeyboardInterrupt) as exc:
            return self._finish(result, "cancelled", exc, persist)
        except Exception as exc:
            status = "disconnected" if isinstance(exc, (TransportIOError, TransportClosedError)) else "failed"
            return self._finish(result, status, exc, persist)

    @staticmethod
    def _finish(result, status, error, persist):
        result.status = status
        result.error = error
        persist()
        return result


def _read_run_rows(out_dir: Path) -> list[dict]:
    return list(read_scurve_run(out_dir).rows)


class _TopLevelManifestWriter:
    """Minimal atomic-write manifest for the top-level autocalibration run.

    Each sub-scan already writes its own full manifest/CSV via
    `radioroc.data.scurve.ScurveRunWriter`; this only needs to record the
    operation config, overall status, and which sub-directories belong to
    this run, so it is its own small writer rather than adapting
    `ScurveRunWriter` (which expects to own a `scurve.csv` this run never
    produces at its own top level).
    """

    def __init__(self, directory: Path, manifest: dict):
        self.directory = Path(directory)
        self.metadata_path = self.directory / "autocalibration_metadata.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.metadata_path.exists():
            raise FileExistsError(f"refusing to overwrite run file: {self.metadata_path}")
        with self.metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())

    def update(self, manifest: dict) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".autocalibration_metadata-", suffix=".tmp",
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(manifest, stream, indent=2, allow_nan=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.metadata_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)
