# Next session: desktop threshold workflow in simulation

Delivery 3 is committed at `8849808` on `feat/threshold-jobs`, package version
`0.3.0`. Its following documentation commit records this handoff. All 55 offline
tests, 15 CLI help checks, source/wheel builds and isolated installed-wheel
checks (including a synthetic job, offline preview and plot) pass on macOS ARM64 /
Python 3.13. No hardware was accessed. No commits were pushed.

---

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md` (especially
“Threshold jobs”) and Delivery 4 in `CROSS_PLATFORM_REBUILD_PLAN.md`. Continue
from `feat/threshold-jobs` on a new local feature branch. Keep this chat limited
to a minimal desktop threshold workflow in simulation, consuming the shared API.

First inspect `radioroc.application.threshold`, its result/event contracts and
`tests/test_threshold_jobs.py`. Define a small UI/worker boundary and acceptance
checks before editing. Use an optional PySide6 dependency so core/CLI installs
remain headless. Implement device/simulation selection, threshold configuration,
offline preview, run/progress/cancel, a live plot and reopening saved results.
Keep preparation options and temporary scan restoration visible in the preview.
The simulator must be explicitly labelled and produce deterministic configurable
threshold counts through the shared workflow; the existing memory backend and
scripted unit-test transport are not an analog simulator.

Acceptance checks:

- The UI submits `ThresholdJobConfig` to `ThresholdJob.run`; it contains no
  register sequences or duplicate measurement loop.
- Device I/O runs on an owned worker thread. GUI widgets stay on the UI thread.
  Event delivery is bounded/coalesced for display while saved data remains complete.
- Configure → preview → simulated run → progress/plot → cancel/finish → reopen
  works. Display terminal status, partial points, simulation mode and cleanup /
  storage failures truthfully. Nonterminal manifests are incomplete runs.
- Closing during a run requests cancellation and completes cleanup before
  releasing the worker/session. No automatic resume or silent device opening.
- Existing API, legacy CLI and offline dry-run behavior stay compatible. Core
  installation/help checks still run without Qt or a display server.
- Add focused worker/UI tests using simulation and fault injection; run existing
  development checks and installed-wheel checks. Record the actual desktop launch
  evidence separately from headless tests. Check the optional GUI installation
  and local app launch; multi-OS app bundling is a later bounded task if it grows.
- Review, update status/handoff and commit locally. Do not push or change main.

Exclude acquisition/autocalibration migration, complete Windows feature parity,
full register editors, automatic hardware control-interface detection and release
packaging across all OSes. Record discoveries instead of broadening this slice.
If even the simulation desktop workflow grows too large, checkpoint a coherent
worker/simulator + launchable shell with explicit remaining acceptance checks;
do not mark Delivery 4 complete prematurely.

The previous board status check was 5 at `/dev/cu.usbserial-RD3_320`, USB serial
`RD3_32`, powered with no SiPM or pulse generator. That is historical information,
not a new connection check. Delivery 3's expanded snapshot/restore register set
has only offline validation. Do not run a hardware scan as a GUI test. Hardware
validation needs a separate reviewed test card stating register coverage,
equipment/wiring, expected observations, cancellation and cleanup. Keep ignored
experiment folders and `radioroc_runs` local and untouched.

Tell me when the scope is expanding, and recommend another fresh chat after a
stable committed milestone or before changing subsystem. Persist any unfinished
work as an explicit WIP checkpoint before handing off.

---

Other pending work stays in `IMPLEMENTATION_STATUS.md`: physical snapshot/restore
validation, Linux USB/installation, Windows control-level inventory, other jobs,
recovery readers, and publication/CI with confirmed Git author identity.
