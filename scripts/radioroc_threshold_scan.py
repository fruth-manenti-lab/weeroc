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
from radioroc_client import (
    DEFAULT_CONFIG, RadiorocDevice, RadiorocSerial, ThresholdScanConfig, default_run_dir, parse_channels,
)
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
    parser.add_argument("--channels", help="Channels to scan, e.g. 4, 0-15, or all (default: 4)")
    parser.add_argument("--dac-min", type=int, help="First threshold DAC code")
    parser.add_argument("--dac-max", type=int, help="Last threshold DAC code")
    parser.add_argument("--dac-step", type=int, help="Threshold DAC step")
    parser.add_argument("--window-ms", type=float, help="Counter window per DAC/channel")
    parser.add_argument("--averages", type=int, help="Repeated windows to average per point")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the measured channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the measured channel")
    parser.add_argument("--verify-restoration", action="store_true",
                        help="Independently read back captured FPGA/ASIC state after scan cleanup")
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
    if args.channels is None:
        args.channels = "4"
    if args.dac_min is None:
        args.dac_min = 0
    if args.dac_max is None:
        args.dac_max = 600
    if args.dac_step is None:
        args.dac_step = 5
    if args.window_ms is None:
        args.window_ms = 100.0
    if args.averages is None:
        args.averages = 1
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
        operation = ThresholdJobConfig(scan_config,
                                       config_path=Path(args.config) if args.config is not None else DEFAULT_CONFIG,
                                       initialize_fpga=not args.skip_fpga_init,
                                       apply_defaults=args.apply_defaults)
        preview = ThresholdJob.preview(operation)
        if args.verify_restoration:
            preview["verify_restoration"] = True
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
        session_error = False
        result = None
        try:
            if args.verify_restoration:
                session = RadiorocSerial.from_config(connection)
                transport = None
                entered = False
                primary_error = None
                close_error = None
                try:
                    transport = session.__enter__()
                    entered = True
                    try:
                        result = ThresholdJob().run(
                            RadiorocDevice(transport), operation, metadata=metadata,
                            cancellation=cancellation, on_event=progress, verify_restoration=True)
                    except BaseException as exc:
                        primary_error = exc
                except BaseException as exc:
                    primary_error = exc
                finally:
                    if entered:
                        try:
                            session.__exit__(None, None, None)
                        except BaseException as exc:
                            close_error = exc
                if primary_error is not None:
                    _print_error_chain("ERROR", primary_error)
                if close_error is not None:
                    _print_error_chain("CLOSE ERROR", close_error)
                session_error = primary_error is not None or close_error is not None
                if result is None:
                    return 1
            else:
                with RadiorocSerial.from_config(connection) as transport:
                    result = ThresholdJob().run(RadiorocDevice(transport), operation, metadata=metadata,
                                                cancellation=cancellation, on_event=progress)
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        print(f"threshold scan {result.status}: {result.points} points; cleanup={result.cleanup_status}")
        print(f"threshold scan CSV: {result.csv_path}")
        print(f"threshold attempts CSV: {result.attempts_csv_path}")
        print(f"metadata: {result.metadata_path}")
        if result.verification is not None:
            print("restoration verification: " + json.dumps(result.verification, sort_keys=True))
        if result.error is not None:
            if args.verify_restoration:
                _print_error_chain("ERROR", result.error)
            else:
                print(f"{type(result.error).__name__}: {result.error}", file=sys.stderr)
        for error in result.cleanup_errors + result.persistence_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if result.verification is not None:
            for error in result.verification.get("errors", ()):
                print(f"VERIFICATION ERROR: {error}", file=sys.stderr)
            for error in result.verification.get("cleanup", {}).get("errors", ()):
                print(f"VERIFIER CLEANUP ERROR: {error}", file=sys.stderr)
        if session_error:
            return 1
        if result.cleanup_errors or result.persistence_errors:
            return 1
        if result.verification is not None and result.verification.get("status") != "passed":
            return 1
        return 0 if result.status == "completed" else (130 if result.status == "cancelled" else 1)
    except Exception as exc:
        if args.verify_restoration:
            _print_error_chain("ERROR", exc)
        else:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _print_error_chain(label: str, error: BaseException) -> None:
    """Print an exception plus its causal/context chain and attached notes."""
    seen = set()
    current = error
    prefix = label
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        print(f"{prefix}: {type(current).__name__}: {current}", file=sys.stderr)
        for note in getattr(current, "__notes__", ()):
            print(f"{prefix} NOTE: {note}", file=sys.stderr)
        current = current.__cause__ or current.__context__
        prefix = f"{label} CAUSED BY"


if __name__ == "__main__":
    raise SystemExit(main())
