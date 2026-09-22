# RADIOROC 30 — Wire hover-hints into MainWindow/ASIC panels, or "Main" tab register mapping

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 29 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 29 entry for full detail. Summary:

1. **Diagnosed a real hold-scan run the operator asked about** (no code
   change): `radioroc_runs/hardware/20260922-105042-43d9bc20/`, run at
   `threshold_dac=150`, showed `ch4_count` ≈ 21–22 against a requested 10,
   and huge stdev (up to ~420) specifically in the 475–625 ns transition/peak
   region. Traced this to 150 sitting inside the noisy region this session's
   earlier threshold scan had mapped, combined with this run's
   `trigger_source=3` (individual per-channel discriminator) ADC config —
   meaning the ADC also arms on the channel's own noise-triggered crossings,
   not just the FPGA synchro pulse, roughly doubling the count and mixing
   randomly-timed noise samples into each batch. **Not yet confirmed**: the
   operator hasn't re-run at `threshold_dac=250` (the validated preset
   value) to check whether the count drops to ~11 and the stdev collapses,
   which would confirm this diagnosis. Worth doing early next session if the
   operator has the board.
2. **Hardware is now the default mode** in all three scan windows
   (`ThresholdWindow`/`HoldScanWindow`/`ScurveWindow`), not Simulation —
   direct operator request, since the desktop app is now used against real
   hardware routinely. The three GUI test suites (which are
   simulation-only by design) now select Simulation explicitly in `setUp`
   instead of relying on the old default; a new regression test
   (`test_scan_windows_default_to_hardware_mode` in `test_main_window.py`)
   guards the new default going forward.
3. **New hover-hint status line**: `src/radioroc/gui/hint_bar.py`'s
   `HintBar` wires Enter/Leave events on any widget to a `QStatusBar`
   (each scan window's own `self.statusBar()`), showing a one-line
   description of whatever's under the cursor and a window-level default
   otherwise — mirroring the vendor app's bottom help line. Wired into
   every control in all three scan windows, including plain-language
   descriptions of Ctest and the FPGA synchro-trigger pulse (the operator
   asked what these do). Unit-tested directly in `tests/test_hint_bar.py`.

296/296 offline tests (6 new), full suite re-run clean, `tools/check_development.py` passes.

## What's explicitly still missing

1. **Hover-hints don't cover `MainWindow` or the ASIC-config panels yet** —
   only the three scan windows have them. `MainWindow` itself (its tab bar,
   the shared `ConnectionPanel`) and the five ASIC-config sub-tabs (channel
   config, input DAC grid, probes/masks, threshold calibration, raw
   registers) still show no hint when hovered. `MainWindow` is a
   `QMainWindow` too, so the same `HintBar(self.statusBar(), ...)` pattern
   applies directly — see any of the three scan windows' `__init__` (near
   the end, after all widgets/signals are set up) for the exact pattern to
   copy. This is bounded, repetitive, well-specified work — a good
   candidate to delegate per `AGENTS.md` rather than have the lead do by hand.
2. **"Main" sub-tab (`F02`) register mapping** — still unbuilt, carried
   over from RADIOROC 28/29 (trigger preamp gain/compensation, HG/LG gain
   and shaping, T1/T2/TQ thresholds, delay code/slope, test-input routing).
   The reverse-engineering method is proven and repeatable (`strings` on
   the raw `.pyc`, or `marshal.loads()` + `dis`) — see RADIOROC 27's entry
   for what was tried on the common-block (`add >= 64`) registers
   specifically. Needs someone to spend more time on this tab, not a new
   technique.
3. **Hardware follow-up:** none of RADIOROC 27/28's new panels (input DAC
   grid, mask grids, threshold calibration grid, raw registers) have been
   validated against the *real* board yet — only S-curve/Hold-scan/
   Threshold-scan have real hardware evidence.

## Suggested next task (pick with judgment, same as always)

1. **If the operator is present with the board**, ask them to re-run the
   hold scan at `threshold_dac=250` first — cheap, confirms or refutes
   RADIOROC 29's diagnosis before building anything else on top of it.
2. **Wire `HintBar` into `MainWindow` and the five ASIC-config panels** —
   delegate this to a subagent: give it `src/radioroc/gui/hint_bar.py`'s
   API and one of the three scan windows as a reference pattern, and the
   list of panel files above. Should include a test per file confirming at
   least one hint fires (see `tests/test_hint_bar.py` for the
   `QEvent(QEvent.Type.Enter)` pattern used to test this without a real
   mouse).
3. **Extend the register-mapping technique to "Main"** (see above) if
   there's more appetite for reverse-engineering than for GUI polish this
   session.
4. Anything else reasonable from `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that
   doesn't need new register mappings.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check (it enumerates hardware through
D2XX even when you don't intend to use it). Run `tools/check_development.py`
after every meaningful change — after touching anything connection/
threading-related, don't just check it prints "OK": wrap it in a hard
`timeout` and confirm the process itself exits. When a panel or window
submits work to `ConnectionWorker` and then reads a result, remember that
submission is asynchronous — verify with a real (or faithfully fake)
transport under timing, not just a synchronous test double, before trusting
that the result shown is fresh. Delegate bounded, well-specified
implementation/test work to subagents per `AGENTS.md`; keep shared
contracts, uncertain hardware reasoning, and integration for the lead.
Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
