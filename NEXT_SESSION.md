# RADIOROC 42 — Priority 0's real remaining question: single-shot coincidence anomaly, then Priority 2/3

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else**, then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s
RADIOROC 39 entries (search "RADIOROC 39" — there are five, all near the
top of the file, read them in order — the most recent one, "Case (c)
attempted with real external single-shot triggering," is the one this
handoff continues directly from and is not fully summarized below). Older
status entries may be superseded; verify current source before treating a
historical gap as live. The standing per-action hardware-authorization
rule applies as always: a grant given in one conversation is for that
conversation only.

Continuing on `feat/daq-results-gui`. Working tree clean once this handoff
is committed.

## Where Priority 0 actually stands

Not a firmware limitation anymore, and not fully closed either — read
this carefully, it's more specific than earlier handoffs assumed:

- **The register/mask fix is solidly demonstrated** under continuous,
  repeated real-signal conditions: accept/reject/exclusion/per-channel
  association all held up correctly across 20+ real events, reproduced
  multiple times.
- **External single-shot triggering is now achievable** — the earlier
  "BST* commands unsupported over SCPI" finding was real but a red
  herring: the operator configured burst mode on the generator's **front
  panel**, not remotely. Confirmed genuinely gated (zero acquisitions
  while idle) and confirmed exactly one scope acquisition per one fired
  synchro trigger, clean pulse shape (~52 mV, ~100 ns, matching the
  continuous-mode calibration point after the operator corrected the
  amplitude for a fan-in/fan-out module's insertion loss).
- **A new, reproducible, unexplained anomaly showed up specifically in
  single-shot mode.** The *identical* configuration that passed
  repeatedly under continuous signal conditions gave backwards results
  under single-shot conditions: a trivial positive control (both channels
  hit simultaneously by one pulse) was rejected, and the genuine "outside
  the window" case (two channels ~150 ms apart) was accepted — the
  opposite of what both should do. Three specific causes were tested and
  ruled out (a stale ready flag, hold/conversion timing, a bug in this
  session's own test-script arming logic — see the full entry for exactly
  how each was ruled out). **Not resolved.** Stopped deliberately rather
  than force a conclusion, given deadline pressure, with the operator's
  agreement.

## This session's job

### 1. Investigate the single-shot anomaly

One specific, undeveloped hypothesis from the prior entry, worth testing
first: continuous mode gives the trigger logic thousands of chances per
test, so a per-attempt reliability problem could hide behind that
repetition. Concretely:

- Repeat the single-shot positive control (Ctest on both channels, one
  external trigger) **many times** (e.g. 20-50 separate single-shot
  attempts) and check whether it accepts *some fraction of the time*
  rather than never — a nonzero but imperfect accept rate would point at
  a timing/reliability race, not a logic bug, and would also explain why
  case (c) seemed to "accept" (same intermittent phenomenon, wrong
  case).
- Check whether the FPGA's ready flag (word 4 bit 5) is a level that
  stays high until read, or something more transient that a 10 ms polling
  interval could miss — worth checking the vendor's `adc.pyc`
  disassembly again specifically for this, or bench-testing with a
  tighter poll interval.
- Consider whether the *previous* session's continuous-mode success
  might have been masking this the whole time — i.e. whether continuous
  mode's "10/10 events" success was actually closer to "10 accepted out
  of many more attempts than 10," which the batch-count-based
  `acquire_adc_batch` API wouldn't surface either way.

### 2. Once resolved (or if it resolves quickly): case (c)

Re-run channel-4-then-channel-6-~150ms-apart and confirm rejection, now
that the mechanism is understood. If the anomaly turns out to be a
genuine hardware/timing limitation of single-shot triggering rather than
a fixable software issue, that itself is a legitimate, documentable
answer for Priority 0 — but only after the "many attempts" check above,
not before.

### 3. If Priority 0 is closed (or the operator decides to move on
regardless): Priority 2/3

Both remain **not started at all**:

- **Priority 2 (calibration procedure)**: pedestals/noise per channel,
  dead/noisy/saturated identification, relative gain characterization,
  threshold alignment, hold/conversion timing suitable for the trigger
  setup, saved/attributable calibration. This session's threshold scan
  (DAC 550 for a ~50 mV Ctest-injected signal) and hold scan (peak at
  ~530-550 ns) were done to unblock the coincidence test, not as
  calibration deliverables — don't treat them as more settled than that.
- **Priority 3 (provenance/trustworthiness)**: re-check (don't assume)
  event ID uniqueness across appended segments, host-receipt vs.
  physical-event timestamp distinction, retaining below-threshold
  amplitudes (already observed working in this session's bench data for
  the uninvolved channel in an accepted event — worth citing once
  reviewed properly), no irreversible cuts in saved data.
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
this session found IO1's FPGA mux index had silently drifted to `0` (not
`5`) since earlier in the *same* day — check `read_fpga_io_mux()` rather
than assuming a previously-set mux index, sync routing, or generator mode
is still in effect. When something that worked before doesn't, prefer
systematically ruling out specific hypotheses (as this session did) over
guessing at alternate syntax or settings repeatedly.

Multiple Claude Code sessions share this working directory (confirmed via
peer messaging this session — several were active on this same repo,
some on a different branch as recently as the same day). Confirm no
other session is mid-hardware-action before touching the board or bench
instruments.

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
