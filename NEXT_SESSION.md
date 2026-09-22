# RADIOROC 32 — Live-visual-check the new Autocalibration tab, hardware-validate F08, or pick up T1/T2/TQ enable bits / F11-F13

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 31 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 31 entry for full detail. Summary:

1. **Hover hints now cover the whole app** — `MainWindow` and all six
   ASIC-config panels, closing the gap from RADIOROC 29/30.
2. **F08 (automatic threshold calibration) is fully built, end to end**:
   - `AutocalibrationJob` (the real 4-step hardware sequence) — lead-built,
     lead-owned register/hardware-safety reasoning.
   - A CLI command, `scripts/radioroc_autocalibrate.py`.
   - Wired into the shared `ConnectionWorker` (`run_autocalibration`/
     `cancel_autocalibration`/`autocalibration_snapshot`), mirroring the
     existing scurve/hold/threshold pattern — lead-built (shared, critical
     file).
   - A saved-run reader, `read_autocalibration_run`.
   - A full GUI tab, `AutocalibrationWindow`, wired into `MainWindow` as a
     fourth Calibration tab — delegated, reviewed diff-by-diff.
   - **Deliberately hardware-only**: no standalone simulation mode/worker,
     confirmed with the operator before proceeding on that basis. If
     simulation-mode parity (matching S-curve/Threshold/Hold-scan's own
     synthetic-curve preview) is wanted later, that is new, separately
     scoped work — building a believable 4-step calibration-convergence
     simulator, not a small addition.
3. **Two real bugs caught and fixed during this build**, both before or via
   a test that specifically caught them (not by later discovery): a
   cleanup-clobbers-primary-error hazard in the restoration `finally` block,
   and a missing `status = "preparing"` reset that would have silently
   frozen the GUI's step-progress tracking on step 1 forever.

344/344 offline tests total this session, `tools/check_development.py`
clean under a hard `timeout` with confirmed process exit, re-run
independently at every stage (not just trusting delegated reports).

## What's explicitly still missing

1. **No live visual/screenshot check of the new `AutocalibrationWindow` tab.**
   Every other GUI change this session got one (it's how the window-sizing
   bug earlier in this session was actually found); this one didn't,
   because the operator appeared to be actively using the app on the shared
   display when the GUI work landed, and touching it uninvited risked
   disruption or an accidental hardware action. This tab has 13 form fields
   grouped into four boxes (Trigger preamplifier, Energy measurement, three
   DAC-range groups, common controls) — more than any existing tab — so a
   screen-fit/scroll check is worth doing deliberately, not skipping twice.
   **Do this early next session**: launch the app for real
   (`PYTHONPATH=src:. .conda-radioroc/bin/python -m radioroc.gui` with
   `DISPLAY` set, screenshot with `scrot`) and look at the Autocalibration
   tab specifically.
2. **Never run against real hardware.** Every test at every layer (job,
   CLI, worker, GUI) uses a scripted fake transport. The main *new*
   hardware-facing risk, since the sub-scans reuse `ScurveJob`'s
   already-hardware-validated logic verbatim: the calibration-DAC
   force/restore sequencing around the reference channel, and the dynamic
   DAC-range computation between steps. A first real-hardware test should
   focus narrowly on those two things (small channel set, conservative
   ranges), not a full production calibration run.
3. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, untouched since.
4. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.
5. **Hardware follow-up, generally:** none of the ASIC-config panels
   (channel config, input DAC grid, mask grids, threshold calibration grid,
   raw registers, "Main") have been validated against the real board yet —
   only S-curve/Hold-scan/Threshold-scan have real hardware evidence.

## Suggested next task (pick with judgment, same as always)

1. **Live-visual-check the Autocalibration tab** (item 1) — cheap, fast,
   directly continues this session's own established discipline.
2. **If the operator is present with the board**, do the narrow, deliberate
   first hardware test described in item 2 — the calibration-DAC
   force/restore sequencing and dynamic range computation are the specific
   things worth watching, not a full production run.
3. **Or start F11–F13** if there's more appetite for a new vertical slice —
   larger and less scoped, expect real scoping time before delegating any
   of it.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead — this session delegated HintBar wiring and
the `AutocalibrationWindow` GUI (both mechanical, well-specified once their
contracts were fixed) but built `AutocalibrationJob` and the
`ConnectionWorker` wiring directly (new hardware-orchestrating logic and a
shared critical file), and reviewed every delegated diff line by line
before trusting it. For any GUI change, do a live visual check when the
display is actually free to use — check for signs of an active operator
session (e.g. `ps aux` for an already-running `radioroc.gui` you didn't
start) before launching or interacting with one yourself. Record what you
did, what's next, and any real findings in `IMPLEMENTATION_STATUS.md` and a
fresh `NEXT_SESSION.md` before you stop.
