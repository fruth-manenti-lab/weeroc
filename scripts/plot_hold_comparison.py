#!/usr/bin/env python3
"""Compare multiple RADIOROC hold scan CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radioroc_analysis import plot_hold_comparison, read_hold_csv  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Comparison plot parser.
    """

    parser = argparse.ArgumentParser(description="Compare multiple RADIOROC hold scan CSV files.")
    parser.add_argument("csv", nargs="+", type=Path, help="Input holdscan.csv files.")
    parser.add_argument("--channel", type=int, default=4, help="Channel to compare.")
    parser.add_argument("--gain", choices=["hg", "lg"], default="hg", help="Gain to compare.")
    parser.add_argument("--out", type=Path, default=Path("radioroc_runs/hold_comparison.png"))
    parser.add_argument("--title", default="RADIOROC hold scan comparison")
    return parser


def main() -> int:
    """Run the comparison plot command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    args = build_parser().parse_args()
    try:
        scans = [read_hold_csv(path) for path in args.csv]
        out = plot_hold_comparison(scans, channel=args.channel, gain=args.gain, out=args.out, title=args.title)
        print(out)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
