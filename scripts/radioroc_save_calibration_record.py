#!/usr/bin/env python3
"""Save a plint calibration record (Step 6 of the plint calibration procedure).

A thin, hand-run record-keeping tool: it ties together the sub-scan output
directories from Steps 1/2/4/5 plus the operator's judgment calls (threshold
margin reasoning, excluded channels, per-channel relative response) into one
saved `calibration_record.json`. See `docs/plint_calibration_procedure.md`
Step 6 and `radioroc.data.calibration_record`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from uuid import uuid4

# Prefer this checkout's package when running without installation (matches
# radioroc_client.py's own bootstrap, needed since this script has no other
# reason to import that legacy module first).
_source_package = Path(__file__).resolve().parents[1] / "src"
if (_source_package / "radioroc").is_dir():
    sys.path.insert(0, str(_source_package))

from radioroc.data.calibration_record import save_calibration_record


def _default_out_dir() -> Path:
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return Path.cwd() / "radioroc_runs" / "calibration" / name


def _parse_sub_scan(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--sub-scan must be label=path, got {text!r}")
    label, path = text.split("=", 1)
    return label, path


def _parse_per_channel(text: str) -> tuple[str, float]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--per-channel-response must be ch=value, got {text!r}")
    channel, value = text.split("=", 1)
    try:
        return channel, float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--per-channel-response value is not numeric: {text!r}") from exc


def _parse_excluded(text: str) -> dict:
    if ":" not in text:
        raise argparse.ArgumentTypeError(f"--excluded-channel must be channel:reason, got {text!r}")
    channel, reason = text.split(":", 1)
    return {"channel": channel, "reason": reason}


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    **Inputs**
    - None

    **Returns**
    - `argparse.ArgumentParser`: Parser for saving a calibration record.
    """

    parser = argparse.ArgumentParser(description="Save an attributable plint calibration record.")
    parser.add_argument("--out-dir", type=Path,
                        help="Directory to write calibration_record.json into; "
                             "default is a new timestamped radioroc_runs/calibration/<...> directory")
    parser.add_argument("--operator", required=True, help="Who ran the calibration")
    parser.add_argument("--threshold-dac", type=int, required=True, help="Chosen threshold DAC code")
    parser.add_argument("--threshold-margin-reasoning", required=True,
                        help="Why this threshold margin was chosen")
    parser.add_argument("--sub-scan", action="append", default=[], type=_parse_sub_scan,
                        metavar="label=path",
                        help="Sub-scan output directory, repeatable, "
                             "e.g. --sub-scan step1_pedestal=/path/to/dir")
    parser.add_argument("--per-channel-response", action="append", default=[], type=_parse_per_channel,
                        metavar="ch=value",
                        help="Per-channel relative response, repeatable, e.g. --per-channel-response ch4=10800.0")
    parser.add_argument("--excluded-channel", action="append", default=[], type=_parse_excluded,
                        metavar="channel:reason",
                        help="Excluded channel and why, repeatable, e.g. --excluded-channel ch6:dead preamp")
    parser.add_argument("--hold-delay-ns", type=int, help="Chosen hold delay in ns")
    parser.add_argument("--conversion-delay-ns", type=int, help="Chosen conversion delay in ns")
    parser.add_argument("--trigger-preamp-gain-code", type=int, help="Trigger preamp gain code used")
    return parser


def main() -> int:
    """Run the save-calibration-record command.

    **Inputs**
    - None

    **Returns**
    - `int`: Process exit code.
    """

    args = build_parser().parse_args()
    out_dir = args.out_dir if args.out_dir is not None else _default_out_dir()
    out_path = Path(out_dir) / "calibration_record.json"
    sub_scan_dirs = dict(args.sub_scan)
    per_channel_relative_response = dict(args.per_channel_response)
    try:
        written = save_calibration_record(
            out_path,
            operator=args.operator,
            threshold_dac=args.threshold_dac,
            threshold_margin_reasoning=args.threshold_margin_reasoning,
            per_channel_relative_response=per_channel_relative_response,
            sub_scan_dirs=sub_scan_dirs,
            excluded_channels=args.excluded_channel,
            hold_delay_ns=args.hold_delay_ns,
            conversion_delay_ns=args.conversion_delay_ns,
            trigger_preamp_gain_code=args.trigger_preamp_gain_code,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
