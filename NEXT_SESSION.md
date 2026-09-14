# RADIOROC 16 — Extend Stage C or move toward Stage D

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 15 — First Stage-C oscilloscope validation**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 15 was the project's first Stage-C
(oscilloscope) physical result: the operator connected a scope to the
board's IO1 output and confirmed, both by direct observation and by
independent software-side timing instrumentation, a genuine ~10 ms period
synchro-trigger pulse train at mux index 5 — corroborating a
2026-06-26/2026-06-29 logbook finding on the current board/software. Along
the way, an apparent 50x timing discrepancy (operator saw ~500 ms spacing)
was diagnosed as an oscilloscope trigger/timebase setup issue, not a
code/hardware fault, using an independently instrumented measurement rather
than guessing. Evidence is local under
`radioroc_runs/physical_scope_20260914T025434Z/`.

State: Stage B is complete for everything with existing, non-persistent-
change code (see `docs/hardware/stage_b_completion.md`). Stage C has now
produced its first result, but only for one signal (IO1 sync pulse
existence/period) — amplitude/voltage was not measured, no other FPGA IO
signal was probed, and no analog signal (S-curve/hold-scan response, which
needs a pulse generator, i.e. Stage D) has been touched at all.

Next bounded task: with the designated operator, choose a direction:

1. **Extend Stage C** while the scope is already connected: measure the
   IO1 pulse's actual voltage/amplitude (cross-check against the vendor
   guide's "2.5V TTL" figure for the board's documented FPGA sync
   connectors, which was never independently confirmed), check pulse
   width/rise time, or probe a different FPGA IO line (io0, io2-io4, or the
   separately-documented `IO_FPGA6`/`IO_FPGA7` SMA connectors) for the same
   kind of existence/timing check RADIOROC 15 did for IO1.
2. **Move to Stage D** if a pulse generator is also available: this is what
   the historical logbook workflow (2026-06-26) actually built toward — IO1
   triggering a generator, generator output attenuated into the `in-test1`
   Ctest injection connector, enabling real S-curve/hold-scan signal
   response validation (`F07`/`F10` in the plan's feature table). This is a
   larger step: it requires an attenuator (not needed for RADIOROC 15's
   passive observation) and involves actually injecting a signal into the
   ASIC, so it needs its own careful setup review before authorization, not
   just a rerun of today's scripts.
3. **Non-hardware work instead**: item 7 (persistent defaults/FPGA init) is
   still deferred and open; so are the input-DAC/TQ-mask feature gaps and
   the already-queued branch/CI review and Windows-parity inventory backlog
   items.

Whatever is chosen, follow the RADIOROC 09-15 discipline: confirm
preconditions (including, for Stage C/D, what's physically connected and at
what point) before any hardware access, get an explicit authorization
statement (operator, host, UTC start time, scope) for the exact action, and
when something doesn't match expectations (like RADIOROC 15's apparent 50x
timing gap), diagnose with independent instrumentation before concluding
anything is wrong — and before just retrying blindly.

Acceptance: the chosen direction is authorized, run (or explicitly scoped as
non-hardware work), and its outcome recorded with the same evidence rigor as
RADIOROC 09-15 in both `IMPLEMENTATION_STATUS.md` and this file, along with
the next task. No ASIC/FIFO access, verifier, scan, persistent configuration
write, defaults, repair, power-cycle, signal injection, or detector
connection beyond what is explicitly authorized for that exact action; no
push or change to `main`.
