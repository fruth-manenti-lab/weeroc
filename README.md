# WEEROC RADIOROC 2 tools

Small Python tools for working with a WEEROC RADIOROC 2 evaluation board over USB serial on macOS.

This repository intentionally does not include the WEEROC installer, extracted binaries, local conda environment, or generated run outputs.

## Contents

- `scripts/radioroc_standard_scurves.py`: standard setup, default ASIC I2C write/readback, pedestal S-curve scan, and experimental autocalibration flow.
- `scripts/radioroc_serial_probe.py`: read-only USB serial probe for FPGA register reads.
- `scripts/radioroc_env_check.py`: environment/import/device visibility check.
- `configs/radio_default_i2c.csv`: default RADIOROC 2 ASIC I2C table used by the standard setup flow.
- `environment-radioroc.yml`: conda environment specification.

## Environment

Create an environment:

```bash
conda env create -f environment-radioroc.yml
conda activate radioroc
```

The working Mac setup used the board's FTDI VCP serial port:

```text
/dev/cu.usbserial-RD3_320
```

## Standard Setup

Apply the default ASIC configuration and verify readback:

```bash
python scripts/radioroc_standard_scurves.py --execute --apply-defaults --verify-defaults --verify-limit 0
```

Expected result on the tested board:

```text
Verified 677 I2C default rows: 677 ok, 0 mismatch
```

## Pedestal S-Curve

Run a no-external-signal pedestal/noise S-curve. Do not pass `--use-ctest` for this mode.

```bash
python scripts/radioroc_standard_scurves.py --execute --scurve --channels 0 --dac-min 100 --dac-max 200 --dac-step 10
```

On the tested board, channel 0 crossed around DAC `145-155`.

## Signal S-Curve

For signal S-curves, pass `--use-ctest` and provide an external pulse into `in_test`/Ctest synchronized from the S-curve clock output, normally FPGA `IO0`.

## Notes

Autocalibration support is present but should be treated carefully. First verify default I2C readback and a small pedestal S-curve on a few channels before running it across all 64 channels.

