#!/usr/bin/env python3
"""Collect fixed-setting RADIOROC ADC events."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
import sys
import time

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
from radioroc_client import (
    AsicRegisterSnapshot,
    FpgaWordSnapshot,
    RadiorocDevice,
    RadiorocSerial,
    default_run_dir,
    parse_channels,
    write_metadata_json,
)


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
    parser.add_argument("--channels", default="4", help="Channels to save, e.g. 4 or 0-3")
    parser.add_argument("--trigger-channel", type=int, help="Trigger channel; defaults to first saved channel")
    parser.add_argument("--threshold-dac", type=int, default=530, help="T1/T2 threshold DAC before acquisition")
    parser.add_argument("--hold-delay-ns", type=int, default=530, help="External hold delay in ns")
    parser.add_argument("--conversion-delay-ns", type=int, default=400, help="ADC conversion delay in ns")
    parser.add_argument("--acquisitions-per-batch", type=int, default=50, help="Requested ADC acquisitions per batch")
    parser.add_argument("--batches", type=int, default=10, help="Number of acquisition batches")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="Timeout per acquisition batch")
    parser.add_argument("--pat-gain", type=int, default=1, help="Trigger preamp paT gain code, 1=max, 63=min")
    parser.add_argument("--hg-gain-code", type=int, help="High-gain ADC shaper gain code, 1..15")
    parser.add_argument("--lg-gain-code", type=int, help="Low-gain ADC shaper gain code, 1..15")
    parser.add_argument("--peak-sensing", action="store_true", help="Use external peak-sensing ADC path")
    parser.add_argument("--t2", action="store_true", help="Use T2 threshold instead of T1")
    parser.add_argument("--no-mask", action="store_true", help="Do not isolate the trigger channel with masks")
    parser.add_argument("--adc-trigger-type", type=int, default=0, help="Vendor ADC trigger type code")
    parser.add_argument("--adc-trigger-source", type=int, default=3, help="Vendor ADC trigger source code")
    parser.add_argument("--adc-window-ns", type=int, default=50, help="ADC coincidence/window width")
    parser.add_argument("--adc-nb-trig", type=int, default=1, help="ADC time-window trigger count")
    parser.add_argument("--rstn-manual", action="store_true", help="Set vendor ADC reset-n manual bit")
    parser.add_argument("--synchro-trigger", action="store_true", help="Pulse FPGA synchro trigger for each ADC batch")
    parser.add_argument("--live-plot", action="store_true", help="Refresh a spectrum PNG during acquisition")
    parser.add_argument("--plot-channel", type=int, help="Channel for live plot; defaults to trigger channel")
    parser.add_argument("--plot-gain", choices=["hg", "lg"], default="hg", help="Gain for live plot")
    parser.add_argument("--plot-bins", type=int, default=100, help="Histogram bins for live plot")
    parser.add_argument("--plot-yscale", choices=["log", "linear"], default="log", help="Live plot y-axis scale")
    parser.add_argument("--plot-every", type=int, default=1, help="Refresh live plot every N batches")
    parser.add_argument("--plot-out", type=Path, help="Live plot PNG path; defaults beside events.csv")
    parser.add_argument("--append", action="store_true", help="Append to an existing events.csv instead of overwriting")
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
    connection = connection_config_from_args(args)
    channels = parse_channels(args.channels)
    trigger_channel = args.trigger_channel if args.trigger_channel is not None else channels[0]
    plot_channel = args.plot_channel if args.plot_channel is not None else trigger_channel
    out_dir = Path(args.out_dir) if args.out_dir else default_run_dir("acquire", channels=channels)
    csv_path = out_dir / "events.csv"
    plot_path = Path(args.plot_out) if args.plot_out else out_dir / f"live_spectrum_ch{plot_channel}_{args.plot_gain}.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    start_batch, existing_events, live_values = load_existing_events(
        csv_path,
        channel=plot_channel,
        gain=args.plot_gain,
    ) if args.append else (0, 0, [])
    csv_mode = "a" if args.append and csv_path.exists() else "w"
    write_header = csv_mode == "w"

    try:
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
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            firmware = prepare_device(device, args)
            metadata = run_metadata(
                connection=connection,
                settings=settings_from_args(
                    args,
                    scan="acquisition",
                    out_dir=out_dir,
                    trigger_channel=trigger_channel,
                    start_batch=start_batch,
                    existing_events=existing_events,
                ),
                firmware_word=firmware,
            )

            saved_fpga: FpgaWordSnapshot = device.snapshot_fpga_words([2])
            saved_asic_registers = [(65, 12)] + [(channel, 2) for channel in channels]
            saved_asic: AsicRegisterSnapshot = device.snapshot_asic_registers(saved_asic_registers)
            if args.pat_gain is not None:
                device.set_trigger_preamp_gain(args.pat_gain, channels=[trigger_channel])
            device.set_energy_shaper_gain(
                channels=channels,
                high_gain_code=args.hg_gain_code,
                low_gain_code=args.lg_gain_code,
            )
            device.set_threshold_dac(args.threshold_dac, t1=not args.t2)
            device.prepare_trigger_masks(t1=not args.t2, use_mask=not args.no_mask, use_ctest=False)
            if not args.no_mask:
                device.set_mask_for_channel(trigger_channel, t1=not args.t2, enabled=True)

            with csv_path.open(csv_mode, newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=["batch", "event", "channel", "hg", "lg"])
                if write_header:
                    writer.writeheader()
                start = time.perf_counter()
                total_events = existing_events
                progress_step = max(1, math.ceil(args.batches / 10))
                try:
                    for batch_offset in range(args.batches):
                        batch = start_batch + batch_offset
                        device.configure_adc_external_hold(
                            trigger_channel=trigger_channel,
                            hold_delay_ns=args.hold_delay_ns,
                            conversion_delay_ns=args.conversion_delay_ns,
                            nb_acq=args.acquisitions_per_batch,
                            trigger_type=args.adc_trigger_type,
                            trigger_source=args.adc_trigger_source,
                            rstn_manual=args.rstn_manual,
                            ext_trig=False,
                            peak_sensing=args.peak_sensing,
                            adc_window_ns=args.adc_window_ns,
                            adc_nb_trig=args.adc_nb_trig,
                        )
                        high_gain, low_gain = device.acquire_adc_batch(
                            nb_acq=args.acquisitions_per_batch,
                            timeout_s=args.timeout_s,
                            synchro_trigger=args.synchro_trigger,
                        )
                        observed = max((len(high_gain[channel]) for channel in channels), default=0)
                        for channel in channels:
                            for event, (hg, lg) in enumerate(zip(high_gain[channel], low_gain[channel])):
                                writer.writerow({"batch": batch, "event": event, "channel": channel, "hg": hg, "lg": lg})
                                total_events += 1
                                if args.live_plot and channel == plot_channel:
                                    live_values.append(hg if args.plot_gain == "hg" else lg)
                        fp.flush()
                        batches_done = batch_offset + 1
                        total_batches_done = batch + 1
                        if args.live_plot and batches_done % args.plot_every == 0:
                            write_live_spectrum(
                                live_values,
                                out=plot_path,
                                channel=plot_channel,
                                gain=args.plot_gain,
                                bins=args.plot_bins,
                                batches_done=total_batches_done,
                                yscale=args.plot_yscale,
                            )
                        should_print_progress = (
                            batches_done == args.batches
                            or batches_done % progress_step == 0
                        )
                        if should_print_progress:
                            percent = 100.0 * batches_done / args.batches
                            print(
                                f"progress {percent:5.1f}% ({batches_done}/{args.batches} batches): "
                                f"last_batch_events={observed}; total_events={total_events}"
                            )
                finally:
                    if not args.no_mask:
                        device.prepare_trigger_masks(t1=not args.t2, use_mask=True, use_ctest=False)
                    device.restore_asic_registers(saved_asic)
                    device.restore_fpga_words(saved_fpga)
                elapsed = time.perf_counter() - start
            metadata_path = write_metadata_json(metadata, out_dir)
        if not args.live_plot:
            print(f"events CSV: {csv_path}")
        print(f"metadata: {metadata_path}")
        print(f"elapsed seconds: {elapsed:.3f}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
