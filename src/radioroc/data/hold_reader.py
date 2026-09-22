"""Minimal reader for saved hold-scan runs, for the GUI's "reopen" feature.

This is a v1 scope reduction relative to ``radioroc.data.threshold_reader``:
it loads the manifest and CSV and does light structural validation, but it
does not attempt threshold_reader's extensive cross-validation between the
manifest and CSV (DAC/point-value ordering cross-checks, legacy bare-CSV
channel inference, a 1024-point salvage cap, and so on). It is intended to
let the hold-scan GUI display a previously saved run, not to be a
fault-tolerant archival format reader.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path

_CSV_NAME = "holdscan.csv"
_METADATA_NAME = "metadata.json"


@dataclass(frozen=True)
class SavedHoldRun:
    directory: Path
    manifest: dict
    rows: tuple[dict, ...]
    status: str
    execution_mode: str
    x_name: str
    warnings: tuple[str, ...]


def read_hold_run(path: Path) -> SavedHoldRun:
    """Open a hold-scan run directory/manifest/CSV.

    Accepts a run directory, its ``metadata.json``, or its ``holdscan.csv``.
    """

    path = Path(path)
    if path.is_dir():
        directory = path
    elif path.name in {_CSV_NAME, _METADATA_NAME}:
        directory = path.parent
    else:
        raise ValueError("hold-scan run path must be a directory, metadata.json, or holdscan.csv")
    csv_path = directory / _CSV_NAME
    metadata_path = directory / _METADATA_NAME
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)

    warnings: list[str] = []
    manifest: dict = {}
    if metadata_path.is_file():
        try:
            manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read hold-scan manifest {metadata_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("hold-scan manifest must contain a JSON object")
    else:
        warnings.append("provenance unavailable: metadata.json was not found")

    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if not fields:
            raise ValueError("hold-scan CSV has no header")
        x_name = fields[0]
        rows = []
        for row in reader:
            if None in row or any(row[field] is None for field in fields):
                warnings.append("a CSV row had the wrong column count; later rows were ignored")
                break
            try:
                parsed = {x_name: int(row[x_name])}
                for field in fields[1:]:
                    parsed[field] = int(row[field]) if field.endswith("_count") else float(row[field])
            except ValueError as exc:
                warnings.append(f"invalid CSV row skipped: {exc}")
                continue
            rows.append(parsed)

    operation = manifest.get("operation") if isinstance(manifest.get("operation"), dict) else {}
    scan = operation.get("scan") if isinstance(operation.get("scan"), dict) else {}
    manifest_x_name = "hold_code" if scan.get("mode") == "internal" else (
        "hold_delay_ns" if scan.get("mode") == "external" else None)
    if manifest_x_name is not None and manifest_x_name != x_name:
        warnings.append(
            f"CSV x-axis column {x_name!r} does not match manifest mode-implied {manifest_x_name!r}")

    status = manifest.get("status") if isinstance(manifest.get("status"), str) else "unknown"
    if status in {"preparing", "running", "cancelling"}:
        warnings.append(f"saved run was nonterminal ({status!r}); showing it as incomplete")
        status = "incomplete"
    cleanup = manifest.get("cleanup") if isinstance(manifest.get("cleanup"), dict) else {}
    if cleanup.get("errors"):
        warnings.extend(f"cleanup error: {error}" for error in cleanup["errors"])
    persistence_errors = manifest.get("persistence_errors")
    if isinstance(persistence_errors, list) and persistence_errors:
        warnings.extend(f"storage error: {error}" for error in persistence_errors)
    verification = manifest.get("verification")
    if isinstance(verification, dict) and verification.get("status") not in (None, "passed"):
        warnings.append(f"restoration verification did not pass ({verification.get('status')!r})")
    execution_mode = manifest.get("execution_mode") if isinstance(manifest.get("execution_mode"), str) else "unknown"

    return SavedHoldRun(directory, manifest, tuple(rows), status, execution_mode, x_name, tuple(warnings))
