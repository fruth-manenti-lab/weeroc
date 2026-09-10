# Desktop hardware threshold validation card (PENDING)

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

**Disposition:** PENDING until the designated operator records fresh GUI
evidence for T1, T2, both cancellation cases, close during a long scan, safe
shutdown, and any exercised fault/close-retry path.
