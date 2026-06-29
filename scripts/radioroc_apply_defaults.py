#!/usr/bin/env python3
"""Apply and optionally verify the RADIOROC default ASIC configuration."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from radioroc_cli_common import (
    add_connection_args,
    apply_preset_defaults,
    connection_config_from_args,
    load_preset_from_argv,
)
from radioroc_client import DEFAULT_CONFIG, RadiorocDevice, RadiorocSerial, bits


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for applying defaults.
    """

    parser = argparse.ArgumentParser(description="Apply the default RADIOROC ASIC I2C configuration.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    parser.add_argument("--execute", action="store_true", help="Write hardware. Without this, dry-run only.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"I2C config CSV (default: {DEFAULT_CONFIG})")
    parser.add_argument("--skip-fpga-init", action="store_true", help="Do not write the standard FPGA init words.")
    parser.add_argument("--verify", action="store_true", help="Read back the config after applying.")
    parser.add_argument("--verify-limit", type=int, default=16, help="Rows to verify; use 0 for the full table.")
    return parser


def main() -> int:
    """Run default configuration apply/verify.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    connection = connection_config_from_args(args)
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            device.load_default_config(Path(args.config))
            firmware = device.read_word(100)
            print(f"firmware/status word: {firmware}")
            if not args.skip_fpga_init:
                device.initialize_fpga()
            device.apply_default_config()
            print(f"{'DRY ' if not args.execute else ''}applied {len(device.i2c_rows)} default rows")
            if args.verify:
                limit = None if args.verify_limit == 0 else args.verify_limit
                mismatches = device.verify_default_config(limit=limit)
                print(f"verified rows: {len(device.i2c_rows) if limit is None else limit}; mismatches: {len(mismatches)}")
                for add, subadd, expected, observed in mismatches[:20]:
                    print(f"mismatch add={add} subadd={subadd}: expected={bits(expected)} observed={bits(observed)}")
                return 2 if mismatches else 0
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
