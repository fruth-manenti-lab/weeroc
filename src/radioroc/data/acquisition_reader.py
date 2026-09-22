"""Read and validate saved ADC acquisition runs without UI dependencies.

Mirrors `radioroc.data.threshold_reader`'s defensive manifest-vs-CSV
cross-validation (warn-and-degrade rather than raise wherever the data can
still be shown), adapted to acquisition's different shape: `events.csv` is a
variable-length tall/long log (`batch,event,channel,hg,lg`, one row per
physical ADC event per channel) rather than threshold's fixed, strictly-
ascending DAC grid, and `AcquisitionRunWriter`'s `append=True` mode lets the
CSV accumulate rows from multiple separate job runs while `metadata.json`
only ever reflects the *latest* run's own manifest (replaced, not merged, on
each append -- see `AcquisitionRunWriter.__init__`). So unlike threshold,
the whole CSV can never be validated against the manifest wholesale; only
the portion the manifest's own `start_batch`/`batches` claims to have
written (the "current segment") can be.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path


_CSV_NAME = "events.csv"
_METADATA_NAME = "metadata.json"
_MAX_ROWS = 2_000_000
_EXPECTED_FIELDS = ["batch", "event", "channel", "hg", "lg"]
_NONTERMINAL = {"preparing", "running", "cancelling"}


@dataclass(frozen=True)
class SavedAcquisitionRun:
    directory: Path
    manifest: dict
    rows: tuple[dict, ...]
    current_segment_rows: tuple[dict, ...]
    channels: list[int]
    status: str
    execution_mode: str
    warnings: tuple[str, ...]


def read_acquisition_run(path: Path) -> SavedAcquisitionRun:
    """Open a schema-1 acquisition run directory/manifest/CSV, or a legacy bare CSV."""
    directory, csv_path, metadata_path = _resolve_paths(Path(path))
    has_manifest = metadata_path.exists()
    manifest = _read_manifest(metadata_path) if has_manifest else {}
    warnings: list[str] = []

    if has_manifest:
        if manifest.get("schema_version") != 1:
            raise ValueError(f"unsupported acquisition manifest schema: {manifest.get('schema_version')!r}")
        manifest_channels, start_batch, batches = _manifest_acquisition(manifest)
    else:
        manifest_channels = None

    # Row parsing never rejects a row for using a channel outside the
    # current manifest's channel list. events.csv can hold rows from earlier
    # append segments that legitimately used a different --channels value
    # (nothing prevents that today), and this reader must not let an old
    # segment's channel set corrupt its read of the CURRENT segment: csv.Error
    # handling below treats a bad row as "the tail is truncated" and discards
    # everything from that point on, which would silently drop the current
    # (later, more relevant) segment's genuinely valid rows if an earlier
    # segment's channel mismatch were treated as a parse failure. Channel
    # membership is instead cross-checked against `current_segment_rows`
    # only, further down, as a warning -- the same "warn on the segment
    # that matters, tolerate the rest of the file" treatment `batches`
    # already gets.
    rows, csv_warnings = _read_rows(csv_path)
    warnings.extend(csv_warnings)

    if not has_manifest:
        channels = sorted({row["channel"] for row in rows})
        warnings.append("provenance unavailable: metadata.json was not found")
        return SavedAcquisitionRun(directory, {}, rows, rows, channels, "unknown", "unknown", tuple(warnings))

    channels = list(manifest_channels)

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
    verification = manifest.get("verification")
    if "verification" in manifest:
        verification_status = verification.get("status") if isinstance(verification, dict) else None
        if verification_status != "passed":
            inconsistencies.append(f"restoration verification did not pass ({verification_status!r})")
            if status in {"completed", "cancelled"}:
                status = "incomplete"
        if isinstance(verification, dict):
            for error in verification.get("errors", ()):
                warnings.append(f"verification error: {error}")

    # The append-mode subtlety: metadata.json only ever describes the latest
    # run's own segment, so cross-validate that segment against the manifest
    # rather than the whole (possibly multi-run) CSV history.
    expected_batches = range(start_batch, start_batch + batches)
    expected_batch_set = set(expected_batches)
    current_segment_rows = tuple(row for row in rows if row["batch"] in expected_batch_set)
    segment_batches = {row["batch"] for row in current_segment_rows}
    # `current_segment_rows` is filtered to `expected_batch_set` by
    # construction, so `segment_batches` can never contain a batch outside
    # it; the only way this segment can disagree with the manifest is by
    # *missing* batches the manifest's own batches/start_batch imply it
    # should have written. That "missing" case is the one checked below.
    if original_status == "completed" and segment_batches != expected_batch_set:
        missing = sorted(expected_batch_set - segment_batches)
        inconsistencies.append(f"CSV is missing batches the manifest expects: {missing}")
    segment_channels = {row["channel"] for row in current_segment_rows}
    unexpected_channels = sorted(segment_channels - set(manifest_channels))
    if unexpected_channels:
        inconsistencies.append(
            f"CSV rows in this run's own batch range use channels the manifest doesn't declare: "
            f"{unexpected_channels}"
        )
    completed_points = manifest.get("completed_points")
    if not _is_int(completed_points) or completed_points != len(segment_batches):
        inconsistencies.append(
            f"manifest completed_points is {completed_points!r}; "
            f"CSV has {len(segment_batches)} distinct batches in this run's segment"
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
    return SavedAcquisitionRun(directory, manifest, rows, current_segment_rows, channels,
                               status, mode, tuple(_unique(warnings)))


def _resolve_paths(path: Path) -> tuple[Path, Path, Path]:
    if path.is_dir():
        directory = path
    elif path.name in {_CSV_NAME, _METADATA_NAME}:
        if path.name == _METADATA_NAME and not path.is_file():
            raise FileNotFoundError(path)
        directory = path.parent
    else:
        raise ValueError("acquisition run path must be a directory, metadata.json, or events.csv")
    csv_path = directory / _CSV_NAME
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    return directory, csv_path, directory / _METADATA_NAME


def _read_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read acquisition manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("acquisition manifest must contain a JSON object")
    return value


def _manifest_acquisition(manifest: dict) -> tuple[list[int], int, int]:
    try:
        acquisition = manifest["operation"]["acquisition"]
        channels = acquisition["channels"]
        batches = acquisition["batches"]
    except (KeyError, TypeError) as exc:
        raise ValueError("acquisition manifest lacks operation.acquisition configuration") from exc
    start_batch = acquisition.get("start_batch", 0) if isinstance(acquisition, dict) else 0
    if (not isinstance(channels, list) or not channels or
            any(not _is_int(ch) or not 0 <= ch < 64 for ch in channels) or
            len(set(channels)) != len(channels)):
        raise ValueError("manifest acquisition channels must be unique integers in range 0..63")
    if not _is_int(batches) or batches < 0:
        raise ValueError("manifest acquisition batches must be a non-negative integer")
    if not _is_int(start_batch) or start_batch < 0:
        raise ValueError("manifest acquisition start_batch must be a non-negative integer")
    return channels, start_batch, batches


def _read_rows(path: Path) -> tuple[tuple[dict, ...], list[str]]:
    warnings: list[str] = []
    valid: list[dict] = []
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames
            if fields is None:
                raise ValueError("acquisition CSV has no header")
            if list(fields) != _EXPECTED_FIELDS:
                raise ValueError(f"acquisition CSV columns are {fields!r}; expected {_EXPECTED_FIELDS!r}")
            for number, row in enumerate(reader, start=2):
                if len(valid) >= _MAX_ROWS:
                    warnings.append(f"CSV exceeds the {_MAX_ROWS}-row defensive limit; remaining rows were ignored")
                    break
                try:
                    valid.append(_parse_row(row))
                except (TypeError, ValueError) as exc:
                    warnings.append(f"invalid CSV tail at row {number}: {exc}; later rows were ignored")
                    break
    except csv.Error as exc:
        warnings.append(f"truncated or malformed CSV tail: {exc}")
    return tuple(valid), warnings


def _parse_row(row: dict) -> dict:
    if None in row or set(row) != set(_EXPECTED_FIELDS) or any(row[field] is None for field in _EXPECTED_FIELDS):
        raise ValueError("column count does not match the header")
    batch = _parse_nonneg_int(row["batch"], "batch")
    event = _parse_nonneg_int(row["event"], "event")
    channel = _parse_nonneg_int(row["channel"], "channel")
    parsed = {"batch": batch, "event": event, "channel": channel}
    for field in ("hg", "lg"):
        try:
            value = float(row[field])
        except ValueError as exc:
            raise ValueError(f"{field} is not numeric") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{field} must be finite and nonnegative")
        parsed[field] = value
    return parsed


def _parse_nonneg_int(text: str, name: str) -> int:
    text = text.strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not an integer") from exc
    if str(value) != text or value < 0:
        raise ValueError(f"{name} must be a canonical non-negative integer")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
