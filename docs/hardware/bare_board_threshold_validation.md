# Bare-board threshold validation card (review required)

**Status: NOT EXECUTED.** This is an opt-in procedure for the designated
operator. Hardware threshold Run stays disabled until this card is reviewed,
the board identity and wiring are confirmed, and every check below can be
completed. Agent/offline work must use the dry-run or a fake transport; it must
not discover, open, or scan hardware.

## Scope and equipment

Use a powered bare RADIOROC board with no SiPM and no external pulser
connected. Confirm the selected control serial port from a fresh, read-only
status check; historical port names and status observations are stale. Use the
approved USB/serial cable, a stable power supply, host time, and an output
directory under `radioroc_runs/`. Do not connect or probe detector/pulser
wiring for this card. Record board identity, firmware/status word, operator,
port, time, config-table path and ambient conditions.

The expected observation is a successfully captured snapshot, a finite run
that can be cancelled, successful restoration readback, and a recorded rate
trace. With no sensor or pulser, rates may be zero or reflect noise/ambient
activity. A rate curve, plateau, or threshold code must not be treated as proof
of analog gain, DAC linearity, timing accuracy, or detector performance.

## Exact state boundary

Before temporary scan writes, the job captures FPGA words **0, 1 and 6** and
ASIC rows selected by the scan configuration. ASIC addresses are written as
`(add, subadd)`:

| Scan choice | Captured ASIC rows | Channel mapping |
| --- | --- | --- |
| T1 (`t1=true`) | `(65,2)`, `(65,1)` | global T1 DAC split across these two rows |
| T2 (`t1=false`) | `(65,2)`, `(65,3)` | global T2 DAC split across these two rows |
| always | `(66,ch)` for `ch=0..63` | discriminator selection for every ASIC channel |
| `use_mask=true` | `(ch,6)` for `ch=0..63` | T1 string index 3 or T2 index 4 (zero-based from MSB) |
| `use_ctest=true` | `(ch,7)` for `ch=0..63` | Ctest string index 3 (zero-based from MSB) |
| `trigger_preamp_gain` supplied | `(ch,1)` for each selected `ch` | selected-channel paT gain rows, based on the loaded table |

The scan writes the selected DAC variant, selects T1 (`00010000`) or T2
(`00100000`) in every `(66,ch)`, clears masks/Ctest as requested, then enables
the selected channel while measuring. `set_threshold_dac` encodes T1 into
`(65,2)` plus `(65,1)`, and T2 into `(65,2)` plus `(65,3)`. A T1 and a T2 pass
must therefore be reviewed as separate variants; never infer one variant's
state from the other. Mask, Ctest and gain writes use the loaded table for
unmodified bits; only final restoration uses the measured snapshot bytes.

FPGA word 6 selects the channel during each measurement. FPGA word 1 is
temporarily used for counter start/stop and is restored; word 0 is used by the
I2C transaction path and is restored. FPGA word 60 is the I2C command strobe,
not saved configuration: cleanup writes `00000000` to leave it idle and does
not replay a captured command. Once I2C snapshot access has started, cleanup
attempts this idle write even on cancellation or failure. Its readback semantics are
not established; record successful completion of the idle write, and abort on
any write error rather than claiming a word-60 readback comparison.

`--skip-fpga-init` and omission of `--apply-defaults` are the recommended
first-pass preparation. If FPGA initialization is enabled, it intentionally
writes words 0 and 1 (`00111111`, `01000000`) and persists after the scan. If
`--apply-defaults` is enabled, the loaded ASIC table is intentionally written
and also persists. These preparation changes are outside the temporary
snapshot/restoration contract; an interrupted preparation can leave partial
or unknown configuration and must be recorded as such.

## Dry-run and opt-in execution

The following is the conservative preview for one channel and two DAC points.
It is the default and must be run first; it validates the table and prints a
JSON preview without opening serial, touching hardware, or creating run files:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 1 --dac-step 1 --window-ms 10 --averages 1 \
  --skip-fpga-init --out-dir radioroc_runs/bare_threshold_t1_preview
```

After review, the designated operator may run the same command with
`--execute`, once for T1 and once with `--t2` for T2. Keep `--skip-fpga-init`,
omit `--apply-defaults`, and use a new empty output directory for each pass:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 1 --dac-step 1 --window-ms 10 --averages 1 \
  --skip-fpga-init --execute --out-dir radioroc_runs/bare_threshold_t1
```

Do not substitute `--execute` into an unreviewed command. `Ctrl-C` requests
cooperative cancellation; allow the process to finish cleanup and report its
terminal status. Cancellation is checked before preparation, before each DAC
point, during I2C polling, and at least every 10 ms during a counter window.
The two-point example is only a write/cleanup smoke test; it is too short to
demonstrate cancellation inside a window.

## Acceptance and abort checks

Before starting, verify the preview, selected port, empty output path, stable
power, no detector/pulser connections, and the intended T1/T2 and channel
settings. Abort before execution if any is uncertain.

During the run, abort/cancel on an unexpected board reset, transport timeout or
disconnect, malformed/short readback, unexpected status word, unsafe wiring or
power, or any output/storage error. A failed snapshot is a hard stop: do not
invent ASIC restore values. Cleanup must still be attempted and every cleanup
error retained.

Completion requires a terminal result with no cleanup or persistence errors,
`cleanup=restored`, a readable metadata manifest and complete CSV rows for the
reported points. The reviewed acceptance matrix is:

| Case | Required observation |
| --- | --- |
| T1 pass | Complete run, cleanup, and exact restoration readback for the T1 row variant |
| T2 pass | Complete run, cleanup, and exact restoration readback for the T2 row variant |
| Cancel during a deliberately long counter window | Cancellation becomes terminal only after cleanup; all captured state is restored |
| Cancel after a complete DAC point | Completed point remains readable; later work stops and cleanup/restoration still succeeds |

Independent reread verification is a review prerequisite because every ASIC
read uses the I2C FIFO and temporarily changes FPGA I2C control state. Capture
the FPGA readbacks before ASIC snapshot reads; after the job restores its state,
perform the verifier's ASIC rereads under the same board owner, then restore
the verifier's own temporary FPGA controls and write word 60 as idle. The
current code has no dedicated side-effect-safe verification helper, so plain
manual reads are not evidence of restoration until this procedure is reviewed
and an operator records the exact command trace. Compare exact 8-bit values for
FPGA words 0, 1 and 6 and every captured ASIC row with the pre-scan snapshot,
recording the comparison separately from the job result. Word 60 is not
compared; any failed idle write, mismatch, missing row, or failed reread is an
abort: stop further scans and leave Hardware Run disabled pending review.

Record observed values and command/result metadata: board/firmware identity,
operator and timestamp, approved port, exact command and config hash, T1/T2
variant, channels, DAC/window/average settings, preparation flags, snapshot,
readback comparison, terminal/cleanup/persistence status, CSV and manifest
paths, cancellation case (if any), and aborts/errors. Mark the card and its
checks **not executed** until the designated operator performs them. Label all
conclusions as workflow and register-state validation; this card cannot
establish analog accuracy or physical detector behavior on a bare board.
