# RADIOROC 13 — Decide and authorize the next hardware slice

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/desktop_status_recovery.md`,
and `docs/hardware/desktop_threshold_validation.md`. The preceding chat is
**RADIOROC 12 — Desktop threshold validation card complete**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 12 reran the full (unmodified)
`desktop_threshold_validation.md` card after RADIOROC 11's status-only
recovery, and **all five required cases passed**, including the two
cancellation cases and the close-during-run case that RADIOROC 07 never
reached: `cleanup=restored` and `verification.status=passed` (exact
expected/observed match against FPGA words 0/1/6 and all 130 ASIC rows) for
every case. Evidence is local under
`radioroc_runs/physical_desktop_20260911T075002Z/`. Source hashes confirm no
code changed since RADIOROC 07 — the fix is attributed to the operator's
power-cycle (RADIOROC 10/11), not a software change.

The desktop hardware threshold workflow's originally-required case set is now
fully evidenced on a bare board. Everything still untested and out of scope
for every card so far: wider DAC/channel/scan ranges, Ctest/gain variation,
FPGA initialization/defaults, and any detector (SiPM or pulser) connection —
none of that has physical evidence yet on this branch.

Next bounded task: with the designated operator, choose and authorize the
next concrete hardware slice. Do not default to the largest option. Candidates
to put to the operator, smallest scope first:

1. A modest wider-range DAC scan on the still-bare board (e.g. a few more DAC
   points, still no detector), to build confidence before real signal input.
2. Multi-channel behavior (still bare board) if the current cards only ever
   exercised channel 4.
3. First detector connection (SiPM) for a real dark-count/threshold run —
   materially larger scope: new safety considerations (bias voltage, ESD,
   detector damage risk) that none of the existing cards cover. This needs a
   new card written and reviewed before authorization, not just a rerun of an
   existing script.
4. Non-hardware work instead: e.g. reviewing/integrating local branches for
   publishing, or expanding the Windows-parity inventory (both already queued
   in `IMPLEMENTATION_STATUS.md`'s "Next bounded tasks" backlog).

Whatever is chosen, follow the RADIOROC 09-12 discipline: confirm
preconditions, get an explicit authorization statement (operator, host, UTC
start time, scope), reuse/extend an existing bounded, evidenced harness where
one already fits, and stop immediately on any error or unexpected value.

Acceptance: the chosen next step is authorized, run (or explicitly deferred
in favor of non-hardware work), and its outcome is recorded with the same
evidence rigor as RADIOROC 09-12 in both `IMPLEMENTATION_STATUS.md` and this
file, along with the next task. No ASIC/FIFO access, verifier, scan,
configuration write, defaults, repair, power-cycle, or detector connection
beyond what is explicitly authorized for that exact action; no push or change
to `main`. Use a smaller-model agent for bounded, well-scoped pieces (drafting
a new card's text, an evidence checklist, offline script prep) while the lead
retains protocol reasoning, authorization tracking, and the physical-run
decision itself.
