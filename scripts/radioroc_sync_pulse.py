#!/usr/bin/env python3
"""Pulse the RADIOROC FPGA synchro trigger output."""

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
from radioroc_client import FPGA_FIRMWARE_STATUS_WORD, FPGA_IO_NAMES, RadiorocDevice, RadiorocSerial, SyncPulseConfig


def build_parser(preset: dict[str, object] | None = None, preset_path: Path | None = None) -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for sync pulse tests.
    """

    parser = argparse.ArgumentParser(description="Pulse the FPGA synchro trigger output.")
    apply_preset_defaults(parser, preset or {}, preset_path)
    add_connection_args(parser)
    parser.add_argument("--execute", action="store_true", help="Write hardware. Without this, dry-run only.")
    parser.add_argument("--sync-io", choices=FPGA_IO_NAMES, default="io1", help="FPGA IO used for sync diagnostics")
    parser.add_argument("--sync-io-mux-index", type=int, help="Set sync IO mux index before pulsing")
    parser.add_argument("--pulses", type=int, default=1000, help="Number of pulses")
    parser.add_argument("--period-ms", type=float, default=10.0, help="Pulse period")
    return parser


def main() -> int:
    """Run the sync pulse command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    preset_path, preset = load_preset_from_argv()
    args = build_parser(preset, preset_path).parse_args()
    connection = connection_config_from_args(args)
    config = SyncPulseConfig(
        sync_io=args.sync_io,
        sync_io_mux_index=args.sync_io_mux_index,
        pulses=args.pulses,
        period_ms=args.period_ms,
    )
    config.validate()
    try:
        with RadiorocSerial.from_config(connection) as transport:
            device = RadiorocDevice(transport, dry_run=not args.execute)
            firmware = device.read_word(FPGA_FIRMWARE_STATUS_WORD)
            metadata = run_metadata(connection=connection, settings=settings_from_args(args, scan="sync_pulse"), firmware_word=firmware)
            result = device.run_sync_pulse(config, metadata=metadata)
        print(f"pulsed {result.pulses} times on {result.sync_io}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
