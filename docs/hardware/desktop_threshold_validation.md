# Desktop hardware threshold validation card (RADIOROC 12/13 — PASSED, all cases)

**State: PASSED.** All five required GUI cases (T1, T2, cancel-in-window,
cancel-after-point, close-during-run) completed with `cleanup=restored` and
`verification.status=passed` (exact expected/observed match) on 2026-09-11.
See "RADIOROC 12 execution record" below. RADIOROC 13 (2026-09-14) extended
coverage beyond the single hardcoded channel (4) used by every case above to a
small set of channels spanning the 64-channel ASIC's low/adjacent/boundary
range; see "RADIOROC 13 multi-channel execution record" below. This card
covers the desktop `ConnectionWorker` hardware workflow only. The earlier
`bare_board_threshold_validation.md` records RADIOROC 05 CLI evidence,
separate from this GUI authorization.

## Setup and preflight

Use a powered bare RADIOROC board over USB with no SiPM or pulser connected.
Close competing vendor software and terminals. The designated operator must
perform a fresh read-only port discovery and status check, select the control
port explicitly, record the operator, host/time, USB identity, port, baud,
timeout, status word, and config-table path/hash. Use baud **115200**, timeout
**0.5 s**, and `configs/radio_default_i2c.csv`, subject to the fresh confirmed
port and table hash. Confirm the desktop build and that the connection is owned
by one `ConnectionWorker`. Do not infer firmware identity or capability from an
opaque status word. Stop before Run if any port, status, wiring, power,
ownership, or output-path check is uncertain.

The UI must first show an offline preview with no device open and no output
directory created. Configure exactly: T1 and T2 as separate passes; channel 4;
DAC 0..1, step 1; counter window 10 ms; averages 1; mask enabled; Ctest
disabled; unchanged trigger gain; FPGA initialization false; default
application false; and mandatory restoration verification true. Use a new empty
run directory for each pass. Review the preview before connecting or running.

## Required GUI cases

Run T1 and T2 separately. Each case must show the selected device/session,
live completed points and terminal status, and must save a readable manifest and
CSV. The shared `ThresholdJob` must perform cleanup and its independent
restoration verifier in the same owned session before terminal delivery. A
successful case requires complete rows, no cleanup/storage/persistence/close
errors, `cleanup=restored`, and verifier `status=passed` with exact expected and
observed values. The connected session remains open after a normal completed or
cancelled terminal result; only an explicit Disconnect or window shutdown
releases it. Record the console/UI log and run paths.

Exercise cancellation with the same conservative settings:

1. Set DAC 0..0 and window 60000 ms. Request Cancel during the long window.
   A generic UI `running` state does not establish that the counter is active;
   use an explicit instrumented worker phase event if available. Otherwise
   record request-to-terminal timing and state that the in-window phase was not
   independently established. Record completed points, cleanup, verification,
   and confirmation that the connected session remains open after terminal
   delivery. The timing establishes UI responsiveness and bounded cleanup; it
   must not claim an independently observed counter edge.
2. Set DAC 0..2 and window 1000 ms. Request Cancel after the first completed
   point is visibly persisted. Confirm that point remains readable, later work
   stops, cleanup and verification complete before the terminal result, and the
   connection remains open for explicit Disconnect.
3. Start the 60000 ms case and close the window while the scan is still running.
   Confirm that shutdown requests cancellation, waits for cleanup and
   verification, then releases the session and ownership. Record stop timing,
   terminal/error evidence, and whether close succeeds or remains retryable.

For every case, stop and preserve evidence on timeout, disconnect, unexpected
status, malformed or short readback, output failure, cleanup failure, verifier
mismatch/incompleteness, or close failure. A failed close must leave the session
owned for an explicit retry; retry the close only through the worker and record
the result. Any fault blocks another scan until reviewed and, where applicable,
the operator disconnects. The application must not silently repair device state,
retry a scan, or continue after a failed verifier.

## Shutdown and evidence

For normal operation, use explicit Disconnect after the final run and verify
that it releases the session. For the close-during-run case, verify that the
worker stops accepting new jobs, waits for cancellation/cleanup and
verification, releases the session on successful window shutdown, and leaves a
visible retry path when close fails. Record stop/cleanup/error evidence, session
ownership transitions, terminal status, verifier report, manifest/CSV paths, and
the exact settings.
Do not start a wider scan, change Ctest or gain, apply defaults, initialize the
FPGA, connect detector/pulser hardware, or claim analog/detector performance.

## RADIOROC 07 stopped execution record

On 2026-09-11, the designated lead was the sole board operator. The authorized
setup was a powered bare board over USB only, with no SiPM or pulser and no
competing software. Evidence is preserved locally and ignored under
`radioroc_runs/physical_desktop_20260911T015835Z/`. The configuration hash was
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

Native Cocoa preflight discovery, connect, repeated status reads and disconnect
passed. It found USB identity `usb:0403:6010:serial:RD3_32`, control port
`/dev/cu.usbserial-RD3_320`, and status word `5`; the status word is recorded
without a firmware interpretation.

The actual GUI was driven by the local harness. T1 and T2 normal DAC 0..1,
channel 4, 10 ms cases each completed 2 points / 2 windows, restored the
temporary configuration, retained the connection, passed mandatory verification,
and reopened successfully. Each
verification matched the exact 130 ASIC rows and FPGA words 0/1/6
`00111111` / `00000000` / `00000000`; all observed rates were 0 Hz. The T2
terminal screenshot also retains the previous T1 saved-result banner while
showing the correct T2 live plot/details. This is an evidence/UI presentation
issue for offline investigation, not a completed physical acceptance criterion.

The next T1 case used DAC 0 and a 60000 ms window. It failed at
2026-09-11 02:07:02.014 UTC, after about 0.639 s, with
`TransportTimeoutError` after the 0.5 s
transport timeout, before a complete snapshot: 0 points, 0 windows, no
counter-window marker, and incomplete verification. No GUI Cancel was
requested, so this is not cancellation evidence. The lead interrupted the
harness with SIGINT at 02:07:27.651 UTC while it waited for a marker after the
board fault had already finished. The emergency GUI Disconnect then succeeded with idle
`port=None` and `close_error=None`; shutdown stopped the worker and the process
exited 1. No later cases, retry, repair, wider scan, or close-during-run case
was attempted.

Offline audit shows preparation succeeded and FPGA words 0/1/6 were read;
the timeout occurred during the 130-row ASIC `read_fifo` before its snapshot
was assigned. No trigger-mask, DAC, channel or counter operation was reached.
Outer cleanup's word-60 idle write and word-0 restore succeeded, but the
verifier remained incomplete with all 3 FPGA and 130 ASIC expected snapshot
entries missing. The saved evidence does not identify which underlying device
request caused the timeout.

The card remains pending/stopped. The successful T1/T2 normal cases are
recorded physical evidence, but the two cancellation cases and successful
close-during-run acceptance remain untested. Explicit Disconnect and shutdown
after the fault did succeed. The failure leaves restoration verification
incomplete because the required pre-scan snapshot was incomplete.

**Disposition:** STOPPED after the first long-window transport fault. Do not
claim cancellation or close-during-run acceptance and do not auto-retry scans.
Next work is offline diagnosis and improved local phase-wait fault detection
and evidence, followed by a concrete status-only recovery card.

## RADIOROC 08 offline follow-up

The original 49 inventoried files were verified unchanged. The timeout remains
unlocalized within ASIC snapshot acquisition; no hardware was accessed. Local
phase-wait handling was improved and the stale saved-result banner corrected
with offline regression coverage. See `IMPLEMENTATION_STATUS.md` for checks.
The physical card stays stopped. The next bounded procedure is
[status-only recovery](desktop_status_recovery.md), requiring fresh operator
authorization; it does not authorize resuming these scan cases.

## RADIOROC 12 execution record

On 2026-09-11, after RADIOROC 11's evidenced status-only recovery, the user
confirmed the preconditions (powered bare board, no SiPM/pulser, no competing
software) and authorized rerunning this exact card, unmodified, via the
existing `radioroc07_gui_card.py` harness (same script used for the RADIOROC 07
attempt, byte-identical). The lead was sole software operator. Evidence is
local and ignored under `radioroc_runs/physical_desktop_20260911T075002Z/`.

The harness ran the full sequence: offline preview, connect/status (status 5),
`t1_normal` and `t2_normal` (2 points/2 windows each, as in RADIOROC 07),
`t1_cancel_window` (DAC 0..0, 60000 ms window, Cancel requested after the
instrumented long-window marker fired), `t1_cancel_after_point` (DAC 0..2,
1000 ms window, Cancel requested after the first point was visibly persisted),
an explicit Disconnect/reconnect between the fourth and fifth case, and
`t1_close_window` (60000 ms window, native window closed while scanning).

All five cases passed. For every case, `cleanup.status == "restored"` with no
cleanup errors, and `verification.status == "passed"` with empty
`mismatches`/`missing`/`errors` against the expected FPGA words 0/1/6 and all
130 ASIC snapshot rows. The two cancellation cases and the close-during-run
case — the exact scope left untested when RADIOROC 07 stopped — are now
positively verified: cancellation during a long counter window, cancellation
after a completed point, and window-close during an active scan all leave the
board's temporary configuration independently confirmed restored, not just
self-reported. The harness script itself raises on any mismatch before
declaring a case passed, so no result here is inferred without that check.
The worker reached `stopped` cleanly at the end with no close error and no
`close_failed` state at any point; `git status`/source hashes recorded in
`source_provenance.json` for this run confirm the transport/threshold-job code
is unchanged from RADIOROC 07.

This completes the required case set defined earlier in this document. Not
covered by this card, still requiring separate authorization: wider DAC/scan
ranges, Ctest/gain variation, FPGA initialization/defaults, detector
(SiPM/pulser) connection, and any analog/detector performance claim — the
board remained bare throughout.

## RADIOROC 13 multi-channel execution record

Every prior physical GUI case (RADIOROC 07, 12) used a single hardcoded
channel (4). On 2026-09-14, with the board confirmed powered/bare (no
SiPM/pulser) and competing software closed, the user authorized two new T1
scans reusing the exact same conservative settings (DAC 0..1, 10 ms window,
averages 1, mask enabled, Ctest disabled, no FPGA init/defaults, mandatory
restoration verification) but varying the `channels` field: adjacent channels
`[4, 5]`, then boundary channels `[0, 31, 63]` (first, middle, and last of the
64-channel ASIC). No cancellation or close-during-run case was in scope. The
lead wrote a new harness (`radioroc13_multichannel_card.py`, adapted from the
RADIOROC 07/12 script) and was sole software operator.

A first execution attempt
(`radioroc_runs/physical_multichannel_20260914T013419Z/`) stopped on a
`RuntimeError` for the `[4, 5]` case — but the only reported problem was a
mismatched expected `attempts` count (`4` observed vs. `2` hardcoded in the
harness). The scan's own `cleanup.status == "restored"` and
`verification.status == "passed"` (exact FPGA/ASIC match) were unaffected; the
harness's emergency handler disconnected and closed the session cleanly
(`idle` -> `stopped`, no `close_failed`, no fault). Root cause: `attempts`
scales as `channels x DAC points x averages` in the shared `ThresholdJob`
(confirmed by reading `src/radioroc/application/threshold.py`), not just DAC
points as the single-channel cases had it; the harness's hardcoded expected
values did not account for that. This was a bug in the new local verification
script, not a hardware or application fault, and did not require a fresh
authorization to correct and rerun (same board state, same two authorized
cases, same settings).

The harness's expected-attempts values were corrected (`4` for `[4, 5]`, `6`
for `[0, 31, 63]`) and rerun immediately
(`radioroc_runs/physical_multichannel_20260914T013527Z/`). Both cases passed:
`t1_multichannel_adjacent` (channels 4, 5; 2 points, 4 attempts) and
`t1_multichannel_boundary` (channels 0, 31, 63; 2 points, 6 attempts), each
with `cleanup.status == "restored"` and `verification.status == "passed"`
(empty mismatches/missing) against the expected FPGA words 0/1/6 and full ASIC
snapshot, and each CSV carrying a populated rate column per requested channel.
The connection ended in a clean explicit Disconnect and worker shutdown
(`stopped`, not alive). `source_provenance.json` for the passing run confirms
the transport/threshold-job source is unchanged from RADIOROC 12.

This is the first physical evidence that the multi-channel scan path (masking
and measuring more than one channel within a single job) works correctly,
including at the ASIC's channel-index boundaries (0 and 63). Not covered:
channels other than 0, 4, 5, 31, 63; more than 3 channels in one scan; wider
DAC ranges; or any cancellation/close-during-run case with multiple channels
— each would need its own bounded authorization.
