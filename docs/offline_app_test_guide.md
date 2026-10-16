# Offline app test guide (no equipment)

This guide is for a tester (person or AI assistant) checking the RADIOROC desktop
app with **no board, generator or SiPMs connected**. Its job is to find bugs and
usability problems a student would hit. Report what you find; don't fix it.

## Ground rules

- **No hardware.** Don't run `scripts/radioroc_env_check.py` (it enumerates USB
  devices), and don't run any script with `--execute`. Don't pick "Hardware
  connection" and press Connect. Even with nothing plugged in, keep to
  Simulation.
- **Don't change the code or the git state.** Work on branch
  `lab/newest-app-test` as it is. Don't commit, push, reset, stash or switch
  branches. If you want to try a fix, describe it in your report instead.
  Claude is maintaining this branch, and parallel edits will collide.
- **Never delete or edit anything in `radioroc_runs/`**: it holds real measured
  data. You may *open* runs from it in the app (read-only). Write your own
  simulation outputs to a new folder, e.g. `radioroc_runs/simulation/test_<date>/`.
- Use `.venv-foundation`, not `.conda-radioroc`, which lacks the GUI library.

## Setup

```bash
cd /Users/tengiz/weeroc
git status                     # should show branch lab/newest-app-test, no changes
.venv-foundation/bin/radioroc-desktop
```

Automated checks, about a minute (all 487 should pass, with none skipped):

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg \
  .venv-foundation/bin/python tools/check_development.py > /tmp/check.log 2>&1; echo EXIT $?
grep -E "^Ran|^OK|FAILED|skipped=" /tmp/check.log
```

## Layout

The sidebar has three pages.

- **ASIC config.**: the shared connection panel plus tabs Main, Channel config,
  input DAC, Threshold calibration, Probes/Masks and Registers. These need a
  board; offline you can only check layout, hover hints and input validation.
- **Acquisition**: collects events and shows HG/LG spectra.
- **Calibration**: tabs Threshold scan, Hold scan, S-curve and Autocalibration.

**Every scan tab opens in hardware mode.** Set "Device / mode" to
**Simulation** first. Autocalibration has no simulation; offline you can only
reopen saved results.

## What to test

For each, note what you did, what you expected and what happened, with a
screenshot if useful.

1. **Threshold scan (Simulation)**: channels 4,5,6; run, Cancel mid-run, run
   to completion; Log Y; "Open saved result…" on your own run and on a real run
   (e.g. `radioroc_runs/step1_pedestal_ch4_6_32_20261016T052958Z/scan`). Is the
   saved run labelled HARDWARE vs SIMULATION correctly? Do reopened values match?
2. **Hold scan (Simulation)**: internal and external modes, different
   delay ranges and steps, invalid inputs (min > max, step 0). Reopen a real run
   (e.g. `radioroc_runs/step5_hold_selftrig_ctest_ch4_20261016T054013Z/scan`).
3. **S-curve (Simulation)**: a basic run and reopen.
4. **Acquisition (Simulation)**: 1 channel and all 8 channels; several batches.
   - Check the status says "N events (M channel rows)", with M = N × channels.
   - Check the plot stays usable with the window resized to **1024×768**; this
     matters on the lab display.
   - Check HG/LG switch, bins, Log Y, Clear plot, per-channel checkboxes.
   - Cancel mid-run, then reopen the partial run: is the data readable and the
     status honest?
   - A long run (many batches): does the window stay responsive, and can you
     Cancel promptly?
   - Reopen a real run: `radioroc_runs/acq_ctest_selftrig_ch4_20261016T062341Z/acq`
     should show 100 events (100 channel rows).
5. **Autocalibration**: reopen the operator's real run
   `radioroc_runs/hardware/20261016-155312-11f4dd6c/autocalibration_metadata.json`.
   Is the result understandable?
6. **General**: hover hints (bottom bar) on controls, closing the window
   during a simulated run, error messages for bad input (e.g. channel 64,
   duplicate channels), whether anything a student needs is confusing or
   missing.

## Known issues (don't re-report, but do note if they look worse)

- Board hangs on large I2C transfers (hardware only).
- No Ctest control on the Acquisition tab (planned).
- Hold scan can't set the second coincidence channel (planned).
- HG/LG shaper-gain fields may be swapped (hardware evidence, under investigation).
- Connection errors can be briefly overwritten by the next status update.

## Report format

Write findings to a new file, e.g. `docs/app_test_report_<date>.md` (the one
file you may add), or paste them back to the operator. For each finding give:
severity (blocks a student / annoying / cosmetic), steps to reproduce, expected,
actual, and the screenshot or saved-run path.
