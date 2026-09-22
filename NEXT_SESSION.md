# RADIOROC 32 — Wire AutocalibrationJob into CLI/GUI, hardware-validate this session's work, or pick up F11–F13/F08's enable bits

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 31 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 31 entry for full detail. Summary:

1. **Hover hints now cover the whole app.** `MainWindow` and all six
   ASIC-config panels report into a shared `HintBar`, closing the gap
   carried over from RADIOROC 29/30. Delegated, reviewed diff-by-diff.
2. **F08 (automatic threshold calibration) is now fully built and tested
   offline, end to end.** `src/radioroc/application/autocalibration.py`'s
   `AutocalibrationJob` runs the real 4-step algorithm (LSB-ratio probe,
   transition scan, corrected calibration-DAC writes, verification scan)
   against real hardware, composing four `ScurveJob` sub-scans under one
   held session lock. Built directly by the lead (register/hardware-safety
   reasoning), not delegated. A real bug (a cleanup-clobbers-primary-error
   hazard in the restoration `finally` block) was caught and fixed in
   self-review before any test ran.
3. **`tests/test_autocalibration_jobs.py`** (6 tests) drives the real job
   against `test_scurve_jobs.ScurveTransport` — the same scripted
   fake-hardware transport `ScurveJob` itself is tested against — with
   hand-computed expected corrections at every step, not just "did it not
   crash." Covers cancellation-triggered restoration, `verify_restoration`,
   dry-run, and end-to-end session-lock rejection of a concurrent job.

327/327 offline tests total this session, `tools/check_development.py`
clean under a hard `timeout` with confirmed process exit, re-run
independently (not just trusting a delegated report) at every stage.

## What's explicitly still missing

1. **`AutocalibrationJob` has no CLI or GUI entry point.** No
   `scripts/radioroc_autocalibrate.py`, no GUI button/panel wiring it up.
   This is the natural next bounded slice — mirror how `ScurveJob` got a
   CLI command (`scripts/radioroc_scurve.py`) and how the S-curve GUI tab
   drives it via a worker (`src/radioroc/application/scurve_worker.py`,
   `src/radioroc/gui/scurve_window.py`) as the patterns to copy. A CLI
   command alone (no GUI) would already make this genuinely usable and is
   a smaller, well-bounded first step if GUI wiring feels like too much for
   one task.
2. **Never run against real hardware.** Every test so far is against a
   scripted fake transport. Before trusting this on the real board: the
   sub-scans reuse `ScurveJob`'s already-hardware-validated per-point logic
   verbatim, so the main *new* hardware-facing risk is specifically the
   parts this session added — the calibration-DAC force/restore sequencing
   around the reference channel, and the dynamic DAC-range computation
   between steps. Worth a deliberate, narrow first hardware test (small
   channel set, conservative ranges) focused on exactly those two things,
   not a full production run, the first time it touches the real board.
3. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7: `EN_th1`/`EN_th2`/`EN_thQ`/`EN_bg`) — carried over from RADIOROC 30,
   untouched since (bit order inside the shared byte wasn't cross-checked
   to the same confidence as everything else recovered that session).
4. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.
5. **Hardware follow-up, generally:** none of the ASIC-config panels
   (channel config, input DAC grid, mask grids, threshold calibration grid,
   raw registers, "Main") have been validated against the real board yet —
   only S-curve/Hold-scan/Threshold-scan have real hardware evidence.

## Suggested next task (pick with judgment, same as always)

1. **Wire `AutocalibrationJob` into a CLI command** (item 1's smaller
   half) — bounded, well-specified now that the job itself is solid;
   `scripts/radioroc_scurve.py` is the pattern to copy. Good delegation
   candidate once the CLI's exact argument surface is decided (the lead
   should settle that contract first, same discipline as this session).
2. **If the operator is present with the board**, do the narrow,
   deliberate first hardware test described in item 2 above before
   building more on top of `AutocalibrationJob`.
3. **Or start F11–F13** if there's more appetite for a new vertical slice
   than finishing F08's CLI/GUI or hardware validation — larger and less
   scoped, expect real scoping time before delegating any of it.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead — this session delegated HintBar wiring (a
mechanical, well-specified six-panel task) but built `AutocalibrationJob`
directly (a new hardware-orchestrating job type with a safety-critical
restoration requirement), and reviewed the delegated diff line by line
before trusting it either way. Record what you did, what's next, and any
real findings in `IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md`
before you stop.
