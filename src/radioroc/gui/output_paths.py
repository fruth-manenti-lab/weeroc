"""Run-directory defaults that follow the Simulation/Hardware device mode."""
from __future__ import annotations

import re
from pathlib import Path

_STAMP = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
_MODES = ("simulation", "hardware")


def auto_directory_mode(text):
    """Return 'simulation'/'hardware' if text is an app-generated default directory, else None."""
    path = Path(str(text).strip())
    if (_STAMP.match(path.name) and path.parent.name in _MODES
            and path.parent.parent.name == "radioroc_runs"):
        return path.parent.name
    return None


def tree_mode(text):
    """Return which radioroc_runs/<mode> tree a path lives in, or None."""
    parts = Path(str(text).strip()).parts
    if "radioroc_runs" not in parts:
        return None
    rest = parts[parts.index("radioroc_runs") + 1:]
    return rest[0] if rest and rest[0] in _MODES else None


def refresh_auto_output(field, mode_name, new_directory):
    """Regenerate an auto-generated default for mode_name; keep user-chosen paths."""
    current = auto_directory_mode(field.text())
    if current is not None and current != mode_name:
        field.setText(new_directory(mode_name))


def guard_output(field, mode_name, new_directory):
    """Run-start guard. An auto default in the wrong tree is regenerated; a user-chosen
    path inside the opposite radioroc_runs tree is refused (never silently moved)."""
    text = field.text().strip()
    wrong = tree_mode(text)
    if wrong is None or wrong == mode_name:
        return text
    if auto_directory_mode(text) is not None:
        field.setText(new_directory(mode_name))
        return field.text().strip()
    raise ValueError(f"{mode_name.title()} run but the output directory is inside "
                     f"radioroc_runs/{wrong}/; choose a {mode_name} directory or use the default")
