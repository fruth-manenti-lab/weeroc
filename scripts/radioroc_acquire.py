#!/usr/bin/env python3
"""Collect fixed-setting RADIOROC ADC events."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import signal
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
    AcquisitionConfig,
    DEFAULT_CONFIG,
    RadiorocDevice,
    RadiorocSerial,
    default_run_dir,
    parse_channels,
)
from radioroc.application import CancellationToken
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig


def write_live_spectrum(
    values: list[float],
    *,
    out: Path,
    channel: int,
    gain: str,
    bins: int,
    batches_done: int,
    yscale: str,
) -> None:
    """Write or refresh a live spectrum PNG.

    **Inputs**
    - `values` (`list[float]`): Accumulated ADC values.
    - `out` (`Path`): Output PNG path.
    - `channel` (`int`): Channel being plotted.
    - `gain` (`str`): Gain name, `"hg"` or `"lg"`.
    - `bins` (`int`): Histogram bin count.
    - `batches_done` (`int`): Number of completed batches.
    - `yscale` (`str`): Y-axis scale, usually `"log"` or `"linear"`.

    **Returns**
    - `None`
    """

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/radioroc-matplotlib")
    import matplotlib.pyplot as plt

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    if values:
        ax.hist(values, bins=bins, histtype="stepfilled", alpha=0.75)
        ax.text(
            0.98,
            0.95,
            f"events={len(values)}\nmin={min(values):.2f}\nmax={max(values):.2f}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.8},
        )
    else:
        ax.text(0.5, 0.5, "Waiting for events", transform=ax.transAxes, ha="center", va="center")
        ax.set_xlim(0, 1)
        ax.set_ylim(0.1 if yscale == "log" else 0, 1)
    ax.set_title(f"RADIOROC ch{channel} {gain.upper()} spectrum after {batches_done} batches")
    ax.set_xlabel("ADC amplitude (vendor scale 0.25/code)")
    ax.set_ylabel("Counts")
    ax.set_yscale(yscale)
    ax.grid(True, alpha=0.3)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def load_existing_events(csv_path: Path, *, channel: int, gain: str) -> tuple[int, int, list[float]]:
    """Load existing acquisition rows for append mode.

    **Inputs**
    - `csv_path` (`Path`): Existing `events.csv` path.
    - `channel` (`int`): Channel to collect values for the live plot.
    - `gain` (`str`): Gain column to collect, `"hg"` or `"lg"`.

    **Returns**
    - `tuple[int, int, list[float]]`: Next batch index, existing row count, and
      live-plot values for the requested channel/gain.
    """

    if not csv_path.exists():
        return 0, 0, []

    max_batch = -1
    row_count = 0
    values: list[float] = []
    with csv_path.open(newline="") as fp:
        for row in csv.DictReader(fp):
            row_count += 1
            max_batch = max(max_batch, int(row["batch"]))
            if int(row["channel"]) == channel:
                values.append(float(row[gain]))
    return max_batch + 1, row_count, values


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - `preset` (`dict[str, object] | None`): Optional preset defaults.
    - `preset_path` (`Path | None`): Preset path.

    **Returns**
    - `argparse.ArgumentParser`: Acquisition parser.
    """

    parser = argparse.ArgumentParser(description="Collect fixed-setting RADIOROC ADC events.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--channels", help="Channels to save, e.g. 4 or 0-3")
    parser.add_argument("--trigger-channel", type=int, help="Trigger channel; defaults to first saved channel")
    parser.add_argument("--threshold-dac", type=int, help="T1/T2 threshold DAC before acquisition")
    parser.add_argument("--hold-delay-ns", type=int, help="External hold delay in ns")
    parser.add_argument("--conversion-delay-ns", type=int, help="ADC conversion delay in ns")
    parser.add_argument("--acquisitions-per-batch", type=int, help="Requested ADC acquisitions per batch")
    parser.add_argument("--batches", type=int, help="Number of acquisition batches")
    parser.add_argument("--timeout-s", type=float, help="Timeout per acquisition batch")
    parser.add_argument("--pat-gain", type=int, help="Trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--hg-gain-code", type=int, help="High-gain ADC shaper gain code, 1..15")
    parser.add_argument("--lg-gain-code", type=int, help="Low-gain ADC shaper gain code, 1..15")
    parser.add_argument("--peak-sensing", action="store_true", help="Use external peak-sensing ADC path")
    parser.add_argument("--t2", action="store_true", help="Use T2 threshold instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the trigger channel with masks")
    parser.add_argument("--adc-trigger-type", type=int, help="Vendor ADC trigger type code")
    parser.add_argument("--adc-trigger-source", type=int, help="Vendor ADC first coincidence-input code (T1 slot)")
    parser.add_argument("--adc-trigger-source-2", type=int,
                         help="Vendor ADC second coincidence-input code (T2 slot)")
    parser.add_argument("--trigger-channel-2", type=int,
                         help="Second coincidence channel, used when --adc-trigger-source-2 selects Individual (3)")
    parser.add_argument("--adc-window-ns", type=int, help="ADC coincidence/window width")
    parser.add_argument("--adc-nb-trig", type=int, help="ADC time-window trigger count")
    parser.add_argument("--rstn-manual", action="store_true", help="Set vendor ADC reset-n manual bit")
    parser.add_argument("--synchro-trigger", action="store_true", help="Pulse FPGA synchro trigger for each ADC batch")
    parser.add_argument("--live-plot", action="store_true", help="Refresh a spectrum PNG during acquisition")
    parser.add_argument("--plot-channel", type=int, help="Channel for live plot; defaults to trigger channel")
    parser.add_argument("--plot-gain", choices=["hg", "lg"], help="Gain for live plot")
    parser.add_argument("--plot-bins", type=int, help="Histogram bins for live plot")
    parser.add_argument("--plot-yscale", choices=["log", "linear"], help="Live plot y-axis scale")
    parser.add_argument("--plot-every", type=int, help="Refresh live plot every N batches")
    parser.add_argument("--plot-out", type=Path, help="Live plot PNG path; defaults beside events.csv")
    parser.add_argument("--append", action="store_true", help="Append to an existing events.csv instead of overwriting")
    parser.add_argument("--verify-restoration", action="store_true",
                        help="Independently read back captured FPGA/ASIC state after acquisition cleanup")
    parser.add_argument("--out-dir", type=Path, help="Output directory; default is under radioroc_runs/")
    return parser


def main() -> int:
    """Run ADC event acquisition.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    if args.channels is None:
        args.channels = "4"
    if args.threshold_dac is None:
        args.threshold_dac = 530
    if args.hold_delay_ns is None:
        args.hold_delay_ns = 530
    if args.conversion_delay_ns is None:
        args.conversion_delay_ns = 400
    if args.acquisitions_per_batch is None:
        args.acquisitions_per_batch = 50
    if args.batches is None:
        args.batches = 10
    if args.timeout_s is None:
        args.timeout_s = 5.0
    if args.pat_gain is None:
        args.pat_gain = 1
    if args.adc_trigger_type is None:
        args.adc_trigger_type = 0
    if args.adc_trigger_source is None:
        args.adc_trigger_source = 3
    if args.adc_trigger_source_2 is None:
        args.adc_trigger_source_2 = 0
    if args.trigger_channel_2 is None:
        args.trigger_channel_2 = 0
    if args.adc_window_ns is None:
        args.adc_window_ns = 50
    if args.adc_nb_trig is None:
        args.adc_nb_trig = 1
    if args.plot_gain is None:
        args.plot_gain = "hg"
    if args.plot_bins is None:
        args.plot_bins = 100
    if args.plot_yscale is None:
        args.plot_yscale = "log"
    if args.plot_every is None:
        args.plot_every = 1
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    trigger_channel = args.trigger_channel if args.trigger_channel is not None else channels[0]
    plot_channel = args.plot_channel if args.plot_channel is not None else trigger_channel
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("acquire", channels=channels)
    csv_path = out_dir / "events.csv"
    plot_path = Path(args.plot_out) if args.plot_out else out_dir / f"live_spectrum_ch{plot_channel}_{args.plot_gain}.png"
    start_batch, existing_events, live_values = load_existing_events(
        csv_path,
        channel=plot_channel,
        gain=args.plot_gain,
    ) if args.append else (0, 0, [])

    acquisition_config = AcquisitionConfig(
        channels=channels,
        trigger_channel=trigger_channel,
        threshold_dac=args.threshold_dac,
        hold_delay_ns=args.hold_delay_ns,
        conversion_delay_ns=args.conversion_delay_ns,
        acquisitions_per_batch=args.acquisitions_per_batch,
        batches=args.batches,
        start_batch=start_batch,
        timeout_s=args.timeout_s,
        trigger_preamp_gain=args.pat_gain,
        high_gain_code=args.hg_gain_code,
        low_gain_code=args.lg_gain_code,
        peak_sensing=args.peak_sensing,
        t1=not args.t2,
        use_mask=not args.no_mask,
        trigger_type=args.adc_trigger_type,
        trigger_source=args.adc_trigger_source,
        trigger_source_2=args.adc_trigger_source_2,
        trigger_channel_2=args.trigger_channel_2,
        adc_window_ns=args.adc_window_ns,
        adc_nb_trig=args.adc_nb_trig,
        rstn_manual=args.rstn_manual,
        synchro_trigger=args.synchro_trigger,
        out_dir=out_dir,
    )
    try:
        connection.validate()
        operation = AcquisitionJobConfig(
            acquisition_config,
            config_path=Path(args.config) if args.config is not None else DEFAULT_CONFIG,
            initialize_fpga=not args.skip_fpga_init,
            apply_defaults=args.apply_defaults,
        )
        preview = AcquisitionJob.preview(operation)
        if args.verify_restoration:
            preview["verify_restoration"] = True
        # Dry-run takes no dependency on transport creation or discovery.
        if not args.execute:
            print(json.dumps(preview, indent=2))
            return 0

        append = args.append and csv_path.exists()
        if args.live_plot:
            write_live_spectrum(
                live_values,
                out=plot_path,
                channel=plot_channel,
                gain=args.plot_gain,
                bins=args.plot_bins,
                batches_done=start_batch,
                yscale=args.plot_yscale,
            )
            print(f"events CSV: {csv_path}")
            print(f"live plot: {plot_path}")
            if args.append:
                print(f"append mode: existing_events={existing_events}; next_batch={start_batch}")

        settings = settings_from_args(
            args, scan="acquisition", out_dir=out_dir,
            trigger_channel=trigger_channel, start_batch=start_batch, existing_events=existing_events,
        )
        metadata = run_metadata(connection=connection, settings=settings, firmware_word=None)
        cancellation = CancellationToken()
        total_events = existing_events
        progress_step = max(1, math.ceil(args.batches / 10))

        def progress(event):
            nonlocal total_events
            if event.kind != "point":
                return
            values = dict(event.values)
            observed = max((len(values.get(f"ch{ch}_hg", [])) for ch in channels), default=0)
            total_events += sum(len(values.get(f"ch{ch}_hg", [])) for ch in channels)
            if args.live_plot:
                live_values.extend(values.get(f"ch{plot_channel}_{args.plot_gain}", []))
                if event.completed_points % args.plot_every == 0:
                    write_live_spectrum(
                        live_values,
                        out=plot_path,
                        channel=plot_channel,
                        gain=args.plot_gain,
                        bins=args.plot_bins,
                        batches_done=start_batch + event.completed_points,
                        yscale=args.plot_yscale,
                    )
            if event.completed_points == event.total_points or event.completed_points % progress_step == 0:
                percent = 100.0 * event.completed_points / event.total_points
                print(
                    f"progress {percent:5.1f}% ({event.completed_points}/{event.total_points} batches): "
                    f"last_batch_events={observed}; total_events={total_events}",
                    flush=True,
                )

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
                        result = AcquisitionJob().run(
                            RadiorocDevice(transport), operation, metadata=metadata,
                            cancellation=cancellation, on_event=progress, verify_restoration=True, append=append)
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
                    result = AcquisitionJob().run(RadiorocDevice(transport), operation, metadata=metadata,
                                                  cancellation=cancellation, on_event=progress, append=append)
        finally:
            signal.signal(signal.SIGINT, previous_handler)
        print(f"acquisition {result.status}: {result.points} batches; cleanup={result.cleanup_status}")
        print(f"events CSV: {result.csv_path}")
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
