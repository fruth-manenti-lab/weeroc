# RADIOROC 18 — Resume Stage C/D, or wire and validate input DAC/TQ mask

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 17 — Input DAC and TQ mask: register mapping recovered,
implemented offline** (non-hardware work done while the operator was away).

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**Hardware state (unchanged since RADIOROC 16, no hardware touched in 17):**
RADIOROC 15 confirmed FPGA IO1 (mux index 5) carries a real ~10-13ms period
sync pulse. RADIOROC 16 measured its amplitude: ~1.44V under 50-ohm
termination, after catching a 10x probe-attenuation-setting mismatch (always
check this on any new scope measurement). Stage C so far covers only IO1;
Stage D (pulse generator, signal injection) hasn't started.

**New in RADIOROC 17 (no hardware access):** the two Stage-B gaps that had
*no existing code at all* — per-channel input DAC value/enable/impedance and
the TQ mask — now have a register-level mapping, recovered by loading the
vendor's own compiled `radioroc2UI.pyc`/`uiroc/i2c.pyc` bytecode directly
with Python's `marshal`+`dis` (the vendor's PyInstaller build turned out to
use a Python 3.13-era marshal format the current interpreter reads natively,
no decompiler needed) rather than guessing. The mapping cross-checks cleanly
against this codebase's already hardware-validated T1/T2 mask bit positions.
Implemented as four new `RadiorocDevice` methods (`set_tq_mask_for_channel`,
`set_input_dac_enable_for_channel`, `set_input_dac_impedance`,
`set_input_dac_value`), with one new offline test; full suite (119 tests)
passes. See `IMPLEMENTATION_STATUS.md`'s RADIOROC 17 entry for the exact bit
mapping and its provenance. **Not yet wired into any CLI script or the GUI,
and not yet physically validated** — these are the two natural next steps
for this specific feature, separate from the Stage C/D hardware track.

Next bounded task: with the designated operator, choose a direction — there
are now two independent threads, either is fine to pick up:

1. **Continue the Stage C/D hardware track** (unchanged from RADIOROC 17's
   handoff): extend Stage C (pulse width/rise-time on IO1, an
   untermination-corrected amplitude, or probing io0/io2-io4/
   `IO_FPGA6`/`IO_FPGA7`) or move to Stage D if a pulse generator is
   available (bigger step: needs an attenuator, involves injecting a signal
   into the ASIC, needs its own setup review before authorization).
2. **Finish the input-DAC/TQ-mask feature**: wire the four new device
   methods into a CLI script (following the existing
   `scripts/radioroc_*.py` pattern: `--execute`-gated, dry-run default,
   preset/connection args) and/or the GUI, then design a bounded physical
   validation card for them (same discipline as every prior card: fresh
   authorization, bare board, independent restoration verification) —
   this would be the first physical evidence for either control.
3. **Other deferred items**: persistent defaults/FPGA init (item 7, still
   explicitly deferred by operator choice) or the already-queued branch/CI
   review and Windows-parity inventory backlog items.

Whatever is chosen, follow the RADIOROC 09-17 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement (operator, host, UTC start time, scope) for the exact action, and
when a reading or result doesn't match expectations, diagnose with
independent instrumentation or a sanity check on the setup/tooling before
concluding anything about the hardware itself (this session's own register
mapping is offered with that same discipline: cross-checked, not guessed,
but still flagged unverified against real hardware).

Acceptance: the chosen direction is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-17 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write, defaults,
repair, power-cycle, signal injection, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
