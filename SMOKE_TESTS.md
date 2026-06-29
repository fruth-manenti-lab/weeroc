# RADIOROC Smoke Tests

Use these commands after refactor chunks to confirm the known-good workflows
still run. Hardware write commands require the RADIOROC board to be connected
and powered. The synchronized Ctest commands assume:

- FPGA `IO1` is routed to the signal generator trigger input.
- `IO1` mux index `5` produces the synchro pulse.
- The generator output is attenuated into `in-test1`/Ctest.
- Channel `4` is the test channel.

## Read-Only Serial Probe

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_serial_probe.py \
  --port /dev/cu.usbserial-RD3_320 \
  --baud 115200 \
  --address 100 \
  --timeout 0.25
```

Expected response payload at address `100` on the tested board:

```text
aa 00 e4 05 55
```

## Sync Pulse Test

Preset form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_sync_pulse.py \
  --execute \
  --preset configs/presets/sync_pulse_io1_mux5.json
```

Expanded form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_sync_pulse.py \
  --execute \
  --sync-io io1 \
  --sync-io-mux-index 5 \
  --pulses 100 \
  --period-ms 10
```

Expected result: oscilloscope sees a pulse train on the FPGA IO line used as
the generator trigger.

## IO Mux Scan

Preset form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_io_mux_scan.py \
  --execute \
  --preset configs/presets/io_mux_scan_io1.json
```

Expanded form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_io_mux_scan.py \
  --execute \
  --sync-io io1 \
  --pulses-per-index 100 \
  --period-ms 10
```

Expected result: the connected IO line shows pulses at mux index `5`.

## SiPM Dark Threshold Scan

Preset form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --execute \
  --preset configs/presets/threshold_ch4_sipm_dark.json \
  --out-dir radioroc_runs/smoke_threshold_ch4_gain1
```

Expanded form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --execute \
  --apply-defaults \
  --channels 4 \
  --pat-gain 1 \
  --dac-min 0 \
  --dac-max 600 \
  --dac-step 5 \
  --window-ms 100 \
  --averages 1 \
  --out-dir radioroc_runs/smoke_threshold_ch4_gain1
```

Expected result: a channel-4 SiPM dark staircase/trigger-rate curve when the
SiPM is powered and dark.

## External Track-And-Hold Ctest Scan

Preset form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_track_ctest_ch4.json \
  --out-dir radioroc_runs/smoke_external_hold_ch4_ctest
```

Expanded form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_hold_scan.py \
  --execute \
  --mode external \
  --channels 4 \
  --trigger-channel 4 \
  --threshold-dac 250 \
  --hold-min 440 \
  --hold-max 640 \
  --hold-step 10 \
  --acquisitions 30 \
  --conversion-delay-ns 400 \
  --pat-gain 1 \
  --use-ctest \
  --synchro-trigger \
  --sync-io io1 \
  --sync-io-mux-index 5 \
  --rstn-manual \
  --out-dir radioroc_runs/smoke_external_hold_ch4_ctest
```

Expected result: HG rises around `450..475 ns`, plateaus near `800` ADC units,
then rolls off after roughly `575 ns`.

## External Peak-Sensing Ctest Scan

Preset form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_hold_scan.py \
  --execute \
  --preset configs/presets/hold_external_peak_ctest_ch4.json \
  --out-dir radioroc_runs/smoke_external_peak_ch4_ctest
```

Expanded form:

```bash
/Users/tengiz/weeroc/.conda-radioroc/bin/python scripts/radioroc_hold_scan.py \
  --execute \
  --mode external \
  --peak-sensing \
  --channels 4 \
  --trigger-channel 4 \
  --threshold-dac 250 \
  --hold-min 350 \
  --hold-max 750 \
  --hold-step 25 \
  --acquisitions 30 \
  --conversion-delay-ns 160 \
  --pat-gain 1 \
  --use-ctest \
  --synchro-trigger \
  --sync-io io1 \
  --sync-io-mux-index 5 \
  --rstn-manual \
  --out-dir radioroc_runs/smoke_external_peak_ch4_ctest
```

Expected result: HG rises around `450..475 ns` and remains near the peak value
for later hold delays.
