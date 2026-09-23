# RADIOROC 40 — Priority 0's last step: the operator bench test, then Priority 2/3

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else** (still
this week's priority document, not summarized completely below), then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s
RADIOROC 39 entries (search "RADIOROC 39" — there are three, all near the
top of the file, read all of them in order). Older status entries may be
superseded; verify current source before treating a historical gap as
live. The standing per-action hardware-authorization rule applies as
always: a grant given in one conversation is for that conversation only.
Coordinate any bench work through the operator directly.

Continuing on `feat/daq-results-gui`. Working tree clean once this handoff
is committed.

## What RADIOROC 39 did — Priority 0's software side is now complete

Three things landed this session, all recorded in their own
`IMPLEMENTATION_STATUS.md` entries (read those for full detail; this is a
compressed summary):

1. **Recovered the real ADC coincidence-trigger register contract** from
   `radioroc2UI.pyc`/`adc.pyc` disassembly, cross-checked against the
   vendor PDF guide, and **fixed a confirmed bug**: `configure_adc_
   external_hold` only ever exposed one of the vendor app's two independent
   coincidence-input slots, hardcoding the second to "OR of every unmasked
   channel." So `trigger_type=1` ("2 channels coincidence") never actually
   implemented two-*distinct*-channel coincidence, regardless of settings.
   Added `trigger_source_2`/`trigger_channel_2` to `configure_adc_
   external_hold`, `AcquisitionConfig`, `HoldScanConfig`, writing the
   correct FPGA words (23/30). Backward compatible.
2. **Closed the channel-mask gap** without guessing the one remaining
   unknown (which discriminator level — T1, T2, or TQ — "Individual
   trigger" mode actually taps; more disassembly hit a genuine dead end,
   likely FPGA gateware this codebase's Python control-plane can't see).
   Added `RadiorocDevice.unmask_channel_for_individual_coincidence`, which
   defensively unmasks all three levels for one named channel — safe
   because genuine 2-channel coincidence never runs an OR-tree mode on
   either slot simultaneously, so this can't pull in an unintended channel.
   Wired into both `application/acquisition.py` and `application/
   hold_scan.py`.
3. **Added `AcquisitionWindow` GUI controls** for trigger type, both
   coincidence slots' channel + mode, window width, and time-window
   trigger count — a student can now actually configure 2-channel
   coincidence from the app, not just from a script. Independently
   rendered and visually inspected offscreen.

450/450 offline tests pass under `.conda-radioroc`
(`tools/check_development.py`).

**What remains for Priority 0 is exactly one thing, and it's the one thing
no amount of further disassembly or code review can substitute for**: per
the directive, "simulated behavior alone cannot close this item." Every
other part of Priority 0's software contract is done and tested.

## This session's job: the operator bench test

1. **Get the operator's per-action authorization first**, per the standing
   rule — a grant from any earlier conversation does not carry over.
   Coordinate timing; do not launch or close another session's apps or
   interfere with an active operator.
2. **Design the 5-case test before touching hardware**, per the directive
   (specify expected accept/reject outcomes and timing tolerances first):
   - (a) One selected channel pulsing alone; repeated pulses on that same
     channel — must NOT trigger a coincidence accept.
   - (b) Two distinct selected channels, pulses inside the coincidence
     window — must accept.
   - (c) Two channels, pulses outside the window (with timing margin
     appropriate to the hardware) — must NOT accept.
   - (d) An excluded (unselected) channel plus representative pairs across
     the selected channel set.
   - (e) Known, distinguishable amplitudes on multiple channels — confirms
     event/channel association is correct (not just matching array
     lengths), including channels that stayed below threshold still being
     recorded.
   Use the now-known-correct configuration recipe: `trigger_type=1`,
   `trigger_source=3` + `trigger_channel=A`, `trigger_source_2=3` +
   `trigger_channel_2=B`, `use_mask=True` (the mask fix above then unmasks
   both A and B automatically). Use the new `AcquisitionWindow` controls
   directly rather than a script, since that's the actual student path and
   is worth exercising for real.
3. **Do not interpret uncontrolled dark-count activity as proof of
   coincidence semantics** — use suitable controlled inputs (pulser/
   injection per the directive's equipment note) and check capture/hold
   timing as well as the trigger decision.
4. **If the board can't implement the requested multiplicity as expected**,
   surface it promptly with evidence and propose concrete alternatives
   (a different supported trigger mode; external coincidence hardware; a
   documented offline-cuts scheme with explicit rate/dead-time caveats) —
   do not silently substitute one or guess a register write.
5. Record the outcome — accept/reject results per case, any timing
   findings, and whether the "unmask all three levels" defensive choice
   from RADIOROC 39 turned out to matter (e.g., did an "Individual trigger"
   config only work once a specific level was unmasked, which would
   actually answer the open discriminator-level question after the fact) —
   in a fresh `IMPLEMENTATION_STATUS.md` entry, closing Priority 0 for real
   if it passes, or documenting the blocker precisely if it doesn't.

## Once Priority 0 is physically closed: what's next

Per the directive, Priorities 2 and 3 are **not started at all** yet and
should not wait on a second Priority-0-adjacent session if bench time with
the operator becomes the bottleneck — offline-safe work can proceed in
parallel:

- **Priority 2 (calibration procedure)**: pedestals/noise per channel
  (dead/noisy/saturated identification), relative gain characterization,
  threshold alignment, hold/conversion timing suitable for the now-settled
  trigger setup, saved/attributable calibration. Reuse F02–F10 and existing
  calibration/scan jobs — this is about defining and documenting the
  *procedure*, not new hardware primitives, unless a real gap turns up.
- **Priority 3 (provenance/trustworthiness)**: re-check (don't assume) that
  the current CSV/manifest schema actually satisfies: event IDs unique
  within a run including appended segments, host-receipt vs. physical-event
  timestamp distinction, retaining below-threshold amplitudes for all
  selected channels, no irreversible cuts in saved data. This is a review
  task against existing code (`radioroc/data/acquisition.py`,
  `AcquisitionRunWriter`), not necessarily new implementation — read it
  first and report findings before changing anything.
- **Priority 1 leftovers**: an individual-event amplitude view distinct
  from the histogram (not built yet); the M2 raw/scaled units check is
  folded into the Priority 3 review above since they overlap.

Priority 4 (stabilization + student rehearsal) is the final gate and
should not be started until at least Priority 0 is physically closed and
some calibration procedure exists for Priority 2.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` after every meaningful change — wrap it in a hard
`timeout` and confirm the process itself exits (it takes ~3 minutes; do not
assume a shorter timeout means failure — background it and poll rather
than truncating). A self-created venv without the `[gui]` extra will
silently skip every GUI test and look green when it isn't (RADIOROC 36).
Delegate bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead. When delegating, review the actual diff
line-by-line against the contract before merging (RADIOROC 39's legend-fix
delegation is the model: bounded to non-overlapping files, reviewed
line-by-line, independently re-rendered and re-tested rather than trusting
the agent's own report), and go beyond the delegated agent's own test count
with at least one real check of your own.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`; when this branch's scope feels like a complete
stage, the same PR-then-branch pattern from RADIOROC 37 is the model to
repeat — raise the timing with the operator rather than deciding alone.
Given Priority 0's software side is now essentially done, this may be a
natural point to raise that question once the bench test above lands.

`gh` is installed and authenticated — use it (`gh run list --branch
<branch>`, `gh run view <id>`, `gh run view --log-failed`) to check CI
status directly after any push. Watch for the occasional stale/transient
`gh run list` result — re-list with a larger `--limit` if the top row looks
implausible.

**Before pushing anything**: actually reproduce CI's *environment*, not
just its commands. `.conda-radioroc` or any other long-lived dev
environment with every extra already installed cannot catch a
missing-extra-only failure. Root-cause a local repro failure before
assuming your own current changes caused it.

Per the directive's own instruction: track each MVP item as implemented,
offline-verified, physically verified, or blocked, with concrete evidence
and the next action. Separate software completion from equipment/operator
dependencies. Record actual checks and remaining limitations in a fresh
`IMPLEMENTATION_STATUS.md` entry and `NEXT_SESSION.md`, retaining the
session-numbering convention, rather than copying aspirational acceptance
claims into the log.

## Deferred, not dropped

Broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release work remain
explicitly deferred by the directive until after this checkpoint. None of
F01–F17/M0–M5 are deleted by this reprioritization. F15/A7585 remains
permanently out of scope.
