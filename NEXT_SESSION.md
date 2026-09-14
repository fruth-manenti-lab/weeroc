# RADIOROC 14 — Decide and authorize the next hardware slice

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/desktop_status_recovery.md`,
and `docs/hardware/desktop_threshold_validation.md`. The preceding chat is
**RADIOROC 13 — First physical multi-channel threshold scans**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 13 ran two new T1 scans varying the
`channels` field beyond the single hardcoded channel (4) every earlier
physical case used: `[4, 5]` and `[0, 31, 63]` (spanning the 64-channel
ASIC's low/mid/high boundary). Both **passed** with `cleanup=restored` and
`verification.status=passed` (exact FPGA/ASIC match). A first attempt hit a
bug in the new harness's own expected-attempts count (not a hardware/app
fault); it was corrected and rerun under the same authorization. Evidence is
local under `radioroc_runs/physical_multichannel_20260914T013419Z/` (failed
harness validation only) and `radioroc_runs/physical_multichannel_20260914T013527Z/`
(passed).

State of physical validation so far: status-only recovery (RADIOROC 11), the
full single-channel T1/T2/cancellation/close-during-run case set (RADIOROC
12), and now a small multi-channel sample (RADIOROC 13) all pass on the bare
board with independently verified restoration. Still with zero physical
evidence on this branch: wider DAC/scan ranges, Ctest/gain variation, FPGA
initialization/defaults, more than 3 channels in one scan, any
cancellation/close-during-run case with multiple channels, and — the larger
step — any detector (SiPM/pulser) connection.

Next bounded task: with the designated operator, choose and authorize the
next concrete hardware slice, or pivot to non-hardware backlog work. Do not
default to the largest option. Candidates to put to the operator, smallest
scope first:

1. A modest wider-range DAC scan (still bare board, still a small channel
   set), to build on RADIOROC 12/13's settings incrementally.
2. A multi-channel cancellation case (combine RADIOROC 12's cancel-in-window
   or cancel-after-point cases with RADIOROC 13's multi-channel scans) —
   still bare board, still no new physical risk category.
3. First detector (SiPM) connection for a real dark-count/threshold run —
   materially larger scope: bias voltage, ESD, and detector-damage risk that
   no existing card covers. This needs a new safety card written and
   reviewed before any authorization, not a rerun of an existing script.
4. Non-hardware work instead: reviewing/integrating local branches for
   publishing, or expanding the Windows-parity inventory (both already queued
   in `IMPLEMENTATION_STATUS.md`'s "Next bounded tasks" backlog).

Whatever is chosen, follow the RADIOROC 09-13 discipline: confirm
preconditions, get an explicit authorization statement (operator, host, UTC
start time, scope), reuse/extend an existing bounded, evidenced harness where
one already fits (adapt rather than rewrite from scratch), and stop
immediately on any error or unexpected value — treat a harness bug (like
RADIOROC 13's attempts-count mistake) as fixable-and-rerunnable under the same
authorization only when the board's own behavior was unaffected, never as
license to loosen the stop-on-error discipline itself.

Acceptance: the chosen next step is authorized, run (or explicitly deferred
in favor of non-hardware work), and its outcome is recorded with the same
evidence rigor as RADIOROC 09-13 in both `IMPLEMENTATION_STATUS.md` and this
file, along with the next task. No ASIC/FIFO access, verifier, scan,
configuration write, defaults, repair, power-cycle, or detector connection
beyond what is explicitly authorized for that exact action; no push or change
to `main`. Use a smaller-model agent for bounded, well-scoped pieces (drafting
a new card's text, an evidence checklist, offline script prep) while the lead
retains protocol reasoning, authorization tracking, and the physical-run
decision itself.
