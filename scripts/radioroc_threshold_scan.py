#!/usr/bin/env python3
"""Run a RADIOROC trigger-rate threshold scan."""

from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path
import sys

if __package__:
    from .radioroc_cli_common import (
        add_connection_args,
        add_write_safety_args,
        apply_preset_defaults,
        connection_config_from_args,
        load_preset_from_argv,
        run_metadata,
        settings_from_args,
    )
else:
    from radioroc_cli_common import (
        add_connection_args,
        add_write_safety_args,
        apply_preset_defaults,
        connection_config_from_args,
        load_preset_from_argv,
        run_metadata,
        settings_from_args,
    )
from radioroc_client import RadiorocDevice, RadiorocSerial, ThresholdScanConfig, default_run_dir, parse_channels
from radioroc.application import CancellationToken
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for threshold scans.
    """

    parser = argparse.ArgumentParser(description="Run a threshold staircase scan.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--channels", default="4", help="Channels to scan, e.g. 4, 0-15, or all (default: 4)")
    parser.add_argument("--dac-min", type=int, default=0, help="First threshold DAC code")
    parser.add_argument("--dac-max", type=int, default=600, help="Last threshold DAC code")
    parser.add_argument("--dac-step", type=int, default=5, help="Threshold DAC step")
    parser.add_argument("--window-ms", type=float, default=100.0, help="Counter window per DAC/channel")
    parser.add_argument("--averages", type=int, default=1, help="Repeated windows to average per point")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the measured channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the measured channel")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    """Run the threshold scan command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("threshold_scan", channels=channels)
    scan_config = ThresholdScanConfig(
        channels=channels,
        dac_min=args.dac_min,
        dac_max=args.dac_max,
        dac_step=args.dac_step,
        trigger_window_ms=args.window_ms,
        averages=args.averages,
        t1=not args.t2,
        use_mask=not args.no_mask,
        use_ctest=args.use_ctest,
        trigger_preamp_gain=args.pat_gain,
        out_dir=out_dir,
    )
    try:
        connection.validate()
        operation = ThresholdJobConfig(scan_config, config_path=Path(args.config),
                                       initialize_fpga=not args.skip_fpga_init,
                                       apply_defaults=args.apply_defaults)
        preview = ThresholdJob.preview(operation)
        # Dry-run takes no dependency on transport creation or discovery.
        if not args.execute:
            print(json.dumps(preview, indent=2))
            return 0
        settings = settings_from_args(args, scan="threshold", out_dir=out_dir)
        metadata = run_metadata(connection=connection, settings=settings, firmware_word=None)
        cancellation = CancellationToken()

        def progress(event):
            if event.kind == "point":
                values = dict(event.values)
                print(f"threshold dac={event.dac} hz={[values[f'ch{ch}'] for ch in channels[:8]]}", flush=True)

        # SIGINT only requests cancellation; cleanup is allowed to finish.
        previous_handler = signal.signal(signal.SIGINT, lambda *_: cancellation.cancel())
        try:
            with RadiorocSerial.from_config(connection) as transport:
                result = ThresholdJob().run(RadiorocDevice(transport), operation, metadata=metadata,
                                            cancellation=cancellation, on_event=progress)
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        print(f"threshold scan {result.status}: {result.points} points; cleanup={result.cleanup_status}")
        print(f"threshold scan CSV: {result.csv_path}")
        print(f"threshold attempts CSV: {result.attempts_csv_path}")
        print(f"metadata: {result.metadata_path}")
        if result.error is not None:
            print(f"{type(result.error).__name__}: {result.error}", file=sys.stderr)
        for error in result.cleanup_errors + result.persistence_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if result.cleanup_errors or result.persistence_errors:
            return 1
        return 0 if result.status == "completed" else (130 if result.status == "cancelled" else 1)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
