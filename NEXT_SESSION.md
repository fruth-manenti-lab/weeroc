# RADIOROC 19 — Validate input DAC/TQ mask physically, or resume Stage C/D

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 18 — Input DAC/TQ mask CLI wiring** (non-hardware).

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**Hardware state (unchanged since RADIOROC 16):** IO1 (mux index 5) confirmed
at ~10-13ms period, ~1.44V amplitude under 50-ohm termination. Stage C so far
covers only IO1; Stage D (pulse generator, signal injection) hasn't started.

**RADIOROC 17/18 (no hardware access in either):** recovered the register
mapping for input DAC (value/enable/impedance) and TQ mask directly from the
vendor's compiled GUI bytecode (cross-checked against this codebase's
already-hardware-validated T1/T2 mask bits), implemented as four new
`RadiorocDevice` methods, then wired into a new CLI script,
`scripts/radioroc_channel_config.py` (`--tq-mask`, `--input-dac-enable`,
`--input-dac-value`/`--value`, `--input-dac-impedance {low,high}`, plus
`--verify` and a `--restore` bounded-validation mode that snapshots touched
registers, writes, independently reads back, then restores and re-verifies).
Dry-run only so far; full suite (119 tests) passes. GUI wiring was
deliberately not started — a separate, larger scope decision to check with
the operator, not assumed.

Next bounded task: with the designated operator, pick a direction:

1. **Physically validate the new CLI script** — this would be the first
   hardware evidence for either input DAC or TQ mask control. Natural first
   card: bare board, `--restore --verify`, small scope (e.g. `--tq-mask 4`,
   `--input-dac-value 4 --value 200`, `--input-dac-impedance low`), same
   discipline as RADIOROC 09-16: confirm preconditions, explicit
   authorization (operator, host, UTC time, exact scope), stop on any error
   or mismatch. Since `--restore` already snapshots/verifies/restores,
   running it does **not** need the item-7-style "persistent change"
   sign-off — only running it *without* `--restore` would, and that's not
   what this first validation needs.
2. **Decide on GUI wiring** for input DAC/TQ mask before or after physical
   validation — ask the operator whether they want this now or want to defer
   it; it's a real UI feature addition (new panel/tab), not a small change.
3. **Resume the Stage C/D hardware track** instead: extend Stage C (pulse
   width/rise-time on IO1, an untermination-corrected amplitude, other IO
   lines) or move to Stage D if a pulse generator is available (bigger step:
   attenuator needed, injects a signal into the ASIC, needs its own setup
   review).
4. **Other deferred items**: persistent defaults/FPGA init (item 7, still
   explicitly deferred), or the already-queued branch/CI review and
   Windows-parity inventory backlog items.

Whatever is chosen, follow the RADIOROC 09-18 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, and treat a new/first-of-its-kind script
(like `radioroc_channel_config.py`) with the same care as any other
never-before-run path — diagnose surprises with independent instrumentation
before concluding anything about the hardware itself.

Acceptance: the chosen direction is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-18 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write (without
`--restore`, unless explicitly authorized as such), defaults, repair,
power-cycle, signal injection, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
