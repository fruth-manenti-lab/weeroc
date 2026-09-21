#!/usr/bin/env python3
"""Run a RADIOROC internal or external hold scan."""

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
    DEFAULT_CONFIG, FPGA_IO_NAMES, HoldScanConfig, RadiorocDevice, RadiorocSerial, default_run_dir, parse_channels,
)
from radioroc.application import CancellationToken
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for hold scans.
    """

    parser = argparse.ArgumentParser(description="Run a RADIOROC hold scan.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--mode", choices=["internal", "external"], help="Hold scan mode")
    parser.add_argument("--channels", help="ADC channels to summarize")
    parser.add_argument("--trigger-channel", type=int, help="ADC trigger channel; defaults to first selected channel")
    parser.add_argument("--hold-min", type=int, help="First hold code or external delay in ns")
    parser.add_argument("--hold-max", type=int, help="Last hold code or external delay in ns")
    parser.add_argument("--hold-step", type=int, help="Hold code or external delay step")
    parser.add_argument("--threshold-dac", type=int, help="Optional T1/T2 threshold DAC to set before scan")
    parser.add_argument("--acquisitions", type=int, help="ADC acquisitions per hold point")
    parser.add_argument("--conversion-delay-ns", type=int, help="ADC conversion delay; divisible by 40 ns")
    parser.add_argument("--synchro-trigger", action="store_true", help="Pulse FPGA synchro trigger for each ADC batch")
    parser.add_argument("--sync-io", choices=FPGA_IO_NAMES, help="FPGA IO used for sync diagnostics")
    parser.add_argument("--sync-io-mux-index", type=int, help="Set sync IO mux index before the scan")
    parser.add_argument("--peak-sensing", action="store_true", help="Use vendor external peak-sensing path")
    parser.add_argument("--external-trigger", action="store_true", help="Use external ASIC acquisition trigger bit")
    parser.add_argument("--adc-trigger-type", type=int, help="Vendor ADC trigger type code")
    parser.add_argument("--adc-trigger-source", type=int, help="Vendor ADC trigger source code")
    parser.add_argument("--adc-window-ns", type=int, help="ADC coincidence/window width; divisible by 5 ns")
    parser.add_argument("--adc-nb-trig", type=int, help="ADC time-window trigger count")
    parser.add_argument("--rstn-manual", action="store_true", help="Set vendor ADC reset-n manual bit")
    parser.add_argument("--timeout-s", type=float, help="Timeout per ADC batch")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--hg-gain-code", type=int, help="High-gain ADC shaper gain code, 1..15")
    parser.add_argument("--lg-gain-code", type=int, help="Low-gain ADC shaper gain code, 1..15")
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the trigger channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the trigger channel")
    parser.add_argument("--verify-restoration", action="store_true",
                        help="Independently read back captured FPGA/ASIC state after scan cleanup")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    """Run the hold scan command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    if args.mode is None:
        args.mode = "external"
    if args.channels is None:
        args.channels = "4"
    if args.hold_min is None:
        args.hold_min = 0
    if args.acquisitions is None:
        args.acquisitions = 10
    if args.conversion_delay_ns is None:
        args.conversion_delay_ns = 400
    if args.sync_io is None:
        args.sync_io = "io1"
    if args.adc_trigger_type is None:
        args.adc_trigger_type = 0
    if args.adc_trigger_source is None:
        args.adc_trigger_source = 3
    if args.adc_window_ns is None:
        args.adc_window_ns = 50
    if args.adc_nb_trig is None:
        args.adc_nb_trig = 1
    if args.timeout_s is None:
        args.timeout_s = 5.0
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    trigger_channel = args.trigger_channel if args.trigger_channel is not None else channels[0]
    hold_max = args.hold_max if args.hold_max is not None else (255 if args.mode == "internal" else 800)
    hold_step = args.hold_step if args.hold_step is not None else (5 if args.mode == "internal" else 25)
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir(f"{args.mode}_hold_scan", channels=channels)
    scan_config = HoldScanConfig(
        mode=args.mode,
        channels=channels,
        trigger_channel=trigger_channel,
        hold_min=args.hold_min,
        hold_max=hold_max,
        hold_step=hold_step,
        threshold_dac=args.threshold_dac,
        acquisitions=args.acquisitions,
        conversion_delay_ns=args.conversion_delay_ns,
        trigger_type=args.adc_trigger_type,
        trigger_source=args.adc_trigger_source,
        rstn_manual=args.rstn_manual,
        external_trigger=args.external_trigger,
        peak_sensing=args.peak_sensing,
        adc_window_ns=args.adc_window_ns,
        adc_nb_trig=args.adc_nb_trig,
        timeout_s=args.timeout_s,
        synchro_trigger=args.synchro_trigger,
        sync_io=args.sync_io,
        sync_io_mux_index=args.sync_io_mux_index,
        t1=not args.t2,
        use_mask=not args.no_mask,
        use_ctest=args.use_ctest,
        trigger_preamp_gain=args.pat_gain,
        high_gain_code=args.hg_gain_code,
        low_gain_code=args.lg_gain_code,
        out_dir=out_dir,
    )
    x_name = "hold_code" if args.mode == "internal" else "hold_delay_ns"
    try:
        connection.validate()
        operation = HoldScanJobConfig(scan_config,
                                      config_path=Path(args.config) if args.config is not None else DEFAULT_CONFIG,
                                      initialize_fpga=not args.skip_fpga_init,
                                      apply_defaults=args.apply_defaults)
        preview = HoldScanJob.preview(operation)
        if args.verify_restoration:
            preview["verify_restoration"] = True
        # Dry-run takes no dependency on transport creation or discovery.
        if not args.execute:
            print(json.dumps(preview, indent=2))
            return 0
        settings = settings_from_args(
            args, scan="hold", out_dir=out_dir,
            trigger_channel=trigger_channel, hold_max=hold_max, hold_step=hold_step,
        )
        metadata = run_metadata(connection=connection, settings=settings, firmware_word=None)
        cancellation = CancellationToken()

        def progress(event):
            if event.kind == "point":
                values = dict(event.values)
                summary = [(ch, values[f"ch{ch}_hg_mean"], values[f"ch{ch}_lg_mean"], values[f"ch{ch}_count"])
                          for ch in channels[:4]]
                print(f"hold {x_name}={event.point} values={summary}", flush=True)

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
                        result = HoldScanJob().run(
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
                    result = HoldScanJob().run(RadiorocDevice(transport), operation, metadata=metadata,
                                               cancellation=cancellation, on_event=progress)
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        print(f"hold scan {result.status}: {result.points} points; cleanup={result.cleanup_status}")
        print(f"hold scan CSV: {result.csv_path}")
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
