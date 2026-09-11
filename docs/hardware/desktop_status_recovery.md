# Desktop status-only recovery card (RADIOROC 09)

**State: STOPPED after the authorized RADIOROC 09 attempt.** Connect's first
status-100 request timed out on 2026-09-11 at 05:16:23 UTC. No repeat occurred;
automatic owner-mediated release and shutdown succeeded with no close error.
Two-read acceptance remains unmet. Evidence is local under
`radioroc_runs/physical_status_20260911T051700Z/`; see `IMPLEMENTATION_STATUS.md`.
Further physical access requires a separately reviewed and authorized card.

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
