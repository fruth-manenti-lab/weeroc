#!/usr/bin/env python3
"""Run a RADIOROC automatic threshold calibration (F08)."""

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
from radioroc_client import DEFAULT_CONFIG, RadiorocDevice, RadiorocSerial, default_run_dir, parse_channels
from radioroc.application import CancellationToken
from radioroc.application.autocalibration import AutocalibrationJob, AutocalibrationJobConfig


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for automatic threshold calibration.
    """

    parser = argparse.ArgumentParser(description="Run a RADIOROC automatic threshold calibration.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--channels", help="Channels to calibrate together, e.g. 4,5 or 0-15 or all. "
                        "The first channel is the LSB-ratio reference channel.")
    parser.add_argument("--t2", action="store_true", help="Calibrate T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the measured channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the measured channel")
    parser.add_argument("--clock-index", type=int, help="S-curve clock index 0..3")
    parser.add_argument("--trigger-level", action="store_true", help="Count trigger level instead of rising edge")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--probe-dac-min", type=int, help="Step-1 LSB-ratio probe: first DAC code")
    parser.add_argument("--probe-dac-max", type=int, help="Step-1 LSB-ratio probe: last DAC code")
    parser.add_argument("--probe-dac-step", type=int, help="Step-1 LSB-ratio probe: DAC step")
    parser.add_argument("--transition-dac-step", type=int, help="Step-2 transition scan: DAC step")
    parser.add_argument("--transition-margin", type=int,
                        help="Added past the step-1 estimate to pick the step-2 scan's upper DAC bound")
    parser.add_argument("--transition-dac-floor", type=int,
                        help="Minimum step-2 transition scan upper DAC bound")
    parser.add_argument("--transition-dac-cap", type=int,
                        help="Maximum step-2 transition scan upper DAC bound")
    parser.add_argument("--final-window-before", type=int,
                        help="Final verification scan: DAC codes below the step-2 mean crossing")
    parser.add_argument("--final-window-after", type=int,
                        help="Final verification scan: DAC codes above the step-2 mean crossing")
    parser.add_argument("--final-dac-step", type=int, help="Final verification scan: DAC step")
    parser.add_argument("--verify-restoration", action="store_true",
                        help="Independently read back the reference channel's calibration DAC after restoration")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    """Run the automatic-threshold-calibration command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    if args.channels is None:
        args.channels = "4"
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("autocalibrate", channels=channels)
    config_kwargs = dict(
        channels=channels,
        t1=not args.t2,
        use_mask=not args.no_mask,
        use_ctest=args.use_ctest,
        trigger_preamp_gain=args.pat_gain,
        out_dir=out_dir,
        config_path=Path(args.config) if args.config is not None else DEFAULT_CONFIG,
        initialize_fpga=not args.skip_fpga_init,
        apply_defaults=args.apply_defaults,
    )
    for field_name, arg_name in (
        ("clock_index", "clock_index"), ("trigger_level", "trigger_level"),
        ("probe_dac_min", "probe_dac_min"), ("probe_dac_max", "probe_dac_max"),
        ("probe_dac_step", "probe_dac_step"), ("transition_dac_step", "transition_dac_step"),
        ("transition_margin", "transition_margin"),
        ("transition_dac_floor", "transition_dac_floor"), ("transition_dac_cap", "transition_dac_cap"),
        ("final_window_before", "final_window_before"), ("final_window_after", "final_window_after"),
        ("final_dac_step", "final_dac_step"),
    ):
        value = getattr(args, arg_name)
        if value is not None:
            config_kwargs[field_name] = value
    autocal_config = AutocalibrationJobConfig(**config_kwargs)
    try:
        connection.validate()
        preview = AutocalibrationJob.preview(autocal_config)
        if args.verify_restoration:
            preview["verify_restoration"] = True
        # Dry-run takes no dependency on transport creation or discovery.
        if not args.execute:
            print(json.dumps(preview, indent=2))
            return 0
        settings = settings_from_args(args, scan="autocalibrate", out_dir=out_dir)
        metadata = run_metadata(connection=connection, settings=settings, firmware_word=None)
        cancellation = CancellationToken()

        def progress(event):
            if event.kind == "point":
                values = dict(event.values)
                print(f"autocalibrate dac={event.dac} values={values}", flush=True)

        # SIGINT only requests cancellation; cleanup is allowed to finish.
        previous_handler = signal.signal(signal.SIGINT, lambda *_: cancellation.cancel())
        try:
            with RadiorocSerial.from_config(connection) as transport:
                result = AutocalibrationJob().run(
                    RadiorocDevice(transport), autocal_config, metadata=metadata,
                    cancellation=cancellation, on_event=progress,
                    verify_restoration=args.verify_restoration)
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        print(f"Autocalibration {result.status}: reference channel {result.reference_channel}, "
              f"lsb_ratio={result.lsb_ratio}")
        print(f"calibration before: {result.calibration_before}")
        print(f"calibration after:  {result.calibration_after}")
        print(f"metadata: {result.metadata_path}")
        for name, sub_dir in result.sub_runs.items():
            print(f"  {name}: {sub_dir}")
        if result.reference_restored is not None:
            print(f"reference channel restored: {result.reference_restored}")
        if result.error is not None:
            _print_error_chain("ERROR", result.error)
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if result.reference_restored is False:
            return 1
        return 0 if result.status == "completed" else (130 if result.status == "cancelled" else 1)
    except Exception as exc:
        _print_error_chain("ERROR", exc)
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
