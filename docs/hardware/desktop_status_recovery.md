# Desktop status-only recovery card (RADIOROC 09/10/11)

**State: PASSED under the bounded evidence harness (RADIOROC 11).** After the
RADIOROC 09 timeout (05:16:23 UTC) and the operator's reported power-cycle
recovery, the lead ran this exact status-only card end-to-end at
2026-09-11T07:09:24-07:09:26 UTC: fresh candidate refresh/select, Connect
(status-100 read #1, value 5), one gated repeat (read #2, value 5), explicit
Disconnect, then shutdown, with no error and no close error. This meets the
"Acceptance" criteria defined below. A pre-Connect USB enumeration snapshot
(`system_profiler SPUSBDataType`, no port opened) confirmed the board was
present beforehand. Evidence is local under
`radioroc_runs/physical_status_20260911T070909Z/`. This still does not accept
configuration restoration, ASIC/FPGA readback, scan behavior, cancellation, or
close-during-run behavior; any further physical access for those still
requires fresh, explicit authorization for that exact action.

This card is a
read-only recovery check after the RADIOROC 07 desktop pre-scan fault, reviewed
offline in RADIOROC 08. It is not authorization to touch the board. Before any hardware access, a designated
operator must freshly authorize this exact status-only procedure and record
the operator, host, UTC start time, and scope.

## Preconditions

Use a powered bare USB board with no SiPM or pulser connected. Close competing
apps and terminals. Designate one operator and one owning `ConnectionWorker`.
Refresh the GUI candidate port list, select the control port explicitly, and
set baud **115200** and transport timeout **0.5 s**. Do not infer identity,
firmware, or configuration from a status word. The historical status `5` is
reference evidence only; it does not prove current configuration restoration.

## Permitted sequence

After fresh authorization and a clear preflight, perform only this sequence:

1. Connect through the owning worker; Connect itself issues the first status-100 read.
2. Only if Connect succeeds with the expected historical value 5, issue one
   explicit repeat status-100 read. A different value stops this card for review.
3. Compare the two exact returned status values. Any error, unexpected value,
   or difference stops status operations immediately.
4. Explicitly Disconnect through the owning worker, then shut down through that
   worker. Do not use a second owner or a direct transport close.

There is no scan, retry, repair, power-cycle, configuration write, defaults or
initialization action. Do not call `read_fifo` (it has write side effects), run
the verifier, or read ASIC/FPGA configuration. Do not automatically retry a
status read.

## Stop and ownership rules

On any error, stop status operations and preserve the exact exception and
before/after snapshots. Connect/status exceptions already cause the owning
worker to attempt session release; count that as the error-path close attempt.
If it succeeds, the worker reports `error` with no selected port or close error;
Disconnect is unavailable in that state, so record the automatic owner-mediated
release and shut down the released worker. If a session remains connected (for
example, after an unexpected returned value), explicitly Disconnect once.
A failed close leaves ownership in place; any further close retry requires
explicit review. In `close_failed`, do not press Disconnect, close the window,
or call shutdown: each can attempt another close. Preserve the live owner and
report the failure for review.
An unexpected or differing status is a stop, not a diagnosis or permission to
continue. Do not claim restoration from this card.

## Evidence to save

Record the fresh candidate list and selected port, USB identity, operator,
host, UTC timestamps, baud, timeout, worker/owner identity, connect and
disconnect results, each returned status-100 bit string/value (and raw frames if captured),
decoded integer only as a convenience, request and response timings, terminal state, shutdown
result, exact exception text and close error (if any), and paths/hashes of all
saved snapshots. Record whether the first read succeeded before attempting the
explicit repeat. Preserve evidence on the first fault.

Acceptance is limited to two matching successful status reads followed by a
successful owner-mediated disconnect and shutdown, with no close error and
complete timestamped evidence. This does not accept configuration restoration,
ASIC/FPGA readback, scan behavior, cancellation, analog performance, or
close-during-run behavior.

## Offline comparison and diagnostic proposal (RADIOROC 10)

Evidence inventory reverified by the lead: all 11 tracked files under
`physical_status_20260911T051700Z/` (12 including `complete_inventory.json`
itself) match the SHA-256 hashes recorded in `evidence_manifest.json`,
consistent with the prior Luna audit in `offline_audit.json`.

**Cross-session comparison, same board/port/parameters** (`/dev/cu.usbserial-RD3_320`,
`usb:0403:6010:serial:RD3_32`, 115200 baud, 0.5 s timeout, request `aa00e40055`,
identical `read_word(100)` call path in `connection_worker.py`/`serial.py` with
no retry logic and no explicit DTR/RTS handling in any of the three runs below):

- `physical_threshold_20260910T042911Z` (2026-09-10 04:29:22 UTC, CLI): a single
  status-100 read returned bits `00000101` (5); close passed.
- `physical_desktop_20260911T015835Z` (RADIOROC 07, native GUI): Connect and its
  initial status read succeeded at 02:06:49-02:06:50 UTC (status 5, per
  `native_preflight.json`). Two full threshold scans (`t1_normal`, `t2_normal`)
  then completed and reported `restored` at 02:06:55 and 02:07:01 UTC on that
  same open session. A later `t1_cancel_window` job then raised
  `TransportTimeoutError` at 02:07:27.651 UTC, about 26 s into that job and, per
  RADIOROC 08's source-order analysis, inside `read_fifo` rather than at Connect.
- `physical_status_20260911T051700Z` (RADIOROC 09): a brand-new Connect on the
  same port, about 3 h 9 min after the 07 fault, timed out on its very first
  status-100 request at 05:16:23.145 UTC, with no successful transaction on that
  session at all.

The contrast: 07's fault occurred mid-session and mid-job, deep in a request
sequence, after many prior successful transactions on the same open port; 09's
fault occurred on the first request of a freshly opened port, with no physical
intervention recorded between the two. Source hashes recorded in
`source_provenance.json` show the same transport/connection-worker code across
these runs, which makes a framing or software regression an unlikely
explanation on current evidence, though it is not excluded.

**Host-level offline check (this session):** `pmset -g log` shows no actual
Sleep/Wake transition on the host between the 07 fault (02:07:27 UTC / 12:07
AEST) and the 09 attempt (05:16:23 UTC / 15:16 AEST) on 2026-09-11 — only
unrelated scheduled "Wake Requests" predictions appear. This rules out an OS
sleep/USB-bus-reset cycle as an explanation for the gap. A deeper unified-log
USB/FTDI trace for that window could not be obtained offline in this session
(`log show` returned "Operation not permitted"; this shell lacks Full Disk
Access) and remains a limitation, not a finding.

**No root cause is established.** Two unproven hypotheses remain open:

- **H1 - stuck board/bridge state.** The `read_fifo` timeout during 07's
  `t1_cancel_window` job, or its automatic cleanup, left the ASIC/FPGA or the
  FTDI bridge unresponsive to any further request, including a fresh Connect.
  Only a power-cycle or physical reseat would be expected to clear this; a
  software reconnect cannot detect or repair it.
- **H2 - independent transient/environmental fault.** An unrelated intermittent
  contact, cable, or hub condition affected the unrelated 09 attempt; its
  timing relative to 07 is coincidental.

**Proposed next card ("RADIOROC 11 candidate"), status-only, no power-cycle:**
this is a proposal for future authorization, not an executed or authorized
procedure.

1. Same preconditions as the existing status-only card: powered bare board, no
   SiPM/pulser, competing software closed, one designated operator, one owning
   `ConnectionWorker`, explicit port selection, 115200 baud, 0.5 s timeout.
2. Before Connect, capture a host-side USB enumeration snapshot without opening
   the port (for example `system_profiler SPUSBDataType`, or the existing
   refreshed candidate list) to confirm the board's USB identity/location is
   still present and unchanged.
3. Connect through the owning worker (issues the first status-100 read) with
   the same parameters as RADIOROC 09.
4. Expected observations and their reading:
   - An identical timeout, with the board still enumerated in step 2, would
     support H1 (persistent stuck state) and argue against a USB-level dropout.
   - A successful read (status 5) would support H2 (transient fault); the
     existing two-read acceptance sequence in this card could then proceed as
     already authorized.
5. Stop/release rules: identical to the existing card in this document above —
   any error or unexpected value stops immediately; the owning worker performs
   the single close attempt; no retry, no repeat beyond the existing gated one,
   no FIFO/verifier/scan/configuration/defaults/repair/power-cycle action.
6. Evidence to capture: everything the existing "Evidence to save" section
   requires, plus the pre-Connect USB enumeration snapshot and the elapsed time
   since the 07 fault and since the board was last physically touched.

If this card's outcome supports H1, the natural follow-up (a designated-operator
power-cycle or physical reseat, then a repeat of this same status-only card) is
explicitly outside this card's scope and needs its own separate authorization.

## Operator power-cycle recovery (post-RADIOROC 10)

Reported directly by the designated operator, not captured through this card's
bounded evidence harness: immediately after the RADIOROC 09 timeout was found,
the operator power-cycled the board. A subsequent Connect through the native
desktop GUI succeeded, showing "Connected - /dev/cu.usbserial-RD3_320" and
"Firmware status 0x05 (5)" (operator screenshot). No exact UTC timestamp,
request-level trace, explicit repeat status-100 read, or Disconnect/shutdown
result was captured for this action, so it does not by itself satisfy the
"Acceptance" criteria defined above, and configuration-restoration state is
still not established from it.

This is still useful evidence: a power-cycle performed right after the fault,
followed immediately by a successful Connect at the same status value (5) seen
before the fault, strongly supports **H1** from the RADIOROC 10 comparison
below (the board or USB bridge was left in a state that required a power-cycle
to clear) over **H2** (an unrelated transient/environmental fault). This is
support, not proof: no independent control (for example, retrying without a
power-cycle first) was run. The "RADIOROC 11 candidate" card below was written
specifically to test this discrimination in a bounded, evidenced way, and was
in fact run next (see "RADIOROC 11 evidenced re-verification" below).

## RADIOROC 11 evidenced re-verification (PASSED)

With fresh authorization confirming the board powered/bare, no SiPM/pulser,
and the operator's manual GUI session closed, the lead ran this exact card
end-to-end through the same harness used in RADIOROC 09
(`radioroc_runs/physical_status_20260911T051700Z/status_card.py`, source
unchanged, hash `d721df6e...880b0`), preceded by a `system_profiler
SPUSBDataType` snapshot (no port opened) confirming `PCB_RADIOROC` /
`RD3_32` still enumerated on the bus.

Results, from `radioroc_runs/physical_status_20260911T070909Z/run/`:

- Candidate refresh/select and Connect succeeded; status-100 read #1 at
  `07:09:24.139-07:09:24.154 UTC` returned `00000101` (5) in 11.2 ms.
- The gated repeat, status-100 read #2 at `07:09:24.247-07:09:24.249 UTC`,
  also returned `00000101` (5), in 1.6 ms.
- Explicit Disconnect and shutdown both completed cleanly: `terminal_summary.json`
  records `status: passed`, `accepted: true`, `error: null`, `worker_alive: false`.
- `source_provenance.json` for this run records the same
  `connection_worker.py` / `serial.py` / `ownership.py` hashes as the
  RADIOROC 09 stopped run, confirming no source change explains the
  difference in outcome.

This satisfies the card's "Acceptance" criteria (two matching successful
status reads, clean owner-mediated disconnect and shutdown, complete
timestamped evidence) and is further evidence for **H1** over **H2**: the same
board, port, and unmodified code that timed out at RADIOROC 09 now answers
promptly and correctly, consistent with an intervening power-cycle having
cleared a stuck state rather than a persistent environmental fault. It remains
support, not formal proof (no controlled A/B test isolating the power-cycle as
the sole variable was performed). This card still does not accept
configuration restoration, ASIC/FPGA readback, scan behavior, cancellation, or
close-during-run behavior — those remain separately authorized, bounded tasks.

## Offline diagnosis from RADIOROC 08

The saved 49-file inventory was verified by the lead. The failed manifest at
`2026-09-11 02:07:02.013701 UTC` elapsed `0.638615667 s` before a complete ASIC
snapshot: 0 points, 0 windows. Source order places the timeout within
`read_fifo` after FPGA 0/1/6 reads, but the exact underlying request is
unknown. The timeout path records zero response bytes by the deadline; it does
not identify a board root cause. Possible FIFO subrequests include the initial
word-0 read, status-100 polling, and final FIFO read, but these remain
unproven. Manifest snapshot assignment is atomic, so the verifier is expected
to lack all three FPGA and 130 ASIC snapshot entries despite earlier FPGA
reads. Cleanup recorded successful commands, which is not verified
restoration.

Events: faulted `02:07:27.651320 UTC`; emergency disconnect left idle
`port=None`, `status=None`, `close_error=None` at `02:07:29.171427 UTC`;
shutdown stopped at `02:07:29.297004 UTC`. There was no phase marker or GUI
Cancel. SIGINT occurred after the terminal fault while waiting, so it is not
cancellation evidence. These facts do not prove the cause; keep all further
hypotheses unproven.
