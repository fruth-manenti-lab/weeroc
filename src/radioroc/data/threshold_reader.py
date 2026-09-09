"""Read and validate saved threshold runs without UI dependencies."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


_CSV_NAME = "thresholdscan.csv"
_METADATA_NAME = "metadata.json"
_MAX_POINTS = 1024
_CHANNEL_COLUMN = re.compile(r"ch(\d+)")
_NONTERMINAL = {"preparing", "running", "cancelling"}


@dataclass(frozen=True)
class SavedThresholdRun:
    directory: Path
    manifest: dict
    rows: tuple[dict, ...]
    status: str
    execution_mode: str
    warnings: tuple[str, ...]


def read_threshold_run(path: Path) -> SavedThresholdRun:
    """Open a schema-1 run directory/manifest/CSV, or a legacy bare CSV."""
    directory, csv_path, metadata_path = _resolve_paths(Path(path))
    has_manifest = metadata_path.exists()
    manifest = _read_manifest(metadata_path) if has_manifest else {}
    warnings: list[str] = []

    if has_manifest:
        if manifest.get("schema_version") != 1:
            raise ValueError(f"unsupported threshold manifest schema: {manifest.get('schema_version')!r}")
        channels, expected_dacs = _manifest_scan(manifest)
        expected_fields = ["DAC", *(f"ch{channel}" for channel in channels)]
    else:
        expected_fields = None
        expected_dacs = None

    rows, csv_warnings, fields = _read_rows(csv_path, expected_fields)
    warnings.extend(csv_warnings)

    if not has_manifest:
        _legacy_channels(fields)
        warnings.append("provenance unavailable: metadata.json was not found")
        return SavedThresholdRun(directory, {}, rows, "unknown", "unknown", tuple(warnings))

    for warning in manifest.get("warnings", ()):
        warnings.append(f"run warning: {warning}")
    cleanup = manifest.get("cleanup", {})
    cleanup_errors = cleanup.get("errors", ()) if isinstance(cleanup, dict) else ()
    for error in cleanup_errors:
        warnings.append(f"cleanup error: {error}")
    persistence_errors = manifest.get("persistence_errors", ())
    for error in persistence_errors if isinstance(persistence_errors, list) else ():
        warnings.append(f"storage error: {error}")

    original_status = manifest.get("status")
    status = original_status if isinstance(original_status, str) else "incomplete"
    run_error = manifest.get("error")
    if original_status in {"failed", "disconnected"} and run_error:
        warnings.append(f"run error: {run_error}")
    terminal_statuses = {"completed", "cancelled", "failed", "disconnected"}
    if status in _NONTERMINAL or status not in terminal_statuses:
        warnings.append(f"saved run was nonterminal ({original_status!r}); showing it as incomplete")
        status = "incomplete"

    inconsistencies: list[str] = []
    for index, row in enumerate(rows):
        if index >= len(expected_dacs) or row["DAC"] != expected_dacs[index]:
            warnings.append(
                f"CSV DAC {row['DAC']} at point {index + 1} does not match the configured scan; later rows were ignored"
            )
            rows = rows[:index]
            break
    if original_status == "completed" and len(rows) != len(expected_dacs):
        inconsistencies.append(f"CSV has {len(rows)} valid points; expected {len(expected_dacs)}")
    completed_points = manifest.get("completed_points")
    if not _is_int(completed_points) or completed_points != len(rows):
        inconsistencies.append(
            f"manifest completed_points is {completed_points!r}; CSV has {len(rows)} valid points"
        )
    cleanup_failed = isinstance(cleanup, dict) and cleanup.get("status") == "failed"
    cleanup_incomplete = (original_status == "completed" and
                          (not isinstance(cleanup, dict) or cleanup.get("status") not in {"restored", "not_required"}))
    storage_failed = bool(persistence_errors)
    if cleanup_failed:
        inconsistencies.append("manifest reports failed cleanup")
    elif cleanup_incomplete:
        inconsistencies.append("manifest does not report completed cleanup")
    if cleanup_errors:
        inconsistencies.append("manifest reports cleanup errors")
    if storage_failed:
        inconsistencies.append("manifest reports storage errors")
    warnings.extend(_unique(inconsistencies))
    if original_status == "completed" and (csv_warnings or inconsistencies):
        status = "incomplete"

    mode = manifest.get("execution_mode", "unknown")
    if not isinstance(mode, str):
        mode = "unknown"
        warnings.append("manifest execution_mode is invalid")
    return SavedThresholdRun(directory, manifest, rows, status, mode, tuple(_unique(warnings)))


def _resolve_paths(path: Path) -> tuple[Path, Path, Path]:
    if path.is_dir():
        directory = path
    elif path.name in {_CSV_NAME, _METADATA_NAME}:
        if path.name == _METADATA_NAME and not path.is_file():
            raise FileNotFoundError(path)
        directory = path.parent
    else:
        raise ValueError("threshold run path must be a directory, metadata.json, or thresholdscan.csv")
    csv_path = directory / _CSV_NAME
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    return directory, csv_path, directory / _METADATA_NAME


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read threshold manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("threshold manifest must contain a JSON object")
    return value


def _manifest_scan(manifest: dict) -> tuple[list[int], list[int]]:
    try:
        scan = manifest["operation"]["scan"]
        channels = scan["channels"]
        dac_min, dac_max, dac_step = scan["dac_min"], scan["dac_max"], scan["dac_step"]
    except (KeyError, TypeError) as exc:
        raise ValueError("threshold manifest lacks operation.scan configuration") from exc
    if (not isinstance(channels, list) or not channels or
            any(not _is_int(ch) or not 0 <= ch < 64 for ch in channels) or
            len(set(channels)) != len(channels)):
        raise ValueError("manifest scan channels must be unique integers in range 0..63")
    if not all(_is_int(value) for value in (dac_min, dac_max, dac_step)):
        raise ValueError("manifest DAC bounds and step must be integers")
    if not (0 <= dac_min <= dac_max <= 1023) or dac_step <= 0:
        raise ValueError("manifest DAC scan must be ascending within range 0..1023")
    dacs = list(range(dac_min, dac_max + 1, dac_step))
    if len(dacs) > _MAX_POINTS:
        raise ValueError("manifest threshold scan exceeds 1024 points")
    total = manifest.get("total_points")
    if total is not None and (not _is_int(total) or total != len(dacs)):
        raise ValueError("manifest total_points does not match operation.scan")
    return channels, dacs


def _read_rows(path: Path, expected_fields: list[str] | None) -> tuple[tuple[dict, ...], list[str], list[str]]:
    warnings: list[str] = []
    valid: list[dict] = []
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames
            if fields is None:
                raise ValueError("threshold CSV has no header")
            if expected_fields is not None and fields != expected_fields:
                raise ValueError(f"threshold CSV columns are {fields!r}; expected {expected_fields!r}")
            _legacy_channels(fields)
            for number, row in enumerate(reader, start=2):
                if len(valid) >= _MAX_POINTS:
                    warnings.append("CSV exceeds the 1024-point threshold DAC limit; remaining rows were ignored")
                    break
                try:
                    valid.append(_parse_row(row, fields, valid[-1]["DAC"] if valid else None))
                except (TypeError, ValueError) as exc:
                    warnings.append(f"invalid CSV tail at row {number}: {exc}; later rows were ignored")
                    break
    except csv.Error as exc:
        warnings.append(f"truncated or malformed CSV tail: {exc}")
        fields = fields if "fields" in locals() and fields is not None else []
    return tuple(valid), warnings, list(fields)


def _legacy_channels(fields: list[str]) -> list[int]:
    if not fields or fields[0] != "DAC" or len(fields) < 2:
        raise ValueError("threshold CSV columns must begin with DAC and include a channel")
    channels = []
    for field in fields[1:]:
        match = _CHANNEL_COLUMN.fullmatch(field)
        if match is None or not 0 <= int(match.group(1)) < 64:
            raise ValueError(f"invalid threshold channel column: {field!r}")
        channels.append(int(match.group(1)))
    if len(channels) != len(set(channels)):
        raise ValueError("threshold CSV contains duplicate channel columns")
    return channels


def _parse_row(row: dict, fields: list[str], previous_dac: int | None) -> dict:
    if None in row or set(row) != set(fields) or any(row[field] is None for field in fields):
        raise ValueError("column count does not match the header")
    dac_text = row["DAC"].strip()
    try:
        dac = int(dac_text)
    except ValueError as exc:
        raise ValueError("DAC is not an integer") from exc
    if str(dac) != dac_text or not 0 <= dac <= 1023:
        raise ValueError("DAC must be a canonical integer in range 0..1023")
    if previous_dac is not None and dac <= previous_dac:
        raise ValueError("DAC values must be strictly ascending")
    parsed: dict = {"DAC": dac}
    for field in fields[1:]:
        try:
            rate = float(row[field])
        except ValueError as exc:
            raise ValueError(f"{field} rate is not numeric") from exc
        if not math.isfinite(rate) or rate < 0:
            raise ValueError(f"{field} rate must be finite and nonnegative")
        parsed[field] = rate
    return parsed


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
