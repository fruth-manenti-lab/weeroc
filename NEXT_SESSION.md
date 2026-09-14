# RADIOROC 23 — Real next feature: Stage D (if equipment allows) or app backlog

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 22 — IO0 sync-pulse characterization (PASSED)**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**Course correction:** the operator asked to stay focused on what the app
and end user actually need, not open-ended/completionist hardware
exploration. Prior handoffs (including an earlier draft of this file) listed
things like "characterize io2-4 for completeness" and "investigate the mux
4/6/7 baseline-shift artifact" as options — neither ties to a real feature
in `CROSS_PLATFORM_REBUILD_PLAN.md`'s feature table, so drop them. Only
propose hardware or exploratory work that unblocks a concrete feature-parity
row or end-user capability.

**Hardware state:** IO1 (RADIOROC 15/16) and IO0 (RADIOROC 22) are both
confirmed carrying the real ~10 ms, ~1.44 Vpp sync pulse at mux index 5 —
that's the FPGA-routing/sync-timing evidence Stage C exists to establish,
and it's now been shown on two independent signal paths. Treat that claim as
adequately supported; do not re-verify it further without a concrete reason.

The input DAC/TQ mask feature (RADIOROC 17-21) is complete and evidenced on
both the CLI and GUI paths.

Next bounded task: with the designated operator, pick a direction that
serves a real feature:

1. **Move to Stage D** if a pulse generator is available — this is the
   actual blocked feature work: `F07` (S-curves) and `F10` (hold scans) in
   the plan's feature table need real signal injection to validate, and
   existing CLI scripts (`scripts/radioroc_scurve.py`,
   `scripts/radioroc_hold_scan.py`, `scripts/radioroc_standard_scurves.py`)
   already implement the backend but have no GUI and no physical evidence
   under this rebuild. This is a bigger step (needs an attenuator, injects
   a signal into the ASIC) needing its own setup review before
   authorization, but it is real feature-parity work, not exploration.
2. **Non-hardware app work**: persistent defaults/FPGA init (item 7, `F06`
   in the feature table — still explicitly deferred by operator choice);
   branch/CI review before publishing; or expanding the Windows-parity
   inventory (`CROSS_PLATFORM_REBUILD_PLAN.md` M0 step 3, "build the
   detailed parity table" — still only a summary table exists, not the
   full per-row inventory the plan calls for).
3. If neither is right, ask the operator directly what's next rather than
   defaulting to more hardware characterization.

Whatever is chosen, follow the RADIOROC 09-22 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, and stop immediately on any error, fault, or
mismatch.

Acceptance: the chosen direction is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-22 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write, defaults,
repair, power-cycle, signal injection, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
