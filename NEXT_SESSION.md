# RADIOROC 39 — Build F13's spectra/histogram rendering, or start the Windows-comparison groundwork

Continuing on `feat/daq-results-gui` (a fresh branch off `main`, which now
has the M3 milestone merged — see below). Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 34-37 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 35, 36 and 37 entries for the
full account (all three are long — read them in full, not just this
summary).

**RADIOROC 34/35**: live-visual-check of the GUI; reviewed a real
operator-run hardware `AutocalibrationJob` test; re-confirmed the T1/T2/TQ
enable-bit blocker; closed the `check_installed_package.py --gui`
routine-checks blind spot; **landed F12** (`AcquisitionJob`); recovered the
real vendor acquisition file format from `adc.pyc` disassembly.

**RADIOROC 36**: corrected a false claim about M3's shared-connection gate
(it's been met since RADIOROC 28 — a stale grep hit was repeated without
checking current source; caught by the operator); **landed F13 Phase A**
(`read_acquisition_run`, `read_vendor_acquisition_file`), finding and fixing
one more real bug in review (an append-mode channel-set edge case that
silently destroyed the current segment's data); gave a rough plan-completion
estimate on request (~35-40% overall, M0 ~50%/M1 ~85%/M2 ~85%/M3 100%/M4
~15-55% depending on the bar used/M5 ~5%).

**RADIOROC 37** (operator squash-merged `feat/desktop-hardware-threshold`
into `main` via PR #1 after confirming M3's gate was genuinely met — 92
commits, +29257/-978 lines, `main` hadn't moved since 2026-06-29):
1. New branch `feat/daq-results-gui` cut from the updated `main` for the
   next stage of work, per the operator's explicit request.
2. **Landed an `AcquisitionWindow` GUI skeleton** for F13: connect (via the
   same shared `ConnectionWorker` shell every window uses), configure an
   `AcquisitionConfig`, preview/run/cancel, a live batches-completed
   progress bar plus a compact per-channel count/min/max/mean summary of
   the most recent batch, and "Open saved run" via the already-landed
   `read_acquisition_run`. Deliberately excludes spectra/histogram
   rendering, bins/scales controls, and vendor-file import/export UI — those
   need visual iteration this session (built in the last ~30 minutes before
   the operator left for a train, then reviewed/merged after) wasn't
   positioned to do blind.
   Delegated with a contract built from a careful read of
   `threshold_worker.py`/`connection_worker.py`'s threshold-specific state/
   `threshold_window.py`'s dual-mode split, then reviewed line-by-line: the
   ~130-line `connection_worker.py` addition was checked field-for-field
   against `_run_threshold`/`_threshold_fault`/`run_threshold` and confirmed
   an exact, correct mirror; ran a real end-to-end smoke test beyond the
   delegated agent's own unit tests (constructed the window offscreen, ran a
   3-batch simulation to completion, reopened the saved run through a fresh
   window instance) to confirm the whole path works together, not just in
   isolated unit tests. One pre-existing quirk noted but not touched (an
   output-directory-relabeling asymmetry that already exists identically in
   `ThresholdWindow` — not a regression, out of scope for this task).
   440/440 independently verified under `.conda-radioroc`, before and after
   merging.

**F13's GUI is a skeleton, not complete.** The data layer (Phase A) and the
connect/run/cancel/reopen skeleton (this entry) are both done and reviewed;
spectra/histogram rendering, bins/scales controls, live-plot-during-run, and
vendor-file import/export UI are the next slice.

## What's explicitly still missing

1. **F13's spectra/histogram rendering** on top of the now-landed
   `AcquisitionWindow` skeleton: a matplotlib canvas showing HG/LG channel
   spectra (mirror `ScurveWindow`'s/`ThresholdWindow`'s existing plotting
   pattern — `canvas`/`axes`/live-update-during-run), separate HG/LG
   event/acquisition views, channel selection/visibility/clear, bins/scale
   controls, and vendor-file import (reading a real vendor
   `readable_adc_acq.txt` via the already-landed `read_vendor_acquisition_file`
   for a Windows-comparison view — no writer, per RADIOROC 36's research).
   This is genuinely GUI-layout work that benefits from a live visual check
   the way RADIOROC 34's did — consider getting a screenshot reviewed by the
   operator before or shortly after building it, rather than iterating fully
   blind through another unattended stretch.
2. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
3. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, re-confirmed blocked in RADIOROC 34.
   Needs either a genuinely new evidence source or a narrow
   authorized-operator hardware test: write one candidate bit pattern,
   observe which physical threshold/channel responds. Do not guess and ship
   a write for this byte.
4. **F11 is largely covered by F12's `AcquisitionConfig`** (trigger_type/
   trigger_source/adc_window_ns/adc_nb_trig are the same primitives F11
   asks for), but hasn't been explicitly validated as "done" against F11's
   own row in `CROSS_PLATFORM_REBUILD_PLAN.md` §3 — worth a deliberate
   check rather than assuming.
5. **No real Windows-comparison work has started at all** (M5, and the
   strict reading of M4's own gate). Everything vendor-derived so far is
   static `.pyc` disassembly, never a live side-by-side run against the
   actual Windows app. This is the single biggest gap in the rough
   plan-completion estimate given in RADIOROC 36 — worth discussing with
   the operator what equipment/access this actually needs before treating
   it as a normal "pick with judgment" backlog item.
6. All of M5's other scope (performance, packaging/release) hasn't begun.
   See `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.
7. **Minor, not urgent:** the CI run's own annotations flag
   `actions/checkout@v4`/`actions/setup-python@v5` as targeting a
   deprecated Node.js version.

## Suggested next task (pick with judgment, same as always)

1. **Build F13's spectra rendering** (item 1) if there's appetite for
   another vertical slice — the skeleton underneath it is now settled and
   reviewed. Strongly consider a screenshot check-in given this is the
   part of F13 most likely to need visual iteration to get right.
2. **If the operator is present with the board and wants to resolve
   T1/T2/TQ (item 3)**, the narrow hardware test described there is the
   only path left to unblock it.
3. Raising item 5 (Windows-comparison groundwork) with the operator is
   worth doing regardless of what else gets picked — it's the largest
   remaining unknown in the plan's own completion picture, and likely
   needs something (a Windows machine, a licensed copy of the vendor app,
   lab time) that isn't just "more delegated coding work."

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` (the project's actual GUI-capable environment) after
every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A self-created venv without the `[gui]` extra will
silently skip every GUI test and look green when it isn't — this has now
happened once already (RADIOROC 36). A7585 (F15) is permanently out of
scope. Delegate bounded, well-specified implementation/test work to
subagents per `AGENTS.md`; keep shared contracts, uncertain hardware/
register reasoning, and integration for the lead. When delegating to an
isolated worktree, review the actual diff line-by-line against the
contract before merging, and go beyond the delegated agent's own unit
tests with at least one real end-to-end smoke test of your own — every
delegated task so far this stretch (F12, F13 Phase A, `AcquisitionWindow`)
found something worth fixing or confirming this way, not by trusting the
subagent's own passing test count alone.

`main` now has the M3 milestone (PR #1, squash-merged). New feature work
continues on `feat/daq-results-gui`; when this branch's own scope feels
like a complete stage, the same PR-then-branch pattern from RADIOROC 37
is the model to repeat — raise the timing with the operator rather than
deciding alone.

`gh` is installed and authenticated on this machine — use it
(`gh run list --branch <branch>`, `gh run view <id>`, `gh run view --log-failed`)
to check CI status directly after any push, instead of asking the operator
to check the Actions UI manually. Watch for the occasional stale/transient
`gh run list` result — re-list with a larger `--limit` if the top row looks
implausible, rather than trusting a single query.

**Before pushing anything** (not just after a packaging change, per
`AGENTS.md`'s existing "verify an installed wheel" rule): actually
reproduce CI's *environment*, not just its commands. Build a from-scratch
venv with only the exact extras a given CI step installs, confirm the
thing that's supposed to be absent (e.g. `import PySide6`) genuinely fails
in it, then run the real command there. `.conda-radioroc` or any other
long-lived dev environment with every extra already installed cannot catch
a missing-extra-only failure no matter how many times it's used. When a
local repro does fail, root-cause it before assuming your own current
changes caused it — reproducing against an earlier commit in an isolated
`git worktree` (cheap, doesn't disturb the working tree) is what
distinguished "pre-existing bug" from "something I just broke" in a past
session. And never state a CI run "probably passed" as a substitute for
checking — say what you actually verified and what you didn't.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
