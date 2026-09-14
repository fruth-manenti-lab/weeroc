# Stage-C FPGA IO1 sync-pulse validation (RADIOROC 15 — PASSED)

**State: PASSED.** This is the project's first Stage-C physical result
(`CROSS_PLATFORM_REBUILD_PLAN.md` section 5: "Oscilloscope and suitable
probe/cables — Actual FPGA routing, sync clocks/pulses... register readback
alone cannot establish signal correctness"). It confirms, by direct
oscilloscope observation on the current board, that FPGA IO1 carries a real
synchro-trigger pulse train at mux index 5 — corroborating a logbook finding
from 2026-06-26/2026-06-29 that the plan document itself cautions must be
re-checked against the current wiring and board revision before being
trusted.

## Setup

Board powered/bare (no SiPM/pulser), no competing software, same as every
prior Stage-B card. The operator connected an oscilloscope probe to the
board's IO1 connector (bottom-right corner of the board, per the vendor user
guide) — a passive voltage observation, no signal sourced onto the board, no
attenuator needed (that's only required later if a signal generator's output
is injected into the ASIC via `in-test1`, which this card does not do).

## Steps

1. Reran `scripts/radioroc_io_mux_scan.py --execute --sync-io io1` (identical
   to the RADIOROC 14 invocation) — the default full sweep of mux indices
   0-7, 100 pulses/10ms period per index (~8 s total) — while the operator
   watched the oscilloscope.
2. The operator was not tracking which index was live during the sweep, so a
   small new script, `hold_mux_index5.py`, isolates mux index 5 on `io1` and
   holds it there (no sweeping) so the signal is a stationary target to
   observe. It mirrors `RadiorocDevice.pulse_synchro_trigger` exactly
   (`write_word(22, high)` then `write_word(22, low)` per pulse, sleeping
   `period_ms` between pulses), restoring the original mux state in a
   `finally` block, same as the sweep script.
3. First run of the hold script: the operator reported pulses that looked
   about 500 ms apart — a 50x discrepancy from the requested 10 ms period.
   Rather than dismiss this or just retry blindly, the script was
   instrumented to independently measure the actual wall-clock period between
   pulses at the `write_word` level (not trusting the requested `period_ms`
   alone). Rerun with 1000 pulses: **measured mean period 12.66 ms** (min
   10.31, max 15.36), consistent with the requested 10 ms plus a few
   milliseconds of expected serial round-trip overhead per pulse. This ruled
   out a code- or hardware-side timing fault.
4. With the actual signal timing confirmed independently, the discrepancy was
   attributed to oscilloscope trigger/timebase configuration (e.g. Normal
   trigger mode with a long holdoff showing a stroboscoped subset of pulses,
   or a timebase left at the wide setting suggested for viewing the whole
   8-second sweep rather than one steady 10 ms train). After the operator
   adjusted the scope, they confirmed pulses genuinely ~10 ms apart, matching
   both the requested period and the independent software measurement.

## Evidence

Local under `radioroc_runs/physical_scope_20260914T025434Z/`: both console
logs, the `hold_mux_index5.py` script, `terminal_summary.json` (full
narrative and measurements), `evidence_manifest.json`. The oscilloscope
observation itself is operator-reported, not automatically captured (no
scope-to-computer integration exists in this project) — this is the same
evidentiary standard as every prior "operator confirms via GUI/physically"
step in this project, not a lower one.

## What this does and doesn't establish

Establishes: FPGA IO1, mux index 5, genuinely carries a ~10 ms period digital
pulse train, both by independent software timing measurement and by direct
electrical observation — Stage C's core claim ("register readback alone
cannot establish signal correctness") is now backed by an actual signal
observation for this one signal path.

Does not establish: exact voltage levels/logic family (the operator did not
report measured amplitude; the vendor guide's "2.5V TTL" figure for the
board's FPGA sync connectors was not independently confirmed by a voltage
reading), pulse width/rise-time/signal integrity, or any other FPGA IO
signal (io0, io2-io4, or the separately-documented `IO_FPGA6`/`IO_FPGA7` SMA
connectors). Those remain open Stage-C work if useful later.
