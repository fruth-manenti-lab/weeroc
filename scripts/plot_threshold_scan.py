from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/radioroc-matplotlib")

import matplotlib.pyplot as plt


DEFAULT_RUNS_DIR = Path("radioroc_runs")


def find_latest_threshold_scan(root: Path) -> Path:
    candidates = [p for p in root.rglob("thresholdscan.csv") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"no thresholdscan.csv files found under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_threshold_csv(path: Path) -> tuple[list[float], dict[str, list[float]]]:
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None or "DAC" not in reader.fieldnames:
            raise ValueError(f"{path} does not look like a threshold scan CSV")
        channels = [name for name in reader.fieldnames if name != "DAC"]
        dacs: list[float] = []
        series = {ch: [] for ch in channels}
        for row in reader:
            dacs.append(float(row["DAC"]))
            for ch in channels:
                value = row.get(ch, "")
                series[ch].append(float(value) if value not in ("", None) else float("nan"))
    return dacs, series


def parse_channels(value: str | None, available: list[str]) -> list[str]:
    if not value:
        return available
    selected: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        name = part if part.startswith("ch") else f"ch{int(part)}"
        if name not in available:
            raise ValueError(f"{name} not present in CSV; available: {', '.join(available)}")
        selected.append(name)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a RADIOROC threshold scan CSV.")
    parser.add_argument("csv", nargs="?", type=Path, help="Input thresholdscan.csv. Defaults to the newest run.")
    parser.add_argument("--latest", action="store_true", help="Plot the newest thresholdscan.csv under --runs-dir.")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR, help="Run directory searched by --latest.")
    parser.add_argument("--out", type=Path, help="Output PNG path. Defaults beside the CSV.")
    parser.add_argument("--channels", help="Comma-separated channel list, e.g. 4 or 0,4,7. Defaults to all CSV channels.")
    parser.add_argument("--yscale", choices=["linear", "log", "symlog"], default="symlog")
    parser.add_argument("--steps", action="store_true", help="Draw as a staircase using steps-post instead of straight line segments.")
    parser.add_argument("--title", default="RADIOROC threshold scan")
    args = parser.parse_args()

    csv_path = find_latest_threshold_scan(args.runs_dir) if args.latest or args.csv is None else args.csv
    dacs, series = read_threshold_csv(csv_path)
    channels = parse_channels(args.channels, list(series))
    out = args.out or csv_path.with_suffix(".png")

    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    drawstyle = "steps-post" if args.steps else "default"
    for ch in channels:
        ax.plot(dacs, series[ch], marker="o", linewidth=1.3, markersize=3, drawstyle=drawstyle, label=ch)
    ax.set_title(args.title)
    ax.set_xlabel("Threshold DAC code")
    ax.set_ylabel("Trigger frequency (Hz)")
    ax.set_yscale(args.yscale)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best")
    fig.savefig(out, dpi=160)
    print(f"input={csv_path}")
    print(out)


if __name__ == "__main__":
    main()
