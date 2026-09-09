#!/usr/bin/env python3
"""Plot a RADIOROC threshold scan CSV."""

from __future__ import annotations

import argparse
import json
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


def read_run_setting(csv_path: Path, name: str) -> object | None:
    """Read a setting from metadata.json beside a scan CSV."""

    metadata_path = csv_path.parent / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open(encoding="utf-8") as fp:
            metadata = json.load(fp)
    except Exception:
        return None
    settings = metadata.get("settings", {})
    return settings.get(name) if isinstance(settings, dict) else None


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
    parser.add_argument("--dots-only", action="store_true", help="Draw unconnected marker dots.")
    parser.add_argument("--derivative", action="store_true", help="Plot -d(rate)/dDAC instead of raw trigger rate.")
    parser.add_argument(
        "--derivative-mode",
        choices=["raw", "log-profile"],
        default="raw",
        help="Derivative source: raw rate, or residual after subtracting a smoothed log10(rate) profile.",
    )
    parser.add_argument("--smooth-window", type=int, default=1, help="Moving-average window used before derivative.")
    parser.add_argument("--profile-window", type=int, default=31, help="Moving-average window for --derivative-mode log-profile.")
    parser.add_argument("--error-band", choices=["none", "poisson", "std"], default="none", help="Draw uncertainty band on raw rate plots.")
    parser.add_argument("--error-scale", type=float, default=1.0, help="Multiplier for shaded uncertainty band.")
    parser.add_argument("--error-panel", action="store_true", help="Add lower panel showing relative uncertainty.")
    parser.add_argument("--attempts-csv", type=Path, help="Per-attempt CSV for --error-band std. Defaults beside the mean CSV.")
    parser.add_argument("--window-ms", type=float, help="Counter window used for Poisson error bands; inferred from metadata if omitted.")
    parser.add_argument("--averages", type=int, help="Number of averaged windows for Poisson error bands; inferred from metadata if omitted.")
    parser.add_argument("--x-unit", choices=["dac", "mv"], default="dac", help="Threshold x-axis unit.")
    parser.add_argument("--threshold-mv-offset", type=float, default=270.0, help="Threshold mV at DAC 0 for --x-unit mv.")
    parser.add_argument("--threshold-mv-per-code", type=float, default=0.25, help="Threshold mV per DAC code for --x-unit mv.")
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
        window_ms = args.window_ms
        averages = args.averages
        if args.error_band == "poisson":
            if window_ms is None:
                value = read_run_setting(csv_path, "window_ms")
                window_ms = float(value) if value is not None else None
            if averages is None:
                value = read_run_setting(csv_path, "averages")
                averages = int(value) if value is not None else None
        attempts_csv = args.attempts_csv
        if args.error_band == "std" and attempts_csv is None:
            attempts_csv = csv_path.parent / "thresholdscan_attempts.csv"
        plot_threshold_scan(
            data,
            channels=channels,
            out=out,
            yscale=args.yscale,
            steps=args.steps,
            dots_only=args.dots_only,
            derivative=args.derivative,
            derivative_mode=args.derivative_mode,
            smooth_window=args.smooth_window,
            profile_window=args.profile_window,
            error_band=args.error_band,
            error_scale=args.error_scale,
            error_panel=args.error_panel,
            window_ms=window_ms,
            averages=averages,
            attempts_csv=attempts_csv,
            x_unit=args.x_unit,
            threshold_mv_offset=args.threshold_mv_offset,
            threshold_mv_per_code=args.threshold_mv_per_code,
            title=args.title,
        )
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
