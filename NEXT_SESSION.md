# RADIOROC 41 — Step 5 hold-scan rehearsal, write the real Step 6 record, then the Priority 4 rehearsal

Read `PLINT_STUDENT_MVP_DIRECTIVE.md` in full before anything else, then
`AGENTS.md`, then this file in full, then `IMPLEMENTATION_STATUS.md`'s three
RADIOROC 40 entries (search "RADIOROC 40" -- one plus two "(continued)"
entries, near the top), which this handoff continues directly from. The
standing per-action hardware-authorization rule applies as always: a grant
given in one conversation is for that conversation only.

Continuing on `feat/daq-results-gui`.

## Where things stand at handoff

RADIOROC 40 was an entirely offline overnight session (operator asleep;
before that, remote via AnyDesk with PSU channels 1/3 and the signal
generator confirmed off, board USB-connected but unpowered -- no hardware
actions taken at any point). It ran as a self-paced autonomous loop
(multiple delegated worker agents, each reviewed and integrated by the
lead before committing) and closed real work across three areas, landed
as three separate commits:

1. **Step 3 (operating threshold) finalized: DAC 575.** Reasoning tied to
   the actual saved Step 1/Step 4 CSVs, recorded in `IMPLEMENTATION_STATUS.md`.
2. **Step 6 (saved calibration record) now has a real artifact**:
   `src/radioroc/data/calibration_record.py` (save/load, schema_version 1),
   `scripts/radioroc_save_calibration_record.py` (CLI), and
   `tests/test_calibration_record.py`. Validates that every referenced
   sub-scan is `completed` and that they all agree on `board_identity`.
   **Not yet run for real** -- no actual `calibration_record.json` exists;
   that needs Step 5 done first (hold delay is one of its fields).
3. **GUI restructure** (direct operator request): `AcquisitionWindow` is
   now its own top-level sidebar page (sidebar: ASIC config. / Acquisition
   / Calibration), not Calibration's fifth sub-tab. Real visual check done
   offscreen, not just tests.
4. **A real, severe bug found and fixed**: `MainWindow` could hang
   forever on close if a hardware job faulted at exactly the moment the
   app was closed (`ConnectionWorker`'s own documented held-shutdown
   contract requires an explicit retry that `closeEvent` never issued).
   Found via a delegated, scope-bounded defect-hunt review; independently
   reproduced, fixed, and reproduced-again-without-the-fix to confirm the
   regression test actually guards it. See the second RADIOROC 40
   "(continued)" entry for the full mechanism.
5. **Priority 3's outstanding timestamp question resolved**: no,
   Threshold/HoldScan/S-curve/Autocalibration manifests do not need the
   same host-receipt timestamp Acquisition got -- they're aggregate
   rate/mean curves, not accepted physical events, and the directive's
   Priority 3 language is specifically about the latter. Checked and
   closed, not left ambiguous.
6. **Closed 5 genuine Priority-4-sanctioned test-coverage gaps** (offline
   cancellation/storage-failure/connection-loss/cleanup-failure exercises
   for `acquisition` and `autocalibration`) and flagged one API
   inconsistency in `AutocalibrationJob`'s manifest-writer error handling
   for the lead's attention (not a live bug, verified both callers already
   turn it into a visible fault -- see the third RADIOROC 40
   "(continued)" entry).
7. **Found and fixed a real, high-severity silent data-loss bug**: a
   second defect-hunt pass (GUI panel/window files) found that
   `AcquisitionConfig.validate()` never required `trigger_channel`/
   `trigger_channel_2` to be among the saved `channels` -- a student
   running 2-channel coincidence whose channel-selection grid didn't
   happen to include both trigger channels (exactly the GUI's own default
   state: `channel_select` defaults to channel 4 alone, `trigger_channel_2`
   defaults to 5) got a hardware-correct trigger but silently lost that
   second channel's amplitude from every accepted event. Fixed with two
   narrowly-scoped, evidence-tied validation checks; regression tests
   added.
8. **Confirmed and fixed the identical bug in `HoldScanConfig`** as a
   direct follow-up (same investigation thread): `application/hold_scan.py`
   has the exact same unconditional-unmask + channels-only-write shape, so
   a hold scan's trigger channel absent from `channels` would never have
   its own response curve recorded -- arguably worse there, since
   characterizing the triggering channel's timing response is the whole
   point of a hold scan. Latent API/CLI-level gap only; `HoldScanWindow`'s
   own GUI defaults were already safe and don't currently expose
   `trigger_channel_2` at all.

461/461 offline tests pass under `.conda-radioroc` (`tools/check_development.py`),
confirmed clean after every change, run as one combined suite before each
commit. All five commits are already on `feat/daq-results-gui`, nothing
pushed.

**Every delegated result this session was independently verified before
being trusted** -- one delegated worker's own environment-gap explanation
turned out to be wrong (see the first RADIOROC 40 entry); the defect-hunt
finding was independently reproduced, not taken on faith; the two
test-coverage-audit results were spot-checked against the actual
manifest-writing code before being accepted. Keep doing this -- it caught
a real bug and a real wrong claim in the same night.

## Equipment state at handoff -- check before assuming

Unchanged from RADIOROC 39's own handoff, since nothing physical happened
this session either: SiPM bias PSU channel 3 was left ON at RADIOROC 39's
handoff, but was confirmed OFF (along with channel 1) at the start of
RADIOROC 40 -- don't assume either state, check PSU directly. Signal
generator: mode left as burst/single-shot external-triggering, output
off. Board: USB-connected, unpowered. IO1 FPGA mux index: was found
drifted to `0` (not `5`) partway through RADIOROC 39 -- check
`read_fpga_io_mux()` rather than assume it's still `5`.

## This session's job

1. **Run Step 5 through `HoldScanWindow`** for rehearsal completeness
   (now that it lives on its own Acquisition-adjacent Calibration tab, not
   affected by the sidebar change), using the trigger configuration
   Priority 0 actually settled on. RADIOROC 39's earlier same-day CLI
   hold-scan result (peak ~530-550 ns, channel 4, Simple trigger) is
   evidence, not a substitute for the GUI rehearsal.
2. **Write the real Step 6 record**: once Step 5 has a real output
   directory, run `scripts/radioroc_save_calibration_record.py` for real,
   pointing `--sub-scan` at the actual Step 1/2/4/5 output directories,
   `--threshold-dac 575` with the recorded margin reasoning, and the
   Step 4 per-channel plateau values. Confirm it validates cleanly (all
   sub-scans `completed`, `board_identity` agreeing) against real data,
   not just the unit tests' fakes.
3. **Then move toward the actual Priority 4 rehearsal**: a complete
   calibration -> acquisition -> stop -> reopen/export pass, with the
   operator continuing to stand in for the student per their own decision
   to do so. Case (c) (Priority 0's remaining item) was explicitly skipped
   by the operator's own decision to keep moving toward the MVP deadline --
   don't reopen it without them raising it.
4. Optional, low-priority, flagged not required: decide whether
   `AutocalibrationResult` should grow its own `persistence_errors` field
   to match its sibling jobs' manifest-write-failure contract (currently
   raises instead; both real callers already handle that safely). Not
   worth doing under deadline pressure unless it's blocking something
   else -- it was flagged, not queued.

## Standing discipline (unchanged, all still applies)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action -- a grant
from an earlier conversation does not carry over. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` after every meaningful change (~3 minutes;
background it and poll rather than assuming a short timeout means
failure; redirect to a file and check the file's own exit code rather than
piping through `tail`, which masks a non-zero exit -- this actually
happened in RADIOROC 40 and hid a real failure on the first attempt).
A self-created venv without the `[gui]` extra will silently skip every GUI
test and look green when it isn't (RADIOROC 36).

**When delegating bounded work to a worker agent, review the actual diff
and re-run the real acceptance check yourself before accepting its
report** -- proven twice over in RADIOROC 40: one worker's own claimed
environment-gap explanation was wrong (the real bug only surfaced once the
lead ran `tools/check_development.py` directly), and a separate defect-hunt
finding was only trustworthy because the lead independently reproduced it
(and reproduced its absence-of-fix) rather than taking the report at face
value. When agents run concurrently in the same working tree, wait for
each to fully hand back before running the combined suite or committing --
a check run started while another agent is still mid-edit can produce a
misleading result.

Multiple Claude Code sessions share this working directory. Confirm no
other session is mid-hardware-action before touching the board or bench
instruments.

`main` has the M3 milestone (PR #1, squash-merged). Feature work continues
on `feat/daq-results-gui`. `gh` is installed and authenticated for CI
checks after any push (`gh run list --branch <branch>`). Nothing has been
pushed this session -- only committed locally.

Per the directive's own instruction: track each MVP item as implemented,
offline-verified, physically verified, or blocked, with concrete evidence
and the next action. Record actual checks and remaining limitations in a
fresh `IMPLEMENTATION_STATUS.md` entry and `NEXT_SESSION.md`, retaining
the session-numbering convention.

## Deferred, not dropped

Broad Windows screen-by-screen parity, unrelated trigger combinations,
cosmetic refinements, and general macOS/Debian/Ubuntu release work remain
explicitly deferred by the directive until after this checkpoint. None of
F01-F17/M0-M5 are deleted by this reprioritization. F15/A7585 remains
permanently out of scope. Priority 0's case (c) is deferred by the
operator's own explicit decision, not resolved.
