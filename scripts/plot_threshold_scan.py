#!/usr/bin/env python3
"""Plot a RADIOROC threshold scan CSV."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radioroc_analysis import (  # noqa: E402
    DEFAULT_RUNS_DIR,
    find_latest_scan,
    parse_threshold_channels,
    plot_threshold_scan,
    read_threshold_csv,
    summarize_threshold,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Plot command parser.
    """

    parser = argparse.ArgumentParser(description="Plot a RADIOROC threshold scan CSV.")
    parser.add_argument("csv", nargs="?", type=Path, help="Input thresholdscan.csv. Defaults to the newest run.")
    parser.add_argument("--latest", action="store_true", help="Plot the newest thresholdscan.csv under --runs-dir.")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR, help="Run directory searched by --latest.")
    parser.add_argument("--out", type=Path, help="Output PNG path. Defaults beside the CSV.")
    parser.add_argument("--channels", help="Comma-separated channel list, e.g. 4 or 0,4,7. Defaults to all CSV channels.")
    parser.add_argument("--yscale", choices=["linear", "log", "symlog"], default="symlog")
    parser.add_argument("--steps", action="store_true", help="Draw as a staircase using steps-post.")
    parser.add_argument("--summary", action="store_true", help="Print simple threshold landmarks.")
    parser.add_argument("--title", default="RADIOROC threshold scan")
    return parser


def main() -> int:
    """Run the threshold plot command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    args = build_parser().parse_args()
    try:
        csv_path = find_latest_scan(args.runs_dir, "thresholdscan.csv") if args.latest or args.csv is None else args.csv
        data = read_threshold_csv(csv_path)
        channels = parse_threshold_channels(args.channels, list(data.series))
        out = args.out or csv_path.with_suffix(".png")
        plot_threshold_scan(data, channels=channels, out=out, yscale=args.yscale, steps=args.steps, title=args.title)
        if args.summary:
            for item in summarize_threshold(data):
                if item.channel in channels:
                    print(
                        f"{item.channel}: peak={item.peak_hz} Hz at DAC {item.peak_dac}; "
                        f"first_nonzero={item.first_nonzero_dac}; last_above_1khz={item.last_above_1khz_dac}"
                    )
        print(f"input={csv_path}")
        print(out)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
