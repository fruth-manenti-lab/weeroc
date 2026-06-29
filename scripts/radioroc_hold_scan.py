#!/usr/bin/env python3
"""Run a RADIOROC internal or external hold scan."""

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
from radioroc_client import FPGA_IO_NAMES, HoldScanConfig, RadiorocDevice, RadiorocSerial, default_run_dir, parse_channels


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
    parser.add_argument("--mode", choices=["internal", "external"], default="external", help="Hold scan mode")
    parser.add_argument("--channels", default="4", help="ADC channels to summarize")
    parser.add_argument("--trigger-channel", type=int, help="ADC trigger channel; defaults to first selected channel")
    parser.add_argument("--hold-min", type=int, default=0, help="First hold code or external delay in ns")
    parser.add_argument("--hold-max", type=int, help="Last hold code or external delay in ns")
    parser.add_argument("--hold-step", type=int, help="Hold code or external delay step")
    parser.add_argument("--threshold-dac", type=int, help="Optional T1/T2 threshold DAC to set before scan")
    parser.add_argument("--acquisitions", type=int, default=10, help="ADC acquisitions per hold point")
    parser.add_argument("--conversion-delay-ns", type=int, default=400, help="ADC conversion delay; divisible by 40 ns")
    parser.add_argument("--synchro-trigger", action="store_true", help="Pulse FPGA synchro trigger for each ADC batch")
    parser.add_argument("--sync-io", choices=FPGA_IO_NAMES, default="io1", help="FPGA IO used for sync diagnostics")
    parser.add_argument("--sync-io-mux-index", type=int, help="Set sync IO mux index before the scan")
    parser.add_argument("--peak-sensing", action="store_true", help="Use vendor external peak-sensing path")
    parser.add_argument("--external-trigger", action="store_true", help="Use external ASIC acquisition trigger bit")
    parser.add_argument("--adc-trigger-type", type=int, default=0, help="Vendor ADC trigger type code")
    parser.add_argument("--adc-trigger-source", type=int, default=3, help="Vendor ADC trigger source code")
    parser.add_argument("--adc-window-ns", type=int, default=50, help="ADC coincidence/window width; divisible by 5 ns")
    parser.add_argument("--adc-nb-trig", type=int, default=1, help="ADC time-window trigger count")
    parser.add_argument("--rstn-manual", action="store_true", help="Set vendor ADC reset-n manual bit")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="Timeout per ADC batch")
    parser.add_argument("--pat-gain", type=int, help="Optional trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the trigger channel with masks")
    parser.add_argument("--use-ctest", action="store_true", help="Enable Ctest on the trigger channel")
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
        out_dir=out_dir,
    )
    scan_config.validate()
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            firmware = prepare_device(device, args)
            if args.sync_io_mux_index is not None:
                mux = device.write_fpga_io_mux(**{args.sync_io: args.sync_io_mux_index})
                print(f"sync IO mux: {mux}")
            settings = settings_from_args(
                args,
                scan="hold",
                out_dir=out_dir,
                trigger_channel=trigger_channel,
                hold_max=hold_max,
                hold_step=hold_step,
            )
            metadata = run_metadata(connection=connection, settings=settings, firmware_word=firmware)
            result = device.run_hold_scan(scan_config, metadata=metadata)
        print(f"hold scan CSV: {result.csv_path}")
        if result.metadata_path:
            print(f"metadata: {result.metadata_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
