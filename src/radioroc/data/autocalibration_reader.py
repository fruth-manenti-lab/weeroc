"""Minimal reader for saved autocalibration (F08) runs, for the GUI's
"reopen" feature.

Same v1 scope reduction as ``radioroc.data.scurve_reader``/``hold_reader``:
loads the top-level manifest and each sub-scan directory it names, with
light structural validation, not exhaustive cross-validation. Each sub-scan
is itself a complete S-curve run (its own ``metadata.json``/``scurve.csv``),
so this reader composes ``read_scurve_run`` rather than re-parsing CSVs
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .scurve_reader import SavedScurveRun, read_scurve_run

_METADATA_NAME = "autocalibration_metadata.json"


@dataclass(frozen=True)
class SavedAutocalibrationRun:
    directory: Path
    manifest: dict
    sub_runs: dict[str, SavedScurveRun]
    status: str
    warnings: tuple[str, ...]


def read_autocalibration_run(path: Path) -> SavedAutocalibrationRun:
    """Open a saved autocalibration run directory/manifest.

    Accepts a run directory or its ``autocalibration_metadata.json``.
    """

    path = Path(path)
    if path.is_dir():
        directory = path
    elif path.name == _METADATA_NAME:
        directory = path.parent
    else:
        raise ValueError(
            "autocalibration run path must be a directory or autocalibration_metadata.json")
    metadata_path = directory / _METADATA_NAME
    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)

    try:
        manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read autocalibration manifest {metadata_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("autocalibration manifest must contain a JSON object")

    warnings: list[str] = []
    status = manifest.get("status") if isinstance(manifest.get("status"), str) else "unknown"
    if status in {"preparing", "running"}:
        warnings.append(f"saved run was nonterminal ({status!r}); showing it as incomplete")
        status = "incomplete"
    manifest_warnings = manifest.get("warnings")
    if isinstance(manifest_warnings, list):
        warnings.extend(str(item) for item in manifest_warnings)

    sub_run_paths = manifest.get("sub_runs")
    sub_runs: dict[str, SavedScurveRun] = {}
    if isinstance(sub_run_paths, dict):
        # Sub-runs are read in the fixed step order when present, so the GUI
        # can show them in a sensible sequence rather than dict/JSON order.
        for name in ("step1_zero", "step1_full", "step2", "final"):
            sub_path = sub_run_paths.get(name)
            if sub_path is None:
                continue
            try:
                sub_runs[name] = read_scurve_run(Path(sub_path))
            except (OSError, ValueError) as exc:
                warnings.append(f"could not read sub-run {name!r}: {exc}")
        for name, sub_path in sub_run_paths.items():
            if name in sub_runs or name in ("step1_zero", "step1_full", "step2", "final"):
                continue
            try:
                sub_runs[name] = read_scurve_run(Path(sub_path))
            except (OSError, ValueError) as exc:
                warnings.append(f"could not read sub-run {name!r}: {exc}")
    else:
        warnings.append("manifest lacks a sub_runs mapping")

    return SavedAutocalibrationRun(directory, manifest, sub_runs, status, tuple(warnings))
