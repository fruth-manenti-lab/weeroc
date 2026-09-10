# Bare-board threshold validation card (review required)

**Status: EXECUTED — RADIOROC 05 evidence recorded.** This remains an opt-in
procedure for the designated operator. Hardware threshold Run stays disabled;
the RADIOROC 05 checks used the reviewed CLI directly on the confirmed bare
board. Agent/offline work must use the dry-run or a fake transport; it must not
discover, open, or scan hardware.

## Scope and equipment

Use a powered bare RADIOROC board with no SiPM and no external pulser
connected. Confirm the selected control serial port from a fresh, read-only
status check; historical port names and status observations are stale. Use the
approved USB/serial cable, a stable power supply, host time, and an output
directory under `radioroc_runs/`. Do not connect or probe detector/pulser
wiring for this card. Record board identity, firmware/status word, operator,
port, time, config-table path and ambient conditions.

The expected observation is a successfully captured snapshot, a finite run
that can be cancelled, a restoration-verification result, and a
recorded rate trace. With no sensor or pulser, rates may be zero or reflect noise/ambient
activity. A rate curve, plateau, or threshold code must not be treated as proof
of analog gain, DAC linearity, timing accuracy, or detector performance.

## RADIOROC 05 executed evidence

On 2026-09-10, the lead assistant was the sole software operator, using the
user-confirmed powered bare board with USB connected, no SiPM or pulser, and
competing vendor software/terminals closed. Fresh discovery identified USB
`usb:0403:6010:serial:RD3_32`. A fresh status read used port `/dev/cu.usbserial-RD3_320`, baud 115200, timeout 0.5 s,
address 100, and status word `00000101`; status close passed. Ambient was not
measured and board revision was not independently identified. These setup
limits are recorded in `radioroc_runs/physical_threshold_20260910T042911Z/`.

All four cases used `configs/radio_default_i2c.csv` with SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`, channel
4, `--skip-fpga-init`, no `--apply-defaults`, `--verify-restoration`, and
130 captured ASIC rows per case. The exact FPGA snapshot was word 0
`00111111`, word 1 `00000000`, and word 6 `00000000`.

| Case | Result | Evidence |
| --- | --- | --- |
| T1 | 2 points, exit 0; verification passed | `t1/` |
| T2 | 2 points, exit 0; verification passed | `t2/` |
| 60 s window cancellation | First 10 ms delay slice, 0 rows, exit 130; verification passed | `cancel_window/` |
| After-point cancellation | First persisted point, 1 row, exit 130; verification passed | `cancel_after_point/` |

All four cleanups report `restored`; storage, persistence, close, and
verification errors are absent. Word 60 was written idle (`00000000`) during
cleanup; its readback semantics were not used as evidence. The recorded rates
were zero and make no analog or detector-performance claim.

The cancellation cases used `cancel_runner.py`, which instruments the process
locally and raises SIGINT through the production CLI handler. The window phase
was established by production ordering after the enable write and first 10 ms
delay slice, before the stop write; it was not established by an oscilloscope,
active-bit readback, or a human Ctrl-C. The after-point phase was established
after the point had been persisted to CSV and manifest. This instrumentation
does not change production code. Hardware GUI Run remains disabled; the next
slice is desktop integration.

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
  --skip-fpga-init --verify-restoration \
  --out-dir radioroc_runs/bare_threshold_t1_preview
```

After review, the designated operator may run the following physical commands,
once for T1 and once for T2. `--verify-restoration` is required on every
physical card command. Keep `--skip-fpga-init`, omit `--apply-defaults`, and
use a new empty output directory for each pass:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 1 --dac-step 1 --window-ms 10 --averages 1 \
  --skip-fpga-init --execute --verify-restoration \
  --out-dir radioroc_runs/bare_threshold_t1
```

The corresponding T2 command is:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 1 --dac-step 1 --window-ms 10 --averages 1 \
  --skip-fpga-init --t2 --execute --verify-restoration \
  --out-dir radioroc_runs/bare_threshold_t2
```

Do not substitute `--execute` into an unreviewed command. `Ctrl-C` requests
cooperative cancellation; allow the process to finish cleanup and report its
terminal status. Cancellation is checked before preparation, before each DAC
point, during I2C polling, and at least every 10 ms during a counter window.
The two-point example is only a write/cleanup smoke test; it is too short to
demonstrate cancellation inside a window. For that check, start this command
and press Ctrl-C while its long counter window is running:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 0 --dac-step 1 --window-ms 60000 --averages 1 \
  --skip-fpga-init --execute --verify-restoration \
  --out-dir radioroc_runs/bare_threshold_t1_cancel_window
```

For cancellation after a complete DAC point, watch for the first
`threshold dac=...` line from this command, then press Ctrl-C. This is shell
operator observation; the cancellation point is not deterministic and must not
be reported as a timing guarantee:

```bash
.conda-radioroc/bin/python scripts/radioroc_threshold_scan.py \
  --port 'REPLACE_WITH_APPROVED_CONTROL_PORT' --channels 4 \
  --dac-min 0 --dac-max 2 --dac-step 1 --window-ms 1000 --averages 1 \
  --skip-fpga-init --execute --verify-restoration \
  --out-dir radioroc_runs/bare_threshold_t1_cancel_after_point
```

In both cases, Ctrl-C only requests cancellation. Wait for the process to
print terminal scan status, cleanup result, metadata path, and any separate
verification errors. Verification is stored as a `verification` field in the
result and manifest; it is not a second output file. A long window may produce
no point line before cancellation, and the CLI does not make the precise
counter phase observable from point output alone. Use the attempts CSV,
terminal status, and operator timing as practical evidence, without claiming
deterministic phase timing. The after-point case should retain the observed
complete point; cancellation may be observed after entry into a later point,
so record the actual completed rows.

## Acceptance and abort checks

Before starting, verify the preview, selected port, empty output path, stable
power, no detector/pulser connections, and the intended T1/T2 and channel
settings. Abort before execution if any is uncertain.

During the run, abort/cancel on an unexpected board reset, transport timeout or
disconnect, malformed/short readback, unexpected status word, unsafe wiring or
power, or any output/storage error. A failed snapshot is a hard stop: do not
invent ASIC restore values. Cleanup must still be attempted and every cleanup
error retained.

Completion requires a terminal result with no cleanup, persistence or close errors,
`cleanup=restored`, a readable metadata manifest with a readable `verification`
field with `status=passed`, and complete CSV rows for the reported points.
Exit 0 indicates completion; exit 130 indicates clean cancellation with passing
verification; exit 1 requires investigation. Close errors are reported by the
CLI after the manifest is finalized and are not stored in that manifest. Save
the console output alongside the run evidence. The acceptance matrix is:

| Case | Required observation |
| --- | --- |
| T1 pass | Complete run, cleanup, and verifier report with exact restoration matches for the T1 row variant |
| T2 pass | Complete run, cleanup, and verifier report with exact restoration matches for the T2 row variant |
| Cancel during a deliberately long counter window | Cancellation becomes terminal only after cleanup; the verifier report records exact restoration matches |
| Cancel after a complete DAC point | Completed point remains readable; later work is cancelled after the request is observed; cleanup and verification still succeed |

The `--verify-restoration` verifier runs after job cleanup under the same
session lock. It first captures the post-job FPGA baseline (words 0, 1 and 6),
then reads every ASIC row captured by the job. Because ASIC reads use the I2C
FIFO and temporarily change FPGA I2C control state, it finally writes word 60
as idle and restores the exact *observed post-job* FPGA word 0 before rereading
FPGA words 0, 1 and 6. The report includes `status` (`passed`, `failed`, or
`incomplete`), execution mode, expected/observed values, mismatches, missing
rows, errors, and cleanup attempts (`status`, `errors`,
`word60_idle_attempted`, and `word0_restore_attempted`). A mismatch is reported as a verification
error; it is never repaired or hidden. Word 60 readback semantics remain
unresolved, so the idle write is recorded but no word-60 readback comparison is
invented. A failed idle write, mismatch, missing row, or failed reread is an
abort: stop further scans and leave Hardware Run disabled pending review. The
verification field is separate from the primary scan status/result and the CLI
prints verification errors separately; a requested verification that does not
pass also gives the CLI a failing exit status.

Record observed values and command/result metadata: board/firmware identity,
operator and timestamp, approved port, exact command and config hash, T1/T2
variant, channels, DAC/window/average settings, preparation flags, snapshot,
readback comparison, terminal/cleanup/persistence status, CSV and manifest
paths, cancellation case (if any), and aborts/errors. For a future rerun, mark
a case pending until the designated operator records fresh evidence. Label all
conclusions as workflow and register-state validation; this card cannot
establish analog accuracy or physical detector behavior on a bare board.
