# WEEROC RADIOROC 2 tools

Small Python tools for working with a WEEROC RADIOROC 2 evaluation board over USB serial on macOS.

This repository intentionally does not include the WEEROC installer, extracted binaries, local conda environment, or generated run outputs.

## Contents

- `scripts/radioroc_standard_scurves.py`: standard setup, default ASIC I2C write/readback, pedestal S-curve scan, threshold scan, and experimental autocalibration flow.
- `scripts/plot_threshold_scan.py`: plot threshold-scan CSV files to PNG.
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

## Threshold Scan

Run a trigger-rate threshold scan for one channel. This is the basis of the SiPM staircase measurement described in the RADIOROC user guide.

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --threshold-scan \
  --channels 4 \
  --dac-min 80 \
  --dac-max 180 \
  --dac-step 2 \
  --trigger-window-ms 100 \
  --out-dir radioroc_runs/threshold_ch4
```

Optionally set the selected channel's trigger preamplifier gain before the scan:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --threshold-scan \
  --channels 4 \
  --trigger-preamp-gain 8 \
  --dac-min 60 \
  --dac-max 220 \
  --dac-step 2 \
  --trigger-window-ms 200 \
  --out-dir radioroc_runs/threshold_ch4_gain8
```

The trigger preamplifier gain code follows the RADIOROC UI convention: `1` is maximum gain, `63` is minimum gain, and `0` is intentionally rejected because it opens/unbiases the preamplifier.

For an EXE-like SiPM dark staircase comparison, use a longer window and repeated acquisitions:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --apply-defaults \
  --threshold-scan \
  --channels 4 \
  --pat-gain 1 \
  --dac-min 0 \
  --dac-max 600 \
  --dac-step 5 \
  --trigger-window-ms 500 \
  --threshold-averages 3 \
  --out-dir radioroc_runs/staircase_ch4_gain1_compare
```

Plot the result:

```bash
python scripts/plot_threshold_scan.py
```

By default the plotter finds the newest `thresholdscan.csv` under `radioroc_runs` and writes a PNG beside it. To plot a specific file:

```bash
python scripts/plot_threshold_scan.py \
  radioroc_runs/threshold_ch4/thresholdscan.csv \
  --channels 4 \
  --yscale log \
  --steps
```

## Notes

Autocalibration support is present but should be treated carefully. First verify default I2C readback and a small pedestal S-curve on a few channels before running it across all 64 channels.
