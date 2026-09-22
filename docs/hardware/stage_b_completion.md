# Stage-B completion sweep (RADIOROC 14 — PASSED)

**State: PASSED.** This card completes the remaining Stage-B items identified
in `CROSS_PLATFORM_REBUILD_PLAN.md` section 5 (powered bare board over USB
only — no oscilloscope, pulse generator, or SiPM/detector) that had existing
code but no physical evidence: Ctest, trigger preamp gain, wider DAC ranges,
broader/all-64-channel coverage, HG/LG gain and shaping, a first-ever
forced/synchro-triggered ADC acquisition, and FPGA IO-mux readback. It does
**not** cover applying persistent defaults/FPGA initialization (deferred by
explicit operator choice — see "Deliberately skipped" below) or two items
with no existing code (per-channel input DAC/impedance; a TQ mask).

On 2026-09-14, with the board confirmed powered/bare (no SiPM/pulser) and
competing software closed, the user authorized this whole day's Stage-B work
and separately confirmed including the first-ever forced-trigger ADC
acquisition. The lead was sole software operator throughout.

## Part 1 — GUI sweep card (Ctest, gain, wide DAC range, all channels)

New harness `radioroc14_sweep_card.py` (closely modeled on the RADIOROC
07/12/13 GUI harnesses, drafted by a coding sub-agent and reviewed before
execution), run once through the standard `ConnectionWorker`/`ThresholdJob`
path used by every prior physical GUI card. Four sequential T1 "completed"
cases, no cancellation:

| Case | Channels | DAC range | Ctest | Gain | Points | Attempts |
|---|---|---|---|---|---|---|
| `t1_ctest_enabled` | [4] | 0..1 | **on** | 0 | 2 | 2 |
| `t1_gain_variation` | [4] | 0..1 | off | **32** | 2 | 2 |
| `t1_wide_dac_range` | [4] | **0..1000 step 100** | off | 0 | 11 | 11 |
| `t1_all_channels` | **0..63 (all 64)** | 0..1 | off | 0 | 2 | 128 |

Before execution, the restoration verifier's design was independently
re-confirmed by reading `src/radioroc/application/threshold.py`'s
`_run_locked`: it captures a live pre-scan snapshot of FPGA words 0/1/6 and
the full ASIC register set *before* applying any temporary scan setting
(mask/Ctest/gain), and `verify_threshold_restoration()` compares post-cleanup
readback against that same in-memory snapshot — never a hardcoded table. So
enabling Ctest or a non-zero gain does not change what "expected" means for
that run; no special-casing was needed for this card to be safe.

All four cases passed: `cleanup.status == "restored"` and
`verification.status == "passed"` (empty mismatches/missing/errors) for
every case, exactly as in RADIOROC 12/13. Evidence (57 files) is local under
`radioroc_runs/physical_sweep_20260914T020107Z/`.

## Part 2 — CLI wrapper (HG/LG gain, forced-trigger ADC, FPGA IO-mux)

Three more items (HG/LG gain/shaping, forced/synchro-triggered ADC
acquisition, FPGA IO-mux readback) are not wired into the GUI
`ConnectionWorker`/`ThresholdJob` path — they exist only as separate,
already safety-gated CLI tools (`scripts/radioroc_acquire.py`,
`scripts/radioroc_io_mux_scan.py`), neither of which has an automated
restoration-verification comparison like `ThresholdJob` does (their cleanup
`finally` blocks blind-write saved register values back, without reading
them again to confirm the write took).

A new wrapper, `radioroc14_cli_wrapper.py`, adds that missing independent
check: before and after each subprocess call it opens its own short-lived
connection and reads back exactly the registers each tool itself
snapshots/restores (FPGA word 2 and ASIC registers `(65,12)`/`(4,2)` around
`radioroc_acquire.py`; FPGA words 77/78 around `radioroc_io_mux_scan.py`),
then requires the before/after readback to match exactly.

Both subprocess calls used `--skip-fpga-init` and never passed
`--apply-defaults`, consistent with skipping item 7 today. A first execution
attempt stopped immediately, before any hardware write, on a bug in the
wrapper itself: `RadiorocDevice.read_word()` returns a bit-string
(`"00000101"`), and the wrapper compared it directly to the integer `5`. The
board's own read was correct (status 5); this was purely a wrapper defect,
fixed (`int(status_bits, 2)`) and rerun immediately under the same
authorization.

The rerun passed cleanly:

- `radioroc_acquire.py --channels 4 --hg-gain-code 8 --lg-gain-code 8 --synchro-trigger --skip-fpga-init --acquisitions-per-batch 20 --batches 2`: 40 real ADC events acquired (HG/LG pairs like 133.25/132.5 — plausible bare-board noise-floor readings, no detector attached, no analog/detector performance claim made), elapsed 0.578 s. This is the project's first-ever physical exercise of the forced-trigger ADC/DAQ acquisition path. Independent before/after readback of FPGA word 2 and ASIC registers `(65,12)`/`(4,2)` matched exactly (`'00000000'` / `'11011111'` / `'11011101'`, unchanged).
- `radioroc_io_mux_scan.py --sync-io io1 --pulses-per-index 20 --period-ms 10`: tested mux indices 0-7 with real (non-dry) writes, restored the mux to index 0 at the end. Independent before/after readback of FPGA words 77/78 matched exactly (`'00000000'`/`'00000000'`, unchanged).

Evidence (7 files: `events.jsonl`, both subprocess console logs, the
acquire tool's own `events.csv`/`metadata.json`, `terminal_summary.json`,
`evidence_manifest.json`) is local under
`radioroc_runs/physical_cli_20260914T020329Z/`. The earlier failed attempt's
evidence is not preserved as a separate run directory (it stopped before
creating any hardware-touching output; the fix and rerun are recorded here).

## Deliberately skipped today

- **Item 7 — raw register write / `apply_defaults` / FPGA initialization.**
  Code exists (`scripts/radioroc_apply_defaults.py`, `RadiorocDevice.
  initialize_fpga`/`apply_default_config`) but the project's own docs mark
  these as making **persistent** changes with no automatic restoration
  (unlike everything else validated today). The operator explicitly chose to
  leave this for a separately considered session rather than bundle it into
  today's routine sweep.

## Not attempted — no existing code (real development needed first)

- **Per-channel input DAC / enable / impedance** (distinct from the
  already-tested threshold DAC): no setter exists anywhere in
  `RadiorocDevice`.
- **TQ mask**: `set_mask_for_channel` only supports T1/T2 (bit index 3 or 4
  of the channel's row 6); no TQ-specific bit or method exists.
- **USB self-test writes** (`F01`): no such operation is defined in code or
  in the plan beyond "requires an identified safe target."

With today's work, every Stage-B feature-table item (F01-F14, F16-F17
subset relevant to a bare board) that has existing code and does not
require a persistent, unrestorable change now has physical evidence. The
remaining Stage-B gap is exclusively items 4, 6's TQ sub-item, 7, and 10's
self-test sub-item, as listed above. All further physical validation
(F07/F10/F11 signal-timing correctness, S-curves, hold scans, full DAQ
trigger combinations, detector response) requires Stage C (oscilloscope),
Stage D (pulse generator), or Stage E (SiPM) equipment per
`CROSS_PLATFORM_REBUILD_PLAN.md` section 5.
