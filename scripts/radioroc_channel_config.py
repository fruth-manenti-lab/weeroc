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
from radioroc.application.channel_config import ChannelConfigOperation, apply_channel_config
from radioroc_client import RadiorocDevice, RadiorocSerial, parse_channels


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
    parser.add_argument("--tq-mask-value", type=int, choices=[0, 1],
                        help="TQ mask bit to write (default: 1/enabled)")
    parser.add_argument("--input-dac-enable", help="Channels to set input DAC enable for")
    parser.add_argument("--input-dac-enable-value", type=int, choices=[0, 1],
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
    if args.tq_mask_value is None:
        args.tq_mask_value = 1
    if args.input_dac_enable_value is None:
        args.input_dac_enable_value = 1
    if args.input_dac_value is not None and args.value is None:
        print("ERROR: --input-dac-value requires --value", file=sys.stderr)
        return 1
    operations = [args.tq_mask, args.input_dac_enable, args.input_dac_value, args.input_dac_impedance]
    if not any(operations):
        print("ERROR: at least one of --tq-mask, --input-dac-enable, --input-dac-value, "
              "--input-dac-impedance is required", file=sys.stderr)
        return 1

    operation = ChannelConfigOperation(
        tq_mask_channels=tuple(parse_channels(args.tq_mask)) if args.tq_mask else (),
        tq_mask_value=bool(args.tq_mask_value),
        input_dac_enable_channels=tuple(parse_channels(args.input_dac_enable)) if args.input_dac_enable else (),
        input_dac_enable_value=bool(args.input_dac_enable_value),
        input_dac_value_channels=tuple(parse_channels(args.input_dac_value)) if args.input_dac_value is not None else (),
        input_dac_value=args.value,
        input_dac_impedance=(args.input_dac_impedance == "low") if args.input_dac_impedance else None,
        verify=args.verify,
        restore=args.restore,
    )

    connection = connection_config_from_args(args)
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            prepare_device(device, args)
            result = apply_channel_config(device, operation)

            for line in result.applied:
                print(("DRY " if not args.execute else "") + line)
            if operation.verify:
                print(f"verified {result.touched_rows} rows; mismatches: {len(result.verify_mismatches)}")
                for mismatch in result.verify_mismatches[:20]:
                    print(f"mismatch add={mismatch.add} subadd={mismatch.subadd}: "
                          f"expected={mismatch.expected} observed={mismatch.observed}")
            if result.restored:
                print(f"restored {result.touched_rows} rows")
                if operation.verify:
                    print(f"restore-verified {result.touched_rows} rows; "
                          f"mismatches: {len(result.restore_mismatches)}")
                    for mismatch in result.restore_mismatches[:20]:
                        print(f"restore mismatch add={mismatch.add} subadd={mismatch.subadd}: "
                              f"expected={mismatch.expected} observed={mismatch.observed}")
        return 2 if (result.verify_mismatches or result.restore_mismatches) else 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
