"""List candidate USB interfaces and board ownership identities without opening them."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import radioroc_client  # Makes source-package imports available to legacy scripts.
from radioroc.transport.discovery import list_board_ports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable candidate information")
    args = parser.parse_args()
    ports = list_board_ports()
    if args.json:
        print(json.dumps([{**asdict(p), "identity": p.identity} for p in ports], indent=2))
    elif not ports:
        print("No FTDI 0403:6010 candidates found.")
    else:
        for port in ports:
            print(f"{port.port}: {port.description}; {port.identity}")
        print("Candidates only; choose --port explicitly and verify a firmware/status response.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
