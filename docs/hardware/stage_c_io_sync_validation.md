# Stage-C FPGA IO0/IO1 sync-pulse validation (RADIOROC 15/16/22 — PASSED)

**State: PASSED.** This is the project's first Stage-C physical result
(`CROSS_PLATFORM_REBUILD_PLAN.md` section 5: "Oscilloscope and suitable
probe/cables — Actual FPGA routing, sync clocks/pulses... register readback
alone cannot establish signal correctness"). It confirms, by direct
oscilloscope observation on the current board, that FPGA IO1 carries a real
synchro-trigger pulse train at mux index 5 — corroborating a logbook finding
from 2026-06-26/2026-06-29 that the plan document itself cautions must be
re-checked against the current wiring and board revision before being
trusted. RADIOROC 16 added a follow-up amplitude reading (~1.44V under
50-ohm termination, after correcting a 10x probe-attenuation-setting
mismatch). RADIOROC 22 repeated the full characterization on **IO0** and
found the same result at the same mux index — see "IO0 characterization
(RADIOROC 22)" below.

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

## Amplitude follow-up (RADIOROC 16)

With the scope already connected, the operator held `io1` at mux index 5
again (`hold_mux_index5.py`, 3000 pulses, ~38 s; measured mean period again
~12.6 ms, consistent with the first run) and read the pulse amplitude: first
reported as **14.4V with 50-ohm termination**. That is about 6x the vendor
guide's documented "2.5V TTL" figure for the board's FPGA sync connectors,
and suspiciously close to a 10x multiple of a plausible TTL-ish value — so,
rather than record it as a real 14.4V signal, the operator was asked to check
the scope channel's probe-attenuation setting. It was set to **10X** while
the physical connection was a direct (1x) cable, so the true amplitude is
**14.4V / 10 ~= 1.44V** under 50-ohm termination.

This corrected 1.44V figure does not exactly match the vendor guide's 2.5V
TTL figure either, but that figure is documented specifically for the
`IO_FPGA6`/`IO_FPGA7` SMA connectors (External Synchro/External Hold), not
confirmed to be the same signal path as `io1`'s mux-selected sync output; a
50-ohm termination can also load a not-low-impedance source down from its
open-circuit level. Treat 1.44V (terminated) as the current empirical
reading for this specific point, not as a contradiction of the vendor figure
for a different connector.

## What this does and doesn't establish

Establishes: FPGA IO1, mux index 5, genuinely carries a ~10 ms period digital
pulse train, both by independent software timing measurement and by direct
electrical observation — Stage C's core claim ("register readback alone
cannot establish signal correctness") is now backed by an actual signal
observation for this one signal path. A follow-up amplitude reading, after
correcting an initial 10x probe-attenuation-setting mismatch, put the pulse
at ~1.44V under 50-ohm termination.

Does not establish: pulse width/rise-time/signal integrity, an
untermination-corrected open-circuit amplitude, or (before RADIOROC 22) any
other FPGA IO signal (io0, io2-io4, or the separately-documented
`IO_FPGA6`/`IO_FPGA7` SMA connectors). io2-io4 and the SMA pair remain open
Stage-C work if useful later.

## IO0 characterization (RADIOROC 22)

With the oscilloscope moved to the board's IO0 connector, the operator
first ran the full default `radioroc_io_mux_scan.py --sync-io io0` sweep
(mux indices 0-7, ~8 s) twice, but the fast automated sweep made it hard to
attribute an observed signal to a specific index. A new script,
`hold_mux_index.py <io_name> <index>` (a generalization of RADIOROC 15's
`hold_mux_index5.py`, taking the IO line and index as arguments), held each
index individually for ~15 s so the operator could watch one at a time.

Results, index by index:

| Mux index | Observation |
|---|---|
| 0-3 | Nothing observable |
| 4 | Baseline level shifted down, no pulsing |
| **5** | **Real pulses observed** |
| 6 | Baseline level shifted down, no pulsing (same as 4) |
| 7 | Baseline level shifted down, no pulsing (same as 4/6) |

A longer hold (3000 pulses, ~30 s) at index 5 let the operator measure
amplitude: **1.44 Vpp, pulses ~10 ms apart** — matching IO1's RADIOROC 16
result (~1.44V, ~10-13 ms) almost exactly, at the *same* mux index. This is
consistent with mux index 5 selecting the same internal "synchro trigger"
signal regardless of which physical IO line it is routed to, and is now
independent evidence from a second signal path, not just one.

The indices 4/6/7 baseline-shift observation is new and not yet explained —
it is a real, repeatable effect (three separate indices, same character),
but this session did not investigate what internal signal or artifact
produces it. Recorded as an open question, not a finding.

Evidence is local under `radioroc_runs/physical_scope_io0_20260914T044151Z/`
(sweep console logs, the `hold_mux_index.py` script, operator observations
and measurements in `terminal_summary.json`).
