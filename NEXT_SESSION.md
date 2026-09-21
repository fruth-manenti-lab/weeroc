# RADIOROC 26 — Autonomous overnight session, no operator present

**This is an autonomous session.** The operator is asleep and explicitly asked
to not be consulted on which options to take — pick your own priorities from
the menu below using judgment, and keep going without stopping to ask.

**Hardware: the operator explicitly authorized using whatever is already
connected** (RADIOROC board, PSU, signal generator, oscilloscope — the same
setup used throughout RADIOROC 23-25) **without asking per-action tonight.**
That's a real, meaningful relaxation of this project's normal
"fresh-authorization-per-action" rule (see `AGENTS.md`), made explicitly
because no one will be awake to grant that per-action authorization — so the
discipline has to move from "ask before each action" to "be conservative
about what you attempt and stop cleanly the moment something looks wrong,"
since there's no one to catch a mistake mid-flight tonight. Concretely:

- Fine: running CLI/GUI scans (threshold/hold-scan/S-curve) against the
  already-connected board using presets or configs already established as
  known-good in `IMPLEMENTATION_STATUS.md` (RADIOROC 23-25), powering the PSU
  channel on/off the same way tonight's session did, reading/writing ASIC
  config through the already-validated code paths.
- Not fine, regardless of how confident you are: connecting anything new
  (a detector, a different instrument, a different cable routing), any
  firmware update, any action this project's own docs describe as needing a
  human "operator" sign-off for a *first-time* validation (e.g. don't attempt
  the first-ever hardware run of some new code path autonomously — do that
  offline/simulated, and leave the physical first-validation for a session
  where the operator is present).
- If a measurement looks physically implausible, a connection faults, or
  anything is ambiguous: stop that specific action, record exactly what
  happened, and move to a different menu item — do not try escalating
  workarounds unsupervised the way tonight's session did together with the
  operator present. Being wrong and stopping is fine; being wrong and pushing
  through alone is not.

Read `AGENTS.md` first regardless of the above for everything else
(delegation/verification discipline, recording convention).

## Uncommitted work from tonight (do this first)

Branch `feat/desktop-hardware-threshold`, last commit `f51323f`. The working
tree has real, tested, but uncommitted work:

```
 M src/radioroc/gui/hold_scan_window.py
 M src/radioroc/gui/__main__.py
 M src/radioroc/gui/scurve_window.py
 M src/radioroc/gui/threshold_window.py
?? src/radioroc/gui/channel_config_panel.py
?? src/radioroc/gui/connection_panel.py
?? src/radioroc/gui/main_window.py
?? tests/test_channel_config_panel.py
?? tests/test_connection_panel.py
?? tests/test_main_window.py
```

This is the shared-shell refactor the operator asked for after finding that
`ThresholdWindow`/`HoldScanWindow`/`ScurveWindow` each duplicated their own
connection + channel-config UI instead of sharing one — built against real
Windows vendor-app screenshots (`local_artifacts/app_pics/image (13-28).png`).
`MainWindow` (`src/radioroc/gui/main_window.py`) is the new shell: a sidebar
("ASIC config." / "Calibration"), one shared `ConnectionPanel` +
`ChannelConfigPanel` on the ASIC-config page, and the three scan workflows as
sub-tabs of Calibration, all sharing one real `ConnectionWorker` instance.
Verified working (one worker instance shared across all four consumers,
screenshotted with no overlap, styled to loosely match the vendor palette).

### Task 1 — finish the test-suite stability fix, then commit

Tonight also found and partially fixed a **real, reproducible-but-intermittent
SIGSEGV** in the test suite: `QObject::killTimer: Timers cannot be stopped
from another thread`. Root cause: every GUI test file (including ones written
weeks before tonight) calls `window.close()` in teardown but never
`window.deleteLater()`; a window's leftover Python reference cycle (via
Qt signal/slot connections) can then get collected by Python's *cyclic*
garbage collector on **any** thread — including a `ConnectionWorker`'s
background thread — which crashes when it destroys a `QTimer` whose thread
affinity is the main thread. Fixed in tonight's new files
(`tests/test_connection_panel.py`) by adding explicit `deleteLater()` +
`app.processEvents()` in cleanup instead of relying on GC timing; confirmed
6/6 clean runs of the specific crashing combination (was ~1/3–1/5 failing
before) and 3/3 clean full-suite runs (242 tests).

**Not yet done:** the same `deleteLater()` fix across the *pre-existing* GUI
test files that share the identical latent pattern — grep for `\.close()`
without a following `deleteLater()` in `tests/test_threshold_gui.py`,
`tests/test_hold_scan_gui.py`, `tests/test_scurve_gui.py`,
`tests/test_connection_gui.py`, and the `*_worker.py` test files that
construct real `ConnectionWorker`/other worker threads. Apply the same fix
(`window.deleteLater()` + `QApplication.instance().processEvents()` in
teardown, after `close()`/worker shutdown), then stress-test: run
`tools/check_development.py` **at least 5-10 times in a row** (not just once —
this bug does not reproduce every time) before concluding it's fixed. Only
then commit this test-suite-stability work together with the shell refactor
above as one RADIOROC entry (see the recording convention in `AGENTS.md` and
how RADIOROC 24/25 did it in `IMPLEMENTATION_STATUS.md`) — commit and push to
`feat/desktop-hardware-threshold` (never `main`), matching tonight's rhythm;
you do not need to ask before committing/pushing to this feature branch, that
permission already stands for tonight's autonomous continuation.

## After that: autonomous priority menu (pick with judgment, don't ask)

All of these are software-only, need no hardware, and are reasonable next
steps. Do as many as you can make real, tested, committed progress on; stop
and write your own handover (mirroring this one) when you either run out of
good options or hit something that genuinely needs the operator.

1. **Physically validate the S-curve GUI path on the already-connected board**
   (this was flagged as pending at the end of RADIOROC 25 — hold scan's GUI
   path got hardware validation same-day, S-curve's didn't). Reuse the exact
   known-good bare-board noise-scan setup from tonight's own diagnosis
   (`Apply defaults` + trigger preamp gain code 1 on channel 4 — see the
   `RADIOROC 24`/`RADIOROC 25` entries and tonight's chat for the DAC range
   that produced a clean turn-off curve around DAC 120-125). This is exactly
   the kind of already-established, low-risk hardware action the operator's
   authorization above covers. Leave the board/PSU/generator in a safe idle
   state when done (matching how every prior session's handoff left it), and
   record the result with the same evidence rigor as RADIOROC 24.
2. **Expand the ASIC-config page to match the vendor app's other sub-tabs.**
   The vendor app's "ASIC config." area (see
   `local_artifacts/app_pics/image (13).png` through `image (16).png`) has
   four sub-tabs: "Main" (trigger/energy-measurement/threshold settings, not
   built at all yet — this is `F02`), "input DAC" (a full 64-channel DAC-value
   grid — our `ChannelConfigPanel` only has a single-channel-range text field,
   not the grid), "Threshold calibration" (per-channel T1/T2 calibration DAC
   trim grid, `F04`, not built), "Probes/Masks" (analog/digital probe
   selection + three 64-channel T1/T2/TQ mask toggle grids with
   enable-all/none, richer than our current per-channel checkbox). This is a
   direct, well-scoped continuation of tonight's shell work using reference
   material already reviewed. Consider whether the existing
   `radioroc.application.channel_config.ChannelConfigOperation`/
   `apply_channel_config` core already supports per-channel-grid operations or
   needs extending — check before assuming either way.
3. **Sweep the rest of the codebase for the same `deleteLater()` gap** if you
   have time after (1)/(2) — every GUI test file, not just the ones touching
   `ConnectionWorker` directly, for consistency and future-proofing.
4. Anything else reasonable from `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that
   doesn't need hardware (e.g. more of the raw-register view, `F06`).

## Standing discipline (unchanged)

Offline tests and fake transports only. Never run `radioroc_env_check.py` as
an offline check (it enumerates hardware through D2XX even when you don't
intend to use it). Run `tools/check_development.py` after every meaningful
change. Record what you did, what's next, and any real findings (bugs, design
decisions, things you scoped down) in `IMPLEMENTATION_STATUS.md` and a fresh
`NEXT_SESSION.md` before you stop, the same way tonight's session did for
RADIOROC 24/25 — the next actual conversation with the operator picks up from
whatever you leave there.
