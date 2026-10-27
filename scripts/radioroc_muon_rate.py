#!/usr/bin/env python3
"""Offline muon rate per minute from a saved RADIOROC acquisition run (no hardware)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__:
    from .radioroc_cli_common import print_effective_settings
else:
    from radioroc_cli_common import print_effective_settings

from radioroc.data import muon_analysis, muon_rate, pedestal_flow
from radioroc.data.muon_types import DetectorLayout


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Muon rate per minute (accepted coincidences / batch-completion time) of a saved run.")
    parser.add_argument("run", type=Path, help="Acquisition run folder (events.csv + metadata.json)")
    parser.add_argument("--background", type=Path, help="Background run folder, analysed with the same settings")
    parser.add_argument("--layout", type=Path, help="Layout JSON (default: 2 layers of 4x8 SiPMs, 10 mm pitch)")
    parser.add_argument("--threshold", type=float, help="Detection threshold in counts above pedestal (default 40)")
    parser.add_argument("--pedestals", help="Pedestal JSON file/run folder, or 'auto' = median of each run (default)")
    parser.add_argument("--area-cm2", type=float, help="Coincidence area for the flux (default: from the layout plints)")
    return parser


def _saved_pedestals(run: Path):
    """High-gain pedestals from RUN/pedestals.json, or None when the run has none."""
    if not (Path(run) / "pedestals.json").is_file():
        return None
    from radioroc.data.pedestals import find_pedestals_for_run
    found = find_pedestals_for_run(Path(run))
    return dict(found.hg()) if found is not None else None


def main(argv: list[str] | None = None) -> int:
    """Run the command. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        layout = DetectorLayout.load_json(args.layout) if args.layout else DetectorLayout.grid(4, 8, 10.0, layers=2)
        threshold = 40.0 if args.threshold is None else args.threshold
        warning = None
        if args.pedestals:
            ped_arg = args.pedestals
            pedestals = None if ped_arg == "auto" else muon_analysis.load_pedestals(Path(ped_arg))
            ped_text = ped_arg if ped_arg == "auto" else f"{ped_arg}"
        else:
            saved = _saved_pedestals(args.run)
            if saved is not None:
                ped_arg = ped_text = f"{args.run / 'pedestals.json'} (saved with the run)"
                pedestals = saved
            else:
                ped_arg, pedestals = "auto", None
                ped_text = "auto: " + pedestal_flow.MEDIAN_TEXT
                warning = ("WARNING: no pedestals saved with this run; " + pedestal_flow.NOT_SAVED_WARNING)
        area = args.area_cm2 if args.area_cm2 is not None else muon_rate.coincidence_area_cm2(layout)
        print_effective_settings("radioroc_muon_rate", {
            "run": args.run, "background": args.background or "none", "layout": args.layout or layout.name,
            "threshold (counts)": threshold, "pedestals": ped_text,
            "area (cm2)": "none" if not area else f"{area:.2f}"},
            defaulted={label for label, name in (("layout", "layout"), ("threshold (counts)", "threshold"),
                                                 ("pedestals", "pedestals"), ("area (cm2)", "area_cm2"))
                       if getattr(args, name) is None})
        if warning:
            print(warning, file=sys.stderr)
        signal_run = muon_rate.analyse_run(args.run, layout, threshold, pedestals)
        background = net = background_timing = None
        if args.background:
            bg_run = muon_rate.analyse_run(args.background, layout, threshold, pedestals)
            background, background_timing = bg_run.result, bg_run.timing
            net = muon_rate.subtract_background(signal_run.result, background)
        print(muon_rate.format_summary(
            signal_run.timing, signal_run.result, blocks=signal_run.blocks, background=background,
            background_timing=background_timing, net=net, area_cm2=area,
            settings=[f"Layout: {layout.name}", f"Detection threshold: {threshold:g} counts",
                      f"Pedestals: {ped_text}"]), end="")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
