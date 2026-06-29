# WEEROC RADIOROC 2 Tools

Python tools for working with a WEEROC RADIOROC 2 evaluation board over USB
serial on macOS.

This repository intentionally does not include the WEEROC installer, extracted
binaries, local conda environment, or generated run outputs.

## Layout

- `radioroc_client.py`: hardware-facing library for serial frames, FPGA words,
  ASIC I2C slow control, scan configuration, scan execution, metadata, and
  non-hardware fake transport tests.
- `radioroc_analysis.py`: CSV parsing, latest-run discovery, plot rendering,
  and simple threshold/hold scan summaries.
- `scripts/radioroc_check_connection.py`: read-only FPGA status-word check.
- `scripts/radioroc_apply_defaults.py`: apply and optionally verify the default
  ASIC I2C table.
- `scripts/radioroc_threshold_scan.py`: trigger-rate threshold scans.
- `scripts/radioroc_scurve.py`: S-curve scans.
- `scripts/radioroc_hold_scan.py`: internal/external hold scans.
- `scripts/radioroc_sync_pulse.py`: FPGA synchro-trigger pulse test.
- `scripts/radioroc_io_mux_scan.py`: FPGA IO mux diagnostic scan.
- `scripts/plot_threshold_scan.py`, `scripts/plot_hold_scan.py`,
  `scripts/plot_hold_comparison.py`: plotting wrappers.
- `configs/radio_default_i2c.csv`: default RADIOROC 2 ASIC I2C table.
- `configs/presets/`: known-good workflow presets.
- `tests/`: non-hardware unit tests.
- `scripts/radioroc_standard_scurves.py`: legacy compatibility script kept as a
  reference until the new scripts fully replace it in daily use.

## Environment

Create the conda environment:

```bash
conda env create -f environment-radioroc.yml
conda activate radioroc
```

The tested Mac setup used:

```text
/dev/cu.usbserial-RD3_320
```

## Safety Model

Write-capable scripts are dry-run by default. Add `--execute` only when the
board is connected, powered, and the input cabling is correct.

Generated outputs go under `radioroc_runs/`, which is ignored by git. Vendor
installers, extracted files, archives, and local notes belong under
`local_artifacts/`, also ignored by git.

## Quick Checks

Read the FPGA firmware/status word:

```bash
python scripts/radioroc_check_connection.py
```

Expected response on the tested board:

```text
OK: address 100 = 00000101 (5)
```

Apply default ASIC settings:

```bash
python scripts/radioroc_apply_defaults.py --execute --verify --verify-limit 0
```

## Preset Workflows

The short user-facing commands use JSON presets. Command-line flags override
values from the preset.

Channel-4 SiPM dark threshold scan:

```bash
python scripts/radioroc_threshold_scan.py \
  --execute \
  --preset configs/presets/threshold_ch4_sipm_dark.json \
  --out-dir radioroc_runs/threshold_ch4_sipm_dark
```

External track-and-hold Ctest scan:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_track_ctest_ch4.json \
  --out-dir radioroc_runs/hold_external_track_ctest_ch4
```

External peak-sensing Ctest scan:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_peak_ctest_ch4.json \
  --out-dir radioroc_runs/hold_external_peak_ctest_ch4
```

IO1 synchro pulse test at mux index 5:

```bash
python scripts/radioroc_sync_pulse.py \
  --execute \
  --preset configs/presets/sync_pulse_io1_mux5.json
```

IO1 mux scan:

```bash
python scripts/radioroc_io_mux_scan.py \
  --execute \
  --preset configs/presets/io_mux_scan_io1.json
```

## Plotting

Plot the newest threshold scan:

```bash
python scripts/plot_threshold_scan.py --latest --steps --summary
```

Plot the newest hold scan:

```bash
python scripts/plot_hold_scan.py --latest --channels 4 --gain hg --summary
```

For internal hold scans, code `0` can be a bad edge-case point. Use:

```bash
python scripts/plot_hold_scan.py --latest --exclude-zero
```

Compare several hold scans:

```bash
python scripts/plot_hold_comparison.py \
  radioroc_runs/run_a/holdscan.csv \
  radioroc_runs/run_b/holdscan.csv \
  --channel 4 \
  --gain hg
```

## Physical Meaning

Threshold scan / SiPM staircase:
The threshold DAC is swept while the FPGA counts discriminator triggers in a
fixed time window. With a biased SiPM, the trigger rate versus DAC reveals the
dark-count staircase and the useful threshold region.

S-curve:
The ASIC threshold is swept while a pulse/noise occupancy counter is read. It is
used for pedestal/noise studies and later calibration work.

Internal hold:
The ASIC internal delay-cell hold code is swept and ADC values are read. Code
`0` can produce an invalid or misleading edge point, so diagnostic plots often
exclude it.

External track-and-hold:
The FPGA-generated external hold delay is swept. With synchronized Ctest
injection, this maps the timing region where the ADC samples the injected pulse
properly.

External peak sensing:
The vendor external peak-sensing path is used instead of a simple external hold
sample. It is useful as a timing diagnostic and comparison to track-and-hold.

## Known Lab Setup

- FPGA `IO1` is connected to the signal generator external trigger input.
- `IO1` mux index `5` produces the usable synchro trigger pulses.
- The signal generator output goes through a 20 dB attenuator into `in-test1`
  for Ctest scans.
- A typical Ctest setup used a 500 mV generator pulse before attenuation, about
  50 mV at the board input, 100 ns width, triggered burst mode.
- Channel `4` is the current test channel.

## Tests

Run non-hardware tests:

```bash
python -m py_compile radioroc_client.py radioroc_analysis.py scripts/*.py tests/*.py
python -m unittest discover -s tests -v
```

Live hardware smoke tests are documented in `SMOKE_TESTS.md`; they are not
automatic tests because they require board state, cabling, and sometimes an
oscilloscope.
