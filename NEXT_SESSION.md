# RADIOROC 31 — Wire an actual HintBar into MainWindow/ASIC panels, hardware-validate the "Main" tab, or pick up F11–F13/F08

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 30 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 30 entry for full detail. Summary:

1. **Confirmed RADIOROC 29's hold-scan noise-self-trigger diagnosis** — a
   `threshold_dac=250` re-run already existed locally
   (`radioroc_runs/hardware/20260922-105500-056b6058/`) but hadn't been
   noticed. `ch4_count` is exactly 10 (not 21–22) and stdev in the 475–625 ns
   region tops out at ~24 (not ~419). Nothing left to do on this item.
2. **A7585 (F15) is permanently out of scope** — operator confirmed this lab
   doesn't use or own the module. Removed from `CROSS_PLATFORM_REBUILD_PLAN.md`'s
   parity table, bench-validation stage table, and M4 slice order.
3. **Recovered the "Main" tab (F02) register map** from the same vendor
   extraction already used for prior register work — a correction, not new
   work: the material was never missing, prior sessions just hadn't mined
   `Ui_MainWindow.retranslateUi`'s ~1400 string constants for it yet. Full
   mapping recorded in `IMPLEMENTATION_STATUS.md`'s RADIOROC 30 entry,
   cross-checked two independent ways.
4. **Implemented the full stack on top of that register map, end to end**:
   device-level `RadiorocDevice` setters (lead-owned register reasoning),
   an application-layer `ChannelConfigOperation` extension and a new
   `MainPanel` GUI tab (delegated, reviewed diff-by-diff, not just the
   delegated report's claims). F02 is now feature-complete offline except
   the T1/T2/TQ enable bits (deliberately deferred, see below).
5. **Found and fixed a real usability bug via a live visual check, not just
   offline tests.** The operator said they couldn't see the bottom of the
   window and didn't know if a hint/status bar existed there. Rather than
   guessing, launched the actual desktop app against the real X display and
   screenshotted it (before/after) — this is the way to check any future GUI
   change too, not just read the code. Confirmed two compounding causes:
   `MainWindow.resize(1280, 900)` requested a window exactly as tall as the
   1600x900 screen with zero margin for window-manager decorations, and the
   new `MainPanel` stacked three full group boxes with no scrolling, taller
   than every other ASIC-config tab's fitted space. Fixed both in
   `src/radioroc/gui/main_window.py`: the initial size now clamps to
   `QApplication.primaryScreen().availableGeometry()`, and every ASIC-config
   tab's panel is now wrapped in its own `QScrollArea` (a new `_scrollable()`
   helper) so any panel taller than the available height scrolls instead of
   clipping — general protection, not a `MainPanel`-only patch. Re-confirmed
   visually after the fix: window fits the screen, Main tab scrolls.
   **This was a visibility bug, not the missing-HintBar feature gap** —
   `MainWindow` has always had one permanent bottom connection-status strip
   (unrelated to hover-hints) that was simply invisible before this fix;
   there is still no `HintBar` (hover-tooltip line) anywhere outside the
   three scan windows.

312/312 offline tests, full suite independently re-run clean three times
across this session's changes, `tools/check_development.py` passing with a
confirmed process exit each time. Two real screenshots (before/after) taken
against the actual display to verify the sizing fix, not just headless tests.

## What's explicitly still missing

1. **T1/T2/TQ *enable* bits are still unimplemented** (address 65,
   subaddress 7: `EN_th1`/`EN_th2`/`EN_thQ`/`EN_bg`) — bit order inside the
   shared byte wasn't cross-checked to the same confidence as everything
   else recovered this session. Needs another default-value cross-check or
   a hardware readback comparison before implementing.
2. **`HintBar` (the actual hover-tooltip status line) still doesn't exist
   for `MainWindow` or any ASIC-config panel** — carried over three sessions
   now, untouched again. Do not confuse this with the connection-status
   strip fixed this session (that's a different, older, always-on widget).
   Same bounded task as before: see any of the three scan windows'
   `__init__` for the `HintBar(self.statusBar(), ...)` pattern to copy. Six
   panels now need it: `MainPanel`, `ChannelConfigPanel`, `InputDacGridPanel`,
   `ThresholdCalibrationPanel`, `ProbesMasksPanel`, `RawRegisterPanel`, plus
   `MainWindow`'s own tab bar/`ConnectionPanel`.
3. **Hardware follow-up:** none of the ASIC-config panels (channel config,
   input DAC grid, mask grids, threshold calibration grid, raw registers,
   and now `MainPanel`) have been validated against the real board yet —
   only S-curve/Hold-scan/Threshold-scan have real hardware evidence. The
   new F02 register writes in particular have never been driven against
   real hardware; only offline/simulated coverage exists.
4. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI) and
   F08 (autocalibration migration into the core package) are still entirely
   unstarted**, and all of M5 (Windows-comparison bench, performance,
   packaging/release) hasn't begun. See `CROSS_PLATFORM_REBUILD_PLAN.md`
   §3/§4 for the full list.
5. **Only the "Main" tab was screenshot-checked.** The other five
   ASIC-config tabs were only just wrapped in `QScrollArea` this session and
   have not themselves been visually re-confirmed to still look right (they
   likely already fit without scrolling, since they predate this bug, but
   that's an assumption, not a screenshot-verified fact).

## Suggested next task (pick with judgment, same as always)

1. **If the operator is present with the board**, hardware-validate
   `MainPanel`/F02 the same way S-curve was validated in RADIOROC 27 —
   especially the T1/T2/TQ threshold DAC shared-byte splits, the part of
   this session's work with the most room for a subtle RMW bug to hide,
   since offline tests can only check the codebase's own RMW logic, not
   that it matches physical register semantics.
2. **Wire an actual `HintBar` into `MainWindow` and all six ASIC-config
   panels** (item 2 above) — bounded, well-specified, good delegation
   candidate now that the sizing bug that would have hidden it either way
   is fixed.
3. **Or start F11–F13/F08** if there's more appetite for a new vertical
   slice — larger and less scoped, expect real scoping time before
   delegating any of it.

## Standing discipline (unchanged, plus one addition)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead, and review a delegated diff line by line
before trusting its own report.

**New this session:** for any GUI change, a live visual check (launch the
real desktop app — `PYTHONPATH=src:. .conda-radioroc/bin/python -m
radioroc.gui` with `DISPLAY` set — and screenshot it, e.g. with `scrot`)
caught a real bug that 312 passing offline/offscreen tests entirely missed,
because every GUI test runs under `QT_QPA_PLATFORM=offscreen` with no real
screen size to clip against. Do this whenever a session touches window
sizing, layout, or adds a new panel — not just when the operator reports a
problem.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
