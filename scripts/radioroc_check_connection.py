#!/usr/bin/env python3
"""Command-line read-only connection check for a RADIOROC 2 board."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radioroc_client import (  # noqa: E402
    DEFAULT_BAUD,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT_SECONDS,
    FPGA_FIRMWARE_STATUS_WORD,
    RadiorocConnectionConfig,
    RadiorocSerial,
    parse_bits,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for the connection-check command.
    """

    parser = argparse.ArgumentParser(description="Read firmware/status word from a RADIOROC 2 board.")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Serial baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Serial timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--address",
        type=int,
        default=FPGA_FIRMWARE_STATUS_WORD,
        help=f"FPGA word address to read (default: {FPGA_FIRMWARE_STATUS_WORD})",
    )
    return parser


def main() -> int:
    """Run the read-only RADIOROC connection check.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code. `0` means the board replied.
    """

    args = build_parser().parse_args()
    config = RadiorocConnectionConfig(port=args.port, baud=args.baud, timeout_s=args.timeout)
    try:
        with RadiorocSerial.from_config(config) as board:
            word = board.read_word(args.address)
        print(f"OK: address {args.address} = {word} ({parse_bits(word)})")
        return 0
    except Exception as exc:
        print(f"ERROR: RADIOROC read failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
