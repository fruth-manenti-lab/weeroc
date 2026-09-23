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
      output directory containing its own completed `metadata.json`.
    - `excluded_channels`: iterable of `{"channel": ..., "reason": ...}` dicts
      (or 2-tuples `(channel, reason)`), passed through as-is.
    - `hold_delay_ns`, `conversion_delay_ns`, `trigger_preamp_gain_code`,
      `shaper_gain_codes`: optional calibration settings, passed through as-is.

    **Returns**
    - `Path`: the path written (same as `out_path`).

    **Raises**
    - `ValueError`: a referenced sub-scan directory has no `metadata.json`,
      is not `status: "completed"`, or the sub-scans disagree on
      `board_identity`.
    """

    out_path = Path(out_path)
    sub_scans: dict[str, dict] = {}
    board_identities: dict[str, str] = {}
    for label, directory in sub_scan_dirs.items():
        directory = Path(directory)
        metadata_path = directory / "metadata.json"
        if not metadata_path.is_file():
            raise ValueError(f"sub-scan {label!r} has no metadata.json at {metadata_path}")
        manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
        status = manifest.get("status")
        if status != "completed":
            raise ValueError(f"sub-scan {label!r} is not completed (status={status!r})")
        board_identities[label] = manifest.get("board_identity")
        sub_scans[label] = {"path": str(directory), "status": "completed"}

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
