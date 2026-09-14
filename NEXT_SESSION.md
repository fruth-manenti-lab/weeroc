# RADIOROC 15 — Choose between equipment-gated work and remaining gaps

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/desktop_threshold_validation.md`,
and `docs/hardware/stage_b_completion.md`. The preceding chat is
**RADIOROC 14 — Stage-B completion sweep**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 14 finished, in one session, every
remaining Stage-B item (bare board over USB, no oscilloscope/pulser/SiPM)
that had existing code and no persistent/unrestorable side effect: Ctest,
trigger preamp gain, wide DAC ranges, all-64-channel coverage (GUI path);
HG/LG gain codes, a first-ever forced/synchro-triggered ADC acquisition, and
FPGA IO-mux readback (CLI tools, wrapped with an added independent
before/after register check). All passed with independently verified
restoration. Evidence under `radioroc_runs/physical_sweep_20260914T020107Z/`
and `radioroc_runs/physical_cli_20260914T020329Z/`.

What's left, per `docs/hardware/stage_b_completion.md`'s closing section:

1. **Item 7 — persistent defaults/FPGA init.** Code exists
   (`scripts/radioroc_apply_defaults.py`, `RadiorocDevice.initialize_fpga`/
   `apply_default_config`) but makes changes with no automatic restoration.
   The operator explicitly deferred this rather than bundle it into the
   routine sweep — it needs its own deliberate framing/card (what state to
   apply, how to independently confirm/record the resulting persistent
   state, and explicit sign-off that persistence is intended) before running.
2. **Per-channel input DAC/enable/impedance** — no setter exists in
   `RadiorocDevice` at all; needs real register-mapping/API work first.
3. **TQ mask** — `set_mask_for_channel` only supports T1/T2; needs a new
   method/bit mapping first.
4. **USB self-test writes** — no defined operation exists; the plan itself
   flags this as needing "an identified safe target" first.
5. Everything else (F07 S-curves, F10 hold scans, F11 full DAQ trigger
   combinations, real signal/timing correctness) is gated on Stage C
   (oscilloscope) or Stage D (pulse generator) equipment per
   `CROSS_PLATFORM_REBUILD_PLAN.md` section 5 — not obtainable with a new
   test card alone.

Next bounded task: with the designated operator, pick a direction:

- **(a)** Design and authorize a dedicated card for item 7 (persistent
  defaults/FPGA init) — different risk category, needs its own review, not a
  routine variation.
- **(b)** Move to Stage C: if an oscilloscope is available, define and run
  the first scope-based card (e.g. FPGA IO-mux/sync signal timing, building
  on today's IO-mux readback).
- **(c)** Non-hardware work: the input-DAC/TQ-mask feature gaps (items 2-3
  above) are real development, not just test cards — could be scoped and
  built now, validated physically later. Or pivot to the already-queued
  branch/CI review or Windows-parity inventory backlog items.

Whatever is chosen, follow the RADIOROC 09-14 discipline: confirm
preconditions, get an explicit authorization statement (operator, host, UTC
start time, scope) before any hardware access, reuse/extend an existing
bounded harness where one fits, verify a coding sub-agent's output yourself
before running it against hardware (as this session did), and stop
immediately on any error or unexpected value — a bug in a new harness itself
(as happened twice today) is fixable-and-rerunnable under the same
authorization only when independent evidence shows the board's own behavior
was unaffected.

Acceptance: the chosen direction is authorized, run (or explicitly scoped as
non-hardware work), and its outcome recorded with the same evidence rigor as
RADIOROC 09-14 in both `IMPLEMENTATION_STATUS.md` and this file, along with
the next task. No ASIC/FIFO access, verifier, scan, persistent configuration
write, defaults, repair, power-cycle, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
