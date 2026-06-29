#!/usr/bin/env python3
"""Plot a RADIOROC hold scan CSV."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radioroc_analysis import (  # noqa: E402
    DEFAULT_RUNS_DIR,
    filter_hold_data,
    find_latest_scan,
    has_invalid_internal_zero_point,
    parse_hold_channels,
    plot_hold_scan,
    read_hold_csv,
    summarize_hold,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Plot command parser.
    """

    parser = argparse.ArgumentParser(description="Plot a RADIOROC hold scan CSV.")
    parser.add_argument("csv", nargs="?", type=Path, help="Input holdscan.csv. Defaults to the newest run.")
    parser.add_argument("--latest", action="store_true", help="Plot the newest holdscan.csv under --runs-dir.")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--channels", help="Channels to plot, e.g. 4 or 0-3. Defaults to all channels in the CSV.")
    parser.add_argument("--gain", choices=["hg", "lg", "both"], default="both")
    parser.add_argument("--exclude-zero", action="store_true", help="Drop hold value/code 0 from the plot.")
    parser.add_argument("--x-min", type=float, help="Drop points below this hold value/code.")
    parser.add_argument("--out", type=Path, help="Output PNG path. Defaults beside the CSV.")
    parser.add_argument("--summary", action="store_true", help="Print simple hold peak/plateau landmarks.")
    parser.add_argument("--title", default="RADIOROC hold scan")
    return parser


def main() -> int:
    """Run the hold plot command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    args = build_parser().parse_args()
    try:
        csv_path = find_latest_scan(args.runs_dir, "holdscan.csv") if args.latest or args.csv is None else args.csv
        data = read_hold_csv(csv_path)
        if has_invalid_internal_zero_point(data) and not args.exclude_zero and args.x_min is None:
            print("note: internal hold scan contains code 0; use --exclude-zero to hide the known zero-code outlier")
        data = filter_hold_data(data, exclude_zero=args.exclude_zero, x_min=args.x_min)
        channels = parse_hold_channels(args.channels, data.series)
        out = args.out or csv_path.with_suffix(".png")
        plot_hold_scan(data, channels=channels, gain=args.gain, out=out, title=args.title)
        if args.summary:
            gains = ("hg", "lg") if args.gain == "both" else (args.gain,)
            for item in summarize_hold(data, channels=channels, gains=gains):
                print(
                    f"ch{item.channel} {item.gain.upper()}: peak={item.peak_value} at {item.peak_x}; "
                    f"plateau={item.plateau_start_x}..{item.plateau_end_x}"
                )
        print(f"input={csv_path}")
        print(out)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
