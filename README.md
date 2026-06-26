# WEEROC RADIOROC 2 tools

Small Python tools for working with a WEEROC RADIOROC 2 evaluation board over USB serial on macOS.

This repository intentionally does not include the WEEROC installer, extracted binaries, local conda environment, or generated run outputs.

## Contents

- `scripts/radioroc_standard_scurves.py`: standard setup, default ASIC I2C write/readback, pedestal S-curve scan, threshold scan, experimental external-hold scan, and experimental autocalibration flow.
- `scripts/plot_threshold_scan.py`: plot threshold-scan CSV files to PNG.
- `scripts/plot_hold_scan.py`: plot hold-scan CSV files to PNG.
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

## Hold Scan

Experimental hold scan support is available. Internal mode follows the vendor holdscan workflow: the ASIC is put in internal-hold mode, ASIC register `add=65, subadd=8` is swept over the 8-bit hold delay code, ADC frames are read from FPGA address `20`, and `holdscan.csv` records mean/stdev high-gain and low-gain values for each selected channel.

Start with a short channel-4 internal hold scan:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --hold-scan \
  --hold-mode internal \
  --channels 4 \
  --hold-trigger-channel 4 \
  --hold-threshold-dac 250 \
  --hold-min-code 0 \
  --hold-max-code 255 \
  --hold-step-code 5 \
  --hold-acquisitions 10 \
  --pat-gain 1 \
  --use-ctest \
  --hold-synchro-trigger \
  --out-dir radioroc_runs/hold_ch4_smoke
```

If needed, apply and verify defaults as a separate setup step before the scan. Keeping it separate makes hardware/I2C timeouts easier to diagnose.

Plot the newest hold scan:

```bash
python scripts/plot_hold_scan.py --channels 4 --exclude-zero
```

For internal hold scans, code `0` can be an invalid delay-cell edge case and may dominate the y-axis. Use `--exclude-zero` for the standard diagnostic plot, or `--x-min` to remove a wider early-code region.

For synchronized Ctest injection, connect the board FPGA synchro output, labeled as `IO1`/synchro trigger in the vendor hold-scan workflow, to the signal generator external trigger input. Set the generator to externally triggered burst/pulse mode, and connect the generator output through the attenuator to `in-test1`. The `--hold-synchro-trigger` flag pulses the FPGA synchro signal once per requested ADC acquisition batch, matching the vendor holdscan behavior.

To scope the FPGA synchro output without running a scan:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --pulse-synchro-test \
  --sync-pulses 1000 \
  --sync-period-ms 10
```

If no pulse is visible on the connector, scan the FPGA IO mux while watching the scope. The script prints each mux index before pulsing, then restores the original mux settings at the end:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --scan-sync-io-mux \
  --sync-io io1 \
  --sync-pulses 100 \
  --sync-period-ms 10
```

If the connector label is uncertain, scan all configurable FPGA IO outputs at the same mux index. This is the best first diagnostic when a specific `IO1` scan is flat:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --scan-all-sync-io-muxes \
  --sync-pulses 100 \
  --sync-period-ms 10
```

Once the visible mux index is known, set it explicitly before a pulse test:

```bash
python scripts/radioroc_standard_scurves.py \
  --execute \
  --sync-io io1 \
  --sync-io-mux-index <index> \
  --pulse-synchro-test \
  --sync-pulses 1000 \
  --sync-period-ms 10
```

External FPGA-generated hold scan is still available with `--hold-mode external`. In external mode the hold value is a delay in ns and must be divisible by 5.

## Notes

Autocalibration support is present but should be treated carefully. First verify default I2C readback and a small pedestal S-curve on a few channels before running it across all 64 channels.
