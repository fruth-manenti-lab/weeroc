from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/radioroc-matplotlib")

import matplotlib.pyplot as plt


def find_latest_hold_scan(root: Path) -> Path:
    candidates = [p for p in root.rglob("holdscan.csv") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"no holdscan.csv files found under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_hold_csv(path: Path) -> tuple[str, list[float], dict[str, list[float]]]:
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if not reader.fieldnames:
            raise ValueError(f"{path} does not look like a hold scan CSV")
        x_col = "hold_code" if "hold_code" in reader.fieldnames else "hold_delay_ns"
        if x_col not in reader.fieldnames:
            raise ValueError(f"{path} does not look like a hold scan CSV")
        delays: list[float] = []
        series: dict[str, list[float]] = {name: [] for name in reader.fieldnames if name != x_col}
        for row in reader:
            delays.append(float(row[x_col]))
            for name in series:
                value = row.get(name, "")
                series[name].append(float(value) if value else float("nan"))
    return x_col, delays, series


def parse_channels(value: str | None, series: dict[str, list[float]]) -> list[int]:
    if value:
        out: set[int] = set()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = [int(x) for x in part.split("-", 1)]
                out.update(range(lo, hi + 1))
            else:
                out.add(int(part))
        return sorted(out)

    channels: set[int] = set()
    for name in series:
        if name.startswith("ch") and name.endswith("_hg_mean"):
            channels.add(int(name[2:].split("_", 1)[0]))
    return sorted(channels)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a RADIOROC hold scan CSV.")
    parser.add_argument("csv", nargs="?", type=Path, help="Input holdscan.csv. Defaults to the newest run.")
    parser.add_argument("--latest", action="store_true", help="Plot the newest holdscan.csv under --runs-dir.")
    parser.add_argument("--runs-dir", type=Path, default=Path("radioroc_runs"))
    parser.add_argument("--channels", help="Channels to plot, e.g. 4 or 0-3. Defaults to all channels in the CSV.")
    parser.add_argument("--gain", choices=["hg", "lg", "both"], default="both")
    parser.add_argument("--exclude-zero", action="store_true", help="Drop hold value/code 0 from the plot.")
    parser.add_argument("--x-min", type=float, help="Drop points below this hold value/code.")
    parser.add_argument("--out", type=Path, help="Output PNG path. Defaults beside the CSV.")
    parser.add_argument("--title", default="RADIOROC hold scan")
    args = parser.parse_args()

    csv_path = find_latest_hold_scan(args.runs_dir) if args.latest or args.csv is None else args.csv
    x_col, delays, series = read_hold_csv(csv_path)
    keep = [True] * len(delays)
    if args.exclude_zero:
        keep = [ok and x != 0 for ok, x in zip(keep, delays)]
    if args.x_min is not None:
        keep = [ok and x >= args.x_min for ok, x in zip(keep, delays)]
    delays = [x for x, ok in zip(delays, keep) if ok]
    series = {name: [value for value, ok in zip(values, keep) if ok] for name, values in series.items()}

    channels = parse_channels(args.channels, series)
    out = args.out or csv_path.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    for ch in channels:
        if args.gain in {"hg", "both"} and f"ch{ch}_hg_mean" in series:
            ax.plot(delays, series[f"ch{ch}_hg_mean"], marker="o", linewidth=1.4, label=f"ch{ch} HG")
        if args.gain in {"lg", "both"} and f"ch{ch}_lg_mean" in series:
            ax.plot(delays, series[f"ch{ch}_lg_mean"], marker="s", linewidth=1.4, label=f"ch{ch} LG")

    ax.set_title(args.title)
    ax.set_xlabel("Internal hold delay code" if x_col == "hold_code" else "External hold delay (ns)")
    ax.set_ylabel("ADC amplitude (mV equivalent, vendor scale 0.25/code)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
