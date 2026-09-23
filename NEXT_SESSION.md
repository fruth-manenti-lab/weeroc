# RADIOROC 44 — Finish Priority 2 (Steps 3/5/6), then the Priority 4 rehearsal

**Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else**, then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s
RADIOROC 39 entries (search "RADIOROC 39" — there are eight, all near the
top of the file, read them in order — the most recent one, "Priority 2
rehearsal: operator ran the calibration procedure through the GUI," is the
one this handoff continues directly from). Older status entries may be
superseded; verify current source before treating a historical gap as
live. The standing per-action hardware-authorization rule applies as
always: a grant given in one conversation is for that conversation only.

Continuing on `feat/daq-results-gui`. Working tree clean once this
handoff is committed.

## Equipment state at handoff — check before assuming

- **SiPM bias**: PSU channel 3, 29.5 V, 10 mA current limit — **left ON**.
  Verify it's still on and at spec before relying on it; don't assume.
- **Signal generator**: mode left as **burst/single-shot external-
  triggering** (front-panel configured, not SCPI-controllable on this
  unit — see the RADIOROC 39 entry on the BST* SCPI limitation),
  **output OFF**. Deliberate choice: this mode was hard-won this session;
  switching to continuous free-run (`PULSFREQ 10000` + `OUTPUT ON`, one
  command) is trivial to redo if this session wants threshold/gain scans
  instead of coincidence-timing work.
- **RADIOROC board**: disconnected cleanly.
- **IO1 FPGA mux index**: was found drifted to `0` (not `5`, needed for
  the synchro-trigger signal) partway through RADIOROC 39 — check
  `read_fpga_io_mux()` rather than assume it's still `5`.

## Where things stand: `docs/plint_calibration_procedure.md`

Steps 1, 2, and 4 were run for real this session (operator driving the
GUI directly, as a genuine Priority 4 rehearsal data point, not just a
Priority 2 exercise) and independently verified from saved run data, not
just on-screen summaries:

- **Step 1** (pedestal/noise/dead-channel ID): done. Clean floor ~DAC
  460-480 on channels 4/6/32, none excluded.
- **Step 2** (threshold alignment): done. Channels aligned to within
  ~2-4 DAC codes (~176-180).
- **Step 4** (relative gain): done, after working through two real
  mistakes live (generator left in gated single-shot mode gave a false
  "no signal" result; a truncated 0-250 DAC rescan looked wrong for a
  different reason — still inside the noise peak, nowhere near the
  informative high-DAC region). Final result: channels 4/6/32 show
  closely matching ~10-11 kHz plateaus, no gain outlier.
- **Step 3** (pick an operating threshold): not finalized. DAC 550-600
  was suggested (comfortably above Step 1's ~460-480 floor) but not
  agreed as a final number.
- **Step 5** (hold/conversion timing): not re-run through
  `HoldScanWindow` this session specifically — the earlier same-day CLI
  hold-scan result (peak ~530-550 ns, channel 4, Simple trigger) stands
  as evidence but wasn't rehearsed through the GUI the way Steps 1/2/4
  were. Worth doing for rehearsal completeness.
- **Step 6** (saved calibration record): still just the manual
  record-keeping checklist in the procedure doc — no dedicated artifact
  exists yet. Worth building now that Steps 1/2/4 have real data to put
  in one: channels 4/6/32, DAC alignment ~178, threshold TBD (Step 3),
  gain characterization (all consistent), hold delay ~530-550ns.

Two real GUI bugs were found live during this rehearsal and already
fixed/committed: `ThresholdWindow` now renders a proper staircase
(matching the CLI tool and the project's own established convention) and
has a "Log Y" toggle (without it, Step 4's actual signal plateau was
visually indistinguishable from zero on a linear axis — this is exactly
what caused the "does this look right?" back-and-forth this session,
resolved by reading the raw CSV values directly rather than trusting the
plot's appearance alone).

## This session's job

1. **Finalize Step 3**: agree an actual operating threshold DAC with the
   operator (550-600 was suggested, not finalized) and record the
   reasoning.
2. **Run Step 5 through `HoldScanWindow`** for rehearsal completeness,
   using the trigger configuration Priority 0 actually settled on.
3. **Build Step 6's saved-calibration-record artifact** — even a minimal
   one (a JSON file referencing the completed sub-scans' output
   directories plus the chosen threshold/gain/hold values, saved
   alongside subsequent acquisition runs) would close a real, named gap
   rather than leaving it as a manual checklist indefinitely. Keep it
   bounded — a record, not a new subsystem.
4. **Then move toward the actual Priority 4 rehearsal**: a complete
   calibration → acquisition → stop → reopen/export pass, with the
   operator continuing to stand in for the student per their own
   decision to do so. Case (c) (Priority 0's remaining item) was
   explicitly skipped by the operator's own decision to keep moving
   toward the MVP deadline — don't reopen it without them raising it.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action — a grant
from an earlier conversation does not carry over. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` after every meaningful change (~3 minutes;
background it and poll rather than assuming a short timeout means
failure). A self-created venv without the `[gui]` extra will silently
skip every GUI test and look green when it isn't (RADIOROC 36).

**When a live result looks wrong, verify against raw data before
concluding anything** — this session's own back-and-forth (generator
gated, truncated DAC range, "is the floor really zero") was resolved every
time by reading the actual saved CSV/manifest rather than trusting a
summary or a plot's appearance, including once when the operator's own
sharp instinct ("the floor is really 0 no?") turned out to be a
reasonable question worth actually checking (it wasn't zero — real,
varying, Poisson-consistent counts) rather than dismissing it.

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
permanently out of scope. Priority 0's case (c) is deferred by the
operator's own explicit decision this session, not resolved — see above.
