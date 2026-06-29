#!/usr/bin/env python3
"""Scan RADIOROC FPGA IO mux indices with synchro pulses."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from radioroc_cli_common import (
    add_connection_args,
    apply_preset_defaults,
    connection_config_from_args,
    load_preset_from_argv,
    run_metadata,
    settings_from_args,
)
from radioroc_client import FPGA_FIRMWARE_STATUS_WORD, FPGA_IO_NAMES, IoMuxScanConfig, RadiorocDevice, RadiorocSerial


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for IO mux scans.
    """

    parser = argparse.ArgumentParser(description="Scan FPGA IO mux indices and pulse the synchro trigger.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    parser.add_argument("--execute", action="store_true", help="Write hardware. Without this, dry-run only.")
    parser.add_argument("--sync-io", choices=FPGA_IO_NAMES, default="io1", help="FPGA IO to scan")
    parser.add_argument("--all-ios", action="store_true", help="Set all IO outputs to each mux index")
    parser.add_argument("--pulses-per-index", type=int, default=100, help="Pulses emitted at each mux index")
    parser.add_argument("--period-ms", type=float, default=10.0, help="Pulse period")
    return parser


def main() -> int:
    """Run the IO mux scan command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    connection = connection_config_from_args(args)
    config = IoMuxScanConfig(
        sync_io=args.sync_io,
        scan_all_ios=args.all_ios,
        pulses_per_index=args.pulses_per_index,
        period_ms=args.period_ms,
    )
    config.validate()
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            firmware = device.read_word(FPGA_FIRMWARE_STATUS_WORD)
            metadata = run_metadata(connection=connection, settings=settings_from_args(args, scan="io_mux_scan"), firmware_word=firmware)
            result = device.run_io_mux_scan(config, metadata=metadata)
        print(f"tested mux indices: {result.indices}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
