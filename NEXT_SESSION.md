# RADIOROC 39 — Priority 0: audit F11/F12's coincidence-trigger semantics against the plint's 2-channel requirement

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else.** It
sets this week's priorities and is not summarized completely below. Also
read `AGENTS.md` and this file in full, and skim `IMPLEMENTATION_STATUS.md`'s
RADIOROC 38 entries (both of them — search for "RADIOROC 38", there are two)
before acting. Older status entries may be superseded; verify current
source before treating a historical gap as live — this exact mistake
happened once already this week (RADIOROC 36 repeated a stale RADIOROC 24
note about the connection shell without checking; it had been fixed by
RADIOROC 28). The standing per-action hardware-authorization rule applies
as always: a grant given in one conversation is for that conversation
only. The directive itself grants no hardware authorization, and does not
authorize launching/closing another session's apps or interfering with an
active operator — coordinate any bench work through the operator directly.

Continuing on `feat/daq-results-gui`. Working tree clean once this handoff
is committed.

## What the last few sessions did

**RADIOROC 34-37** (see their own `IMPLEMENTATION_STATUS.md` entries):
landed F12 (`AcquisitionJob`), F13 Phase A (`read_acquisition_run`,
`read_vendor_acquisition_file`), recovered the real vendor acquisition file
format from `adc.pyc` disassembly, corrected a false claim about M3's
shared-connection gate, squash-merged the M3 milestone to `main` via PR #1,
and cut `feat/daq-results-gui` for the next stage.

**RADIOROC 38** (this conversation, in order):
1. Live-visual-checked the `AcquisitionWindow` skeleton with the operator
   physically present — confirmed it works correctly end-to-end (connect,
   configure, run, cancel, live batch summary, reopen).
2. Delegated, reviewed, and landed **F13's spectra/histogram rendering**:
   a matplotlib histogram of per-channel HG/LG values, channel visibility
   checkboxes, bins/log-scale controls, live updates (throttled disk
   re-read of `events.csv`, not a second in-memory buffer), and vendor-file
   import for comparison. Independently verified 447/447 under
   `.conda-radioroc`, then live-visual-checked with the operator watching —
   a real Gaussian histogram populated correctly during a live simulation
   run.
3. **Received `PLINT_STUDENT_MVP_DIRECTIVE.md`** reprioritizing this week
   around a concrete student-usable MVP (see that file — read it first).
   This handoff exists to carry that reprioritization into a fresh
   conversation, per the directive's and operator's own request, rather
   than starting Priority 0's investigation on a nearly-exhausted context
   window.

**F13's GUI is now functionally complete for its originally scoped slice**
(connect/configure/run/cancel/reopen, live batch summary, spectra
rendering, vendor-file comparison) but has never touched real hardware.

## This session's job: Priority 0 from the directive

Read the directive's "Priority 0" section closely — this summary is not a
substitute. In short: the plint experiment needs **two distinct selected
channels above threshold within a coincidence window** as its trigger. It
is genuinely unknown whether the current firmware/vendor-app's trigger
configuration (`trigger_type`/`trigger_source`/`adc_window_ns`/
`adc_nb_trig` — the same fields `AcquisitionConfig`, already landed in F12,
exposes) actually implements *that*, or whether its "N triggers in a
window" semantics would also accept **repeated pulses on one channel**,
which would silently be a completely different (and wrong) physics result
if assumed equivalent without checking.

**Where to start, concretely:**
1. `radioroc_client.py`'s `configure_adc_external_hold`/`acquire_adc_batch`
   and their `trigger_type`/`trigger_source` parameters are the current
   plumbing (already used by `HoldScanJob` and `AcquisitionJob` — read
   both `application/acquisition.py` and `application/hold_scan.py` for how
   they're actually invoked today). Establish precisely what each vendor
   trigger-type/source code value means at the hardware level.
2. Use the local vendor evidence first, per `AGENTS.md`'s standing
   instruction: `local_artifacts/extracted/RadiorocUI_2_2_0_5.exe_extracted/`
   — the `adc.pyc` module (used already in RADIOROC 35/36 to recover the
   acquisition file format and register byte layout) is the most likely
   place trigger-type/source dropdown values and their real semantics are
   defined or labeled; `generated_notes/*.txt` may already have partial
   disassembly from a prior session — check before re-deriving from
   scratch. The vendor PDF user guide
   (`local_artifacts/downloads/Radioroc2 User Guide - 2_1_0_6(0125).pdf`)
   and `app_pics/*.png` screenshots are the other two evidence sources
   `AGENTS.md` names.
3. Determine specifically: does any documented/observed trigger-source
   value correspond to "OR of N *specific, distinct* channels above
   threshold," as opposed to "N total threshold crossings counted from
   anywhere, including repeatedly from one channel"? Do not assume the
   existing default (`trigger_source=3`, the F12/hold_scan default) has
   ever been checked against this distinction — it hasn't.
4. Design (do not yet run without operator authorization) the directive's
   specified 5-case bounded test: (a) one channel, repeated pulses alone;
   (b) two distinct channels inside the window; (c) two channels outside
   the window with appropriate timing margin; (d) an excluded channel plus
   representative pairs across the selected set; (e) known distinguishable
   amplitudes on multiple channels, confirming event/channel association
   including channels that stayed below threshold. Specify expected
   accept/reject outcomes and timing tolerances *before* proposing to
   measure anything — per the directive, do not interpret uncontrolled
   dark-count activity as proof of coincidence semantics.
5. If the board/firmware cannot implement true multi-channel coincidence
   as configured, say so plainly with the evidence, and propose concrete
   alternatives (a different supported trigger mode; external coincidence
   hardware; a documented offline-cuts scheme with its rate/dead-time
   caveats made explicit) for the operator to choose between — do not
   silently substitute one of these or guess a register write to hit the
   deadline.

**Acceptance for this item** (directive's own words): "a documented
supported trigger/readout contract plus a controlled physical
demonstration. Simulated behavior alone cannot close this item." Offline
research and evidence-gathering can and should proceed without the
operator; the physical demonstration needs their explicit per-action
authorization at the board, same as always.

## Other directive priorities (read the directive for full detail)

- **Priority 1** (mostly done): channel-labelled HG/LG spectra, practical
  channel selection/plot controls, responsive progress/cancellation, saved
  run reopening — all landed in RADIOROC 37/38's `AcquisitionWindow` work.
  Still open per the directive: an "individual-event amplitude view"
  distinct from the histogram (not built — the histogram aggregates, it
  doesn't show individual events), and explicitly re-checking (not
  assuming) that the current CSV/manifest schema satisfies M2's raw/scaled
  encoding and units requirements for *this* experiment's needs.
  **Real usability bug found from a live screenshot, not yet fixed** — see
  the fuller RADIOROC 38 entry in `IMPLEMENTATION_STATUS.md`: all four
  plotting windows (`acquisition_window.py`, `autocalibration_window.py`,
  `scurve_window.py`, `hold_scan_window.py`) call `axes.legend(fontsize=8)`
  with no fixed `loc`, so matplotlib's auto-placement re-decides the
  legend's position on every redraw — confirmed to be exactly what causes
  both the operator-reported "legend jumps around" behavior on live S-curve
  redraws and a title/legend collision the operator directly screenshotted
  on the new spectra plot, which also showed unreadable overlapping
  `10^0`/`10^1` tick labels with Log Y enabled. Fix needs a fixed `loc` in
  all four files (verified against real data shapes, not guessed), a check
  of log-scale tick formatting at this project's actual target screen
  resolution, and a broader look at whether the plot windows' current
  layouts give the plot itself enough space at that resolution. This is
  direct evidence against the directive's own Priority 1 acceptance
  criterion ("a real visual check confirms the screen is usable") — treat
  it as a concrete, bounded, high-priority fix, not a vague polish item.
- **Priority 2**: an end-to-end calibration procedure for the student
  (pedestals/noise per channel, dead/noisy/saturated identification,
  relative gain characterization, threshold alignment, hold/conversion
  timing suitable for the actual trigger setup once Priority 0 resolves
  it, saved/attributable calibration). T1/T2/TQ enable-bit uncertainty
  (RADIOROC 30/34, still unresolved) and `ProbesMasksPanel`'s missing
  hardware read-back are named blockers *if* the chosen workflow needs
  them — check that dependency explicitly rather than assuming either way.
- **Priority 3**: run provenance and data-trustworthiness requirements —
  read closely, this has specific, concrete requirements (event IDs unique
  within a run including appended segments, distinguishing host-receipt
  from physical-event timestamps, retaining below-threshold amplitudes for
  all selected channels, not applying irreversible cuts in saved data).
- **Priority 4**: stabilization and an actual rehearsal with the student
  on the student's machine — the final gate, not a starting point.

Do not treat any of Priority 1-4 as blocked on Priority 0 being fully
resolved before starting — the directive says Priority 0's investigation
"should proceed alongside completion of the current F13 plotting slice,
without duplicate editors or conflicting changes to shared contracts." F13
plotting is now done, so the natural next offline-safe work (Priority 1's
individual-event view, or Priority 3's provenance review) can proceed in
parallel with Priority 0's evidence-gathering, as long as it doesn't touch
the same files Priority 0's investigation might need to change
(`radioroc_client.py`'s trigger primitives, `AcquisitionConfig`).

## Deferred, not dropped

Broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release work are
explicitly deferred by the directive until after this checkpoint —
targeted Windows comparisons needed for Priority 0 remain high priority.
F15/A7585 remains permanently out of scope. None of F01-F17/M0-M5 are
deleted by this reprioritization; this is a checkpoint within the existing
plan, not a replacement for it.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` (the project's actual GUI-capable environment) after
every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A self-created venv without the `[gui]` extra will
silently skip every GUI test and look green when it isn't — this has
happened once already (RADIOROC 36). Delegate bounded, well-specified
implementation/test work to subagents per `AGENTS.md`; keep shared
contracts, uncertain hardware/register reasoning, and integration for the
lead. When delegating to an isolated worktree, review the actual diff
line-by-line against the contract before merging, and go beyond the
delegated agent's own unit tests with at least one real end-to-end smoke
test of your own — every delegated task this week (F12, F13 Phase A,
`AcquisitionWindow`, spectra rendering) found something worth fixing or
confirming this way, not by trusting the subagent's own passing test count
alone.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`; when this branch's scope feels like a complete
stage, the same PR-then-branch pattern from RADIOROC 37 is the model to
repeat — raise the timing with the operator rather than deciding alone.

`gh` is installed and authenticated on this machine — use it
(`gh run list --branch <branch>`, `gh run view <id>`, `gh run view --log-failed`)
to check CI status directly after any push. Watch for the occasional
stale/transient `gh run list` result — re-list with a larger `--limit` if
the top row looks implausible.

**Before pushing anything** (per `AGENTS.md`'s "verify an installed wheel"
rule): actually reproduce CI's *environment*, not just its commands.
`.conda-radioroc` or any other long-lived dev environment with every extra
already installed cannot catch a missing-extra-only failure. Root-cause a
local repro failure before assuming your own current changes caused it —
an isolated `git worktree` against an earlier commit is cheap and doesn't
disturb the working tree. Never state a CI run "probably passed" — say
what you actually verified.

Per the directive's own instruction: track each MVP item as implemented,
offline-verified, physically verified, or blocked, with concrete evidence
and the next action. Separate software completion from equipment/operator
dependencies. Reassess feasibility immediately after this investigation —
do not promise delivery from a test count or code-volume estimate. Record
actual checks and remaining limitations in a fresh `IMPLEMENTATION_STATUS.md`
entry and `NEXT_SESSION.md`, retaining the session-numbering convention,
rather than copying aspirational acceptance claims into the log.
