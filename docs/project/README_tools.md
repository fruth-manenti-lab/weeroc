# RADIOROC Command Guide

Use commands through the conda environment:

```bash
conda activate radioroc
```

or call the environment Python directly:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python <script>
```

## Read-Only

Check that the board responds:

```bash
python scripts/radioroc_check_connection.py
```

Probe a specific FPGA word:

```bash
python scripts/radioroc_serial_probe.py --address 100 --baud 115200
```

## Board Setup

Apply default ASIC I2C settings:

```bash
python scripts/radioroc_apply_defaults.py --execute
```

Apply and verify the full table:

```bash
python scripts/radioroc_apply_defaults.py --execute --verify --verify-limit 0
```

## Threshold Scan

Use the channel-4 SiPM dark-count preset:

```bash
python scripts/radioroc_threshold_scan.py \
  --execute \
  --preset configs/presets/threshold_ch4_sipm_dark.json
```

Short live test:

```bash
python scripts/radioroc_threshold_scan.py \
  --execute \
  --preset configs/presets/threshold_ch4_sipm_dark.json \
  --dac-min 0 \
  --dac-max 100 \
  --dac-step 10 \
  --out-dir radioroc_runs/live_test_threshold_ch4_short
```

## Hold Scan

External track-and-hold Ctest:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_track_ctest_ch4.json
```

Short live test:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_track_ctest_ch4.json \
  --hold-min 450 \
  --hold-max 560 \
  --hold-step 25 \
  --acquisitions 10 \
  --out-dir radioroc_runs/live_test_external_hold_ch4_short
```

External peak-sensing Ctest:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_peak_ctest_ch4.json
```

Internal hold diagnostic:

```bash
python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_internal_ctest_ch4_diagnostic.json
```

## Sync And IO Diagnostics

Pulse IO1 mux index 5:

```bash
python scripts/radioroc_sync_pulse.py \
  --execute \
  --preset configs/presets/sync_pulse_io1_mux5.json
```

Scan IO1 mux indices:

```bash
python scripts/radioroc_io_mux_scan.py \
  --execute \
  --preset configs/presets/io_mux_scan_io1.json
```

## Plotting

Threshold:

```bash
python scripts/plot_threshold_scan.py --latest --steps --summary
```

Hold:

```bash
python scripts/plot_hold_scan.py --latest --channels 4 --gain hg --summary
```

Hold comparison:

```bash
python scripts/plot_hold_comparison.py \
  radioroc_runs/run_a/holdscan.csv \
  radioroc_runs/run_b/holdscan.csv \
  --channel 4 \
  --gain hg
```

## Output Files

Each scan writes:

- scan CSV, for example `thresholdscan.csv` or `holdscan.csv`
- `metadata.json`
- plot PNG when a plot script is run

Run outputs are ignored by git under `radioroc_runs/`.
