"""Generic ASIC I2C register read/write, shared by CLI and GUI.

Unlike `ChannelConfigOperation`'s per-channel semantic writes (a mask bit, an
input DAC code, ...), this is direct register access: any `(add, subadd)`
pair, an arbitrary raw byte -- for the vendor app's "Register mode" toggle
(`F06`), which edits the same underlying I2C table one register at a time
instead of through a named parameter.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from radioroc_client import DEFAULT_CONFIG, I2CRow, RadiorocDevice, bits


def _load_rows(existing, config_path: Path | None) -> list[I2CRow]:
    if config_path is None and existing:
        return deepcopy(list(existing))
    with Path(config_path or DEFAULT_CONFIG).open(newline="") as stream:
        return [I2CRow(int(row["add"]), int(row["subadd"]), row["data"].strip())
                for row in csv.DictReader(stream)]


@dataclass(frozen=True)
class RawRegisterWrite:
    """One raw-register write request.

    **Attributes**
    - `add` (`int`): ASIC register address, 0..255.
    - `subadd` (`int`): ASIC register subaddress, 0..255.
    - `data` (`str`): Eight-character MSB-first binary string, e.g. `"00010000"`.
    - `verify` (`bool`): Independently read the register back after writing.
    - `config_path` (`Path | None`): ASIC I2C config CSV. When `None` and the
      device already has rows loaded, those existing rows are kept;
      otherwise the packaged default config is loaded, mirroring
      `ChannelConfigOperation.load_rows`'s convention.
    """

    add: int
    subadd: int
    data: str
    verify: bool = True
    config_path: Path | None = None

    def validate(self) -> None:
        if not 0 <= self.add <= 255:
            raise ValueError("add must be in range 0..255")
        if not 0 <= self.subadd <= 255:
            raise ValueError("subadd must be in range 0..255")
        if len(self.data) != 8 or any(bit not in "01" for bit in self.data):
            raise ValueError("data must be an 8-character binary string")


@dataclass(frozen=True)
class RawRegisterResult:
    """Outcome of one applied `RawRegisterWrite`.

    **Attributes**
    - `add` (`int`): Register address written.
    - `subadd` (`int`): Register subaddress written.
    - `written` (`str`): The value written.
    - `observed` (`str | None`): Independently read-back value, if `verify`
      was requested.
    - `mismatch` (`bool`): Whether `observed` disagreed with `written`.
    """

    add: int
    subadd: int
    written: str
    observed: str | None = None
    mismatch: bool = False


def read_all_registers(device: RadiorocDevice, config_path: Path | None = None) -> list[I2CRow]:
    """Load (if needed) and independently read back every ASIC register.

    **Inputs**
    - `device` (`RadiorocDevice`): Open device.
    - `config_path` (`Path | None`): See `RawRegisterWrite.config_path`.

    **Returns**
    - `list[I2CRow]`: One row per loaded register, `data` set to the value
      just read from hardware (not the CSV-assumed value).

    **Hardware side effects**
    - May load the ASIC config table into `device.i2c_rows`.
    - Reads every loaded register in one batched FIFO transaction.
    """

    device.i2c_rows = _load_rows(device.i2c_rows, config_path)
    if device.i2c_rows:
        observed = device.read_fifo(device.i2c_rows)
        for row, byte in zip(device.i2c_rows, observed):
            row.data = bits(byte, 8)
    return list(device.i2c_rows)


def write_raw_register(device: RadiorocDevice, write: RawRegisterWrite) -> RawRegisterResult:
    """Write one raw ASIC register, optionally verifying the write.

    **Inputs**
    - `device` (`RadiorocDevice`): Open device.
    - `write` (`RawRegisterWrite`): Validated register write request.

    **Returns**
    - `RawRegisterResult`: What was written and, if requested, observed.

    **Hardware side effects**
    - May load the ASIC config table into `device.i2c_rows`.
    - Writes one ASIC register, and reads it back when `verify` is requested.
    """

    write.validate()
    device.i2c_rows = _load_rows(device.i2c_rows, write.config_path)
    device.write_register(write.add, write.subadd, write.data)
    observed = device.read_register_bits(write.add, write.subadd) if write.verify else None
    mismatch = write.verify and observed != write.data
    return RawRegisterResult(write.add, write.subadd, write.data, observed, mismatch)
