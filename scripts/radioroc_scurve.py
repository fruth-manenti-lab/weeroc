#!/usr/bin/env python3
"""Run a RADIOROC S-curve scan."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from radioroc_cli_common import (
    add_connection_args,
    add_write_safety_args,
    apply_preset_defaults,
    connection_config_from_args,
    load_preset_from_argv,
    prepare_device,
    run_metadata,
    settings_from_args,
)
from radioroc_client import RadiorocDevice, RadiorocSerial, ScurveConfig, default_run_dir, parse_channels


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for S-curves.
    """

    parser = argparse.ArgumentParser(description="Run a RADIOROC S-curve scan.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--channels", default="4", help="Channels to scan, e.g. 4, 0-15, or all")
    parser.add_argument("--dac-min", type=int, default=0)
    parser.add_argument("--dac-max", type=int, default=1023)
    parser.add_argument("--dac-step", type=int, default=50)
    parser.add_argument("--clock-index", type=int, default=3, help="S-curve clock index 0..3")
    parser.add_argument("--trigger-level", action="store_true", help="Count trigger level instead of rising edge")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the measured channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the measured channel")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    """Run the S-curve command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("scurve", channels=channels)
    scan_config = ScurveConfig(
        channels=channels,
        dac_min=args.dac_min,
        dac_max=args.dac_max,
        dac_step=args.dac_step,
        t1=not args.t2,
        use_mask=not args.no_mask,
        use_ctest=args.use_ctest,
        clock_index=args.clock_index,
        trigger_level=args.trigger_level,
        trigger_preamp_gain=args.pat_gain,
        out_dir=out_dir,
    )
    scan_config.validate()
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            firmware = prepare_device(device, args)
            settings = settings_from_args(args, scan="scurve", out_dir=out_dir)
            metadata = run_metadata(connection=connection, settings=settings, firmware_word=firmware)
            result = device.run_scurve(scan_config, metadata=metadata)
        print(f"S-curve CSV: {result.csv_path}")
        if result.metadata_path:
            print(f"metadata: {result.metadata_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
