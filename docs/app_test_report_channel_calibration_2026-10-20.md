# App test report: channel selection and calibration workflow (2026-10-20)

Task: `docs/gpt_visual_task_channel_and_calibration.md`. Tester: Claude (AI assistant).

**How it was run.** No board was connected and Connect was never pressed. The app was not
driven by mouse on a real screen. Instead, a script built the real `MainWindow` (the same
class `radioroc-desktop` starts) with `QT_QPA_PLATFORM=offscreen` from `.venv-foundation`.
The script then pressed the app's own buttons (`click()` on channel buttons, Run,
Select none and so on), switched sidebar pages and tabs, and saved each screenshot with
`QWidget.grab()` at 1280×900. Only "Open saved result…" was called directly through
`open_saved(path)`, which skips the file dialog. Code and git state were not changed. Simulation outputs are
in `radioroc_runs/simulation/test_20261020_channel/`. Real runs were only opened, never
modified. Screenshots and the raw state log (`drive_log.json`, `startup_log.json`) are in
`docs/app_test_report_channel_calibration_2026-10-20/`.

Commit under test: the run started at `48c56f4`. While the test ran, someone else
committed `e61ff5f` (Page menu). The test process had already loaded the code, so the
results describe `48c56f4`.

## 1. Task A: how the channel behaves

All scan tabs open with "Device / mode" = **Hardware connection**. Each was set to
Simulation before running anything (01–06).

| Place | Control | Value on first open | Survives switching to another tab/page and back? | Survives running a scan? | Survives "Open saved result"? |
|---|---|---|---|---|---|
| Calibration: Threshold scan | channel grid | 4,5 | Yes | Yes (ch 4 before and after a sim run) | Yes, grid unchanged. Saved run shows its own channels only in the plot legend |
| Calibration: Hold scan | channel grid | 4,5 | Yes | Yes (ch 38 before and after) | Yes, grid unchanged (38 kept while real ch4 run shown) |
| Calibration: Hold scan | **Trigger channel** (separate spin box) | 4 | Yes | Yes | Yes, unchanged |
| Calibration: S-curve | channel grid | 4 | Yes | Yes (ch 32 before and after) | Yes, unchanged |
| Calibration: Autocalibration | channel grid | 4,5 | Yes | Not tested (no simulation) | **No: replaced by the saved run's channels** (4,5 → 4,6,32) |
| Acquisition page | channel grid | 4 | Yes | Yes (ch 38 before and after) | Yes, unchanged (38 kept while real ch4 run shown) |
| Acquisition page | Trigger channel (T1 slot) / (T2 slot) | 4 / 5 | Yes | Yes | Yes, unchanged |
| ASIC config. > Main | N° channel | 0 | Yes (38 kept after visiting Threshold scan and Acquisition) | n/a | n/a |

Every place has its own control. None of them is linked to another.

**Q1: channel 38 in one tab.** I set the Threshold scan grid to 38 (07). Afterwards no other
tab or page showed 38. Hold scan stayed at 4,5 (08), S-curve at 4 (09),
Autocalibration at 4,5 (10), Acquisition at 4 with T1 trigger 4 (11), and Main
N° channel at 0 (12).

**Q2: different channels in two tabs.** Threshold scan was set to 4 and S-curve to 32 (13, 14).
After three back-and-forth switches, neither had changed. I then ran an S-curve simulation
while viewing Threshold scan, and a Threshold simulation while viewing S-curve (15, 16).
Neither run changed the other tab's channel.
Simulation runs finish in about 0–2 s, so the "during the run" check only caught the
first instant of each run.

**Q3: close and reopen.** I restarted the app in a fresh process (35). The channels were the same as on first
open: Threshold 4,5, Hold 4,5 (trigger 4), S-curve 4, Autocalibration 4,5,
Acquisition 4 (T1 4, T2 5), Main 0. Nothing is remembered between sessions, and every scan tab
is back in Hardware mode.

**Q4: does the screen say which channel a result belongs to?**
- *Plot titles:* no. For example: "SIMULATION · synthetic threshold rates" and
  "HARDWARE · completed · 103 saved points".
- *Plot legend:* yes, this is the only place on the Calibration tabs. It reads `ch4`, `ch6`, `ch32` on
  Threshold, S-curve and Autocalibration, and `ch4 hg` / `ch4 lg` on Hold.
- *Saved-result banner:* gives mode, status and folder path, but no channel. On Threshold, Hold, S-curve and
  Acquisition it adds "Controls show current settings, not this run's". So with the grid at 12, a
  reopened ch 4 run shows "Channels: 12" next to a `ch4` curve (25). Autocalibration instead
  says "Controls show this saved run's settings" and changes the grid (23).
- *Status line:* only Acquisition names channels ("… · channels [4]", 22). Calibration
  tabs show only mode, status and number of points.
- Real folder names often contain the channel (e.g. `step1_pedestal_ch4_6_32_…`), but
  default new run folders are a timestamp plus a random id.

## 2. Task B: calibration walkthrough as a student

Order a student would probably follow, judging from the tabs and the procedure docs:

1. **Calibration > Threshold scan** (27). Fields: mode, channel grid, First/Last DAC, DAC
   step, counter window, averages, discriminator, trigger gain code, Mask, Ctest. Output:
   trigger rate vs threshold DAC. Noise is high at low DAC and drops off; Log Y is needed
   to see the plateau. The help line says the scan is "to find the noise floor and set a
   clean working threshold". *Not on screen:* which DAC to take as the floor, how much margin to
   add, and where to enter the chosen threshold afterwards. Nothing writes a result anywhere.
2. **Calibration > S-curve** (29). Fields: as above plus clock index and "Count trigger
   level". Output: turn-on (%) vs DAC. *Not on screen:* what to read from the curve (50 %
   point? width?) and how it relates to the threshold scan or the operating threshold.
3. **Calibration > Autocalibration** (30, 23). The channel grid's hint says the
   first selected channel is the reference. Several step groups (Step 1 probe, Step 2
   transition, Final window) are pre-filled. Reopening the real run shows only the
   **final** sub-scan's plot (curves for ch4/6/32 lining up near DAC 120–130), plus a JSON box
   with point counts and the manifest. *Not on screen:* the per-channel trim codes that
   resulted, whether they were written to the board, and how to see the other sub-scans.
   ASIC config. > Threshold calibration still shows 32 for every channel (34). Nothing links
   the two.
4. **Calibration > Hold scan** (28). Fields: trigger channel, hold mode (Internal code vs
   External ns), first/last/step, acquisitions per point, threshold DAC, sync IO, external
   ADC timing, gain overrides. Output: ADC counts vs hold delay (hg/lg). The help line says
   it "sweeps the hold delay to trace the peak-detector's held value over time". *Not on
   screen:* that you should pick the delay at the peak, and that external-trigger and self-trigger runs
   peak at different delays. The separate **Trigger channel** field must be one of
   the selected channels. If it isn't, Preview/Run fails with "trigger_channel must be one of
   channels, or its response curve will never be recorded" (17). The message is clear, but the student has
   to change two controls to move to a new channel.
5. **Per-channel gain: ASIC config. > Main** (31). The student picks "N° channel", then sets
   paT gain, paHG/paLG gain and shaping. The thresholds are in the same panel under "Common
   thresholds and timing": Threshold1 **0**, Threshold2 **2**, ThresholdQ **520**. Their
   hover hints say "ASIC-wide, not per channel". The Apply hint says "Apply the front-end
   **and common-threshold settings** above", so Apply writes the thresholds too. This is
   only visible on hover. At 1280×900 the Apply button is below the fold and needs a scroll.
   There is no on-screen warning that the 0/2/520 defaults break the trigger. The gain/threshold
   overrides on the scan tabs ("Keep current") are a second place to set gain, and the screen
   doesn't say how the two places relate.
6. **Acquisition** (19). Takes yet another channel grid and trigger channel.

Overall, the tabs give a separate tool for each scan, but nothing tells the student the
order to use them in. No result is carried from one step to the next, and no screen says
"use this value as the operating threshold".

## 3. Options (proposal, not a finding; no recommendation)

**(a) One shared channel for all Calibration tabs (and maybe Acquisition and Main).**
- Easier: pick the SiPM once, then go through threshold, S-curve and hold for it without
  forgetting a tab. This also fixes the Hold grid vs trigger-channel mismatch if
  they're tied together.
- Harder: Autocalibration needs several channels and a reference, and Threshold scans
  often run on 3 channels at once, so you'd need to define what "shared" means for
  multi-channel tabs. Comparing two SiPMs side by side in two tabs is no longer possible.
  Reopening a saved run would have to either change the shared channel or show a mismatch.

**(b) Independent channels per tab (today), but show the channel in each tab's title, plot title,
saved-result banner and status line.**
- Easier: keeps today's freedom. Removes the "Channels: 12 next to a ch4 curve"
  confusion. Screenshots and saved plots identify themselves.
- Harder: the student still has to set the channel in every tab for each SiPM, which
  gets tedious and error-prone with several SiPMs in one session. It doesn't help with the
  Hold trigger-channel field.

**(c) Something else**, e.g. a "current SiPM" selector at the top of the Calibration
page that pre-fills every tab, where each tab can still be overridden and shows when it
differs. Or a per-SiPM results table that collects each step's value.
- Easier: one place to pick the SiPM, and per-tab overrides still work.
  A results table would answer "which settings do I use".
- Harder: the most new UI. You need a rule for when a tab follows or ignores the shared
  selector, and students may not notice an override.

## 4. Other things that looked broken or confusing

- Every scan tab opens in **Hardware connection** and goes back to it on restart (known, but each new
  session needs four mode changes).
- Two help lines are stacked at the bottom of Calibration tabs: the tab's own description
  line and the main window's generic "RADIOROC: manage the board connection…" line.
- The Autocalibration saved view shows only the final sub-scan, and no step selector is visible.
- After a run, "New run directory" switches back to an auto default
  (`radioroc_runs/simulation/<timestamp>-<id>`). A student who chose a named folder
  has to choose it again for every run.
- Main tab threshold defaults 0/2/520 are shown with no warning (see `gpt_hardware_task…`
  ground rules).
- Not tested: Acquisition with a T1 trigger channel outside the selected channels, and
  hover behaviour with a real mouse (hints were read from the widgets' hint text instead).

## Screenshot index

01–06 first open of each tab/page · 07–12 Q1 (ch 38 in Threshold, every other place) ·
13–16 Q2 (4 vs 32, and each run) · 17 Hold trigger-channel error · 18 Hold run · 19
Acquisition run · 20–23 real runs reopened (Threshold, Hold, Acquisition, Autocalibration) ·
24–25 own runs reopened (S-curve; Threshold ch4 run with grid at 12) · 26 Main N° channel 38 ·
27–34 Task B screens · 35 after restart.
