# Implementation status

## Current delivery

Delivery 0 is checkpointed at tag `pre-desktop-rebuild` (`603c69b`) on
`chore/lab-baseline`. Delivery 1's packaging foundation is on
`build/python-foundation`. All commits are local; no push, PR or CI run has been
performed. `main` remains at the original `b77f76d` baseline.

Baseline commits:

- `e3d3b3d`: acquisition, scan and analysis workflows, preset and tests.
- `352418a`: June/July lab notes and their result figures.
- `603c69b`: rebuild plan and exclusions for local experiment folders.

The five experiment folders were recovered from local Git snapshot
`9c1da1e65fe2384f39c680f5b29add8ca341d2b6`: 27 files verified against blob hashes.
They are present locally and ignored. Other saved runs remain in `radioroc_runs`.
No separate external backup has been configured.

## Implemented in the foundation

- Installable `radioroc-tools` package and `radioroc` / `python -m radioroc` CLI
  dispatching all 14 existing user-facing scripts.
- Original script paths and core module imports retained.
- Single source for configuration/presets, included in the package; default
  configuration resolution works independently of the current working directory.
- Base dependency limited to pySerial; optional analysis/build dependencies.
- Source and installed-wheel offline checks, including headless plot rendering.
- GitHub Actions configuration for Ubuntu/macOS and Python 3.11/3.13.
- Development instructions and repository agent rules.

## Validation and limits

Local platform: macOS ARM64, Python 3.13. Existing conda environment is unchanged;
package validation uses `.venv-foundation`.

- Existing nine unit tests pass.
- Compile checks and all 14 original CLI help commands pass.
- Source distribution and wheel build successfully.
- Installed-wheel checks pass outside the checkout: core imports, default table
  byte equality/677 rows, preset resources, version, console entry point and all
  14 subcommand help pages, without Qt.
- Editable installation and source checks pass.
- Installed CLI rendered a threshold PNG from synthetic CSV data using the
  headless Matplotlib backend; no hardware was accessed.

CI configuration exists but has not run remotely. No Debian validation or new
hardware testing has occurred. The earlier status-read failure is unresolved.
The desktop UI, exclusive board ownership, portable automatic device selection,
and progress/cancellation contracts are not implemented in this delivery.
Some legacy dry-run commands still open serial ports; use only documented
offline checks without hardware. Pending protocol assumptions (including HG/LG
gain nibble mapping), readback error handling and incomplete state restoration
remain tracked migration concerns, not newly validated behavior.

## Next bounded tasks

| Task | Inputs | Done when |
|---|---|---|
| Review/integrate foundation | Baseline tag, development branch, local check evidence | Reviewed changes integrated; CI passes when pushed |
| Expand vendor parity inventory | F01–F17 in rebuild plan; Windows 2.2.0.5 application and older guide | Every observed control has defaults/units, source evidence and acceptance criteria |
| Extract protocol/transport (Delivery 2) | Existing framed transport and fake backend | Existing command bytes preserved; partial/wrong replies, timeout and disconnect tested; explicit errors |
| Identify and exclusively own a board | Dual FTDI interfaces; agreed session contract | Correct interface selected; two processes cannot use the same board; release on exit tested |
| Diagnose current board connection | Read-only status command and user-confirmed powered board | Valid status response on identified interface; actual result logged |

The feature inventory remains preliminary. Full Windows feature parity and
physical validation must not be inferred from a successful package build.

For each subsequent session: select one bounded task, record its acceptance
checks and resulting commit, then update this file with the next task.
