# RADIOROC Refactor Checklist

This file is the working checklist for turning the current RADIOROC scripts from
prototype code into a readable, reusable library plus small command-line tools.
Tick items as they are completed. Keep changes small enough that each step can be
tested on the board or with compile checks before moving on.

## Current Live Hardware Setup

- RADIOROC 2 board connected over USB serial.
- Signal generator configured for external-triggered burst mode.
- Pulse settings: 1 kHz equivalent repetition setup, 500 mVpp, 100 ns pulse width.
- FPGA `IO1` is connected to the signal generator trigger input.
- `IO1` synchro pulse was found on FPGA IO mux index `5`.
- Generator output is attenuated before the RADIOROC `in-test1`/Ctest input.
- Known-good synchronized Ctest command pattern uses:
  - `--sync-io io1`
  - `--sync-io-mux-index 5`
  - `--use-ctest`
  - `--hold-synchro-trigger`
  - channel `4`

## Phase 0: Safety And Baseline Preservation

- [x] Confirm `main` is clean before each refactor chunk.
- [ ] Keep `scripts/radioroc_standard_scurves.py` working until replacement scripts are verified.
- [x] Add a short smoke-test command list for known-good workflows.
- [x] Record current known-good commands for:
  - [x] threshold scan / SiPM staircase
  - [x] external track-and-hold Ctest scan
  - [x] external peak-sensing Ctest scan
  - [x] IO mux scan
  - [x] sync pulse test
- [ ] Decide whether old monolithic script will be kept as compatibility wrapper or deprecated.

## Phase 1: Library Skeleton

- [x] Create `radioroc_client.py` as the reusable library layer.
- [x] Move constants into named library constants:
  - [x] default serial port
  - [x] default baud rate
  - [x] default config path
  - [x] channel count
  - [x] FPGA IO names
  - [x] vendor control words with explanatory names
- [x] Move bit/serial-frame helpers into the library:
  - [x] `bits`
  - [x] `parse_bits`
  - [x] `encode_read_request`
  - [x] `encode_write_request`
  - [x] `parse_channels`
- [x] Add module-level docstring explaining library purpose and boundaries.
- [x] Add type annotations to all public functions and class attributes.
- [x] Add attodry-style docstrings to all public functions/classes:
  - [x] summary
  - [x] `Inputs`
  - [x] `Returns`
  - [x] safety or hardware side effects where relevant

## Phase 2: Core Device API

- [x] Move `RadiorocSerial` into `radioroc_client.py`.
- [x] Rename or wrap `RadiorocOps` as `RadiorocDevice`.
- [x] Split low-level concerns inside the library:
  - [x] raw FPGA word reads/writes
  - [x] ASIC I2C register reads/writes
  - [x] FIFO transactions
  - [x] default config loading/apply/verify
- [x] Add explicit `dry_run` behavior to the library, not only to CLI scripts.
- [x] Add a `RadiorocConnectionConfig` dataclass.
- [x] Add a `RadiorocRunMetadata` dataclass for timestamp, command settings, git commit, port, and board firmware/status word.
- [x] Add cleanup/restore helpers for FPGA/ASIC state after scans.

## Phase 3: Scan Configuration And Results

- [x] Add dataclasses for scan inputs:
  - [x] `ScurveConfig`
  - [x] `ThresholdScanConfig`
  - [x] `HoldScanConfig`
  - [x] `SyncPulseConfig`
  - [x] `IoMuxScanConfig`
- [x] Add dataclasses for scan results:
  - [x] `ScurveResult`
  - [x] `ThresholdScanResult`
  - [x] `HoldScanResult`
  - [x] `SyncPulseResult`
  - [x] `IoMuxScanResult`
- [x] Ensure scan functions return result objects instead of only printing/writing files.
- [x] Keep CSV output support, but make file writing a library helper or CLI choice.
- [x] Write `metadata.json` beside each run CSV.
- [x] Standardize output directory naming.
- [x] Add validation methods that reject invalid settings before writing hardware.

## Phase 4: Thin CLI Scripts

- [x] Replace the monolithic scan CLI with small scripts:
  - [x] `scripts/radioroc_apply_defaults.py`
  - [x] `scripts/radioroc_scurve.py`
  - [x] `scripts/radioroc_threshold_scan.py`
  - [x] `scripts/radioroc_hold_scan.py`
  - [x] `scripts/radioroc_sync_pulse.py`
  - [x] `scripts/radioroc_io_mux_scan.py`
  - [x] `scripts/radioroc_check_connection.py`
- [x] Each CLI should have:
  - [x] a `build_parser()` function
  - [x] a `main() -> int` function
  - [x] explicit exit codes
  - [x] concise `--help`
  - [x] no direct hardware logic beyond calling `radioroc_client.py`
- [x] Remove overloaded flag combinations from user-facing commands.
- [x] Add named command presets for common workflows.
  - Implemented as Phase 5 config-file presets.

## Phase 5: Presets

- [x] Add `configs/presets/`.
- [x] Add JSON or YAML presets for:
  - [x] channel-4 SiPM dark threshold scan
  - [x] channel-4 synchronized external track-and-hold Ctest scan
  - [x] channel-4 synchronized external peak-sensing Ctest scan
  - [x] channel-4 internal hold Ctest diagnostic
  - [x] IO1 mux-index-5 sync pulse test
- [x] CLI scripts should support `--preset PATH`.
- [x] CLI arguments should be able to override preset fields cleanly.

## Phase 6: Plotting And Analysis

- [x] Move shared CSV loading and latest-run discovery into a plotting/helper module.
- [x] Keep `plot_threshold_scan.py` and `plot_hold_scan.py` as thin wrappers.
- [x] Add a comparison plot helper for conversion-delay scans.
- [x] Add a summary helper that extracts:
  - [x] threshold scan peak/staircase landmarks
  - [x] hold scan peak/plateau timing
  - [x] invalid internal hold code-zero point
- [x] Make plot titles and labels consistent.

## Phase 7: Testing

- [x] Add import/compile checks for every script.
- [x] Add unit tests for pure functions:
  - [x] bit formatting/parsing
  - [x] serial frame encoding
  - [x] channel parsing
  - [x] CSV parsing
  - [x] scan config validation
- [x] Add fake serial/backend support for non-hardware tests.
- [x] Add live hardware smoke tests as documented commands, not automatic CI tests.
- [x] Test on board after each CLI replacement:
  - [x] sync pulse
  - [x] IO mux scan
  - [x] short threshold scan
  - [x] short external hold scan

## Phase 8: GUI Readiness

- [ ] Add progress callback support to long scan functions.
- [ ] Add cancellation callback/event support to long scan functions.
- [ ] Ensure library scan functions do not call `argparse` or depend on terminal IO.
- [ ] Replace direct `print` calls in library code with callback/log hooks or returned messages.
- [ ] Define stable library API examples for GUI use.
- [ ] Keep write-capable operations explicit and easy to confirm in a GUI.

## Phase 9: Documentation

- [x] Update `README.md` to describe the new library/script layout.
- [x] Add `README_tools.md` similar to the attodry folder.
- [x] Add a short "known-good lab setup" section.
- [x] Add a "what each scan means physically" section:
  - [x] S-curves
  - [x] threshold scan / SiPM staircase
  - [x] internal hold
  - [x] external track-and-hold
  - [x] external peak sensing
- [x] Keep dated logbooks for meaningful hardware results only.

## Phase 10: Cleanup

- [x] Remove or deprecate duplicated logic after new scripts are verified.
- [x] Decide final fate of `scripts/radioroc_standard_scurves.py`.
  - Kept as legacy compatibility/reference script for now.
- [x] Ensure ignored local artifacts stay out of git.
- [x] Run final compile/import checks.
- [ ] Commit and push each completed group with a clear message.
