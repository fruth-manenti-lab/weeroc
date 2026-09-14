#!/usr/bin/env python3
"""Read/write per-channel input DAC and TQ mask ASIC configuration.

Unlike a threshold scan's temporary mask/Ctest/gain settings, these controls
are configuration state meant to persist (like `radioroc_apply_defaults.py`'s
defaults application), not transient scan parameters that get auto-restored.
Pass `--restore` for a bounded validation run (snapshot before, write, verify,
restore, verify restored) instead of a persistent change.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__:
    from .radioroc_cli_common import (
        add_connection_args,
        add_write_safety_args,
        apply_preset_defaults,
        connection_config_from_args,
        load_preset_from_argv,
        prepare_device,
    )
else:
    from radioroc_cli_common import (
        add_connection_args,
        add_write_safety_args,
        apply_preset_defaults,
        connection_config_from_args,
        load_preset_from_argv,
        prepare_device,
    )
from radioroc_client import N_CHANNELS, RadiorocDevice, RadiorocSerial, parse_channels


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for channel configuration.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    add_write_safety_args(parser)
    parser.add_argument("--tq-mask", help="Channels to set the TQ mask for, e.g. 4 or 0-15 or all")
    parser.add_argument("--tq-mask-value", type=int, choices=[0, 1], default=1,
                        help="TQ mask bit to write (default: 1/enabled)")
    parser.add_argument("--input-dac-enable", help="Channels to set input DAC enable for")
    parser.add_argument("--input-dac-enable-value", type=int, choices=[0, 1], default=1,
                        help="Input DAC enable bit to write (default: 1/enabled)")
    parser.add_argument("--input-dac-value", help="Channels to set the input DAC raw value for")
    parser.add_argument("--value", type=int, help="Raw 8-bit input DAC code, 0..255; required with --input-dac-value")
    parser.add_argument("--input-dac-impedance", choices=["low", "high"],
                        help="Set the single shared input DAC impedance switch (~150 Ohm low, "
                             "or high) across all channels")
    parser.add_argument("--verify", action="store_true", help="Read back touched registers after writing")
    parser.add_argument("--restore", action="store_true",
                        help="Snapshot touched registers before writing and restore them after "
                             "(bounded validation mode). Without this flag, changes persist, "
                             "same as --apply-defaults.")
    return parser


def main() -> int:
    """Run channel configuration read/write/verify/restore.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    if args.input_dac_value is not None and args.value is None:
        print("ERROR: --input-dac-value requires --value", file=sys.stderr)
        return 1
    operations = [args.tq_mask, args.input_dac_enable, args.input_dac_value, args.input_dac_impedance]
    if not any(operations):
        print("ERROR: at least one of --tq-mask, --input-dac-enable, --input-dac-value, "
              "--input-dac-impedance is required", file=sys.stderr)
        return 1

    connection = connection_config_from_args(args)
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            prepare_device(device, args)

            touched: set[tuple[int, int]] = set()
            if args.tq_mask:
                touched.update((ch, 6) for ch in parse_channels(args.tq_mask))
            if args.input_dac_enable:
                touched.update((ch, 6) for ch in parse_channels(args.input_dac_enable))
            if args.input_dac_value is not None:
                touched.update((ch, 0) for ch in parse_channels(args.input_dac_value))
            if args.input_dac_impedance:
                touched.update((ch, 6) for ch in range(N_CHANNELS))

            snapshot: dict[tuple[int, int], str] = {}
            if args.restore:
                snapshot = {(add, subadd): device.read_register_bits(add, subadd) for add, subadd in touched}

            applied: list[str] = []
            if args.tq_mask:
                for ch in parse_channels(args.tq_mask):
                    device.set_tq_mask_for_channel(ch, enabled=bool(args.tq_mask_value))
                    applied.append(f"tq_mask channel={ch} -> {args.tq_mask_value}")
            if args.input_dac_enable:
                for ch in parse_channels(args.input_dac_enable):
                    device.set_input_dac_enable_for_channel(ch, enabled=bool(args.input_dac_enable_value))
                    applied.append(f"input_dac_enable channel={ch} -> {args.input_dac_enable_value}")
            if args.input_dac_value is not None:
                for ch in parse_channels(args.input_dac_value):
                    device.set_input_dac_value(ch, args.value)
                    applied.append(f"input_dac_value channel={ch} -> {args.value}")
            if args.input_dac_impedance:
                device.set_input_dac_impedance(args.input_dac_impedance == "low")
                applied.append(f"input_dac_impedance -> {args.input_dac_impedance}")
            for line in applied:
                print(("DRY " if not args.execute else "") + line)

            mismatches: list[tuple[int, int, str, str]] = []
            if args.verify:
                for add, subadd in sorted(touched):
                    expected = device.find_i2c_row(add, subadd).data
                    observed = device.read_register_bits(add, subadd)
                    if observed != expected:
                        mismatches.append((add, subadd, expected, observed))
                print(f"verified {len(touched)} rows; mismatches: {len(mismatches)}")
                for add, subadd, expected, observed in mismatches[:20]:
                    print(f"mismatch add={add} subadd={subadd}: expected={expected} observed={observed}")

            restore_mismatches: list[tuple[int, int, str, str]] = []
            if args.restore:
                for (add, subadd), data in snapshot.items():
                    device.write_register(add, subadd, data)
                print(f"restored {len(snapshot)} rows")
                if args.verify:
                    for (add, subadd), data in snapshot.items():
                        observed = device.read_register_bits(add, subadd)
                        if observed != data:
                            restore_mismatches.append((add, subadd, data, observed))
                    print(f"restore-verified {len(snapshot)} rows; mismatches: {len(restore_mismatches)}")
                    for add, subadd, expected, observed in restore_mismatches[:20]:
                        print(f"restore mismatch add={add} subadd={subadd}: expected={expected} observed={observed}")
        return 2 if (mismatches or restore_mismatches) else 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
