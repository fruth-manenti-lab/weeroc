# RADIOROC 17 — Extend Stage C or move toward Stage D

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 16 — IO1 sync-pulse amplitude follow-up**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 15 confirmed FPGA IO1 (mux index 5) carries
a real ~10-13ms period sync pulse, cross-validated against a 2026-06/2026-06
logbook finding. RADIOROC 16 followed up with an amplitude reading: initially
14.4V under 50-ohm termination, corrected to **~1.44V** after discovering the
scope channel's probe-attenuation setting (10X) didn't match the physical
1x cable. This doesn't exactly match the vendor guide's "2.5V TTL" figure,
but that figure is documented for a different connector pair
(`IO_FPGA6`/`IO_FPGA7`), so it's recorded as the current empirical reading,
not treated as a contradiction needing resolution. Evidence under
`radioroc_runs/physical_scope_20260914T025434Z/` and
`radioroc_runs/physical_scope_amplitude_20260914T030258Z/`.

**Lesson worth repeating to the operator on any future scope measurement**:
always check the channel's probe-attenuation setting (1X vs 10X) against the
actual physical connection before trusting an absolute voltage reading — this
session hit exactly that mistake once already (a 10x error).

State: Stage B complete for everything with existing, non-persistent-change
code. Stage C has one signal (IO1, mux 5) with existence, timing, and now
amplitude confirmed. No other FPGA IO line has been probed; no analog signal
response (needs Stage D, a pulse generator) has been touched.

Next bounded task: with the designated operator, choose a direction:

1. **Extend Stage C further** while the scope may still be connected: pulse
   width/rise-time, an untermination-corrected (high-Z) amplitude reading, or
   probing a different FPGA IO line (io0, io2-io4, or the documented
   `IO_FPGA6`/`IO_FPGA7` SMA connectors) with the same
   existence/timing/amplitude approach used for IO1.
2. **Move to Stage D** if a pulse generator is also available — this is what
   the historical logbook workflow actually built toward (IO1 triggering a
   generator, generator output attenuated into `in-test1` for real
   S-curve/hold-scan signal response, `F07`/`F10` in the plan's feature
   table). Bigger step: needs an attenuator (not needed for RADIOROC
   15/16's passive observation) and involves injecting a signal into the
   ASIC — needs its own careful setup review before authorization.
3. **Non-hardware work instead**: item 7 (persistent defaults/FPGA init) is
   still deferred and open; so are the input-DAC/TQ-mask feature gaps and
   the already-queued branch/CI review and Windows-parity inventory backlog
   items.

Whatever is chosen, follow the RADIOROC 09-16 discipline: confirm
preconditions (including what's physically connected and at what point)
before any hardware access, get an explicit authorization statement
(operator, host, UTC start time, scope) for the exact action, and when a
reading doesn't match expectations (as happened twice now — the 500ms timing
illusion and the 14.4V amplitude), diagnose with independent instrumentation
or a sanity check on measurement setup before concluding anything about the
hardware itself.

Acceptance: the chosen direction is authorized, run (or explicitly scoped as
non-hardware work), and its outcome recorded with the same evidence rigor as
RADIOROC 09-16 in both `IMPLEMENTATION_STATUS.md` and this file, along with
the next task. No ASIC/FIFO access, verifier, scan, persistent configuration
write, defaults, repair, power-cycle, signal injection, or detector
connection beyond what is explicitly authorized for that exact action; no
push or change to `main`.
