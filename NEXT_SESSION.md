# RADIOROC 40 — Priority 0 continued: pin down "Individual trigger" discriminator level, then close the second-channel mask gap

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else** (still
this week's priority document, not summarized completely below), then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s
RADIOROC 39 entry (search "RADIOROC 39" — near the top of the file). Older
status entries may be superseded; verify current source before treating a
historical gap as live. The standing per-action hardware-authorization rule
applies as always: a grant given in one conversation is for that
conversation only. Coordinate any bench work through the operator directly.

Continuing on `feat/daq-results-gui`. Working tree clean once this handoff
is committed, other than whatever the still-running legend-fix delegation
(see below) leaves staged.

## What RADIOROC 39 did

Investigated Priority 0's core question with hard evidence, not
assumption: does `radioroc_client.py`'s existing `trigger_type`/
`trigger_source` implement genuine two-*distinct*-channel coincidence, or
could one repeatedly-firing channel also satisfy it?

**Found and fixed a real, confirmed bug, not just an ambiguity.** Recovered
the exact FPGA register layout for the ADC DAQ tab's coincidence trigger
from `radioroc2UI.pyc`/`adc.pyc` disassembly (`marshal.loads` + `dis.dis`,
per `AGENTS.md`) cross-checked against the vendor PDF guide's section 3.3.
The vendor app has **two independent coincidence-input slots** (T1 and T2,
each with its own mode combo — NORT1/NORT2/NORTQ/Individual channel/OR64 —
and its own channel-number field), not the single shared `trigger_source`
field `radioroc_client.py` exposed. `configure_adc_external_hold` had T2's
slot **hardcoded** to NORT1 (an OR of every unmasked channel), with no way
to name a second channel at all — meaning every prior `trigger_type=1`
("2 channels coincidence") configuration actually built "channel A AND an
OR of whatever's unmasked," not "channel A AND channel B." Fixed by adding
`trigger_source_2`/`trigger_channel_2` to `configure_adc_external_hold`,
`AcquisitionConfig`, and `HoldScanConfig`, writing FPGA words 23/30 exactly
as the vendor app does, with a new regression test
(`test_adc_two_channel_coincidence_bit_positions` in
`tests/test_radioroc_core.py`) pinning the exact bit positions. Backward
compatible: omitting the new fields reproduces the old (buggy) behavior
bit-for-bit, so nothing existing changed silently. 448/448 offline tests
pass under `.conda-radioroc` (`tools/check_development.py`).

**Read the full RADIOROC 39 entry for the complete evidence trail** — this
summary omits the specific PDF section, `.pyc` function names, and exact
bit offsets recorded there.

## What's still open — this session's job

RADIOROC 39 explicitly left three things unresolved, in dependency order:

### 1. Pin down what discriminator level "Individual trigger" mode uses

The vendor's `comboBox_adcT1`/`comboBox_adcT2` items are NORT1/NORT2/NORTQ
(each explicitly a T1, T2, or TQ *level*) plus a single undifferentiated
"Individual trigger" item — no "Individual T1" vs "Individual T2". So when
a slot is set to "Individual trigger" for a named channel, it's genuinely
unknown from the disassembly gathered so far whether that channel's T1 or
T2 (or TQ) discriminator output is what actually feeds the coincidence
logic, or whether it instead routes through whatever the ASIC's separate,
already-recovered `selTrig`/"Main tab" trigger-selection register (`add=65,
subadd=12`, RADIOROC 30) is currently configured to. This matters because
the fix in (2) below needs to know which per-channel mask bit (`t1=True`
selects the T1 mask bit, `t1=False` selects T2, per `set_mask_for_channel`)
to clear for the second channel — get this wrong and the second channel's
discriminator stays masked out even though the register-level config in
RADIOROC 39 looks correct, silently reproducing the same "coincidence that
isn't" bug in a new place.

**Where to look**: more disassembly of `adc.pyc`/`radioroc2UI.pyc` around
whatever function actually reads `comboBox_adcT1`/`comboBox_adcT2`'s
"Individual trigger" selection and drives the ASIC/FPGA trigger mux — the
functions already checked (`get_acq_setup`, `start_adc`) don't show this
because they only build the register words, not the ASIC-side mux/selTrig
interaction. Also check `generated_notes/*.txt` for anything from a prior
session that might already cover FPGA trigger-mux logic before
re-disassembling from scratch. If disassembly genuinely can't resolve it,
the fallback is asking the operator to drive the real vendor Windows app
(already installed per `local_artifacts/downloads/setup_Radioroc2UI_2_2_0_5.exe`,
if a Windows machine is available) and observe which selTrig/level setting
"Individual trigger" mode actually respects — do not guess.

### 2. Close the second-channel mask gap, once (1) is answered

`application/acquisition.py` and `application/hold_scan.py` currently call
`device.set_mask_for_channel(trigger_channel, t1=..., enabled=True)` for
only the single `trigger_channel`, never for `trigger_channel_2`. This is
mechanically a one-line addition per file (mirroring the existing call,
conditioned on `trigger_source_2 == 3`) — not blocked by any *register*
uncertainty (RADIOROC 39 corrected an earlier draft's mistaken claim that
this depended on the RADIOROC 30/34 `EN_th1`/`EN_th2`/`EN_thQ` ASIC-wide
enable-bit question at `(65, 7)`; that's a different, unrelated register).
It's blocked purely on knowing which `t1` value to pass for the second
channel, per (1) above.

### 3. Add `AcquisitionWindow` coincidence controls

`src/radioroc/gui/acquisition_window.py` still only ever constructs
`AcquisitionConfig` with `trigger_type=0` ("Simple trigger") — no combo for
trigger type, no per-slot mode/channel fields, no window-width or
`adc_nb_trig` inputs. Once (1) and (2) are settled, this is bounded,
well-specified UI work (mirror the vendor's own ADC DAQ tab layout
recovered in RADIOROC 39: a trigger-type combo, two channel-number +
mode-combo pairs for T1/T2, a window-width field, an N-triggers field) —
a good candidate to delegate to a subagent with the settled contract, per
`AGENTS.md`'s delegation preference. Do not build this against the
still-incomplete backend from (2) — the GUI would just surface the same
gap with a nicer control.

### 4. The physical demonstration itself

Per the directive, "simulated behavior alone cannot close this item." Once
(1)-(3) are done, prepare (do not run without the operator) the bounded
5-case test from `PLINT_STUDENT_MVP_DIRECTIVE.md` Priority 0 using the
now-known-correct recipe: `trigger_type=1`, `trigger_source=3` +
`trigger_channel=A`, `trigger_source_2=3` + `trigger_channel_2=B`, both A
and B unmasked. Specify expected accept/reject outcomes and timing
tolerances before proposing to measure anything, per the directive. This
still needs the designated operator at the bench, per-action authorized,
same as always — not run this session or the last one.

## Already landed this session: the delegated Priority 1 legend/log-scale fix

RADIOROC 38 found and documented (but did not fix) a real, confirmed
usability bug: all four plot windows called `axes.legend(fontsize=8)` with
no `loc=`. RADIOROC 39 delegated the fix to a subagent (bounded to the four
GUI files only), reviewed the diff line-by-line, independently re-rendered
and visually inspected two of the affected windows, and re-ran the full
suite itself rather than trusting the agent's reported count (448/448).
See the "RADIOROC 39 (continued) — Landed the delegated Priority 1
legend/log-scale fix" entry in `IMPLEMENTATION_STATUS.md` for the full
diff summary and verification. Nothing further needed here unless new
issues surface during later visual checks. One follow-on worth a look
before Priority 4's student rehearsal: these windows default to
`resize(1180, 820)`, which may exceed a smaller laptop's usable screen
height — not yet checked against the actual student machine.

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
and integration for the lead — this session's register-layout recovery and
the `configure_adc_external_hold` fix were kept with the lead for exactly
that reason. When delegating to an isolated worktree or a parallel
subagent, review the actual diff line-by-line against the contract before
merging, and go beyond the delegated agent's own test count with at least
one real check of your own.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`; when this branch's scope feels like a complete
stage, the same PR-then-branch pattern from RADIOROC 37 is the model to
repeat — raise the timing with the operator rather than deciding alone.

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
claims into the log — this session's own correction of its first-draft
status entry (see "channel-mask gap" in RADIOROC 39) is the concrete
example to hold the next entry to the same standard.

## Other directive priorities (unchanged from RADIOROC 39's handoff; read the directive for full detail)

- **Priority 1**: mostly landed (channel-labelled HG/LG spectra, channel
  selection/plot controls, responsive progress/cancellation, saved-run
  reopening). Still open: an individual-event amplitude view distinct from
  the histogram; re-checking (not assuming) that the current CSV/manifest
  schema satisfies M2's raw/scaled encoding and units requirements; the
  legend/log-scale bug above.
- **Priority 2**: an end-to-end calibration procedure for the student
  (pedestals/noise per channel, dead/noisy/saturated identification,
  relative gain characterization, threshold alignment, hold/conversion
  timing suitable for the actual trigger setup once Priority 0 fully
  resolves it, saved/attributable calibration). Not started this session
  or last.
- **Priority 3**: run provenance and data-trustworthiness requirements —
  event IDs unique within a run including appended segments, distinguishing
  host-receipt from physical-event timestamps, retaining below-threshold
  amplitudes for all selected channels, no irreversible cuts in saved data.
  Not re-reviewed this session or last.
- **Priority 4**: stabilization and an actual rehearsal with the student on
  the student's machine — the final gate, not a starting point.

Do not treat Priority 1-4 as blocked on Priority 0's full physical
resolution — per the directive, work that doesn't touch
`radioroc_client.py`'s trigger primitives or `AcquisitionConfig`/
`HoldScanConfig` can proceed in parallel, as it did this session with the
legend-fix delegation.
