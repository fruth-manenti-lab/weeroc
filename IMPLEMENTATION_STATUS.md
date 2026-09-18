# Implementation status

## RADIOROC 23 — First Stage D signal-injection confirmation (PASSED)

Continuation on `feat/desktop-hardware-threshold` at
`10ae3060a3469a2892770044ffd47d0de088488c` (clean tree before this run), on a
lab machine with the RADIOROC board, a Tektronix MSO56B oscilloscope, a
Keysight EDU36311A power supply, and an Aim-TTi TGF4162 signal generator all
connected over USB. Reached over VISA (`pyvisa` + `pyvisa-py`, installed this
session; USBTMC via `pyusb`/`libusb`, already present).

**DSO housekeeping (prerequisite):** the scope's disk was full enough that
`SAVe:SETUp` failed with "insufficient space." Investigation found the large
data trees (`cryo`, `triplecoin`, ~532k PNGs total) are unrelated prior
projects (SiPM cryo/gain characterization, a muon coincidence search), each
PNG paired with a same-timestamp `.wfm` binary, not a `.csv` as first assumed.
With the operator's scope narrowed to `cryo` only, verified pairing by
per-folder PNG/WFM count equality plus sub-second timestamp proximity (not
filename match — the two files' timestamps differ by tens to hundreds of ms),
flagging any folder that didn't cleanly satisfy both checks. Deleted PNGs in
small throttled batches (batch of 5, `*OPC?` sync, sleep between batches);
this still triggered two real USB faults (an `I/O Error` and the scope fully
dropping off the USB bus once, self-recovering after the operator power-cycled
it) — no data loss in either case, `.wfm` counts verified intact throughout,
and deletion paused rather than retried aggressively. Final count: **11,388
PNGs deleted** out of 24,216 identified as safe; the disk-space fault is
resolved (`SAVe:SETUp` now succeeds; `komal_20260918.set` saved for the other
user). Untouched: `triplecoin` entirely, one folder with a PNG/WFM count
mismatch, and the remainder of the largest `cryo` folder.

**Power supply:** the vendor user guide (`local_artifacts/downloads/Radioroc2
User Guide - 2_1_0_6(0125).pdf`, section 2) confirms the board needs an
external 5V/1A supply at its top-right connector in addition to USB — this
was the reason the operator asked for the PSU, not SiPM bias. Configured and
enabled CH1 at 5V/1A; measured draw 306 mA (healthy, not current-limited).

**Signal generator:** the TGF4162's SCPI command set (fetched from Aim-TTi's
published `TGF4000_Series_Instruction_Manual-Iss3.pdf`) has no query form for
most settable parameters (`WAVE`, `AMPL`, `PULSWID`, `BST*`, `OUTPUT`, `ZLOAD`
are set-only on this firmware; only `CHN?`/`CLKSRC?`/`CNTRVAL?`-style commands
query); verification instead used the `EER?` execution-error register after
every write. Applied the "known lab setup" documented in `README.md` /
`REFACTOR_CHECKLIST.md`: PULSE waveform, 100 ns width, external-triggered
single-cycle burst (trigger source = FPGA `IO1` at mux index 5), output
through the existing 20 dB attenuator into `in_test1`/Ctest.

**Physical confirmation (first Stage D physical result under this rebuild):**

1. Ran `hold_mux_index.py io1 5` (the RADIOROC 15/22 script, reused as-is)
   with the DSO in single-sequence acquisition, edge-triggered on the actual
   pulse: exactly **3000/3000** triggered acquisitions matched the script's
   3000 commanded FPGA sync pulses — unambiguous proof the generator fires
   reliably on every real sync pulse, not just occasionally.
2. Pulse width from that same clean single-shot capture: **100.05 ns** —
   matches the documented 100 ns spec almost exactly.
3. Amplitude required one correction: the generator's `ZLOAD OPEN` setting
   means `AMPL` is an open-circuit value, and an earlier T-split to a 1 MΩ
   DSO tap was independently distorting the fast edge (reflections off the
   unterminated stub). Setting `AMPL 1.0` (compensating for the halving a
   real 50 Ω load causes) and terminating the DSO channel in true 50 Ω (no
   T-split — direct connection) gave a stable **~49-50 mV peak-to-peak**
   reading across multiple samples taken *during* an active burst, matching
   the documented ~50 mV post-attenuation spec.

Evidence is local under
`radioroc_runs/physical_stage_d_first_pulse_20260918/` (the reused hold
script, its console logs across several runs). No push or change to `main`
occurred. At handoff: signal generator output OFF, PSU CH1 output OFF, board
still on USB (data only, no external 5V rail) — a safe idle state before
switching to a different physical machine (Raspberry Pi) for the next
session.

**Not established:** the actual Stage D measurement itself. This session
confirmed the *injection setup* works; the proposed next action — a
`radioroc_hold_scan.py --execute --preset
hold_external_track_ctest_ch4.json` run (the same known-good external
track-and-hold Ctest configuration from the 2026-06-26 logbook, channel 4,
threshold DAC 250, 440-640 ns hold sweep) — was authorized in discussion but
not yet run before the session ended. Also not established: why the
generator's amplitude reading was initially so unstable across trigger/scope
configurations before landing on the 50 Ω/single-sequence method; the root
cause of the two DSO USB faults during batch deletion.

## RADIOROC 22 — IO0 sync-pulse characterization (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `dfc8d339ee5ab950cbdb5d31108fd7f9b63cea5d`
(clean tree before this run). The operator moved the oscilloscope from IO1
to IO0 and asked to characterize it the same way. The fast automated
`radioroc_io_mux_scan.py --sync-io io0` sweep (run twice) made it hard to
attribute a signal to a specific mux index, so a new script,
`hold_mux_index.py <io_name> <index>` (generalizing RADIOROC 15's
single-purpose `hold_mux_index5.py`), held each of the 8 indices
individually for ~15 s while the operator watched.

Result: indices 0-3 showed nothing; indices 4, 6, and 7 showed a static
baseline-level shift with no pulsing (a real, repeatable but unexplained
effect — not investigated further this session); **index 5 showed real
pulses**. A longer hold at index 5 (~30 s) let the operator measure
amplitude: **1.44 Vpp, ~10 ms apart** — matching IO1's RADIOROC 16 result
almost exactly, at the same mux index. This is now independent Stage-C
evidence from a second signal path, both consistent with mux index 5
selecting the same internal synchro-trigger signal regardless of which
physical IO line it's routed to.

Evidence is local under `radioroc_runs/physical_scope_io0_20260914T044151Z/`.
Full narrative in `docs/hardware/stage_c_io_sync_validation.md` under "IO0
characterization (RADIOROC 22)". No push or change to `main` occurred.

Not established: what the indices 4/6/7 baseline shift actually corresponds
to internally; io2-io4; the documented `IO_FPGA6`/`IO_FPGA7` SMA connectors;
pulse width/rise-time; an untermination-corrected (open-circuit) amplitude.

## RADIOROC 21 — First physical validation of the GUI channel-config panel (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `7e9174d3b8ce393802bd3fbf9587150666672ceb`
(clean tree before this run). With the board confirmed powered/bare and
competing software closed, the user authorized driving the actual desktop
GUI (not the CLI script) through Connect -> the new "Input DAC / TQ mask"
panel with Restore checked -> Disconnect: TQ mask channel 4, input DAC value
200 on channel 4, impedance switch to low.

**Passed on the first attempt.** A new harness
(`radioroc21_gui_channel_config_card.py`, modeled on the RADIOROC 07/12/13/14
GUI harnesses) drove `ThresholdWindow` directly: connected (status 5),
filled in the panel fields exactly as authorized, clicked Apply, and watched
the worker transition `connected -> configuring -> connected` cleanly (no
fault). The published `channel_config_snapshot()` result matched RADIOROC
19's CLI outcome exactly: 65 rows touched, 0 verify mismatches, restored,
0 restore mismatches. Explicit Disconnect and worker shutdown both completed
normally. Evidence (15 files: screenshots at each step, event/console logs,
`terminal_summary.json`, `source_provenance.json`) is local under
`radioroc_runs/physical_gui_channel_config_20260914T041722Z/`.

This closes the one gap left open by RADIOROC 20: both the CLI and the GUI
paths through the shared `channel_config` core now have independent physical
evidence, using the same authorization and evidence discipline as every
other physical card in this project. No push or change to `main` occurred.

Next: with the designated operator, decide the next hardware slice — extend
Stage C (other IO lines, pulse width/amplitude follow-up) or move to Stage D
if a pulse generator is available, or continue with deferred non-hardware
items (persistent defaults/FPGA init, branch/CI review, Windows-parity
inventory).

## RADIOROC 20 — Input DAC/TQ mask GUI wiring (offline)

Non-hardware work, at the operator's request to finish GUI wiring alongside
the CLI. Refactored first: the CLI script's inline apply/verify/restore logic
moved into a new shared core, `src/radioroc/application/channel_config.py`
(`ChannelConfigOperation`, `ChannelConfigResult`, `apply_channel_config`),
matching this project's stated "shared core for both UI and CLI" principle
instead of duplicating the logic a second time for the GUI.
`scripts/radioroc_channel_config.py` now calls this shared function; its
dry-run output is byte-identical to before the refactor.

The shared core also fixed a real gap: unlike the CLI (which loads the ASIC
config table via `prepare_device`), the GUI's `ConnectionWorker` never loaded
`device.i2c_rows` at all, so a channel-config write from the GUI would have
silently no-opped (`find_i2c_row` returns `None` on an empty table, and the
RADIOROC 17 setters return early without writing or raising). Added
`ChannelConfigOperation.load_rows`/loading step (mirroring
`ThresholdJobConfig.load_rows`'s exact convention: reuse already-loaded rows,
or load the packaged default CSV) so this now works correctly from either
caller.

`ConnectionWorker` gained a new `"configuring"` busy state,
`apply_channel_config(operation)`, and `channel_config_snapshot()`, mirroring
`read_status`'s shape: on success, published `"connected"` with the result
stored; on a verify/restore mismatch, latches a fault and publishes
`"faulted"` (same "any fault blocks further work until reviewed and
disconnected" policy as threshold-job faults) — not silently reported.

`ThresholdWindow` gained a new "Input DAC / TQ mask (persists unless Restore
is checked)" group box: a shared channel selector, TQ mask/input-DAC-enable/
input-DAC-value checkboxes with value controls, a global impedance combo, a
"Restore after (bounded validation, does not persist)" checkbox, an Apply
button, and a status label reporting applied writes plus verify/restore
results. The persistence framing intentionally matches this codebase's
existing "(persists)" labels on `initialize`/`defaults`. The panel is only
enabled when connected, idle, and fault-free, reusing the exact same
condition as the existing "Run hardware threshold" button.

Tests: `tests/test_channel_config.py` (6, offline core logic against a fully
round-tripping fake ASIC transport — including a genuine forced-mismatch
case, not just the happy path), 2 new `tests/test_connection_worker.py`
cases (apply/verify/restore through the real threaded worker; a mismatch
correctly faults and blocks further commands until disconnect+review), 2 new
`tests/test_connection_gui.py` cases (button enable state, operation
construction from widget state, status text, and input validation before
submission). Full suite: 129 tests pass. The panel was also visually
verified by rendering the real window offline (screenshots, no hardware) —
layout, labels, and the disabled-when-disconnected Apply button all confirmed
correct.

Not done: physical validation of the new GUI path specifically (RADIOROC 19
validated the CLI path only). No push or change to `main` occurred.

## RADIOROC 19 — First physical validation of input DAC/TQ mask (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `3e9e188c3aadeb68d7e85d1df1778906ea245ae8`
(clean tree before this run). With the board confirmed powered/bare and
competing software closed, the user authorized the bounded first card:
`scripts/radioroc_channel_config.py --execute --skip-fpga-init --tq-mask 4
--tq-mask-value 1 --input-dac-value 4 --value 200 --input-dac-impedance low
--verify --restore`.

**Passed on the first attempt.** Firmware status word 5. All three writes
(TQ mask on channel 4, input DAC value 200 on channel 4, impedance switch to
low across all channels) independently read back correctly via a real
hardware I2C read (65 touched rows, 0 mismatches) — not just trusting
in-memory state. All 65 rows were then restored to their pre-run values and
independently re-verified (0 mismatches). This is the project's first
physical evidence for the RADIOROC 17 register mapping (input DAC
value/enable/impedance, TQ mask), recovered from the vendor's compiled GUI
bytecode. Evidence is local under
`radioroc_runs/physical_channel_config_20260914T035857Z/`. No push or change
to `main` occurred.

Not established by this run: input DAC enable (only value/impedance/TQ mask
were exercised; enable uses the same mechanism and register, so risk is low,
but it hasn't specifically been run), behavior without `--restore` (a
genuinely persistent change, which is the eventual real-world use case for
input DAC calibration), or GUI wiring.

## RADIOROC 18 — Input DAC/TQ mask CLI wiring (offline)

Continuation of RADIOROC 17's non-hardware work, following the existing
`scripts/radioroc_*.py` package pattern (`radioroc_cli_common`'s shared
connection/write-safety args, preset loading, `prepare_device`) exactly as
`radioroc_apply_defaults.py` does. New script:
`scripts/radioroc_channel_config.py`, exposing all four RADIOROC 17 methods:
`--tq-mask`/`--tq-mask-value`, `--input-dac-enable`/`--input-dac-enable-value`,
`--input-dac-value`/`--value`, `--input-dac-impedance {low,high}` (channel
selectors reuse the existing `parse_channels` syntax: `4`, `0-15`, `all`).

These are configuration-state writes meant to persist, like
`apply_defaults`/`initialize_fpga` — not transient scan settings that
auto-restore. The script defaults to persisting (same as `apply_defaults`)
and adds an explicit `--restore` flag for bounded validation runs: snapshot
every touched register before writing, then write, then (with `--verify`)
independently read back and compare against the in-memory expected value,
then (with `--restore`) write the snapshot back and independently verify
that restoration too. `--verify` performs a real hardware I2C read in
`--execute` mode (not just trusting the in-memory row state), matching this
project's established independent-verification discipline.

Offline-only: `--execute` was never passed. Dry-run smoke tests exercised
every option combination (missing-argument errors, out-of-range `--value`
raising cleanly, a combined `--tq-mask`+`--input-dac-value`+
`--input-dac-impedance --verify --restore` run reporting 65 touched rows, 0
mismatches, 0 restore mismatches). Full test suite unchanged at 119 passing;
no dedicated CLI-script test file was added, matching this repo's existing
convention that `scripts/radioroc_*.py` CLI entry points aren't unit-tested
directly (their underlying `RadiorocDevice` methods are, in
`tests/test_radioroc_core.py`). No hardware was touched; no push or change
to `main` occurred.

Not done: GUI wiring (a separate, larger scope decision — not started without
checking first) and any physical validation of these four methods or this
script (would be the first hardware evidence for either control).

## RADIOROC 17 — Input DAC and TQ mask: register mapping recovered, implemented offline

Non-hardware work while the operator was away. Two of Stage B's previously
"no existing code" gaps — per-channel input DAC value/enable/impedance and
the TQ mask — had no register-level specification anywhere in this repo (the
vendor user guide describes the UI behavior but not register bits, and the
existing `*_pydisasm.txt` notes for `ndevice`/`device`/`i2c` don't cover
them). Guessing register bits for real hardware writes was rejected as too
risky; instead, the lead recovered the mapping directly from the vendor
application's own compiled bytecode.

The vendor's PyInstaller-extracted `.pyc` files carry a Python 3.13-era
marshal format that the current interpreter (3.13.14) loads and disassembles
natively (`marshal.load` + `dis`), so no decompiler was needed. Searching
`radioroc2UI.pyc`'s `Ui_MainWindow.setupUi` (the Qt-Designer-generated widget
layout) for the relevant widget names found each control's register mapping
encoded as literal `setProperty(add=..., subadd=..., nbbits=..., position=...,
all_channels_add=..., all_channels_subadd=...)` calls, and `uiroc/i2c.pyc`'s
`set_value` docstring gives the authoritative convention: `position` is the
**LSB-numbered** bit position in the register byte. Recovered mapping (all on
the existing per-channel `(channel, 6)` register except the DAC value):

| Control | Vendor `position` (LSB) | This codebase's row-string index (MSB-first) |
|---|---|---|
| T1 mask (existing `set_mask_for_channel`) | 4 | 3 |
| T2 mask (existing `set_mask_for_channel`) | 3 | 4 |
| TQ mask (new) | 2 | 5 |
| Input DAC enable (new) | 6 | 1 |
| Input DAC impedance (new, `all_channels_add=True`: written identically to channels 0-63) | 7 | 0 |
| Input DAC value (new, register `(channel, 0)`, `nbbits=8`) | 0 (whole byte) | whole byte |

The T1/T2 rows are not new discoveries — they're a cross-check: the vendor's
own `position=4`/`position=3` convert to string indices 3/4 exactly matching
`set_mask_for_channel`'s already hardware-validated bit choices (RADIOROC
07/12/13), which is why the new TQ/input-DAC bits are recorded with
reasonable confidence rather than as a guess, while still being explicitly
**not yet independently verified against real hardware**.

Implemented in `radioroc_client.py`: `set_tq_mask_for_channel`,
`set_input_dac_enable_for_channel`, `set_input_dac_impedance`,
`set_input_dac_value`, mirroring `set_mask_for_channel`/`set_ctest_for_channel`'s
existing style exactly (each is a no-op if the loaded config lacks the target
row, same as the existing methods). One new offline test,
`test_tq_mask_and_input_dac_bit_positions` in `tests/test_radioroc_core.py`,
exercises all four against `RadiorocMemoryTransport`/dry-run, including value
validation (`0..255`) and confirming untouched bits on the shared register are
left alone. Full suite: 119 tests pass (`python -m unittest discover -s
tests`). No hardware was touched; `pip install decompyle3` (unused in the
end — wrong Python era) and `brew install poppler` (used earlier, RADIOROC
15) are local environment additions, not repo changes.

Not done: CLI script and GUI wiring for these four methods (the plan requires
every control to be reachable from API, CLI, and GUI — this is API-only so
far), and any physical validation. Both are natural next steps once the
operator wants to authorize a bounded card for them — this needs its own
review before hardware access, same as every other new capability.

## RADIOROC 16 — IO1 sync-pulse amplitude follow-up (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `88974e7584b13f6a026bfa880c9bb7f586b68d04`
(clean tree before this run). With the oscilloscope already connected from
RADIOROC 15, the operator held `io1` at mux index 5 again
(`hold_mux_index5.py`, 3000 pulses; measured mean period again ~12.62 ms,
consistent with RADIOROC 15) and read the pulse amplitude.

First reading: **14.4V under 50-ohm termination** — about 6x the vendor
guide's documented "2.5V TTL" figure for the board's FPGA sync connectors,
and suspiciously close to a 10x multiple of a plausible value. Rather than
record this as a real 14.4V signal, the operator checked the scope channel's
probe-attenuation setting: it was **10X** while the physical connection was a
direct 1x cable. Corrected amplitude: **14.4V / 10 = 1.44V** under 50-ohm
termination.

This ~1.44V figure doesn't exactly match the vendor guide's 2.5V TTL number
either, but that number is documented for a different, separately-named
connector pair (`IO_FPGA6`/`IO_FPGA7`), not confirmed to be the same signal
path as `io1`'s mux-selected output, and 50-ohm termination can load a
non-negligible-impedance source down from its open-circuit level. Recorded as
the current empirical reading, not as a contradiction requiring further
action right now. Evidence is local under
`radioroc_runs/physical_scope_amplitude_20260914T030258Z/`. Full narrative in
`docs/hardware/stage_c_io_sync_validation.md` under "Amplitude follow-up
(RADIOROC 16)". No push or change to `main` occurred.

Next: with the designated operator, decide whether to keep extending Stage C
(other IO lines, pulse width/rise time, an untermination-corrected reading)
or move toward Stage D (pulse generator, per
`CROSS_PLATFORM_REBUILD_PLAN.md` section 5) — a materially bigger step
requiring an attenuator and actual signal injection into the ASIC, needing
its own setup review before authorization.

## RADIOROC 15 — First Stage-C oscilloscope validation (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `af90e576c59de4586273c14930d7c0e116544bee`
(clean tree before this run). The operator connected an oscilloscope to the
board's IO1 output (bottom-right corner) — the project's first move from
Stage B (bare board, USB only) to Stage C (oscilloscope/probe). No signal
generator or injection is involved; this is a passive observation only, so no
attenuator was needed.

Reran RADIOROC 14's `scripts/radioroc_io_mux_scan.py --execute --sync-io io1`
sweep (mux indices 0-7) while the operator watched the scope, then a small
new script (`hold_mux_index5.py`) isolated mux index 5 so the operator had a
stationary target to observe, mirroring `pulse_synchro_trigger`'s exact write
sequence and restoring the original mux state afterward.

The operator's first observation (~500 ms apparent pulse spacing) was 50x off
the requested 10 ms period. Rather than guess, the script was instrumented to
independently measure the actual `write_word`-level pulse timing: **12.66 ms
mean period** (min 10.31, max 15.36) — confirming the code/hardware side was
correct and ruling out a timing bug. The discrepancy was attributed to the
oscilloscope's own trigger/timebase configuration; after the operator
adjusted it, they confirmed pulses genuinely ~10 ms apart, matching both the
request and the independent measurement.

This corroborates a 2026-06-26/2026-06-29 logbook finding (IO1, mux index 5 =
verified sync output) on the **current** board/software, addressing the
plan's own caution against trusting historical wiring notes blindly. Evidence
is local under `radioroc_runs/physical_scope_20260914T025434Z/`. Full
narrative in the new `docs/hardware/stage_c_io_sync_validation.md`.

Not established: exact voltage/amplitude (no independent voltage reading was
taken), pulse width/signal integrity, or any other FPGA IO signal (io0,
io2-io4, or the separate `IO_FPGA6`/`IO_FPGA7` SMA connectors). No push or
change to `main` occurred.

Next: with the designated operator, decide whether to extend Stage-C work
(other IO signals, voltage/amplitude measurement, timing on a second scope
channel) or move toward Stage D (pulse generator) for S-curve/hold-scan
signal-response validation, per `CROSS_PLATFORM_REBUILD_PLAN.md` section 5.

## RADIOROC 14 — Stage-B completion sweep (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `e08c0819104099ce90ffa08582909e51ba8d9415`
(clean tree before this run). The user asked to finish every remaining
Stage-B item (bare board over USB only, no new equipment) in one session,
authorized the whole day's work, and separately confirmed including a
first-ever forced-trigger ADC acquisition while explicitly deferring
persistent defaults/FPGA initialization to a later session.

**Part 1 (GUI, `ConnectionWorker`/`ThresholdJob` path):** a new sweep card
(drafted by a coding sub-agent, reviewed before running) exercised four
dimensions no prior physical case had touched: Ctest enabled, non-zero
trigger preamp gain (32), a wider/coarser DAC sweep (0..1000 step 100, 11
points), and all 64 ASIC channels in one scan. All four passed with
`cleanup=restored` and `verification.status=passed` (exact match), using the
same live pre-scan-snapshot verifier as every prior card — independently
re-confirmed by reading `threshold.py` that Ctest/gain variation doesn't
change what "expected" restoration means. Evidence (57 files) is local under
`radioroc_runs/physical_sweep_20260914T020107Z/`.

**Part 2 (CLI tools, not on the GUI job path):** HG/LG shaper gain codes, a
first-ever forced/synchro-triggered ADC acquisition (40 real events, channel
4, plausible bare-board noise-floor HG/LG values, no detector attached), and
an FPGA IO-mux readback/restore — via the existing `scripts/radioroc_acquire.py`
and `scripts/radioroc_io_mux_scan.py`, wrapped in a new script that adds an
independent before/after register-readback check neither tool has built in.
A first attempt stopped before any hardware write on a wrapper bug (`read_word`
returns a bit-string, compared directly against an int); fixed and rerun
under the same authorization. The rerun passed: independent readback matched
exactly before and after both subprocess calls. Evidence (7 files) is local
under `radioroc_runs/physical_cli_20260914T020329Z/`.

Full narrative in the new `docs/hardware/stage_b_completion.md`. Not
attempted: applying persistent defaults/FPGA init (item 7, deferred by
explicit operator choice) and per-channel input DAC/impedance, a TQ mask, and
USB self-test writes (no existing code for any of these — real feature
development needed first, not just a test card). With this session, every
Stage-B item with existing, non-persistent-change code now has physical
evidence. No push or change to `main` occurred.

Next: remaining work needs either Stage C/D/E equipment (oscilloscope, pulse
generator, or SiPM — see `CROSS_PLATFORM_REBUILD_PLAN.md` section 5) or is
non-hardware (persistent-defaults card design, the input-DAC/TQ-mask feature
gaps, branch/CI review, Windows-parity inventory).

## RADIOROC 13 — First physical multi-channel threshold scans (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `df606cf0c5ba0b2a0d32c823dca5327038abbe38`
(clean tree before this run). With the board confirmed powered/bare (no
SiPM/pulser) and competing software closed, the user authorized two new T1
scans reusing the RADIOROC 07/12 conservative settings but varying the
`channels` field beyond the single hardcoded channel (4) every prior physical
case used: adjacent channels `[4, 5]`, then boundary channels `[0, 31, 63]`
(first, middle, last of the 64-channel ASIC). The lead wrote a small new
harness adapted from the RADIOROC 07/12 script and was sole software operator.

A first attempt stopped on a mismatched expected `attempts` count in the new
harness itself (attempts scale as `channels x DAC points`, not just DAC
points) — the board's own scan, cleanup, and verification were unaffected and
the session closed cleanly. The harness was corrected and rerun immediately
under the same authorization/settings (no new physical scope). Both cases
then passed: `cleanup.status == "restored"` and `verification.status ==
"passed"` (exact FPGA/ASIC match) for channels `[4, 5]` and for `[0, 31, 63]`,
with a populated rate column per channel in each saved CSV. Source hashes
confirm no code change from RADIOROC 12. Evidence is local under
`radioroc_runs/physical_multichannel_20260914T013419Z/` (failed harness
validation, board state unaffected) and
`radioroc_runs/physical_multichannel_20260914T013527Z/` (passed). Full
narrative in `docs/hardware/desktop_threshold_validation.md` under "RADIOROC
13 multi-channel execution record".

This is the first physical evidence that multi-channel scans work correctly,
including at the ASIC's channel-index boundaries. Not covered: channels other
than 0, 4, 5, 31, 63; more than 3 channels in one scan; wider DAC ranges; or
any cancellation/close-during-run case with multiple channels. No ASIC/FIFO
misuse, defaults, repair, power-cycle, push, or change to `main` occurred.

Next: with the designated operator, choose the next bounded hardware slice —
for example a modest wider-range DAC scan, or moving toward first detector
(SiPM) connection (which needs a new safety card, not just a rerun) — or pivot
to non-hardware backlog items (branch/CI review, Windows-parity inventory).

## RADIOROC 12 — Desktop threshold validation card complete (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `33fb47a26323b6babc29ff8b8b717abd4fcdb81f`
(clean tree before this run). With preconditions confirmed (powered bare
board, no SiPM/pulser, no competing software) and explicit authorization to
run `docs/hardware/desktop_threshold_validation.md`'s full case set exactly as
written, the lead reran the unmodified RADIOROC 07 harness
(`radioroc07_gui_card.py`, byte-identical) as sole software operator.

All five required cases passed: `t1_normal`, `t2_normal` (2/2 points each, as
before), and — the exact scope RADIOROC 07 never reached —
`t1_cancel_window` (cancel during a 60000 ms window), `t1_cancel_after_point`
(cancel after one persisted point, 1000 ms window), and `t1_close_window`
(native window closed mid-scan, 60000 ms window). Every case reported
`cleanup.status == "restored"` and `verification.status == "passed"` with
empty mismatches/missing/errors against the expected FPGA words 0/1/6 and all
130 ASIC snapshot rows; the harness itself raises on any mismatch, so these are
checked results, not self-reports. The worker reached `stopped` cleanly with
no `close_failed` state at any point. `source_provenance.json` for this run
confirms the transport/threshold-job source is unchanged from RADIOROC 07, so
the successful outcome is attributable to the board/bridge recovery
(RADIOROC 11), not a code change.

Evidence (77 files) is local and ignored under
`radioroc_runs/physical_desktop_20260911T075002Z/`. This completes the
desktop threshold validation card's required case set for the first time.
Not covered: wider DAC/scan ranges, Ctest/gain variation, FPGA
initialization/defaults, or any detector (SiPM/pulser) connection — the board
remained bare throughout, and each of those needs its own bounded,
separately authorized card. No push or change to `main` occurred.

Next: with the designated operator, decide the next bounded hardware slice —
for example a small wider-range DAC scan, or moving toward first detector
(SiPM) connection — and get fresh, exact-scope authorization before running
it, following the same discipline as RADIOROC 09-12.

## RADIOROC 11 — Evidenced status-only re-verification (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `b4706777fed7a8380dc5baa8f84dc683cb630a62`
(clean tree before this run; no source changes). The user confirmed the board
powered/bare with no SiPM/pulser and closed the manual GUI session used for
their earlier power-cycle test, then authorized exactly the existing
status-only sequence (refresh/select, Connect, one gated repeat, explicit
Disconnect, shutdown; stop on any error/unexpected value). The lead acted as
sole software operator.

Before Connect, `system_profiler SPUSBDataType` (no port opened) confirmed
`PCB_RADIOROC` / `RD3_32` still enumerated. The lead then reran the unmodified
RADIOROC 09 harness (`status_card.py`, same hash as before) against a new
output directory. Result: **passed**. Status-100 read #1 at
`07:09:24.140-07:09:24.154 UTC` and read #2 at `07:09:24.247-07:09:24.249 UTC`
both returned `00000101` (5); Disconnect and shutdown completed with no error
and no close error (`terminal_summary.json`: `status: passed`,
`accepted: true`). `source_provenance.json` for this run matches RADIOROC 09's
transport/connection-worker hashes exactly, ruling out a source-code
explanation for the improved outcome.

This meets the status-only card's "Acceptance" criteria for the first time
since the RADIOROC 07 fault, and is further evidence for **H1** (the board or
USB bridge was in a stuck state that the operator's power-cycle cleared) over
**H2** (unrelated transient fault) — support, not formal proof, since no
controlled A/B isolating the power-cycle was run. Evidence, including the
pre-Connect USB snapshot, screenshots, request/event traces, and a
12-file `complete_inventory.json`, is local under
`radioroc_runs/physical_status_20260911T070909Z/`. Full narrative in
`docs/hardware/desktop_status_recovery.md` under "RADIOROC 11 evidenced
re-verification (PASSED)".

No ASIC/FIFO access, verifier, scan, configuration write, defaults, repair,
power-cycle, push, or change to `main` occurred in this session. Configuration
restoration, scan behavior, and cancellation/close-during-run behavior remain
unverified and out of scope for this card.

Next: with the designated operator, decide whether to proceed to a fresh,
separately authorized physical threshold restoration/scan check now that
status-only communication is evidenced-recovered, or to run further
verification (for example, a repeated status-only pass after a longer idle
period) before trusting the board for scan work.

## RADIOROC 10 — Investigate status-only timeout (offline, STOPPED card unchanged)

Offline-only continuation on `feat/desktop-hardware-threshold`, working tree
clean at `9fd8665`. No hardware discovery/open, status retry, ASIC access,
verifier, scan, defaults, repair, power-cycle, or push/change to `main`
occurred; the RADIOROC 09 stopped card and its acceptance state are unchanged.

The lead reverified the RADIOROC 09 evidence inventory: all 11 tracked files
under `radioroc_runs/physical_status_20260911T051700Z/` (12 including
`complete_inventory.json` itself) match the SHA-256 hashes in
`evidence_manifest.json`, consistent with Luna's prior `offline_audit.json`.

The lead compared that run's exact request/timing/error evidence against prior
successful status reads on the same port/parameters: a 2026-09-10 CLI status
check (`status.json` in `physical_threshold_20260910T042911Z`, status 5) and
RADIOROC 07's native GUI session (`physical_desktop_20260911T015835Z`), whose
Connect and initial status read succeeded (status 5) and which then completed
two full threshold scans before a later job (`t1_cancel_window`) hit the known
`read_fifo` timeout at `02:07:27.651 UTC`. RADIOROC 09's fresh Connect, about
3 h 9 min after that fault, timed out on its very first status-100 request with
no prior successful transaction on that session. Source hashes in each run's
`source_provenance.json` show unchanged transport/connection-worker code across
all three, so a framing/software regression is unlikely on current evidence but
not excluded. A host-level offline check (`pmset -g log`) found no actual
Sleep/Wake transition between the 07 fault and the 09 attempt, ruling out an OS
sleep/USB-reset cycle as an explanation for the gap; a deeper unified-log
USB/FTDI trace could not be obtained offline in this session (`log show`:
"Operation not permitted", no Full Disk Access), which is a limitation, not a
finding.

No root cause is established. Two open, unproven hypotheses and one concrete
next test card (status-only, no power-cycle, evidence requirements, and
stop/release rules) are recorded in
`docs/hardware/desktop_status_recovery.md` under "Offline comparison and
diagnostic proposal (RADIOROC 10)". That card is a proposal only; it is not
authorized to run.

**Addendum, reported after this session's offline analysis:** the designated
operator power-cycled the board immediately after the RADIOROC 09 timeout was
found, and a subsequent native-GUI Connect succeeded (firmware status `0x05`/5
on `/dev/cu.usbserial-RD3_320`), per an operator-provided screenshot. This was
not run through the bounded evidence harness, so it lacks timestamps, a
request-level trace, an explicit repeat status read, and a recorded
Disconnect/shutdown; it does not satisfy this document's evidence standard or
the status-only card's two-read acceptance. It does strongly support **H1**
(stuck board/bridge state cleared by power-cycle) over H2. Details are in
`docs/hardware/desktop_status_recovery.md` under "Operator power-cycle
recovery (post-RADIOROC 10)".

Next: **RADIOROC 11 — <fresh authorization for the proposed status-only card,
or further offline diagnosis>**. This session does not authorize further
physical access; the existing RADIOROC 09 stopped state and two-read acceptance
gap remain current.

## RADIOROC 09 — Status-only desktop recovery (STOPPED)

On 2026-09-11 the user freshly confirmed the powered bare USB board, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the exact status-only card. Native Cocoa execution on
`feat/desktop-hardware-threshold` at `b31d024` stopped on Connect's first read.
Fresh candidates were `PCB_RADIOROC`, identity `usb:0403:6010:serial:RD3_32`;
the explicitly selected control port was `/dev/cu.usbserial-RD3_320`, baud
115200, timeout 0.5 s.

The trace records exactly one status-100 request, `aa00e40055`, beginning at
`05:16:23.144650 UTC`. It raised `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried`, with transfer elapsed
0.501775458 s. No status value or response frame was returned. Unlike the older
FIFO fault, this request is identified exactly; its cause remains unresolved.
No repeat status read, scan, FIFO access, verifier, configuration write,
initialization/defaults, repair or power-cycle occurred.

Connect's error path released the session through its owning worker. The
`05:16:25.164920 UTC` snapshot records `error`, cleared port/status and no close
error. Because the session was already released, there was no explicit
Disconnect or second close attempt. Shutdown recorded `stopped`, worker not
alive, and no close error at `05:16:25.257612 UTC`; process exit was 1.
The two-read acceptance did not pass, and configuration restoration is unknown.

Evidence is local and ignored under
`radioroc_runs/physical_status_20260911T051700Z/`: exact executed harness,
setup/authorization, fresh candidates, timestamped snapshots and request trace,
three native widget screenshots, terminal summary, console, source hashes and
SHA-256 inventory. The directory suffix is a label; actual execution was
05:16:21–05:16:25 UTC. Native GUI methods were driven programmatically with
human controls disabled; evidence does not include independent electrical
observation. The standard production transport and board lock were retained.

Sol prepared the local harness; the lead reviewed and strengthened its guards.
Five offline fake cases passed: success, unexpected first status, first-read
timeout, repeat-read timeout and failed close with live ownership retained and
no close retry. Compilation, help and default refusal passed. No production
source or packaging changed, so no development-suite or wheel rerun was needed.
Luna independently audited the saved sequence and verified all seven original
inventory entries. The lead preserved that manifest and verified an expanded
11-file inventory including console, source provenance and audit summary.
`git diff --check` passed; no push or change to `main` occurred.

Next: **RADIOROC 10 — Investigate status-only timeout**, an offline comparison of
this exact request with prior successful status evidence and the existing
transport, followed by one concrete diagnostic proposal. This stopped card
does not authorize further physical access or resuming GUI scan acceptance.

### Preparation history

Continuation started on `feat/desktop-hardware-threshold` at clean `b31d024`.
Offline source review identified that Connect/status exceptions already attempt
owner-mediated close. The recovery card now counts that attempt and explicitly
prohibits Disconnect/window-close/shutdown after `close_failed` without review,
because those actions can retry close. Successful automatic release is recorded
before shutdown; the normal success path still requires explicit Disconnect.

Documentation-only preparation; `git diff --check` passed. No hardware discovery,
open, status read, scan or configuration operation occurred. Physical acceptance
remains pending fresh setup confirmation and designated-operator authorization
for the exact card. Next task remains execution of that status-only card; the
RADIOROC 09 handoff in `NEXT_SESSION.md` remains current.

Continuation review on 2026-09-11 found HEAD still at `b31d024` with the two
existing documentation edits above, which were preserved. A bounded Luna
offline review confirmed the card matches current worker APIs and error-path
release behavior. Unexpected status values require the operator to stop;
`close_failed` retry restrictions are procedural, not enforced by the API.
`git diff --check` passed again. No source changes or hardware access occurred;
fresh setup confirmation and authorization remain the next required step.

## RADIOROC 08 — Investigate desktop pre-scan timeout

Offline investigation continued on `feat/desktop-hardware-threshold` from clean
`a1b17e6`. Version remains `0.5.0`. No hardware discovery/open, configuration
change, scan retry, repair, push or change to `main` occurred.

All 49 files in the original RADIOROC 07 SHA-256 inventory match their recorded
hashes and sizes. Source ordering and saved evidence place the failure inside
ASIC `read_fifo`, after FPGA 0/1/6 reads and before complete snapshot assignment
or any measurement. The transport error means no response bytes were received
for one unidentified read within 0.5 s. Initial word-0 read, status polling and
final FIFO read remain possible sites; there is no per-request trace to decide
which, or establish a board/USB/firmware root cause. The 60000 ms measurement
window was never reached and does not explain this pre-scan failure.

The failed manifest finished at 02:07:02.013701 UTC with 0 points/windows.
The verifier had no complete snapshot (all 3 FPGA and 130 ASIC expected entries
missing); successful cleanup commands do not establish verified restoration.
The harness recorded the latched fault at 02:07:27.651320 after SIGINT interrupted
its marker-only wait. Disconnect recorded idle with port/status cleared and no
close error at 02:07:29.171427; shutdown recorded stopped at 02:07:29.297004.
Neither GUI cancellation nor an in-window close occurred.

Local-only fixes and their report are preserved under ignored
`radioroc_runs/radioroc08_offline/`. `phase_wait.py` detects terminal outcomes,
faults, disconnect and shutdown before accepting a marker, including simultaneous
marker/fault delivery. `radioroc08_gui_card.py` integrates this for window and
first-point waits and adds a separate request trace without Qt widget access.
The original harness is unchanged. Six deterministic wait tests passed, as did
compilation, help and default refusal (exit 2). Physical execution is gated by
an explicit flag and remains unvalidated/unauthorized; the derivative runs the
scan card and must not be used for the next status-only task. Request tracing
cannot reconstruct the missing historical request and has not been tested on
a board.

The saved T2 screenshot independently confirms the previous T1 saved-result
banner above current T2 data. The minimal production UI change replaces saved
provenance when starting a new run; device logic and shared APIs are unchanged.

Checks: `.venv-foundation/bin/python tools/check_development.py` passed all
**118 offline tests**, compile checks and **15 legacy CLI help checks**, including
the new saved-result/new-run/rejected-submission GUI regression. Log:
`/private/tmp/radioroc08-development.log`. Packaging metadata is unchanged, so
no new installed-wheel check was needed. `git diff --check` passed.

The concrete next task is **RADIOROC 09 — Status-only desktop recovery**, using
`docs/hardware/desktop_status_recovery.md`. Fresh operator authorization is
required before hardware access. Connect's status read, one explicit repeat,
disconnect and shutdown are the entire card; success does not establish restored
configuration or authorize a scan. Physical cancellation/close acceptance,
word-60 semantics, wider scans and analog performance remain pending.

## RADIOROC 07 — Physical desktop threshold validation (STOPPED)

On 2026-09-11, the user confirmed the powered bare board, USB only, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the five-case desktop card. Starting tree was clean on
`feat/desktop-hardware-threshold` at handoff `086d304` (implementation `e6cddf4`).
Sol prepared a local harness and reviewed saved evidence; workers used no hardware.
No production source or packaging changed; version remains `0.5.0`.

Native macOS Cocoa GUI discovery/connect/repeat status/disconnect passed using
`.venv-foundation`. Fresh identity was `usb:0403:6010:serial:RD3_32`, control port
`/dev/cu.usbserial-RD3_320`, baud 115200, timeout 0.5 s; both status reads returned
5. Status is not a decoded firmware version. Five actual offscreen GUI previews
passed without creating a worker or run directory before physical execution.
Config was the explicit `configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

| Native GUI case | Points / windows | Result | Verification |
| --- | --- | --- | --- |
| T1, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T2, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T1, DAC 0, 60000 ms, intended in-window Cancel | 0 / 0 | failed before measurement | incomplete |
| T1, DAC 0..2, 1000 ms, Cancel after first point | — | not executed | — |
| T1, DAC 0, 60000 ms, close during run | — | not executed | — |

All submitted cases used one average, masks on, Ctest off, gain unchanged,
FPGA initialization/default application off and mandatory verification. Normal
T1/T2 terminal displays and saved reopening passed; the session stayed connected.
Their 130 ASIC rows exactly match snapshot/expected/observed values. FPGA words
0/1/6 were `00111111` / `00000000` / `00000000`, matching both verifier passes.
Manifest/CSV counts agree; all four measured rates were 0 Hz. No cleanup,
persistence or verifier errors occurred in these two cases.

The third job recorded `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried` during snapshot
acquisition. Status, preparation and FPGA 0/1/6 reads completed; the 130-row
ASIC `read_fifo` did not return a complete snapshot. No trigger-mask, DAC,
channel-selection or counter operation was reached. The exact failed serial
request within `read_fifo` is not recorded. Cleanup commands succeeded (`restored`), but verification was
`incomplete` because all snapshot entries were absent. This does not establish
verified restoration. No counter-window phase marker or GUI Cancel request
occurred; the intended cancellation test did not reach measurement.

The GUI latched the fault. The local harness was still waiting for its phase
marker, so the lead interrupted that wait with SIGINT after the job had already
failed. Its error handler explicitly disconnected through the owning worker:
state became idle with port/status cleared and no close error, then stopped on
window shutdown; process exit was 1. This SIGINT is not GUI cancellation evidence.
No subsequent scan, repair, initialization/default write or retry occurred.
Hardware configuration was not re-verified after the fault.

Evidence remains local and ignored under
`radioroc_runs/physical_desktop_20260911T015835Z/`: setup and previews, native
widget screenshots/text, timestamped GUI/worker records, three manifests and CSV
pairs, console log, exact local harnesses, two-run equality audit, stopped
summary and SHA-256 inventory. Native controls were driven programmatically;
there was no continuous screen recording or independent electrical observation.
Completed plots were captured, but intermediate point display was not separately
captured. An observed UI issue remains: starting hardware Run after reopening a
saved result leaves the prior saved-result banner visible over the new plot.
The harness phase wait also needs immediate fault detection before future use.

Checks: actual GUI previews, native connection preflight, two successful physical
runs/reopens, exact offline saved-data audit, and `git diff --check`. No new
production-source suite or wheel check was needed; prior 117-test evidence below
is unchanged. Main, lab environments and all measurements were preserved.

Next: **RADIOROC 08 — Investigate desktop pre-scan timeout**. Review the saved
failure offline, improve fault/evidence handling, and prepare a bounded
status-only recovery card before further physical access. The timeout cause is
unresolved; cancellation and close-during-run acceptance remain pending.

## Current checkpoint

**RADIOROC 06 — Desktop hardware threshold workflow** is implemented on
`feat/desktop-hardware-threshold` at `e6cddf4`, based on `b10cf57`. Version remains `0.5.0`;
packaging metadata and legacy entry points are unchanged.

- The persistent `ConnectionWorker` owns the transport, device, shared
  `ThresholdJob`, mandatory restoration verification, disconnect and close retry
  on one thread. Hardware Run uses this owner rather than a competing worker.
- Preview stays offline. Entering hardware mode defaults FPGA initialization
  and ASIC defaults application off; their controls identify persistent changes.
  Temporary scan settings are restored and independently verified.
- Live points, cancellation, saved results and shutdown use the shared job.
  Normal terminal delivery retains the connection after cleanup/verification.
  Shutdown cancels and waits; a new job fault holds shutdown for visible review.
- Job, cleanup, persistence, verification and close faults block another scan.
  Disconnect and explicit fault-review acknowledgement are required before a
  new connection. Failed close retains ownership for an explicit retry.
- Reopening a manifest with failed/incomplete verification preserves its data
  and shows an incomplete result, even if the primary scan completed/cancelled.

Sol implemented/tested the owner, Terra implemented/tested the GUI, and Luna
updated workflow documentation and the separate pending physical GUI card. The
lead reviewed ownership/publication contracts and integrated saved-reader and
installed-artifact checks. No hardware discovery/open/scan, environment diagnostic,
persistent configuration write, push or change to `main` occurred.

Validation on macOS ARM64 / Python 3.13:

- `.venv-foundation/bin/python tools/check_development.py`: **117 offline tests**,
  compile checks and all **15 legacy CLI help checks** passed. New coverage
  includes same-thread session/job/verifier ownership, cancellation and queued
  shutdown, fault latching/review, defensive snapshots, GUI gating and terminal
  delivery order, and saved verification-fault visibility.
- Source distribution and `0.5.0` wheel built with `python -m build --no-isolation`.
  Installed core-only checks passed with Qt absent in `.venv-wheel-core`.
  Installed GUI/plot checks passed outside the checkout using a temporary venv
  with development dependency paths; the wheel itself was installed there.
  The GUI check completed/reopened simulation and exercised the persistent
  hardware job route with a fake transport and passing mandatory verification.
- `git diff --check` passed. Logs and built artifacts remain local under
  `/private/tmp/radioroc06-*`; no generated files or measurement data are committed.
  The foundation editable installation and lab environment were preserved.

Hardware state was not refreshed: the last physical evidence is RADIOROC 05
below, whose historical port/status must not be treated as current. Native GUI
hardware behavior and physical GUI restoration remain unvalidated. Fake transport
tests establish software behavior only; word 60 semantics and analog performance
remain outside this slice.

Next: **RADIOROC 07 — Physical desktop threshold validation**, using
`docs/hardware/desktop_threshold_validation.md`. Its fresh equipment summary and
operator authorization are separate from the completed CLI card.

## RADIOROC 05 — Physical threshold restoration checks

The physical threshold restoration card passed on 2026-09-10 in
**RADIOROC 05 — Physical threshold restoration checks**, on
`test/physical-threshold-restoration`, based on authorization handoff `3c0f82a`
and verifier implementation `4c6d254`. Package version remains `0.5.0`.
Desktop hardware Run was disabled at that checkpoint; RADIOROC 06 above enables it.

The lead was the sole software board operator, using the authorization recorded
in the preceding handoff: powered bare board over USB, no SiPM/pulser, competing
vendor software and terminals closed. Sol reviewed cancellation instrumentation
and audited saved evidence offline; Luna updated the physical card.

Physical evidence is preserved locally and ignored under
`radioroc_runs/physical_threshold_20260910T042911Z/`: discovery/status JSON,
exact preview/execution arguments, preview logs, full console output, exit codes,
four manifests and CSV pairs, process-local cancellation launcher, audit summary
and SHA-256 evidence inventory.
No measured data is committed. Host: macOS 15.1 ARM64. Fresh USB identity:
`usb:0403:6010:serial:RD3_32`; control port `/dev/cu.usbserial-RD3_320`,
115200 baud, 0.5 s timeout. Status word 100 read `00000101` (5), and close
succeeded. This is a status value, not a decoded firmware version. Board revision
was not independently identified; ambient conditions were not measured.

| Physical case | Completed points / windows | Exit | Restoration verification |
| --- | --- | --- | --- |
| T1, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T2, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T1, DAC 0, 60000 ms window, cancel during window | 0 / 0 | 130 | passed |
| T1, DAC 0..2, 1000 ms, cancel after first point | 1 / 1 | 130 | passed |

Every command was previewed offline before execution, used channel 4, one average,
mask isolation, `--skip-fpga-init` and `--verify-restoration`, and omitted
`--apply-defaults`. Each run captured 130 ASIC rows (the variant's two DAC rows,
64 discriminator rows and 64 masks) plus FPGA 0/1/6. Exact FPGA snapshots in every
case were `00111111` / `00000000` / `00000000`; both verifier FPGA passes and
ASIC comparison matched. Job/verifier cleanup succeeded, manifests and CSV row
counts agreed, and there were no persistence or CLI close errors. All completed
windows had zero counts (0 Hz). Configuration:
`configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

Cancellation used a process-local launcher around the unchanged CLI. The window
hook raised SIGINT after the first 10 ms delay slice, which the production loop
reaches after counter enable and before stop/read. The point hook raised SIGINT
from the event callback after the first point and manifest were persisted. Phase
markers and exit 130 establish the real CLI signal-handler/cancellation path;
this was programmatic SIGINT, not a human keystroke. Window phase evidence is
software call ordering, not independent observation of a counter-active signal.

Checks: all four physical acceptance cases and saved-evidence assertions passed.
An independent offline audit confirmed byte-for-byte snapshot/expected/observed
equality, exact variant row coverage, preview/manifest agreement and CSV counts.
`git diff --check` passed; evidence is ignored and `main` remains at `b77f76d`.
No production source or packaging changed; no new development-suite or wheel run
was required (preceding 108-test offline checkpoint remains below). The lab Python
does not have an installed `radioroc` module, so discovery used the preserved
`scripts/radioroc_list_ports.py` entry point after module invocation failed before
hardware access. All physical scans used the documented legacy script entry point.

Limits: word 60 is verified only as a successful idle write; ASIC readback protocol
semantics and analog behavior are not independently established by equality alone.
Ctest/gain changes, other channels, wider DAC ranges, detector measurements,
Linux/Windows USB and native desktop hardware ownership remain outside this card.
Next: **RADIOROC 06 — Desktop hardware threshold workflow**, with explicit
preparation choices, shared job ownership, cancellation and readback verification.

Delivery 2 remains at `6c44092` on `feat/transport-ownership`; `782014f` recorded
its validation and threshold-job handoff.

All commits are local; no push, PR or remote CI run has been performed.
`main` remains at the original `b77f76d` baseline. The development branch
contains the preceding checkpoints:

- `e3d3b3d`: acquisition, scan and analysis workflows, preset and tests.
- `352418a`: June/July lab notes and their result figures.
- `603c69b`: rebuild plan and exclusions; tag `pre-desktop-rebuild` on
  `chore/lab-baseline`.
- `81ee287`: installable package, CLI and offline development checks on
  `build/python-foundation`.

The five experiment folders were recovered from local Git snapshot
`9c1da1e65fe2384f39c680f5b29add8ca341d2b6`: 27 files verified against blob hashes.
They are present locally and ignored. Other saved runs remain in `radioroc_runs`.
No separate external backup has been configured. Recovery verifies snapshot
bytes, not any unrecorded later changes.

## Threshold restoration verifier: implemented and checked offline

- `ThresholdJob.run(..., verify_restoration=True)` and the existing CLI's
  `--verify-restoration` opt in to independent readback after scan cleanup,
  under the same transport owner and job lock. Unflagged behavior is preserved.
- The verifier compares measured FPGA words 0/1/6 and all configured T1/T2 ASIC
  snapshot rows. It captures post-job FPGA state before ASIC reads, then idles
  word 60, restores exact observed word 0 (including its I2C active bit), and
  rereads FPGA state. It never repairs or hides a scan-restoration mismatch.
- Missing snapshots and incomplete payloads cannot pass; no missing value is
  supplied from the configuration table. Verification is a separate report in
  the result and manifest, preserving primary/scan-cleanup/persistence errors.
  Close errors are separately printed even when other failures coexist. Save
  console output: close occurs after the manifest's terminal write.
- The reviewed offline implementation and updated card are ready for operator
  review. The physical card was not executed at this offline checkpoint; see the
  RADIOROC 05 results above. Desktop hardware Run remains disabled; no new UI or device workflow was enabled.

Validation on macOS ARM64 with `.venv-foundation`:

- `python tools/check_development.py`: **108 offline tests** passed, with compile
  checks and all **15 legacy CLI help checks**. The 13 new verifier tests cover
  T1/T2 full register sets, exact transport ordering, active-bit restoration,
  same-session locking, completed/in-window/after-point cancellation, missing
  snapshots, short readback, FPGA/ASIC mismatches, verification/read/cleanup/close
  failures and CLI exit statuses/offline isolation.
- The card's two-point T1 preview passed with `.conda-radioroc/bin/python`, using
  a placeholder port; it created no output directory. This was a dry-run only.
- `git diff --check` passed. No packaging configuration changed, so a new wheel
  build/install check was not required. The development environment now uses an
  editable checkout; the lab environment and measured data were preserved.
- No hardware scans, discovery, physical open, diagnostic enumeration, push or
  remote CI occurred. `main` remains unchanged.

Limits: fake tests establish software behavior, not physical register semantics.
Word 60 readback remains unresolved; its idle-write success is recorded without
claiming readback verification. A passing verifier does not erase job cleanup
errors. Manual CLI Ctrl-C timing does not prove cancellation inside a counter
window because that phase has no explicit start event; establish phase evidence
before accepting the physical cancellation case. Bare-board rates cannot establish
analog response or detector performance. The subsequent RADIOROC 05 physical
acceptance results are recorded above.

## Delivery 4 connection slice: implemented and checked

- Lazy, Qt-independent connection worker with a bounded command mailbox and
  immutable snapshots. Discovery, transport creation/open, status reads and close
  stay on its own thread; no startup discovery occurs.
- Explicit USB candidate refresh/selection, baud/timeout settings, connect,
  status-word 100 read and disconnect. Candidates are labelled unverified;
  simulation and hardware session controls cannot overlap in one window.
- Existing serial transport and board lease are reused. Invalid overlapping
  operations are rejected atomically. Busy, timeout, protocol, I/O and close
  errors retain their exception names. Failed close retains the owned session
  for explicit retry, including failure during partial open. Window shutdown
  waits for session release and leaves close failures visible.
- Hardware threshold Run is disabled. The separate card at
  `docs/hardware/bare_board_threshold_validation.md` specifies the exact register
  boundary, preparation, cancellation and independent restoration checks. It is
  **not executed**; a verification helper that restores its own I2C side effects
  is the next implementation task.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **95 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 14 new tests cover
  connection ownership, command gating, partial-open/close retry, real transport
  framing/lease integration with fake serial, GUI selection, error presentation
  and responsive shutdown. No hardware is enumerated by these checks.
- Source distribution and 0.5.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for simulation/reopen, fake connection/disconnect,
  disabled hardware Run and headless plotting outside the checkout.
- Native macOS Cocoa launch passed fake connect/status and owned shutdown. Visual
  inspection found clipped controls; the corrected layout was launched and
  inspected again. Screenshot remains local at
  `/private/tmp/radioroc-connection-native.png`.
- `git diff --check` passes. No physical board discovery/open or configuration
  writes occurred. Lab data and environments were preserved; development wheel
  environments were updated. No push, PR or remote CI run was performed.

Limits: physical desktop connection/disconnect has not been exercised on the
board. Native validation used a clearly labelled fixture. Linux/Windows GUI,
USB behavior and bundling remain unvalidated; status bits are not decoded into
unverified firmware capabilities. Readback-based scan restoration remains pending.

## Delivery 4 simulation slice: implemented and checked

Committed at `ef92eeb` on `feat/desktop-threshold-simulation`, version `0.4.0`;
handoff at `cf35315`.

- Optional PySide6/Matplotlib desktop entry point `radioroc-desktop`, while the
  core/CLI wheel remains importable and usable without Qt or a display server.
- Configure channels, DAC range/step, counter window, averages, T1/T2, mask,
  Ctest, gain and preparation options; offline preview exposes persistent versus
  temporary settings and creates no output/session.
- A deterministic, configurable logistic threshold simulator drives the actual
  `ThresholdJob.run` device/register path. Every screen, plot and reopened run
  labels synthetic data as simulation; model parameters are saved in metadata.
- A worker owns session create/run/close on one background thread. The UI polls
  a bounded/coalesced display mailbox while the shared writer independently saves
  every completed counter window and DAC row. Cancellation and window close wait
  for cleanup and session release; cleanup/storage/close failures remain visible.
- Saved-run reading validates manifest/CSV schema, channels, DAC order, point
  counts and finite nonnegative rates. It salvages only a valid prefix, labels
  nonterminal/inconsistent runs incomplete and opens legacy CSVs with unknown
  provenance. It never resumes or rewrites a run.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **81 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 26 added tests cover the
  simulator, worker/session ownership, coalescing of all 1024 DAC rows, cancellation,
  close faults, saved-run validation and Qt workflows.
- Source distribution and 0.4.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for configure/preview/run/plot/reopen using Qt offscreen.
- A native macOS Cocoa launch displayed, completed and reopened a 41-point,
  two-channel simulation. The window remained responsive and was captured for
  local visual inspection; the temporary run and screenshot were not added to Git.
- No physical device was enumerated or opened. Ignored experiment folders and
  `radioroc_runs` were preserved. No remote CI, push or PR was performed.

Limits: the simulator is a deterministic workflow exerciser, not an analog/noise
model. Desktop hardware mode is visibly unavailable. Linux desktop launch,
application bundling and Windows GUI execution remain unvalidated. The saved-run
reader is for truthful display, not crash repair or resume.

## Delivery 3: implemented and checked

- `ThresholdJob` / `ThresholdJobConfig` provide a synchronous worker-friendly API.
  The existing threshold CLI and `device.run_threshold_scan` use that runner.
  Existing arguments, counter sequences, DAC encoding and result columns/rates
  are retained; validation now rejects invalid DACs, duplicate channels and
  nonfinite/nonintegral settings before device access or file creation.
- Structured state/point events, cooperative cancellation including I2C ready
  polling and counter windows, Ctrl-C exit handling, and immediate rejection of
  overlapping jobs on one transport session (including multiple device wrappers).
- A manifest exists before preparation. Completed windows and DAC points are
  appended/flushed/fsynced to compatible CSVs. Atomic manifests record status,
  effective table/configuration, snapshots, firmware, source fingerprint, units,
  version, board identity when available and separate cleanup/storage errors.
  Existing run files are never truncated by a new job.
- Captured temporary threshold/gain/mask/Ctest/discriminator and FPGA settings
  are restored; uncaptured ASIC settings are never invented. Cleanup errors do
  not replace the primary failure. Explicit initialization/default application
  remains intentional preparation and persists; interrupted preparation is
  labelled unknown/possibly partial. Memory-transport results are simulated.
- Threshold dry-run validates/previews without serial construction/discovery,
  measurements or output files. Other workflows are unchanged.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **55 offline tests** pass (30 preceding, 25 threshold lifecycle tests),
  plus compile checks and all 15 legacy CLI help checks through
  `python tools/check_development.py`.
- Tests compare complete API/CLI fake-device command traces and CSV bytes; check
  known rates/counts, T1/T2, multiple channels, Ctest, gain, explicit preparation,
  complete captured-state restoration and legacy source execution.
- Fault tests cover cancellation before acquisition, during I2C polling, during
  a long counter window, mid-point and after a point; CLI SIGINT; timeout and
  disconnect; cleanup failure alone/with a primary error; snapshot/preparation
  failure; disk/manifest failure; output collisions; callback failure; concurrent
  session jobs. A subprocess abrupt exit retains a readable point and leaves
  status running with cleanup pending. Existing subprocess board-lock tests pass.
- Source distribution and wheel build with `python -m build --no-isolation`.
  The 0.3.0 wheel is installed in `.venv-foundation`; isolated installed-wheel
  checks outside the checkout pass for resources, all 15 commands, an executed
  synthetic threshold job, genuinely offline preview and headless PNG rendering.
- No physical device was opened in this session. The lab environment, ignored
  experiment folders and `radioroc_runs` were preserved. No remote CI/push/PR.

Delivery 3 limits and follow-ups:

- Physical snapshot/restore behavior, scan timing and throughput remain untested.
  `restored` means restoration commands succeeded, not verified readback. I2C
  control word 60 is idled instead of replaying its command strobe.
- Persistent storage failure can prevent terminal metadata; the result reports
  persistence errors, while the last manifest may lag. Crashed/incomplete runs
  must not be shown as completed; recovery readers should validate any unconfirmed
  CSV tail. There is no resume/recovery service yet.
- The caller owns transport open/close and must surface connection/close failures.
  The whole-job lock covers threshold jobs only; unmigrated workflows and direct
  primitive calls must not run concurrently. Cancellation waits for bounded I/O;
  cleanup can require many transactions and is not instantaneous.
- The memory backend and scripted test transport are not an analog simulator.
  Delivery 4 needs a labelled threshold simulator and a UI worker adapter with
  a bounded/coalesced event queue. No Qt/UI code is included in this delivery.
- Existing T1/T2 shared-register write encoding and table-based mask/gain updates
  were preserved. Compare those semantics with the vendor before broader register
  refactoring. Other commands' offline dry-run, acquisition/autocalibration jobs,
  HG/LG mapping, Windows parity and Linux hardware checks remain separate work.
- Local commit identity follows preceding commits (Tengiz Ibrayev,
  `tengiz@agqhcqjdw32.tail819d22.ts.net`); confirm it before publication.

## Earlier deliveries: implemented

- Installable shared Python package, retaining original script paths and core
  imports. `radioroc` / `python -m radioroc` now dispatch 15 commands, including
  the new read-only port candidate listing.
- Packaged default configuration and presets, independent of working directory.
  Base dependencies are pySerial and filelock; plotting/build tools are optional.
- One framed serial transport used by the core, legacy autocalibration and
  serial-probe scripts. Exact existing request bytes and write chunking retained.
- Validated request bounds, bounded fragmented reads/output waits, explicit
  timeout/protocol/I/O errors and no automatic request retries. Failed ASIC
  readback raises instead of returning unmeasured defaults.
- Cooperative OS-backed ownership across both USB interfaces of a board, keyed
  by USB identity, acquired before opening serial. Normal close and process exit
  release ownership; failed close retains ownership for a later close attempt.
- Offline source and installed-wheel checks; GitHub Actions configuration for
  Ubuntu/macOS and Python 3.11/3.13; development and agent instructions.

## Delivery 2 validation (historical)

Local platform: macOS ARM64, Python 3.13. Development uses `.venv-foundation`.
The existing `.conda-radioroc` lab environment received the new filelock
dependency (3.32.6); the source checks pass there as well.

- All 30 unit tests pass (nine existing, 21 new), including malformed/fragmented
  replies, embedded frame delimiters, timeouts/disconnects, no retries, failed
  readback, open/close cleanup and real subprocess ownership/release after kill.
- Compile checks and all 15 CLI help commands pass.
- Source distribution and wheel build successfully. Editable installation was
  checked; `.venv-foundation` had the built 0.2.0 wheel at that checkpoint
  (now updated to 0.3.0 above).
- Installed-wheel checks pass outside the checkout: imports/transport aliases,
  default table byte equality/677 rows, presets, version and all CLI help pages.
  A synthetic threshold CSV renders to PNG with the headless Matplotlib backend.
- Read-only hardware status on `/dev/cu.usbserial-RD3_320` returned address 100
  as `00000101` (5). While that connection was held, a second process targeting
  `/dev/cu.usbserial-RD3_321` received `DeviceBusyError` before opening serial.
  The owner then closed and released the lease. No configuration writes were
  issued. See `logbooks/2026-09-09.md`.

## Limits and outstanding work

The earlier planning-time status-read failure did not recur; its cause was not
established. Successful status and lock checks do not validate scans or Windows
feature parity. The board is powered, with no SiPM or pulse generator connected
according to the user; the connection was closed after testing.

CI has not run remotely. Linux/Debian installation, physical USB behavior on
Linux and desktop bundling remain unvalidated. The desktop supports the threshold
workflow in simulation. Desktop hardware connection/status is implemented but
physically unvalidated; hardware scan execution remains disabled. The feature
inventory is preliminary and still needs comparison with the actual
Windows 2.2.0.5 application.

Ownership coordinates participating programs for the same OS user with a local
home filesystem. It cannot exclude vendor D2XX programs or other nonparticipating
clients. Missing USB metadata can prevent grouping both interfaces; duplicate
USB serial numbers conservatively collide. Candidate discovery does not identify
the control interface automatically. See `DEVELOPMENT.md` for the full contract.

Response metadata bytes 1–2 remain opaque. Without verified correlation fields,
same-shaped stale replies cannot reliably be rejected. The 65536-byte request
boundary is tested offline only; the vendor wrapper caps it at 65535.

Transaction locking and the threshold job lifecycle are implemented. Other
workflows still need whole-job migration; some legacy dry-run commands still
open ports. HG/LG nibble mapping and state restoration outside threshold scans
remain tracked migration concerns. Do not mix workflows on one session.

## Next bounded tasks

1. Done as of RADIOROC 12: physical threshold restoration checks (including
   both cancellation cases and close-during-run) passed on the desktop GUI
   workflow with independent readback verification. See RADIOROC 12 above and
   `docs/hardware/desktop_threshold_validation.md`.
2. Review/integrate the local branches and run configured CI when publishing is
   authorized; check the intended Git author identity before publication.
3. Expand the Windows parity inventory into control-level acceptance criteria.
4. Done: the desktop hardware threshold workflow is enabled (`e6cddf4`) and its
   full required case set now has physical evidence (RADIOROC 12). Remaining
   desktop-hardware work is wider DAC/scan ranges, Ctest/gain variation, and
   any detector (SiPM/pulser) connection — each needs its own bounded,
   separately authorized card.

At each checkpoint, record the commit, checks, hardware state, limitations and
one next task. Move unrelated discoveries into this backlog.
