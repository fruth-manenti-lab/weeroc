"""Standalone FPGA initialization / ASIC default-register application.

The same two operations the scan jobs run before a scan when their
`initialize_fpga` / `apply_defaults` options are set, exposed as a single
bounded job so the ASIC configuration page can trigger them directly.
Both persist on the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from radioroc_client import DEFAULT_CONFIG, RadiorocDevice

from .asic_config_file import load_asic_config, merge_asic_config


@dataclass(frozen=True)
class ChipInitOperation:
    """Which preparation steps to run (FPGA init first, then defaults)."""

    initialize_fpga: bool = False
    apply_defaults: bool = False
    config_path: Path | None = None  # custom table to write instead of the packaged default

    def validate(self) -> None:
        for name in ("initialize_fpga", "apply_defaults"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")
        if self.config_path is not None:
            if not self.apply_defaults:
                raise ValueError("config_path requires apply_defaults")
            load_asic_config(self.config_path)
        if not (self.initialize_fpga or self.apply_defaults):
            raise ValueError("select at least one of initialize_fpga / apply_defaults")


@dataclass(frozen=True)
class ChipInitResult:
    initialize_fpga: bool
    apply_defaults: bool
    rows_written: int = 0


def run_chip_init(device: RadiorocDevice, operation: ChipInitOperation) -> ChipInitResult:
    """Run the requested steps on an already-open device.

    Hardware side effects: `initialize_fpga` writes FPGA control words 0 and
    1. `apply_defaults` reloads the packaged default ASIC table and writes
    all of it, resetting every ASIC setting and wiping autocalibration trims.
    """

    operation.validate()
    rows_written = 0
    if operation.initialize_fpga:
        device.initialize_fpga()
    if operation.apply_defaults:
        rows = load_asic_config(DEFAULT_CONFIG)
        if operation.config_path is not None:  # custom/vendor file overlays the packaged table
            rows = merge_asic_config(rows, load_asic_config(operation.config_path))
        device.i2c_rows = rows
        device.apply_default_config()
        rows_written = len(device.i2c_rows)
    return ChipInitResult(operation.initialize_fpga, operation.apply_defaults, rows_written)
