"""Save and load a custom ASIC register table (CSV with ``add,subadd,data`` columns).

Same format as the packaged ``configs/radio_default_i2c.csv`` and as the vendor
app's config files. Like the vendor app, a file may be partial: it may list only
some registers, and a ``data`` value may use ``x`` for bits to leave unchanged
(e.g. ``xx1xxxxx``). ``merge_asic_config`` overlays such a file on a full table.
"""

from __future__ import annotations

import csv
from pathlib import Path

from radioroc_client import I2CRow


def save_asic_config(rows, path: Path) -> int:
    """Write rows to ``path`` (overwriting); returns the number of rows saved."""
    rows = list(rows)
    if not rows:
        raise ValueError("no ASIC registers to save")
    with Path(path).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["add", "subadd", "data"])
        for row in rows:
            writer.writerow([row.add, row.subadd, row.data])
    return len(rows)


def load_asic_config(path: Path) -> list[I2CRow]:
    """Read and validate a saved table; raises ``ValueError`` on a malformed file."""
    try:
        with Path(path).open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"add", "subadd", "data"} <= set(reader.fieldnames):
                raise ValueError("expected CSV columns: add, subadd, data")
            rows = []
            for number, record in enumerate(reader, start=2):
                data = (record["data"] or "").strip()
                try:
                    add, subadd = int(record["add"]), int(record["subadd"])
                except (TypeError, ValueError):
                    raise ValueError(f"line {number}: add/subadd must be integers") from None
                if not (0 <= add <= 255 and 0 <= subadd <= 255):
                    raise ValueError(f"line {number}: add/subadd must be in 0..255")
                data = data.lower()
                if len(data) != 8 or set(data) - {"0", "1", "x"}:
                    raise ValueError(f"line {number}: data must be 8 characters of 0, 1 or x")
                rows.append(I2CRow(add, subadd, data))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from None
    if not rows:
        raise ValueError("config file has no registers")
    return rows


def merge_asic_config(base, overlay) -> list[I2CRow]:
    """Overlay ``overlay`` rows on the full ``base`` table; ``x`` bits keep the base value.

    Registers absent from ``base`` are added only when fully specified (no ``x``).
    """
    merged = {(row.add, row.subadd): I2CRow(row.add, row.subadd, row.data) for row in base}
    for row in overlay:
        key = (row.add, row.subadd)
        if key in merged:
            merged[key].data = "".join(new if new != "x" else old
                                       for new, old in zip(row.data, merged[key].data))
        elif "x" not in row.data:
            merged[key] = I2CRow(row.add, row.subadd, row.data)
    return list(merged.values())
