"""Save and load an attributable plint calibration record.

Step 6 of the plint calibration procedure (``docs/plint_calibration_procedure.md``)
asks for a single saved artifact that ties together the sub-scans (pedestal,
threshold alignment, gain, hold scan, ...) run during a calibration, plus the
operator's judgment calls (excluded channels, threshold margin reasoning, the
chosen per-channel relative response values). This module writes and reads
that record; it does not compute any of the values, choose an output
location, or know about run-directory naming -- callers own all of that.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

_SCHEMA_VERSION = 1
_AUTOCAL_NAME = "autocalibration_metadata.json"


def _read_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest for {label!r} at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"manifest for {label!r} at {path} is not a JSON object")
    return data


def _int_in_range(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}, got {value!r}")


def _validate_settings(threshold_dac, hold_delay_ns, conversion_delay_ns,
                       trigger_preamp_gain_code, shaper_gain_codes):
    _int_in_range("threshold_dac", threshold_dac, 0, 1023)
    for name, value in (("hold_delay_ns", hold_delay_ns),
                        ("conversion_delay_ns", conversion_delay_ns)):
        if value is not None:
            _int_in_range(name, value, 0, 1_000_000)
    if trigger_preamp_gain_code is not None:
        _int_in_range("trigger_preamp_gain_code", trigger_preamp_gain_code, 0, 255)
    if shaper_gain_codes is not None:
        if not isinstance(shaper_gain_codes, dict) or not set(shaper_gain_codes) <= {"HG", "LG"}:
            raise ValueError("shaper_gain_codes must be a dict with keys HG and/or LG")
        for key, value in shaper_gain_codes.items():
            _int_in_range(f"shaper_gain_codes[{key}]", value, 0, 255)


def save_calibration_record(
    out_path,
    *,
    operator,
    threshold_dac,
    threshold_margin_reasoning,
    per_channel_relative_response,
    sub_scan_dirs,
    excluded_channels=(),
    hold_delay_ns=None,
    conversion_delay_ns=None,
    trigger_preamp_gain_code=None,
    shaper_gain_codes=None,
) -> Path:
    """Validate referenced sub-scans and write a schema-1 calibration record.

    **Inputs**
    - `out_path`: full file path to write to (parent directories are created).
    - `operator`: str, who ran the calibration.
    - `threshold_dac`: int, the chosen threshold DAC code.
    - `threshold_margin_reasoning`: str, why that margin was chosen.
    - `per_channel_relative_response`: dict[str, float], caller-supplied
      per-channel plateau/response values (e.g. `{"ch4": 10800.0}`).
    - `sub_scan_dirs`: dict[str, str | Path] mapping a step label to a run
      output directory containing its own completed `metadata.json` (with `verification.status`
      `passed` if it has a verification field), or an autocalibration run
      directory (`autocalibration_metadata.json`, completed with final
      verification passed). Must be non-empty.
    - `excluded_channels`: iterable of `{"channel": ..., "reason": ...}` dicts
      (or 2-tuples `(channel, reason)`), passed through as-is.
    - `hold_delay_ns`, `conversion_delay_ns`, `trigger_preamp_gain_code`,
      `shaper_gain_codes`: optional calibration settings, passed through as-is.

    **Returns**
    - `Path`: the path written (same as `out_path`).

    **Raises**
    - `ValueError`: threshold/timing/gain values out of range, no sub-scans, a
      referenced sub-scan directory has no `metadata.json`/autocalibration manifest,
      is not `status: "completed"`, or the sub-scans disagree on
      `board_identity`.
    """

    out_path = Path(out_path)
    _validate_settings(threshold_dac, hold_delay_ns, conversion_delay_ns,
                       trigger_preamp_gain_code, shaper_gain_codes)
    if not sub_scan_dirs:
        raise ValueError("calibration record needs at least one sub-scan as evidence")
    sub_scans: dict[str, dict] = {}
    board_identities: dict[str, str] = {}
    for label, directory in sub_scan_dirs.items():
        directory = Path(directory)
        metadata_path = directory / "metadata.json"
        autocal_path = directory / _AUTOCAL_NAME
        if metadata_path.is_file():
            manifest = _read_json(metadata_path, label)
            status = manifest.get("status")
            if status != "completed":
                raise ValueError(f"sub-scan {label!r} is not completed (status={status!r})")
            if "verification" in manifest:
                verification = manifest["verification"]
                verification_status = (verification.get("status")
                                       if isinstance(verification, dict) else None)
                if verification_status != "passed":
                    raise ValueError(
                        f"sub-scan {label!r} verification did not pass "
                        f"(verification.status={verification_status!r})")
            board_identities[label] = manifest.get("board_identity")
            sub_scans[label] = {"path": str(directory), "status": "completed"}
        elif autocal_path.is_file():
            manifest = _read_json(autocal_path, label)
            status = manifest.get("status")
            if status != "completed":
                raise ValueError(
                    f"autocalibration run {label!r} is not completed (status={status!r})")
            calibration_status = manifest.get("calibration_status")
            if calibration_status is not None and calibration_status != "verified":
                raise ValueError(
                    f"autocalibration run {label!r} calibration is not verified "
                    f"(calibration_status={calibration_status!r})")
            sub_runs = manifest.get("sub_runs")
            final_path = sub_runs.get("final") if isinstance(sub_runs, dict) else None
            if not final_path:
                raise ValueError(
                    f"autocalibration run {label!r} has no final verification scan")
            final_manifest_path = Path(final_path) / "metadata.json"
            if not final_manifest_path.is_file():
                raise ValueError(
                    f"autocalibration run {label!r} final scan has no metadata.json "
                    f"at {final_manifest_path}")
            final_manifest = _read_json(final_manifest_path, label)
            if final_manifest.get("status") != "completed":
                raise ValueError(
                    f"autocalibration run {label!r} final verification scan is not "
                    f"completed (status={final_manifest.get('status')!r})")
            verification = final_manifest.get("verification")
            if verification is not None and (
                    not isinstance(verification, dict) or verification.get("status") != "passed"):
                raise ValueError(
                    f"autocalibration run {label!r} final verification did not pass")
            board_identities[label] = final_manifest.get("board_identity")
            sub_scans[label] = {"path": str(directory), "status": "completed",
                                "kind": "autocalibration"}
        else:
            raise ValueError(
                f"sub-scan {label!r} has no metadata.json or {_AUTOCAL_NAME} at {directory}")

    distinct = set(board_identities.values())
    if len(distinct) > 1:
        conflicts = ", ".join(f"{label}={identity!r}" for label, identity in board_identities.items())
        raise ValueError(f"sub-scans disagree on board_identity: {conflicts}")
    board_identity = next(iter(distinct), None)

    excluded = [
        {"channel": entry[0], "reason": entry[1]} if isinstance(entry, tuple) else dict(entry)
        for entry in excluded_channels
    ]

    record = {
        "schema_version": _SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operator": operator,
        "board_identity": board_identity,
        "threshold_dac": threshold_dac,
        "threshold_margin_reasoning": threshold_margin_reasoning,
        "per_channel_relative_response": dict(per_channel_relative_response),
        "excluded_channels": excluded,
        "hold_delay_ns": hold_delay_ns,
        "conversion_delay_ns": conversion_delay_ns,
        "trigger_preamp_gain_code": trigger_preamp_gain_code,
        "shaper_gain_codes": shaper_gain_codes,
        "sub_scans": sub_scans,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out_path


def load_calibration_record(path) -> dict:
    """Read and validate a schema-1 calibration record.

    **Inputs**
    - `path`: path to a `calibration_record.json` file.

    **Returns**
    - `dict`: the parsed record.

    **Raises**
    - `ValueError`: `schema_version` is missing or not `1`.
    """

    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"unsupported calibration record schema: {record.get('schema_version')!r}")
    return record
