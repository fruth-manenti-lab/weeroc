# Implementation status

## Current checkpoint

Delivery 4's desktop hardware connection/session slice is implemented on
`feat/desktop-hardware-connection`, package version `0.5.0`. The next bounded
task is the opt-in bare-board threshold verification helper and bench validation
specified in `NEXT_SESSION.md`. Hardware threshold Run remains disabled.

The user's preference is to delegate most code, tests and documentation to smaller
models, with the lead primarily orchestrating, reviewing and integrating. Focused
context, minimal duplication and numbered `RADIOROC NN — <bounded task>` session
names are recorded in `AGENTS.md` and the handoff. This session is
**RADIOROC 03 — Desktop hardware connection**; the next is
**RADIOROC 04 — Bare-board threshold validation**. Terra implemented the worker,
Sol implemented the GUI/tests, and Luna drafted the validation card; the lead
reviewed contracts, corrected edge cases and integrated/validated the result.

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

1. Build the opt-in threshold restoration verifier and prepare the reviewed
   bare-board validation described in `NEXT_SESSION.md`.
2. Review/integrate the local branches and run configured CI when publishing is
   authorized; check the intended Git author identity before publication.
3. Expand the Windows parity inventory into control-level acceptance criteria.
4. After reviewed physical threshold snapshot/restore checks pass, enable the
   desktop hardware threshold workflow in its own bounded slice.

At each checkpoint, record the commit, checks, hardware state, limitations and
one next task. Move unrelated discoveries into this backlog.
