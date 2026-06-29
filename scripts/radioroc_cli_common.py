#!/usr/bin/env python3
"""Shared command-line helpers for RADIOROC scripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radioroc_client import (  # noqa: E402
    DEFAULT_BAUD,
    DEFAULT_CONFIG,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT_SECONDS,
    FPGA_FIRMWARE_STATUS_WORD,
    RadiorocConnectionConfig,
    RadiorocDevice,
    RadiorocRunMetadata,
    parse_bits,
)


def load_preset(path: Path | None) -> dict[str, object]:
    """Load a JSON preset file.

    **Inputs**
    - `path` (`Path | None`): Preset path, or `None`.

    **Returns**
    - `dict[str, object]`: Preset settings. Empty when no path is supplied.
    """

    if path is None:
        return {}
    with path.open(encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError("preset JSON must contain an object at the top level")
    return data


def load_preset_from_argv(argv: list[str] | None = None) -> tuple[Path | None, dict[str, object]]:
    """Pre-parse `--preset` before building a full command parser.

    **Inputs**
    - `argv` (`list[str] | None`): Argument list. Defaults to `sys.argv[1:]`.

    **Returns**
    - `tuple[Path | None, dict[str, object]]`: Preset path and loaded values.
    """

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preset", type=Path)
    args, _ = parser.parse_known_args(argv)
    return args.preset, load_preset(args.preset)


def apply_preset_defaults(
    parser: argparse.ArgumentParser,
    preset: dict[str, object],
    preset_path: Path | None,
) -> None:
    """Add `--preset` and apply preset values as parser defaults.

    **Inputs**
    - `parser` (`argparse.ArgumentParser`): Parser to modify.
    - `preset` (`dict[str, object]`): Preset settings.
    - `preset_path` (`Path | None`): Preset path for metadata/default display.

    **Returns**
    - `None`
    """

    parser.add_argument("--preset", type=Path, default=preset_path, help="JSON preset file; CLI flags override it")
    if preset:
        parser.set_defaults(**preset)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    """Add shared serial connection arguments.

    **Inputs**
    - `parser` (`argparse.ArgumentParser`): Parser to modify.

    **Returns**
    - `None`
    """

    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Serial baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Serial timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )


def add_write_safety_args(parser: argparse.ArgumentParser) -> None:
    """Add shared write-safety and board-preparation arguments.

    **Inputs**
    - `parser` (`argparse.ArgumentParser`): Parser to modify.

    **Returns**
    - `None`
    """

    parser.add_argument("--execute", action="store_true", help="Write hardware. Without this, run in dry-run mode.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"I2C config CSV (default: {DEFAULT_CONFIG})")
    parser.add_argument("--skip-fpga-init", action="store_true", help="Do not write the standard FPGA init words.")
    parser.add_argument("--apply-defaults", action="store_true", help="Apply the default I2C table before the command.")


def connection_config_from_args(args: argparse.Namespace) -> RadiorocConnectionConfig:
    """Create connection settings from parsed CLI arguments.

    **Inputs**
    - `args` (`argparse.Namespace`): Parsed arguments with serial fields.

    **Returns**
    - `RadiorocConnectionConfig`: Library connection dataclass.
    """

    return RadiorocConnectionConfig(port=args.port, baud=args.baud, timeout_s=args.timeout)


def prepare_device(device: RadiorocDevice, args: argparse.Namespace) -> str:
    """Load defaults, read firmware, and run optional board setup.

    **Inputs**
    - `device` (`RadiorocDevice`): Open RADIOROC device wrapper.
    - `args` (`argparse.Namespace`): Parsed arguments with setup fields.

    **Returns**
    - `str`: Firmware/status word read from FPGA address 100.

    **Hardware side effects**
    - Reads the firmware/status word.
    - May initialize FPGA words and apply default ASIC configuration.
    """

    device.load_default_config(Path(args.config))
    firmware_word: str = device.read_word(FPGA_FIRMWARE_STATUS_WORD)
    print(f"firmware/status word: {firmware_word} ({parse_bits(firmware_word)})")
    if not args.skip_fpga_init:
        device.initialize_fpga()
    if args.apply_defaults:
        device.apply_default_config()
    return firmware_word


def run_metadata(
    *,
    connection: RadiorocConnectionConfig,
    settings: dict[str, object],
    firmware_word: str | None,
) -> RadiorocRunMetadata:
    """Create standard run metadata for CLI commands.

    **Inputs**
    - `connection` (`RadiorocConnectionConfig`): Serial connection settings.
    - `settings` (`dict[str, object]`): Command-specific settings.
    - `firmware_word` (`str | None`): Firmware/status word read from board.

    **Returns**
    - `RadiorocRunMetadata`: Metadata ready to write as JSON.
    """

    return RadiorocRunMetadata.create(
        connection=connection,
        settings=settings,
        command=sys.argv,
        firmware_status_word=firmware_word,
    )


def settings_from_args(args: argparse.Namespace, **extra: object) -> dict[str, object]:
    """Convert parsed CLI arguments into JSON-safe metadata settings.

    **Inputs**
    - `args` (`argparse.Namespace`): Parsed command-line arguments.
    - `**extra` (`object`): Additional metadata fields.

    **Returns**
    - `dict[str, object]`: Settings suitable for `metadata.json`.
    """

    settings: dict[str, object] = {}
    for key, value in {**vars(args), **extra}.items():
        settings[key] = str(value) if isinstance(value, Path) else value
    return settings
