# Desktop hardware threshold validation card (PENDING / STOPPED)

This card is pending designated-operator review and execution. It covers the
desktop `ConnectionWorker` hardware workflow only. The earlier
`bare_board_threshold_validation.md` records RADIOROC 05 CLI evidence; that
authorization and evidence do not authorize these GUI scans.

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
