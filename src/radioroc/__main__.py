"""Dispatch installed commands to the existing CLI implementations."""

from __future__ import annotations

import argparse
from importlib import import_module
from importlib.metadata import version
import sys


COMMANDS = {
    "check-connection": "radioroc_check_connection",
    "apply-defaults": "radioroc_apply_defaults",
    "scurve": "radioroc_scurve",
    "threshold-scan": "radioroc_threshold_scan",
    "hold-scan": "radioroc_hold_scan",
    "acquire": "radioroc_acquire",
    "sync-pulse": "radioroc_sync_pulse",
    "io-mux-scan": "radioroc_io_mux_scan",
    "plot-threshold": "plot_threshold_scan",
    "plot-hold": "plot_hold_scan",
    "plot-hold-comparison": "plot_hold_comparison",
    "plot-spectrum": "plot_acquisition_spectrum",
    "standard-scurves": "radioroc_standard_scurves",
    "serial-probe": "radioroc_serial_probe",
}


def main(argv: list[str] | None = None) -> int:
    """Route arguments without duplicating hardware or workflow logic."""
    parser = argparse.ArgumentParser(description="RADIOROC board and analysis tools")
    parser.add_argument("--version", action="version", version=version("radioroc-tools"))
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    module = import_module(f"radioroc.cli.{COMMANDS[args.command]}")
    original_argv = sys.argv
    try:
        sys.argv = [f"radioroc {args.command}", *args.arguments]
        return module.main() or 0
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
