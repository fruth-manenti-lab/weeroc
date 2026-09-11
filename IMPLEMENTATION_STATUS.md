# Implementation status

## RADIOROC 11 — Evidenced status-only re-verification (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `b4706777fed7a8380dc5baa8f84dc683cb630a62`
(clean tree before this run; no source changes). The user confirmed the board
powered/bare with no SiPM/pulser and closed the manual GUI session used for
their earlier power-cycle test, then authorized exactly the existing
status-only sequence (refresh/select, Connect, one gated repeat, explicit
Disconnect, shutdown; stop on any error/unexpected value). The lead acted as
sole software operator.

Before Connect, `system_profiler SPUSBDataType` (no port opened) confirmed
`PCB_RADIOROC` / `RD3_32` still enumerated. The lead then reran the unmodified
RADIOROC 09 harness (`status_card.py`, same hash as before) against a new
output directory. Result: **passed**. Status-100 read #1 at
`07:09:24.140-07:09:24.154 UTC` and read #2 at `07:09:24.247-07:09:24.249 UTC`
both returned `00000101` (5); Disconnect and shutdown completed with no error
and no close error (`terminal_summary.json`: `status: passed`,
`accepted: true`). `source_provenance.json` for this run matches RADIOROC 09's
transport/connection-worker hashes exactly, ruling out a source-code
explanation for the improved outcome.

This meets the status-only card's "Acceptance" criteria for the first time
since the RADIOROC 07 fault, and is further evidence for **H1** (the board or
USB bridge was in a stuck state that the operator's power-cycle cleared) over
**H2** (unrelated transient fault) — support, not formal proof, since no
controlled A/B isolating the power-cycle was run. Evidence, including the
pre-Connect USB snapshot, screenshots, request/event traces, and a
12-file `complete_inventory.json`, is local under
`radioroc_runs/physical_status_20260911T070909Z/`. Full narrative in
`docs/hardware/desktop_status_recovery.md` under "RADIOROC 11 evidenced
re-verification (PASSED)".

No ASIC/FIFO access, verifier, scan, configuration write, defaults, repair,
power-cycle, push, or change to `main` occurred in this session. Configuration
restoration, scan behavior, and cancellation/close-during-run behavior remain
unverified and out of scope for this card.

Next: with the designated operator, decide whether to proceed to a fresh,
separately authorized physical threshold restoration/scan check now that
status-only communication is evidenced-recovered, or to run further
verification (for example, a repeated status-only pass after a longer idle
period) before trusting the board for scan work.

## RADIOROC 10 — Investigate status-only timeout (offline, STOPPED card unchanged)

Offline-only continuation on `feat/desktop-hardware-threshold`, working tree
clean at `9fd8665`. No hardware discovery/open, status retry, ASIC access,
verifier, scan, defaults, repair, power-cycle, or push/change to `main`
occurred; the RADIOROC 09 stopped card and its acceptance state are unchanged.

The lead reverified the RADIOROC 09 evidence inventory: all 11 tracked files
under `radioroc_runs/physical_status_20260911T051700Z/` (12 including
`complete_inventory.json` itself) match the SHA-256 hashes in
`evidence_manifest.json`, consistent with Luna's prior `offline_audit.json`.

The lead compared that run's exact request/timing/error evidence against prior
successful status reads on the same port/parameters: a 2026-09-10 CLI status
check (`status.json` in `physical_threshold_20260910T042911Z`, status 5) and
RADIOROC 07's native GUI session (`physical_desktop_20260911T015835Z`), whose
Connect and initial status read succeeded (status 5) and which then completed
two full threshold scans before a later job (`t1_cancel_window`) hit the known
`read_fifo` timeout at `02:07:27.651 UTC`. RADIOROC 09's fresh Connect, about
3 h 9 min after that fault, timed out on its very first status-100 request with
no prior successful transaction on that session. Source hashes in each run's
`source_provenance.json` show unchanged transport/connection-worker code across
all three, so a framing/software regression is unlikely on current evidence but
not excluded. A host-level offline check (`pmset -g log`) found no actual
Sleep/Wake transition between the 07 fault and the 09 attempt, ruling out an OS
sleep/USB-reset cycle as an explanation for the gap; a deeper unified-log
USB/FTDI trace could not be obtained offline in this session (`log show`:
"Operation not permitted", no Full Disk Access), which is a limitation, not a
finding.

No root cause is established. Two open, unproven hypotheses and one concrete
next test card (status-only, no power-cycle, evidence requirements, and
stop/release rules) are recorded in
`docs/hardware/desktop_status_recovery.md` under "Offline comparison and
diagnostic proposal (RADIOROC 10)". That card is a proposal only; it is not
authorized to run.

**Addendum, reported after this session's offline analysis:** the designated
operator power-cycled the board immediately after the RADIOROC 09 timeout was
found, and a subsequent native-GUI Connect succeeded (firmware status `0x05`/5
on `/dev/cu.usbserial-RD3_320`), per an operator-provided screenshot. This was
not run through the bounded evidence harness, so it lacks timestamps, a
request-level trace, an explicit repeat status read, and a recorded
Disconnect/shutdown; it does not satisfy this document's evidence standard or
the status-only card's two-read acceptance. It does strongly support **H1**
(stuck board/bridge state cleared by power-cycle) over H2. Details are in
`docs/hardware/desktop_status_recovery.md` under "Operator power-cycle
recovery (post-RADIOROC 10)".

Next: **RADIOROC 11 — <fresh authorization for the proposed status-only card,
or further offline diagnosis>**. This session does not authorize further
physical access; the existing RADIOROC 09 stopped state and two-read acceptance
gap remain current.

## RADIOROC 09 — Status-only desktop recovery (STOPPED)

On 2026-09-11 the user freshly confirmed the powered bare USB board, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the exact status-only card. Native Cocoa execution on
`feat/desktop-hardware-threshold` at `b31d024` stopped on Connect's first read.
Fresh candidates were `PCB_RADIOROC`, identity `usb:0403:6010:serial:RD3_32`;
the explicitly selected control port was `/dev/cu.usbserial-RD3_320`, baud
115200, timeout 0.5 s.

The trace records exactly one status-100 request, `aa00e40055`, beginning at
`05:16:23.144650 UTC`. It raised `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried`, with transfer elapsed
0.501775458 s. No status value or response frame was returned. Unlike the older
FIFO fault, this request is identified exactly; its cause remains unresolved.
No repeat status read, scan, FIFO access, verifier, configuration write,
initialization/defaults, repair or power-cycle occurred.

Connect's error path released the session through its owning worker. The
`05:16:25.164920 UTC` snapshot records `error`, cleared port/status and no close
error. Because the session was already released, there was no explicit
Disconnect or second close attempt. Shutdown recorded `stopped`, worker not
alive, and no close error at `05:16:25.257612 UTC`; process exit was 1.
The two-read acceptance did not pass, and configuration restoration is unknown.

Evidence is local and ignored under
`radioroc_runs/physical_status_20260911T051700Z/`: exact executed harness,
setup/authorization, fresh candidates, timestamped snapshots and request trace,
three native widget screenshots, terminal summary, console, source hashes and
SHA-256 inventory. The directory suffix is a label; actual execution was
05:16:21–05:16:25 UTC. Native GUI methods were driven programmatically with
human controls disabled; evidence does not include independent electrical
observation. The standard production transport and board lock were retained.

Sol prepared the local harness; the lead reviewed and strengthened its guards.
Five offline fake cases passed: success, unexpected first status, first-read
timeout, repeat-read timeout and failed close with live ownership retained and
no close retry. Compilation, help and default refusal passed. No production
source or packaging changed, so no development-suite or wheel rerun was needed.
Luna independently audited the saved sequence and verified all seven original
inventory entries. The lead preserved that manifest and verified an expanded
11-file inventory including console, source provenance and audit summary.
`git diff --check` passed; no push or change to `main` occurred.

Next: **RADIOROC 10 — Investigate status-only timeout**, an offline comparison of
this exact request with prior successful status evidence and the existing
transport, followed by one concrete diagnostic proposal. This stopped card
does not authorize further physical access or resuming GUI scan acceptance.

### Preparation history

Continuation started on `feat/desktop-hardware-threshold` at clean `b31d024`.
Offline source review identified that Connect/status exceptions already attempt
owner-mediated close. The recovery card now counts that attempt and explicitly
prohibits Disconnect/window-close/shutdown after `close_failed` without review,
because those actions can retry close. Successful automatic release is recorded
before shutdown; the normal success path still requires explicit Disconnect.

Documentation-only preparation; `git diff --check` passed. No hardware discovery,
open, status read, scan or configuration operation occurred. Physical acceptance
remains pending fresh setup confirmation and designated-operator authorization
for the exact card. Next task remains execution of that status-only card; the
RADIOROC 09 handoff in `NEXT_SESSION.md` remains current.

Continuation review on 2026-09-11 found HEAD still at `b31d024` with the two
existing documentation edits above, which were preserved. A bounded Luna
offline review confirmed the card matches current worker APIs and error-path
release behavior. Unexpected status values require the operator to stop;
`close_failed` retry restrictions are procedural, not enforced by the API.
`git diff --check` passed again. No source changes or hardware access occurred;
fresh setup confirmation and authorization remain the next required step.

## RADIOROC 08 — Investigate desktop pre-scan timeout

Offline investigation continued on `feat/desktop-hardware-threshold` from clean
`a1b17e6`. Version remains `0.5.0`. No hardware discovery/open, configuration
change, scan retry, repair, push or change to `main` occurred.

All 49 files in the original RADIOROC 07 SHA-256 inventory match their recorded
hashes and sizes. Source ordering and saved evidence place the failure inside
ASIC `read_fifo`, after FPGA 0/1/6 reads and before complete snapshot assignment
or any measurement. The transport error means no response bytes were received
for one unidentified read within 0.5 s. Initial word-0 read, status polling and
final FIFO read remain possible sites; there is no per-request trace to decide
which, or establish a board/USB/firmware root cause. The 60000 ms measurement
window was never reached and does not explain this pre-scan failure.

The failed manifest finished at 02:07:02.013701 UTC with 0 points/windows.
The verifier had no complete snapshot (all 3 FPGA and 130 ASIC expected entries
missing); successful cleanup commands do not establish verified restoration.
The harness recorded the latched fault at 02:07:27.651320 after SIGINT interrupted
its marker-only wait. Disconnect recorded idle with port/status cleared and no
close error at 02:07:29.171427; shutdown recorded stopped at 02:07:29.297004.
Neither GUI cancellation nor an in-window close occurred.

Local-only fixes and their report are preserved under ignored
`radioroc_runs/radioroc08_offline/`. `phase_wait.py` detects terminal outcomes,
faults, disconnect and shutdown before accepting a marker, including simultaneous
marker/fault delivery. `radioroc08_gui_card.py` integrates this for window and
first-point waits and adds a separate request trace without Qt widget access.
The original harness is unchanged. Six deterministic wait tests passed, as did
compilation, help and default refusal (exit 2). Physical execution is gated by
an explicit flag and remains unvalidated/unauthorized; the derivative runs the
scan card and must not be used for the next status-only task. Request tracing
cannot reconstruct the missing historical request and has not been tested on
a board.

The saved T2 screenshot independently confirms the previous T1 saved-result
banner above current T2 data. The minimal production UI change replaces saved
provenance when starting a new run; device logic and shared APIs are unchanged.

Checks: `.venv-foundation/bin/python tools/check_development.py` passed all
**118 offline tests**, compile checks and **15 legacy CLI help checks**, including
the new saved-result/new-run/rejected-submission GUI regression. Log:
`/private/tmp/radioroc08-development.log`. Packaging metadata is unchanged, so
no new installed-wheel check was needed. `git diff --check` passed.

The concrete next task is **RADIOROC 09 — Status-only desktop recovery**, using
`docs/hardware/desktop_status_recovery.md`. Fresh operator authorization is
required before hardware access. Connect's status read, one explicit repeat,
disconnect and shutdown are the entire card; success does not establish restored
configuration or authorize a scan. Physical cancellation/close acceptance,
word-60 semantics, wider scans and analog performance remain pending.

## RADIOROC 07 — Physical desktop threshold validation (STOPPED)

On 2026-09-11, the user confirmed the powered bare board, USB only, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the five-case desktop card. Starting tree was clean on
`feat/desktop-hardware-threshold` at handoff `086d304` (implementation `e6cddf4`).
Sol prepared a local harness and reviewed saved evidence; workers used no hardware.
No production source or packaging changed; version remains `0.5.0`.

Native macOS Cocoa GUI discovery/connect/repeat status/disconnect passed using
`.venv-foundation`. Fresh identity was `usb:0403:6010:serial:RD3_32`, control port
`/dev/cu.usbserial-RD3_320`, baud 115200, timeout 0.5 s; both status reads returned
5. Status is not a decoded firmware version. Five actual offscreen GUI previews
passed without creating a worker or run directory before physical execution.
Config was the explicit `configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

| Native GUI case | Points / windows | Result | Verification |
| --- | --- | --- | --- |
| T1, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T2, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T1, DAC 0, 60000 ms, intended in-window Cancel | 0 / 0 | failed before measurement | incomplete |
| T1, DAC 0..2, 1000 ms, Cancel after first point | — | not executed | — |
| T1, DAC 0, 60000 ms, close during run | — | not executed | — |

All submitted cases used one average, masks on, Ctest off, gain unchanged,
FPGA initialization/default application off and mandatory verification. Normal
T1/T2 terminal displays and saved reopening passed; the session stayed connected.
Their 130 ASIC rows exactly match snapshot/expected/observed values. FPGA words
0/1/6 were `00111111` / `00000000` / `00000000`, matching both verifier passes.
Manifest/CSV counts agree; all four measured rates were 0 Hz. No cleanup,
persistence or verifier errors occurred in these two cases.

The third job recorded `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried` during snapshot
acquisition. Status, preparation and FPGA 0/1/6 reads completed; the 130-row
ASIC `read_fifo` did not return a complete snapshot. No trigger-mask, DAC,
channel-selection or counter operation was reached. The exact failed serial
request within `read_fifo` is not recorded. Cleanup commands succeeded (`restored`), but verification was
`incomplete` because all snapshot entries were absent. This does not establish
verified restoration. No counter-window phase marker or GUI Cancel request
occurred; the intended cancellation test did not reach measurement.

The GUI latched the fault. The local harness was still waiting for its phase
marker, so the lead interrupted that wait with SIGINT after the job had already
failed. Its error handler explicitly disconnected through the owning worker:
state became idle with port/status cleared and no close error, then stopped on
window shutdown; process exit was 1. This SIGINT is not GUI cancellation evidence.
No subsequent scan, repair, initialization/default write or retry occurred.
Hardware configuration was not re-verified after the fault.

Evidence remains local and ignored under
`radioroc_runs/physical_desktop_20260911T015835Z/`: setup and previews, native
widget screenshots/text, timestamped GUI/worker records, three manifests and CSV
pairs, console log, exact local harnesses, two-run equality audit, stopped
summary and SHA-256 inventory. Native controls were driven programmatically;
there was no continuous screen recording or independent electrical observation.
Completed plots were captured, but intermediate point display was not separately
captured. An observed UI issue remains: starting hardware Run after reopening a
saved result leaves the prior saved-result banner visible over the new plot.
The harness phase wait also needs immediate fault detection before future use.

Checks: actual GUI previews, native connection preflight, two successful physical
runs/reopens, exact offline saved-data audit, and `git diff --check`. No new
production-source suite or wheel check was needed; prior 117-test evidence below
is unchanged. Main, lab environments and all measurements were preserved.

Next: **RADIOROC 08 — Investigate desktop pre-scan timeout**. Review the saved
failure offline, improve fault/evidence handling, and prepare a bounded
status-only recovery card before further physical access. The timeout cause is
unresolved; cancellation and close-during-run acceptance remain pending.

## Current checkpoint

**RADIOROC 06 — Desktop hardware threshold workflow** is implemented on
`feat/desktop-hardware-threshold` at `e6cddf4`, based on `b10cf57`. Version remains `0.5.0`;
packaging metadata and legacy entry points are unchanged.

- The persistent `ConnectionWorker` owns the transport, device, shared
  `ThresholdJob`, mandatory restoration verification, disconnect and close retry
  on one thread. Hardware Run uses this owner rather than a competing worker.
- Preview stays offline. Entering hardware mode defaults FPGA initialization
  and ASIC defaults application off; their controls identify persistent changes.
  Temporary scan settings are restored and independently verified.
- Live points, cancellation, saved results and shutdown use the shared job.
  Normal terminal delivery retains the connection after cleanup/verification.
  Shutdown cancels and waits; a new job fault holds shutdown for visible review.
- Job, cleanup, persistence, verification and close faults block another scan.
  Disconnect and explicit fault-review acknowledgement are required before a
  new connection. Failed close retains ownership for an explicit retry.
- Reopening a manifest with failed/incomplete verification preserves its data
  and shows an incomplete result, even if the primary scan completed/cancelled.

Sol implemented/tested the owner, Terra implemented/tested the GUI, and Luna
updated workflow documentation and the separate pending physical GUI card. The
lead reviewed ownership/publication contracts and integrated saved-reader and
installed-artifact checks. No hardware discovery/open/scan, environment diagnostic,
persistent configuration write, push or change to `main` occurred.

Validation on macOS ARM64 / Python 3.13:

- `.venv-foundation/bin/python tools/check_development.py`: **117 offline tests**,
  compile checks and all **15 legacy CLI help checks** passed. New coverage
  includes same-thread session/job/verifier ownership, cancellation and queued
  shutdown, fault latching/review, defensive snapshots, GUI gating and terminal
  delivery order, and saved verification-fault visibility.
- Source distribution and `0.5.0` wheel built with `python -m build --no-isolation`.
  Installed core-only checks passed with Qt absent in `.venv-wheel-core`.
  Installed GUI/plot checks passed outside the checkout using a temporary venv
  with development dependency paths; the wheel itself was installed there.
  The GUI check completed/reopened simulation and exercised the persistent
  hardware job route with a fake transport and passing mandatory verification.
- `git diff --check` passed. Logs and built artifacts remain local under
  `/private/tmp/radioroc06-*`; no generated files or measurement data are committed.
  The foundation editable installation and lab environment were preserved.

Hardware state was not refreshed: the last physical evidence is RADIOROC 05
below, whose historical port/status must not be treated as current. Native GUI
hardware behavior and physical GUI restoration remain unvalidated. Fake transport
tests establish software behavior only; word 60 semantics and analog performance
remain outside this slice.

Next: **RADIOROC 07 — Physical desktop threshold validation**, using
`docs/hardware/desktop_threshold_validation.md`. Its fresh equipment summary and
operator authorization are separate from the completed CLI card.

## RADIOROC 05 — Physical threshold restoration checks

The physical threshold restoration card passed on 2026-09-10 in
**RADIOROC 05 — Physical threshold restoration checks**, on
`test/physical-threshold-restoration`, based on authorization handoff `3c0f82a`
and verifier implementation `4c6d254`. Package version remains `0.5.0`.
Desktop hardware Run was disabled at that checkpoint; RADIOROC 06 above enables it.

The lead was the sole software board operator, using the authorization recorded
in the preceding handoff: powered bare board over USB, no SiPM/pulser, competing
vendor software and terminals closed. Sol reviewed cancellation instrumentation
and audited saved evidence offline; Luna updated the physical card.

Physical evidence is preserved locally and ignored under
`radioroc_runs/physical_threshold_20260910T042911Z/`: discovery/status JSON,
exact preview/execution arguments, preview logs, full console output, exit codes,
four manifests and CSV pairs, process-local cancellation launcher, audit summary
and SHA-256 evidence inventory.
No measured data is committed. Host: macOS 15.1 ARM64. Fresh USB identity:
`usb:0403:6010:serial:RD3_32`; control port `/dev/cu.usbserial-RD3_320`,
115200 baud, 0.5 s timeout. Status word 100 read `00000101` (5), and close
succeeded. This is a status value, not a decoded firmware version. Board revision
was not independently identified; ambient conditions were not measured.

| Physical case | Completed points / windows | Exit | Restoration verification |
| --- | --- | --- | --- |
| T1, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T2, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T1, DAC 0, 60000 ms window, cancel during window | 0 / 0 | 130 | passed |
| T1, DAC 0..2, 1000 ms, cancel after first point | 1 / 1 | 130 | passed |

Every command was previewed offline before execution, used channel 4, one average,
mask isolation, `--skip-fpga-init` and `--verify-restoration`, and omitted
`--apply-defaults`. Each run captured 130 ASIC rows (the variant's two DAC rows,
64 discriminator rows and 64 masks) plus FPGA 0/1/6. Exact FPGA snapshots in every
case were `00111111` / `00000000` / `00000000`; both verifier FPGA passes and
ASIC comparison matched. Job/verifier cleanup succeeded, manifests and CSV row
counts agreed, and there were no persistence or CLI close errors. All completed
windows had zero counts (0 Hz). Configuration:
`configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

Cancellation used a process-local launcher around the unchanged CLI. The window
hook raised SIGINT after the first 10 ms delay slice, which the production loop
reaches after counter enable and before stop/read. The point hook raised SIGINT
from the event callback after the first point and manifest were persisted. Phase
markers and exit 130 establish the real CLI signal-handler/cancellation path;
this was programmatic SIGINT, not a human keystroke. Window phase evidence is
software call ordering, not independent observation of a counter-active signal.

Checks: all four physical acceptance cases and saved-evidence assertions passed.
An independent offline audit confirmed byte-for-byte snapshot/expected/observed
equality, exact variant row coverage, preview/manifest agreement and CSV counts.
`git diff --check` passed; evidence is ignored and `main` remains at `b77f76d`.
No production source or packaging changed; no new development-suite or wheel run
was required (preceding 108-test offline checkpoint remains below). The lab Python
does not have an installed `radioroc` module, so discovery used the preserved
`scripts/radioroc_list_ports.py` entry point after module invocation failed before
hardware access. All physical scans used the documented legacy script entry point.

Limits: word 60 is verified only as a successful idle write; ASIC readback protocol
semantics and analog behavior are not independently established by equality alone.
Ctest/gain changes, other channels, wider DAC ranges, detector measurements,
Linux/Windows USB and native desktop hardware ownership remain outside this card.
Next: **RADIOROC 06 — Desktop hardware threshold workflow**, with explicit
preparation choices, shared job ownership, cancellation and readback verification.

Delivery 2 remains at `6c44092` on `feat/transport-ownership`; `782014f` recorded
its validation and threshold-job handoff.

All commits are local; no push, PR or remote CI run has been performed.
`main` remains at the original `b77f76d` baseline. The development branch
contains the preceding checkpoints:

- `e3d3b3d`: acquisition, scan and analysis workflows, preset and tests.
- `352418a`: June/July lab notes and their result figures.
- `603c69b`: rebuild plan and exclusions; tag `pre-desktop-rebuild` on
  `chore/lab-baseline`.
- `81ee287`: installable package, CLI and offline development checks on
  `build/python-foundation`.

The five experiment folders were recovered from local Git snapshot
`9c1da1e65fe2384f39c680f5b29add8ca341d2b6`: 27 files verified against blob hashes.
They are present locally and ignored. Other saved runs remain in `radioroc_runs`.
No separate external backup has been configured. Recovery verifies snapshot
bytes, not any unrecorded later changes.

## Threshold restoration verifier: implemented and checked offline

- `ThresholdJob.run(..., verify_restoration=True)` and the existing CLI's
  `--verify-restoration` opt in to independent readback after scan cleanup,
  under the same transport owner and job lock. Unflagged behavior is preserved.
- The verifier compares measured FPGA words 0/1/6 and all configured T1/T2 ASIC
  snapshot rows. It captures post-job FPGA state before ASIC reads, then idles
  word 60, restores exact observed word 0 (including its I2C active bit), and
  rereads FPGA state. It never repairs or hides a scan-restoration mismatch.
- Missing snapshots and incomplete payloads cannot pass; no missing value is
  supplied from the configuration table. Verification is a separate report in
  the result and manifest, preserving primary/scan-cleanup/persistence errors.
  Close errors are separately printed even when other failures coexist. Save
  console output: close occurs after the manifest's terminal write.
- The reviewed offline implementation and updated card are ready for operator
  review. The physical card was not executed at this offline checkpoint; see the
  RADIOROC 05 results above. Desktop hardware Run remains disabled; no new UI or device workflow was enabled.

Validation on macOS ARM64 with `.venv-foundation`:

- `python tools/check_development.py`: **108 offline tests** passed, with compile
  checks and all **15 legacy CLI help checks**. The 13 new verifier tests cover
  T1/T2 full register sets, exact transport ordering, active-bit restoration,
  same-session locking, completed/in-window/after-point cancellation, missing
  snapshots, short readback, FPGA/ASIC mismatches, verification/read/cleanup/close
  failures and CLI exit statuses/offline isolation.
- The card's two-point T1 preview passed with `.conda-radioroc/bin/python`, using
  a placeholder port; it created no output directory. This was a dry-run only.
- `git diff --check` passed. No packaging configuration changed, so a new wheel
  build/install check was not required. The development environment now uses an
  editable checkout; the lab environment and measured data were preserved.
- No hardware scans, discovery, physical open, diagnostic enumeration, push or
  remote CI occurred. `main` remains unchanged.

Limits: fake tests establish software behavior, not physical register semantics.
Word 60 readback remains unresolved; its idle-write success is recorded without
claiming readback verification. A passing verifier does not erase job cleanup
errors. Manual CLI Ctrl-C timing does not prove cancellation inside a counter
window because that phase has no explicit start event; establish phase evidence
before accepting the physical cancellation case. Bare-board rates cannot establish
analog response or detector performance. The subsequent RADIOROC 05 physical
acceptance results are recorded above.

## Delivery 4 connection slice: implemented and checked

- Lazy, Qt-independent connection worker with a bounded command mailbox and
  immutable snapshots. Discovery, transport creation/open, status reads and close
  stay on its own thread; no startup discovery occurs.
- Explicit USB candidate refresh/selection, baud/timeout settings, connect,
  status-word 100 read and disconnect. Candidates are labelled unverified;
  simulation and hardware session controls cannot overlap in one window.
- Existing serial transport and board lease are reused. Invalid overlapping
  operations are rejected atomically. Busy, timeout, protocol, I/O and close
  errors retain their exception names. Failed close retains the owned session
  for explicit retry, including failure during partial open. Window shutdown
  waits for session release and leaves close failures visible.
- Hardware threshold Run is disabled. The separate card at
  `docs/hardware/bare_board_threshold_validation.md` specifies the exact register
  boundary, preparation, cancellation and independent restoration checks. It is
  **not executed**; a verification helper that restores its own I2C side effects
  is the next implementation task.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **95 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 14 new tests cover
  connection ownership, command gating, partial-open/close retry, real transport
  framing/lease integration with fake serial, GUI selection, error presentation
  and responsive shutdown. No hardware is enumerated by these checks.
- Source distribution and 0.5.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for simulation/reopen, fake connection/disconnect,
  disabled hardware Run and headless plotting outside the checkout.
- Native macOS Cocoa launch passed fake connect/status and owned shutdown. Visual
  inspection found clipped controls; the corrected layout was launched and
  inspected again. Screenshot remains local at
  `/private/tmp/radioroc-connection-native.png`.
- `git diff --check` passes. No physical board discovery/open or configuration
  writes occurred. Lab data and environments were preserved; development wheel
  environments were updated. No push, PR or remote CI run was performed.

Limits: physical desktop connection/disconnect has not been exercised on the
board. Native validation used a clearly labelled fixture. Linux/Windows GUI,
USB behavior and bundling remain unvalidated; status bits are not decoded into
unverified firmware capabilities. Readback-based scan restoration remains pending.

## Delivery 4 simulation slice: implemented and checked

Committed at `ef92eeb` on `feat/desktop-threshold-simulation`, version `0.4.0`;
handoff at `cf35315`.

- Optional PySide6/Matplotlib desktop entry point `radioroc-desktop`, while the
  core/CLI wheel remains importable and usable without Qt or a display server.
- Configure channels, DAC range/step, counter window, averages, T1/T2, mask,
  Ctest, gain and preparation options; offline preview exposes persistent versus
  temporary settings and creates no output/session.
- A deterministic, configurable logistic threshold simulator drives the actual
  `ThresholdJob.run` device/register path. Every screen, plot and reopened run
  labels synthetic data as simulation; model parameters are saved in metadata.
- A worker owns session create/run/close on one background thread. The UI polls
  a bounded/coalesced display mailbox while the shared writer independently saves
  every completed counter window and DAC row. Cancellation and window close wait
  for cleanup and session release; cleanup/storage/close failures remain visible.
- Saved-run reading validates manifest/CSV schema, channels, DAC order, point
  counts and finite nonnegative rates. It salvages only a valid prefix, labels
  nonterminal/inconsistent runs incomplete and opens legacy CSVs with unknown
  provenance. It never resumes or rewrites a run.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **81 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 26 added tests cover the
  simulator, worker/session ownership, coalescing of all 1024 DAC rows, cancellation,
  close faults, saved-run validation and Qt workflows.
- Source distribution and 0.4.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for configure/preview/run/plot/reopen using Qt offscreen.
- A native macOS Cocoa launch displayed, completed and reopened a 41-point,
  two-channel simulation. The window remained responsive and was captured for
  local visual inspection; the temporary run and screenshot were not added to Git.
- No physical device was enumerated or opened. Ignored experiment folders and
  `radioroc_runs` were preserved. No remote CI, push or PR was performed.

Limits: the simulator is a deterministic workflow exerciser, not an analog/noise
model. Desktop hardware mode is visibly unavailable. Linux desktop launch,
application bundling and Windows GUI execution remain unvalidated. The saved-run
reader is for truthful display, not crash repair or resume.

## Delivery 3: implemented and checked

- `ThresholdJob` / `ThresholdJobConfig` provide a synchronous worker-friendly API.
  The existing threshold CLI and `device.run_threshold_scan` use that runner.
  Existing arguments, counter sequences, DAC encoding and result columns/rates
  are retained; validation now rejects invalid DACs, duplicate channels and
  nonfinite/nonintegral settings before device access or file creation.
- Structured state/point events, cooperative cancellation including I2C ready
  polling and counter windows, Ctrl-C exit handling, and immediate rejection of
  overlapping jobs on one transport session (including multiple device wrappers).
- A manifest exists before preparation. Completed windows and DAC points are
  appended/flushed/fsynced to compatible CSVs. Atomic manifests record status,
  effective table/configuration, snapshots, firmware, source fingerprint, units,
  version, board identity when available and separate cleanup/storage errors.
  Existing run files are never truncated by a new job.
- Captured temporary threshold/gain/mask/Ctest/discriminator and FPGA settings
  are restored; uncaptured ASIC settings are never invented. Cleanup errors do
  not replace the primary failure. Explicit initialization/default application
  remains intentional preparation and persists; interrupted preparation is
  labelled unknown/possibly partial. Memory-transport results are simulated.
- Threshold dry-run validates/previews without serial construction/discovery,
  measurements or output files. Other workflows are unchanged.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **55 offline tests** pass (30 preceding, 25 threshold lifecycle tests),
  plus compile checks and all 15 legacy CLI help checks through
  `python tools/check_development.py`.
- Tests compare complete API/CLI fake-device command traces and CSV bytes; check
  known rates/counts, T1/T2, multiple channels, Ctest, gain, explicit preparation,
  complete captured-state restoration and legacy source execution.
- Fault tests cover cancellation before acquisition, during I2C polling, during
  a long counter window, mid-point and after a point; CLI SIGINT; timeout and
  disconnect; cleanup failure alone/with a primary error; snapshot/preparation
  failure; disk/manifest failure; output collisions; callback failure; concurrent
  session jobs. A subprocess abrupt exit retains a readable point and leaves
  status running with cleanup pending. Existing subprocess board-lock tests pass.
- Source distribution and wheel build with `python -m build --no-isolation`.
  The 0.3.0 wheel is installed in `.venv-foundation`; isolated installed-wheel
  checks outside the checkout pass for resources, all 15 commands, an executed
  synthetic threshold job, genuinely offline preview and headless PNG rendering.
- No physical device was opened in this session. The lab environment, ignored
  experiment folders and `radioroc_runs` were preserved. No remote CI/push/PR.

Delivery 3 limits and follow-ups:

- Physical snapshot/restore behavior, scan timing and throughput remain untested.
  `restored` means restoration commands succeeded, not verified readback. I2C
  control word 60 is idled instead of replaying its command strobe.
- Persistent storage failure can prevent terminal metadata; the result reports
  persistence errors, while the last manifest may lag. Crashed/incomplete runs
  must not be shown as completed; recovery readers should validate any unconfirmed
  CSV tail. There is no resume/recovery service yet.
- The caller owns transport open/close and must surface connection/close failures.
  The whole-job lock covers threshold jobs only; unmigrated workflows and direct
  primitive calls must not run concurrently. Cancellation waits for bounded I/O;
  cleanup can require many transactions and is not instantaneous.
- The memory backend and scripted test transport are not an analog simulator.
  Delivery 4 needs a labelled threshold simulator and a UI worker adapter with
  a bounded/coalesced event queue. No Qt/UI code is included in this delivery.
- Existing T1/T2 shared-register write encoding and table-based mask/gain updates
  were preserved. Compare those semantics with the vendor before broader register
  refactoring. Other commands' offline dry-run, acquisition/autocalibration jobs,
  HG/LG mapping, Windows parity and Linux hardware checks remain separate work.
- Local commit identity follows preceding commits (Tengiz Ibrayev,
  `tengiz@agqhcqjdw32.tail819d22.ts.net`); confirm it before publication.

## Earlier deliveries: implemented

- Installable shared Python package, retaining original script paths and core
  imports. `radioroc` / `python -m radioroc` now dispatch 15 commands, including
  the new read-only port candidate listing.
- Packaged default configuration and presets, independent of working directory.
  Base dependencies are pySerial and filelock; plotting/build tools are optional.
- One framed serial transport used by the core, legacy autocalibration and
  serial-probe scripts. Exact existing request bytes and write chunking retained.
- Validated request bounds, bounded fragmented reads/output waits, explicit
  timeout/protocol/I/O errors and no automatic request retries. Failed ASIC
  readback raises instead of returning unmeasured defaults.
- Cooperative OS-backed ownership across both USB interfaces of a board, keyed
  by USB identity, acquired before opening serial. Normal close and process exit
  release ownership; failed close retains ownership for a later close attempt.
- Offline source and installed-wheel checks; GitHub Actions configuration for
  Ubuntu/macOS and Python 3.11/3.13; development and agent instructions.

## Delivery 2 validation (historical)

Local platform: macOS ARM64, Python 3.13. Development uses `.venv-foundation`.
The existing `.conda-radioroc` lab environment received the new filelock
dependency (3.32.6); the source checks pass there as well.

- All 30 unit tests pass (nine existing, 21 new), including malformed/fragmented
  replies, embedded frame delimiters, timeouts/disconnects, no retries, failed
  readback, open/close cleanup and real subprocess ownership/release after kill.
- Compile checks and all 15 CLI help commands pass.
- Source distribution and wheel build successfully. Editable installation was
  checked; `.venv-foundation` had the built 0.2.0 wheel at that checkpoint
  (now updated to 0.3.0 above).
- Installed-wheel checks pass outside the checkout: imports/transport aliases,
  default table byte equality/677 rows, presets, version and all CLI help pages.
  A synthetic threshold CSV renders to PNG with the headless Matplotlib backend.
- Read-only hardware status on `/dev/cu.usbserial-RD3_320` returned address 100
  as `00000101` (5). While that connection was held, a second process targeting
  `/dev/cu.usbserial-RD3_321` received `DeviceBusyError` before opening serial.
  The owner then closed and released the lease. No configuration writes were
  issued. See `logbooks/2026-09-09.md`.

## Limits and outstanding work

The earlier planning-time status-read failure did not recur; its cause was not
established. Successful status and lock checks do not validate scans or Windows
feature parity. The board is powered, with no SiPM or pulse generator connected
according to the user; the connection was closed after testing.

CI has not run remotely. Linux/Debian installation, physical USB behavior on
Linux and desktop bundling remain unvalidated. The desktop supports the threshold
workflow in simulation. Desktop hardware connection/status is implemented but
physically unvalidated; hardware scan execution remains disabled. The feature
inventory is preliminary and still needs comparison with the actual
Windows 2.2.0.5 application.

Ownership coordinates participating programs for the same OS user with a local
home filesystem. It cannot exclude vendor D2XX programs or other nonparticipating
clients. Missing USB metadata can prevent grouping both interfaces; duplicate
USB serial numbers conservatively collide. Candidate discovery does not identify
the control interface automatically. See `DEVELOPMENT.md` for the full contract.

Response metadata bytes 1–2 remain opaque. Without verified correlation fields,
same-shaped stale replies cannot reliably be rejected. The 65536-byte request
boundary is tested offline only; the vendor wrapper caps it at 65535.

Transaction locking and the threshold job lifecycle are implemented. Other
workflows still need whole-job migration; some legacy dry-run commands still
open ports. HG/LG nibble mapping and state restoration outside threshold scans
remain tracked migration concerns. Do not mix workflows on one session.

## Next bounded tasks

1. Review the updated card with the designated operator and perform the physical
   threshold restoration checks described in `NEXT_SESSION.md`.
2. Review/integrate the local branches and run configured CI when publishing is
   authorized; check the intended Git author identity before publication.
3. Expand the Windows parity inventory into control-level acceptance criteria.
4. After reviewed physical threshold snapshot/restore checks pass, enable the
   desktop hardware threshold workflow in its own bounded slice.

At each checkpoint, record the commit, checks, hardware state, limitations and
one next task. Move unrelated discoveries into this backlog.
