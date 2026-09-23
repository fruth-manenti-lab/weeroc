# Plint student MVP — delivery priorities for this week

Date: 23 September 2026. Audience: Claude and any delegated development workers.

## Mandate and relationship to the existing plan

The operator's immediate goal is an app a student can use for experiments in
the lab without substantial bugs. Prioritize that outcome this week; broader
development and polishing can continue next week. This is a narrower delivery
checkpoint within `CROSS_PLATFORM_REBUILD_PLAN.md`, not a replacement plan or
permission to weaken its architecture, scientific-data requirements, or final
acceptance gates. Do not claim M4/M5, full Windows parity, or general release
readiness merely because this MVP passes.

Read `AGENTS.md`, the latest entries in `IMPLEMENTATION_STATUS.md`, and
`NEXT_SESSION.md` before acting. Older status entries and the plan's introductory
implementation summary may be superseded. Verify current source before treating
a historical gap as live. Preserve the current branch, active worktrees, user
changes, local vendor artifacts, and all measured data.

This document was requested during a separate read-only review of ongoing work.
It does not authorize hardware actions, launching or closing another session's
apps, or interfering with an active operator. Coordinate bench work through the
existing designated-operator process and the plan's equipment-specific test cards.

## Experiment and intended student workflow

Confirmed by the operator:

- One plastic scintillator, called the **plint**, with 4–8 SiPMs mounted directly
  on its surface.
- Students need to calibrate the channels, then collect data.
- The provisional trigger is **any two selected channels above threshold**.
- Each accepted event must retain the signal amplitudes on all selected SiPMs
  for later hit-position reconstruction and rate analysis.
- Students expect to collect initial data and investigate gamma backgrounds
  versus muon signals. The threshold, coincidence window, and particle-selection
  cuts have not been settled.

Target workflow: connect → identify/configure selected channels → calibrate and
inspect quality → save calibration/settings → configure coincidence → collect
and inspect events → stop → reopen/export data for analysis.

Do not hardcode an assumed threshold or coincidence window. Do not invent bias
settings, detector dimensions, operating voltages, or a position-calibration model.
Confirm equipment and student-machine details when they become prerequisites;
continue independent offline work while waiting.

Two SiPMs seeing the same plint light pulse does not establish that the event
was a muon. Label initial outputs as accepted events and accepted-event rate.
Muon classification, calibrated position reconstruction, and physical flux need
separate evidence. Preserve the data needed to develop those analyses; a finished
classifier or reconstruction GUI is not a prerequisite for this week's MVP.

## Priority 0 — Resolve the experiment's critical hardware uncertainty early

Audit F11/F12 against this specific trigger and readout requirement before assuming
the existing acquisition configuration satisfies it. This investigation should
proceed alongside completion of the current F13 plotting slice, without duplicate
editors or conflicting changes to shared contracts.

Use the local vendor evidence first: saved disassembly, genuine CPython 3.13
bytecode, guide, and screenshots. Establish what the current firmware and vendor
application actually support. Record evidence for register meanings and limits.

The required semantics are **two distinct selected channels within a defined
coincidence window**, followed by acquisition of all selected channels for that
event. A setting described as “N triggers in a window” is not automatically
equivalent: determine whether repeated pulses on one channel can satisfy it.
Likewise, do not infer event association from matching array lengths alone.

Prepare a bounded operator test covering:

1. One selected channel pulsing alone; repeated pulses on that same channel.
2. Two distinct selected channels inside the window.
3. Two channels outside the window, with timing margin appropriate to the hardware.
4. An excluded channel, and representative pairs across the selected channel set.
5. Known distinguishable amplitudes on multiple channels, verifying event/channel
   association and acquisition of channels that did not cross threshold.

Specify expected acceptance/rejection and timing tolerances before measuring.
Use suitable controlled inputs; do not interpret uncontrolled dark activity as
proof of coincidence semantics. Check the capture/hold timing as well as the
trigger decision. Do not assume the apparatus can generate every needed pattern.

If the board cannot implement the requested multiplicity, surface the limitation
promptly with evidence. Propose concrete alternatives for the operator to choose
from, such as supported trigger logic or external coincidence equipment. Offline
cuts after a looser trigger are a different acquisition scheme, with rate/dead-time
implications; do not silently substitute them or fabricate per-channel timing.

Acceptance: a documented supported trigger/readout contract plus a controlled
physical demonstration. Simulated behavior alone cannot close this item.

## Priority 1 — Complete the acquisition slice already in progress

Build on `AcquisitionJob`, existing readers, the shared connection worker, and
`AcquisitionWindow`. Complete and review the active work before starting another
implementation of the same functionality.

For the student, prioritize channel-labelled HG/LG spectra, an individual-event
amplitude view, practical channel selection and plot controls, responsive progress
and cancellation, and saved-run reopening/export. Reuse existing plotting patterns.
Vendor-file reading is useful comparison infrastructure already in scope; do not
invent a vendor writer without an evidenced requirement.

Bound plotting work and memory use so data capture does not depend on rendering
every event. Displayed counts must distinguish physical events from channel rows.
Preserve the raw/scaled encoding and units requirements of M2; check current
storage explicitly rather than assuming the existing CSV closes every requirement.

Acceptance: known synthetic/recorded vectors produce the expected channel spectra
and event values; saved and reopened values match; cancellation leaves readable
partial data; a real visual check confirms the screen is usable.

## Priority 2 — Make calibration an end-to-end student procedure

Reuse F02–F10 and existing calibration/scan jobs. Threshold autocalibration is
one part of calibration, not proof of a fully calibrated detector.

Define the procedure and evidence needed for:

- Pedestals and noise for every selected channel, including dead/noisy/saturated
  channel identification.
- Relative SiPM response/gain characterization using the available supported
  measurement method; retain HG/LG identification and useful dynamic range.
- Threshold alignment and a documented operating threshold choice.
- Hold/conversion timing suitable for this actual signal and trigger setup.
- A saved, attributable calibration/configuration that accompanies subsequent runs.

Do not invent automatic gain or bias equalization where hardware support or
measurement evidence is missing. A documented, reliable manual step is acceptable
for this MVP if the student can perform it and the resulting settings are recorded.
Have the operator agree measurable calibration quality criteria before acceptance.

Investigate existing gaps according to dependency: T1/T2/TQ enable-bit uncertainty
and missing probe/mask readback are blockers if the chosen workflow needs them.
Do not guess register writes to meet the deadline. If a verified fixed setting
avoids a gap, document that supported configuration and restrict unsupported paths.

Acceptance: all channels used in the experiment have reviewed calibration results
and saved settings; the student can repeat the procedure without developer code edits.

## Priority 3 — Preserve trustworthy events and rate information

For each run, retain selected hardware-channel IDs and their sensor-position mapping,
event association, per-channel amplitudes and units/encoding, trigger configuration,
calibration references/settings, board/firmware identity when obtainable, start/end
time, completion status, and errors or loss indicators actually available.

Use event identifiers unique within the run, including appended segments. Preserve
the plan's append compatibility and provenance requirements; do not lose prior
segment configuration by overwriting its only metadata. Keep legacy readers/CLI
entry points working, or provide an explicit compatible schema evolution.

Distinguish host receipt/batch timestamps from physical event timestamps. Do not
claim a timing precision, live-time measurement, or loss counter the hardware does
not supply. Counts divided by wall time may be shown as an observed accepted-event
rate with its limitations; do not label it dead-time-corrected rate or muon flux.

Retain all selected channels for accepted events, including below-threshold values.
Avoid irreversible particle-selection cuts in the saved acquisition data. Thresholds
already affect acceptance, so store them for later bias/efficiency analysis.

Acceptance: an exported/reopened run has enough provenance to reproduce the displayed
counts and amplitude plots, identify its calibration, and explain its timing limits.

## Priority 4 — Stabilize and perform the student acceptance rehearsal

After the required workflow is present, prioritize defect fixes and bench evidence
over extra controls. A substantial MVP bug includes incorrect trigger semantics,
channel/event mixups, silent loss/corruption, misleading calibration state, a frozen
UI that prevents stopping, or unsafe/unverified cleanup presented as successful.

Run the required development checks in an environment with GUI dependencies;
report skips explicitly. Verify the installed wheel after packaging changes.
Do not mistake the existing CI's threshold-only GUI test invocation for coverage
of every GUI workflow. Add focused regression tests for actual behavioral risks.
Keep hardware enumeration and scans out of offline checks.

Exercise cancellation, storage failure, connection loss, and cleanup failures with
fake transports/offline tests. Physically exercise the approved relevant paths
through the designated operator. Unresolved device-state faults must remain visible
and block inappropriate further runs, following the established shared-worker model.

On the actual student machine, conduct one complete calibration → acquisition →
stop → reopen/export rehearsal with the student and a short written guide. Then
perform the plan's at-least-one-hour representative acquisition with live plots
and saved data, checking memory responsiveness, persisted counts, and available
loss/duplication evidence. If the hardware cannot independently establish loss,
record that limitation rather than declaring zero loss.

Acceptance: the student completes the supported workflow without developer
intervention; no known substantial defect remains in that path; the operator
reviews the resulting data and recorded limitations. Passing this gate is a
**plint lab MVP**, not completion of the full rebuild.

## Deferred priorities, retained scope

Defer broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release artifacts until after
this checkpoint. Targeted Windows comparisons needed to resolve the experiment's
hardware semantics remain high priority. Installation and operation on the student's
actual machine are required now, even if that exposes platform-specific work.

These deferrals do not delete F01–F17 or M0–M5 requirements. F15/A7585 remains
explicitly out of scope under the existing operator decision. Position reconstruction,
gamma/muon discrimination, and efficiency-corrected flux analysis remain downstream
experimental work, with saved data supporting their development.

## Execution and reporting

Keep device logic in the shared core and maintain CLI/UI behavior parity. Delegate
bounded offline implementation/test tasks under the existing worktree/file-ownership
rules; the lead owns protocol uncertainty, shared contracts, review, and integration.
Do not start a broad rewrite for this deadline.

Track each MVP item as implemented, offline-verified, physically verified, or blocked,
with concrete evidence and the next action. Separate software completion from
equipment/operator dependencies. Reassess this week's feasibility immediately after
the coincidence/readout investigation; do not promise delivery from a test count or
code-volume estimate.

At the owning session's next normal checkpoint, reference this directive from
`IMPLEMENTATION_STATUS.md` and `NEXT_SESSION.md`, retaining their session-numbering
convention. Those shared files were intentionally left untouched by the author of
this directive to avoid conflicting with Claude's active work. Record actual checks,
remaining limitations, and the next bounded task rather than copying aspirational
acceptance claims into the status log.
