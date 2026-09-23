# RADIOROC 41 — Priority 0's last case, then move to Priority 2/3

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else** (still
this week's priority document), then `AGENTS.md`, then this file in full,
then `IMPLEMENTATION_STATUS.md`'s RADIOROC 39 entries (search "RADIOROC 39"
— there are four, all near the top of the file, read them in order — the
most recent one, "Priority 0's physical bench demonstration," is the one
this handoff continues directly from). Older status entries may be
superseded; verify current source before treating a historical gap as
live. The standing per-action hardware-authorization rule applies as
always: a grant given in one conversation is for that conversation only.
Coordinate any bench work through the operator directly.

Continuing on `feat/daq-results-gui`. Working tree clean once this handoff
is committed.

## Priority 0 is now physically demonstrated, except for one case

RADIOROC 39 closed the register-level bug (T2 coincidence slot hardcoded,
no second channel), the channel-mask gap, added GUI controls, and then —
with three SiPMs mounted on channels 4/6/32, an Aim-TTi TGF4162 signal
generator, and a Tektronix MSO56B oscilloscope already on the bench — ran
the actual bounded 5-case bench test from the directive. Read the full
entry for the complete evidence trail; in short:

- **Cases (a), (a)-mirrored, (b), (d)-and-variants, (b)-repeated: all
  passed.** A single channel firing repeatedly is correctly rejected; only
  the genuine configured pair (ch4 AND ch6) is accepted; an excluded
  channel (ch32) paired with either real channel still correctly rejects;
  per-channel amplitude association (including the uninvolved channel's
  retained below-threshold value) held up across 20 repeated real events.
- **Case (c), "two channels outside the coincidence window," is not yet
  testable with this bench setup.** Ctest is a single shared injection
  line (one SMA input) — reliably offsetting one channel's pulse from the
  other by a known, controlled amount needs either a second independent
  timed pulse path, or the generator's external single-shot burst
  triggering. The latter turned out to be unsupported over SCPI on this
  specific TGF4162 unit's firmware (`01.05-02.10-01.20)` — every `BST*`
  command, even read-only queries, returns error `-111` ("Unsupported
  remote command"), confirmed not a syntax issue. This contradicts the
  "known-good" external-triggered burst setup documented in earlier
  sessions (RADIOROC 15/16/22/23), which either used a different physical
  unit/firmware or a mechanism this session didn't find.

## This session's job

### 1. Resolve external single-shot triggering on this TGF4162 unit

`CLKSRC` is confirmed supported on this firmware (`CLKSRC?` returned
`INT` without error, unlike any `BST*` command). Try `CLKSRC EXT` as a
possible alternate mechanism for gating the generator's output on the
FPGA's synchro-trigger line, since burst-mode commands aren't available.
If that doesn't pan out, ask the operator directly whether the earlier
"known-good" burst setup was documented from a different bench/unit —
their answer resolves this faster than more blind SCPI probing. The
Aim-TTi TGF4000 Series manual (Issue 3) is saved for reference; fetch
fresh via `WebFetch`/`curl` from
`https://resources.aimtti.com/manuals/TGF4000_Series_Instruction_Manual-Iss3.pdf`
if needed again — `pdftotext -layout` converts it for grep-able command
lookup (the "Command list" section starting around printed page 162 has
the exact syntax table). Do the same for the Tektronix MSO if it comes up
again: `https://download.tek.com/manual/4-5-6-MSO-6-LPD-Programmer-Manual-077130511.pdf`.

### 2. Design and run case (c)

Once single-shot/independently-timed triggering is available: pulse ch4
alone, then ch6 alone, with a known, controlled gap clearly longer than
the configured `adc_window_ns` (50 ns default) — confirm rejection. If a
genuinely independent second pulse path can't be found this session,
document that plainly as a hardware-setup limitation (per the directive:
"do not assume the apparatus can generate every needed pattern") rather
than forcing a weak substitute or further blind SCPI guessing.

### 3. Re-run cases (a)/(b)/(d) through the full CLI path

RADIOROC 39's bench test used `RadiorocDevice` primitives directly (a
deliberate, disclosed scope choice for speed while working solo) — not
`AcquisitionJob`/`radioroc_acquire.py`, even though that CLI now has the
needed `--adc-trigger-source-2`/`--trigger-channel-2` flags (added this
session). Re-running the same cases through the real CLI gives a saved,
restoration-verified, reviewable CSV/metadata artifact instead of only
interactive script output — cheap belt-and-suspenders now that the
interactive version already passed.

### 4. If Priority 0 is now fully closed, move to Priority 2/3

Both are **not started at all**:

- **Priority 2 (calibration procedure)**: pedestals/noise per channel,
  dead/noisy/saturated identification, relative gain characterization,
  threshold alignment (the fresh DAC-550 threshold scan from RADIOROC 39
  is a start, not the whole procedure — it was done to unblock the
  coincidence test, not as a calibration deliverable), hold/conversion
  timing suitable for the now-settled 2-channel-coincidence trigger,
  saved/attributable calibration. One thing this session's own bench data
  raises: the accepted-event HG values for ch4/ch6 (~75-79, ~67-71) came
  out *lower* than ch32's untriggered baseline (~106-109) — worth checking
  during Priority 2 whether the arbitrary `hold_delay_ns=530`/
  `conversion_delay_ns=400` used for the bench test is actually sampling
  the injected pulse's shaper response at a sensible point, via a proper
  hold scan, rather than assuming those values were right.
- **Priority 3 (provenance/trustworthiness)**: re-check (don't assume)
  that the current CSV/manifest schema satisfies event ID uniqueness
  across appended segments, host-receipt vs. physical-event timestamp
  distinction, retaining below-threshold amplitudes (RADIOROC 39's bench
  data already shows this working for ch32 in an accepted event — worth
  citing as evidence once this is reviewed properly), and no irreversible
  cuts in saved data.
- **Priority 1 leftover**: an individual-event amplitude view distinct
  from the histogram — not built yet.

Priority 4 (stabilization + student rehearsal) remains the final gate,
not a starting point.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action — a grant
from an earlier conversation does not carry over. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` after every meaningful change — wrap it in a hard
`timeout` and confirm the process itself exits (it takes ~3 minutes).
A self-created venv without the `[gui]` extra will silently skip every
GUI test and look green when it isn't (RADIOROC 36). Delegate bounded,
well-specified implementation/test work to subagents per `AGENTS.md`; keep
shared contracts, uncertain hardware/register reasoning, and integration
for the lead. When delegating, review the actual diff line-by-line before
merging and go beyond the delegated agent's own test count with a real
check of your own.

When identifying which physical device a serial/USB path corresponds to,
prefer read-only OS metadata (`udevadm info -q property -n <device>`) over
guessing from context or sending protocol bytes speculatively — this
session used it to safely confirm the RADIOROC board vs. the signal
generator before touching either. When an instrument's remote command
behavior doesn't match documentation, verify against the actual fetched
manual and test systematically (e.g., confirm a failure is firmware-level
via a read-only query, not just a write) rather than guessing alternate
syntax repeatedly.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`; given Priority 0's software and (nearly) full
physical validation are both now done, raise the PR-then-branch timing
question with the operator rather than deciding alone — this may be a
natural checkpoint.

`gh` is installed and authenticated — use it (`gh run list --branch
<branch>`, `gh run view <id>`, `gh run view --log-failed`) to check CI
status directly after any push. Watch for the occasional stale/transient
`gh run list` result — re-list with a larger `--limit` if the top row looks
implausible.

**Before pushing anything**: actually reproduce CI's *environment*, not
just its commands. `.conda-radioroc` or any other long-lived dev
environment with every extra already installed cannot catch a
missing-extra-only failure.

Per the directive's own instruction: track each MVP item as implemented,
offline-verified, physically verified, or blocked, with concrete evidence
and the next action. Separate software completion from equipment/operator
dependencies. Record actual checks and remaining limitations in a fresh
`IMPLEMENTATION_STATUS.md` entry and `NEXT_SESSION.md`, retaining the
session-numbering convention.

## Deferred, not dropped

Broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release work remain
explicitly deferred by the directive until after this checkpoint. None of
F01–F17/M0–M5 are deleted by this reprioritization. F15/A7585 remains
permanently out of scope.
