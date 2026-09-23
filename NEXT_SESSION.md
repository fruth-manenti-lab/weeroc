# RADIOROC 43 — Design a valid case (c) test, then Priority 2/3

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else**, then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s
RADIOROC 39 entries (search "RADIOROC 39" — there are six, all near the
top of the file, read them in order — the most recent one, "SiPMs biased
for the first time...", is the one this handoff continues directly from
and corrects an alarm raised earlier the same day; read that whole entry,
not just this summary). Older status entries may be superseded; verify
current source before treating a historical gap as live. The standing
per-action hardware-authorization rule applies as always: a grant given
in one conversation is for that conversation only.

Continuing on `feat/daq-results-gui`. Working tree clean once this
handoff is committed.

## Where Priority 0 actually stands — read this carefully, it's nuanced

- **The register/mask fix (cases a/b/d) is solidly demonstrated** under
  continuous, repeated real-signal conditions, reproduced multiple times.
  This remains the operative evidence and is unaffected by anything below.
- **SiPMs are now biased** (PSU channel 3, 29.5 V, 10 mA current limit,
  confirmed ~20x headroom above the ~0.5 mA steady-state draw) — the
  first time this project has exercised real SiPM light response rather
  than Ctest's direct-injection bypass. **Left ON at handoff.**
- **Case (c) ("outside the coincidence window") is still not validly
  tested — not failed, not passed.** A same-day debugging session found
  and then *fully explained* a false-accept pattern: it traced to
  switching which channel has Ctest enabled between two pulses (this
  bench's only way to simulate "channel B fires later" with one shared
  injection line) — the switch itself is a real electrical transient on
  the ASIC that looks like a threshold crossing to the newly-enabled
  channel, independent of any genuine timing question. This was proven
  directly: firing channel 4's pulse, then switching Ctest to channel 6
  **without ever firing a second pulse**, still produced a false accept.
  Every case-(c)-shaped result from today (including an earlier, wrong,
  mid-session conclusion that no real time window is enforced at all) is
  explained by this artifact and should be disregarded as evidence either
  way, not treated as a real hardware finding.

## This session's job

### 1. Design a case (c) test that doesn't share this confound

The core problem: this bench has one shared Ctest injection line, so
"channel 4 fires, then channel 6 fires later" can currently only be
simulated by switching which channel has Ctest enabled — and that switch
is itself a false signal. Two real options, not attempted yet:

- **A genuinely independent second injection path** — not a channel
  switch on the shared line, an actual second, separately controllable
  source. Ask the operator whether this bench can provide one (a second
  pulser channel, a delay generator, two LEDs independently triggered —
  anything that puts a real, controllable-relative-timing signal on
  channel 6 without touching channel 4's Ctest configuration at all).
- **Real, uncorrelated SiPM dark counts as the timing source**, now that
  biasing makes them genuinely available. Set threshold above the real
  noise floor (this session found DAC 550 was *not* clear of it once
  biased — DAC 800 was; re-verify, since the environment may have
  changed), enable both channels' native trigger paths with no Ctest
  involved at all, and observe over a long enough window to characterize
  the real accidental-coincidence rate statistically. This is a genuine
  design task (observation duration, what "no coincidence" would mean
  given a nonzero accidental rate, whether the 50 ns window is even the
  right thing to check this way) — not a quick follow-up script.

Do not reach for channel-switching again as a shortcut; it's now a known,
proven-confounded technique for this specific test.

### 2. If Priority 0 is closed (or the operator decides to move on
regardless): Priority 2/3

Both remain **not started at all**:

- **Priority 2 (calibration procedure)**: pedestals/noise per channel,
  dead/noisy/saturated identification, relative gain characterization,
  threshold alignment, hold/conversion timing suitable for the trigger
  setup, saved/attributable calibration. With SiPMs now biased, a real
  dark-noise threshold scan is finally possible and relevant groundwork —
  this session's own scan (DAC 550 sits inside the real dark-noise tail;
  DAC 800 is clear) was done to unblock debugging, not as a calibration
  deliverable; don't treat it as more settled than that.
- **Priority 3 (provenance/trustworthiness)**: re-check (don't assume)
  event ID uniqueness across appended segments, host-receipt vs.
  physical-event timestamp distinction, retaining below-threshold
  amplitudes (already observed working in earlier bench data for the
  uninvolved channel in a genuinely accepted event), no irreversible cuts
  in saved data.
- **Priority 1 leftover**: an individual-event amplitude view distinct
  from the histogram — not built yet.

Priority 4 remains the final gate, not a starting point.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action — a grant
from an earlier conversation does not carry over. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` after every meaningful change (~3 minutes;
background it and poll rather than assuming a short timeout means
failure). A self-created venv without the `[gui]` extra will silently
skip every GUI test and look green when it isn't (RADIOROC 36). Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register
reasoning, and integration for the lead.

**Before assuming any bench state carried over from a prior session**:
this same day, IO1's FPGA mux index had silently drifted to `0` (not `5`)
between the morning's continuous-mode work and the afternoon's single-shot
work — check `read_fpga_io_mux()` rather than assuming a previously-set
mux index is still in effect. **SiPM bias is currently ON (PSU CH3, 29.5V)
— check its actual state rather than assuming either way; do not power it
off without checking whether it's still needed.**

When a result contradicts strong prior evidence (like this session's
"positive control now fails" and later "no time window enforced"
moments), treat that contradiction itself as a signal to find the
confound in the *new* test before trusting it over the old evidence — this
session did that correctly both times (SiPM bias explained the first
contradiction, the Ctest-switch artifact explained the second) rather
than either dismissing the anomaly or overwriting solid earlier evidence
with an unexplained new result.

Multiple Claude Code sessions share this working directory (confirmed via
peer messaging in an earlier RADIOROC 39 entry). Confirm no other session
is mid-hardware-action before touching the board or bench instruments.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`. `gh` is installed and authenticated for CI
checks after any push (`gh run list --branch <branch>`).

Per the directive's own instruction: track each MVP item as implemented,
offline-verified, physically verified, or blocked, with concrete evidence
and the next action. Record actual checks and remaining limitations in a
fresh `IMPLEMENTATION_STATUS.md` entry and `NEXT_SESSION.md`, retaining
the session-numbering convention.

## Deferred, not dropped

Broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release work remain
explicitly deferred by the directive until after this checkpoint. None of
F01–F17/M0–M5 are deleted by this reprioritization. F15/A7585 remains
permanently out of scope.
