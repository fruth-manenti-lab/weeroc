#!/usr/bin/env python3
"""Plot a simple RADIOROC acquisition spectrum."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/radioroc-matplotlib")

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Spectrum plot parser.
    """

    parser = argparse.ArgumentParser(description="Plot a histogram from radioroc_acquire.py events.csv.")
    parser.add_argument("csv", type=Path, help="Input events.csv")
    parser.add_argument("--channel", type=int, default=4, help="Channel to plot")
    parser.add_argument("--gain", choices=["hg", "lg"], default="hg", help="Gain column to histogram")
    parser.add_argument("--bins", default="100", help="Histogram bins, or 'sqrt' for sqrt(N)")
    parser.add_argument("--xmin", type=float, help="Minimum ADC value to include")
    parser.add_argument("--xmax", type=float, help="Maximum ADC value to include")
    parser.add_argument("--yscale", choices=["log", "linear"], default="log", help="Y-axis scale")
    parser.add_argument("--out", type=Path, help="Output PNG path. Defaults beside CSV.")
    parser.add_argument("--title", help="Plot title")
    return parser


def main() -> int:
    """Run the spectrum plot command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    args = build_parser().parse_args()
    try:
        import matplotlib.pyplot as plt

        values: list[float] = []
        with args.csv.open(newline="") as fp:
            for row in csv.DictReader(fp):
                if int(row["channel"]) == args.channel:
                    value = float(row[args.gain])
                    if args.xmin is not None and value < args.xmin:
                        continue
                    if args.xmax is not None and value > args.xmax:
                        continue
                    values.append(value)
        if not values:
            raise ValueError(f"no events found for channel {args.channel}")
        bins = max(1, round(math.sqrt(len(values)))) if args.bins == "sqrt" else int(args.bins)
        out = args.out or args.csv.with_name(f"spectrum_ch{args.channel}_{args.gain}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        ax.hist(values, bins=bins, histtype="stepfilled", alpha=0.75)
        ax.set_title(args.title or f"RADIOROC ch{args.channel} {args.gain.upper()} spectrum")
        ax.set_xlabel("ADC amplitude (vendor scale 0.25/code)")
        ax.set_ylabel("Counts")
        ax.set_yscale(args.yscale)
        if args.xmin is not None or args.xmax is not None:
            ax.set_xlim(left=args.xmin, right=args.xmax)
        ax.grid(True, alpha=0.3)
        fig.savefig(out, dpi=160)
        print(f"events={len(values)} bins={bins} min={min(values)} max={max(values)}")
        print(out)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
