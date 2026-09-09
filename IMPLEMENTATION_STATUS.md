# Implementation status

## Current checkpoint

Delivery 2 (shared protocol/transport and cooperative board ownership) is
implemented at `6c44092` on `feat/transport-ownership`, package version `0.2.0`.
The next bounded task is Delivery 3: one threshold workflow through a shared
job lifecycle. Use `NEXT_SESSION.md` to start that work in a fresh chat.

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

## Implemented

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

## Validation

Local platform: macOS ARM64, Python 3.13. Development uses `.venv-foundation`.
The existing `.conda-radioroc` lab environment received the new filelock
dependency (3.32.6); the source checks pass there as well.

- All 30 unit tests pass (nine existing, 21 new), including malformed/fragmented
  replies, embedded frame delimiters, timeouts/disconnects, no retries, failed
  readback, open/close cleanup and real subprocess ownership/release after kill.
- Compile checks and all 15 CLI help commands pass.
- Source distribution and wheel build successfully. Editable installation was
  checked; `.venv-foundation` currently has the built 0.2.0 wheel installed.
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
Linux and desktop packaging remain unvalidated. The desktop UI is not built.
The feature inventory is preliminary and still needs comparison with the actual
Windows 2.2.0.5 application.

Ownership coordinates participating programs for the same OS user with a local
home filesystem. It cannot exclude vendor D2XX programs or other nonparticipating
clients. Missing USB metadata can prevent grouping both interfaces; duplicate
USB serial numbers conservatively collide. Candidate discovery does not identify
the control interface automatically. See `DEVELOPMENT.md` for the full contract.

Response metadata bytes 1–2 remain opaque. Without verified correlation fields,
same-shaped stale replies cannot reliably be rejected. The 65536-byte request
boundary is tested offline only; the vendor wrapper caps it at 65535.

Transaction locking is implemented; whole-job serialization, progress,
cancellation and durable partial results are next. Some legacy dry-run commands
still open ports. HG/LG nibble mapping and incomplete state restoration remain
tracked migration concerns. Do not run concurrent workflows on one session.

## Next bounded tasks

1. Implement the threshold-scan job lifecycle specified in `NEXT_SESSION.md`.
2. Review/integrate the local branches and run configured CI when publishing is
   authorized; check the intended Git author identity before publication.
3. Expand the Windows parity inventory into control-level acceptance criteria.
4. Build a desktop shell consuming the tested threshold job API, after Delivery 3.

At each checkpoint, record the commit, checks, hardware state, limitations and
one next task. Move unrelated discoveries into this backlog.
