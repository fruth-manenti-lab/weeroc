"""Small pure helpers that carry saved pedestals from the Calibration page into muon runs (no Qt, no hardware)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

NO_PEDESTALS_TEXT = "Pedestals: none yet, run the Pedestals step on the Calibration page"
NOT_SAVED_WARNING = ("No pedestals saved with this run: run the Pedestals step on the Calibration page "
                     "before a muon run")
MEDIAN_TEXT = "median of this run (biased for muon runs)"


def pedestal_time(pedestal_set) -> str:
    """Creation time of a pedestal set as saved ('' when unknown)."""
    return str(getattr(pedestal_set, "created_at", "") or "")


def missing_channels(pedestal_set, channels: Iterable[int]) -> list[int]:
    """Channels of ``channels`` without a high-gain pedestal in ``pedestal_set``."""
    have = set(pedestal_set.hg())
    return sorted({int(c) for c in channels} - have)


def pedestal_status_text(pedestal_set, run_channels: Iterable[int] | None = None) -> tuple[str, bool]:
    """(text, is_warning) for the Acquisition page status line."""
    if pedestal_set is None or not pedestal_set.hg():
        return NO_PEDESTALS_TEXT, True
    hg = pedestal_set.hg()
    when = pedestal_time(pedestal_set)
    text = "Pedestals: " + ", ".join(f"ch{c} {hg[c]:.1f}" for c in sorted(hg)[:6])
    if len(hg) > 6:
        text += f", +{len(hg) - 6} more"
    text += f" (HG, from pedestal run {when})" if when else " (HG, from pedestal run)"
    missing = missing_channels(pedestal_set, run_channels or ())
    if missing:
        return (f"{text}. Warning: no pedestal for selected channel(s) {', '.join(map(str, missing))}; "
                "they will not be saved with the run"), True
    return text, False


def write_run_pedestals(run_dir, pedestal_set, run_channels: Iterable[int]) -> tuple[bool, str]:
    """Save ``pedestal_set`` as run_dir/pedestals.json. Never overwrites; leaves events/metadata alone.
    Returns (written, message)."""
    from radioroc.data.pedestals import PEDESTALS_FILENAME, save_pedestals_json

    if pedestal_set is None or not pedestal_set.hg():
        return False, "no pedestals available"
    run_dir = Path(run_dir)
    target = run_dir / PEDESTALS_FILENAME
    if target.exists():
        return False, f"{PEDESTALS_FILENAME} already exists in the run folder"
    missing = missing_channels(pedestal_set, run_channels)
    if missing:
        return False, f"pedestals do not cover channel(s) {', '.join(map(str, missing))}"
    if not run_dir.is_dir():
        return False, "run folder not found"
    try:
        save_pedestals_json(target, pedestal_set)
    except OSError as exc:
        return False, f"could not write {PEDESTALS_FILENAME}: {exc}"
    return True, f"pedestals saved with the run ({PEDESTALS_FILENAME})"
