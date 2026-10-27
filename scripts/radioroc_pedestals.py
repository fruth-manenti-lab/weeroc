#!/usr/bin/env python3
"""Measure ADC pedestals with a forced trigger (no input needed; dark box closed, bias on)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys

if __package__:
    from .radioroc_cli_common import (
        add_connection_args, add_write_safety_args, apply_preset_defaults, connection_config_from_args,
        load_preset_from_argv, print_effective_settings, run_metadata, settings_from_args, unset_args,
    )
else:
    from radioroc_cli_common import (
        add_connection_args, add_write_safety_args, apply_preset_defaults, connection_config_from_args,
        load_preset_from_argv, print_effective_settings, run_metadata, settings_from_args, unset_args,
    )
from radioroc_client import DEFAULT_CONFIG, RadiorocDevice, RadiorocSerial, default_run_dir, parse_channels
from radioroc.application import CancellationToken
from radioroc.application.pedestal import DEFAULT_EVENTS, PedestalJob, PedestalJobConfig

_DEFAULT_NOTES = {
    "channels": ("channels", None),
    "hold delay ns": ("hold_delay_ns", "same as the muon run; the desktop app uses the Calibration bar"),
    "conversion delay ns": ("conversion_delay_ns", None),
    "trigger preamp gain code (paT)": ("pat_gain", "the desktop app uses Trigger gain (paT) from the Calibration bar"),
    "events": ("events", None),
}


def build_parser(preset=None, preset_path=None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure ADC pedestals with a forced (synchro) trigger.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--channels", help="Channels, e.g. 6,32 or 0-3")
    parser.add_argument("--hold-delay-ns", type=int, help="Hold delay in ns (use the muon run's value)")
    parser.add_argument("--conversion-delay-ns", type=int, help="ADC conversion delay in ns")
    parser.add_argument("--pat-gain", type=int, help="Trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--events", type=int, help=f"Events per channel (default {DEFAULT_EVENTS})")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    script_defaulted = unset_args(args, [arg for arg, _note in _DEFAULT_NOTES.values()])
    if args.channels is None:
        args.channels = "4"
    if args.hold_delay_ns is None:
        args.hold_delay_ns = 30
    if args.conversion_delay_ns is None:
        args.conversion_delay_ns = 400
    if args.pat_gain is None:
        args.pat_gain = 1
    if args.events is None:
        args.events = DEFAULT_EVENTS
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("pedestals", channels=channels)
    config = PedestalJobConfig(channels, out_dir, hold_delay_ns=args.hold_delay_ns,
                               conversion_delay_ns=args.conversion_delay_ns, pat_gain=args.pat_gain,
                               events=args.events, config_path=Path(args.config) if args.config is not None else DEFAULT_CONFIG,
                               initialize_fpga=not args.skip_fpga_init, apply_defaults=args.apply_defaults)
    defaulted = {label: note for label, (arg, note) in _DEFAULT_NOTES.items() if arg in script_defaulted}
    print_effective_settings("radioroc_pedestals", {
        "channels": args.channels, "trigger": "forced (synchro pulse per ADC batch)",
        "hold delay ns": args.hold_delay_ns, "conversion delay ns": args.conversion_delay_ns,
        "trigger preamp gain code (paT)": args.pat_gain,
        "events": config.batches * 20, "batches": config.batches,
        "apply defaults": args.apply_defaults, "skip fpga init": args.skip_fpga_init,
    }, defaulted)
    try:
        connection.validate()
        preview = PedestalJob.preview(config)
        if not args.execute:
            print(json.dumps(preview, indent=2))
            return 0
        settings = settings_from_args(args, scan="pedestals", out_dir=out_dir)
        metadata = run_metadata(connection=connection, settings=settings, firmware_word=None)
        cancellation = CancellationToken()
        previous = signal.signal(signal.SIGINT, lambda *_: cancellation.cancel())
        try:
            with RadiorocSerial.from_config(connection) as transport:
                result = PedestalJob().run(RadiorocDevice(transport), config, metadata=metadata,
                                           cancellation=cancellation, verify_restoration=True)
        finally:
            signal.signal(signal.SIGINT, previous)
        acq = result.acquisition
        print(f"acquisition {acq.status}: {acq.points} batches; cleanup={acq.cleanup_status}")
        if result.pedestals is not None:
            print(f"{'ch':>3} {'HG med':>8} {'HG sd':>7} {'LG med':>8} {'LG sd':>7} {'n':>5}")
            for ch, p in sorted(result.pedestals.channels.items()):
                print(f"{ch:>3} {p.hg_median:8.1f} {p.hg_sd:7.2f} {p.lg_median:8.1f} {p.lg_sd:7.2f} {p.n:5d}")
                if p.hg_sd > 5:
                    print(f"  warning: ch{ch} HG sd {p.hg_sd:.1f} > 5 counts; pulses present?", file=sys.stderr)
            print(f"pedestals: {result.path}")
        if result.error:
            print(f"ERROR: {result.error}", file=sys.stderr)
        for error in acq.cleanup_errors + acq.persistence_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if acq.error is not None:
            print(f"{type(acq.error).__name__}: {acq.error}", file=sys.stderr)
        if acq.verification is not None and acq.verification.get("status") != "passed":
            return 1
        if acq.cleanup_errors or acq.persistence_errors:
            return 1
        return 0 if acq.status == "completed" and result.pedestals is not None else (130 if acq.status == "cancelled" else 1)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
