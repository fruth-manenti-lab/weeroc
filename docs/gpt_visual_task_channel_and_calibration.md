# Visual app task: channel selection across tabs, and the SiPM calibration workflow

For an AI assistant that controls the RADIOROC desktop app visually (screenshots,
mouse, keyboard). **No board, generator or SiPMs are connected.** Read
`docs/offline_app_test_guide.md` first and follow its **Ground rules** and **Setup**
exactly (Simulation only, never press Connect, don't change code or git state,
never edit or delete anything in `radioroc_runs/`, use `.venv-foundation`).
Report what you see; don't fix anything.

## Why this task exists

The operator wants to calibrate each SiPM to learn which settings to use (gain,
threshold, hold, input DAC). While doing that they noticed that switching between the
Calibration tabs does not carry the channel over. They may want to calibrate different
channels in different tabs, or they may want one shared channel; **this is not decided.**
Your job is to record exactly what the app does today and what a student would
experience, not to decide.

## Task A: how the channel behaves (the main deliverable)

Set "Device / mode" to **Simulation** on every scan tab before you run anything.

Fill this table from what you actually see. One row per place a channel is chosen:

| Place | Control | Value on first open | Survives switching to another tab/page and back? | Survives running a scan? | Survives "Open saved result"? |
|---|---|---|---|---|---|
| Calibration: Threshold scan | channel grid | | | | |
| Calibration: Hold scan | channel grid / trigger channel | | | | |
| Calibration: S-curve | channel grid | | | | |
| Calibration: Autocalibration | channel grid | | | | |
| Acquisition page | channels + trigger channel (T1 slot) | | | | |
| ASIC config. > Main | N° channel | | | | |

Then answer, with a screenshot each:

1. Pick channel 38 in one tab. Which other tabs and pages show channel 38 afterwards?
2. Pick different channels in two tabs (for example 4 in Threshold scan, 32 in S-curve).
   Switch back and forth three times. Does either change by itself? Does a running
   scan in one tab disturb the other tab's channel?
3. Close and reopen the app. What are the channels at start-up?
4. Is anything on screen telling the student which channel a result belongs to?
   Check the plot titles, the saved-result header and the status line.

## Task B: walk through the calibration workflow as a student would

Using Simulation only, write down which tabs a student would use, in what order,
to find per-channel settings for one SiPM, and where the app stops being clear. For each
step give: tab name, the fields you set, what the output looks like, and what the
student would need to know that the screen does not say. Things to check:

- Threshold scan, S-curve and Autocalibration: what each one produces and what the
  student is supposed to do with that result. Does any screen say which value to
  take as the operating threshold?
- Hold scan: is it clear what the hold delay means and how to pick one?
- Where would the student set the per-channel gain, and is it obvious that the Main tab's
  Apply also writes the thresholds? (Do not press Apply with hardware; just read the screen.)
- Autocalibration has no simulation. Say only what you can see (reopening a saved result).

## Report format

Put your report in a new file `docs/app_test_report_channel_calibration_<date>.md`
(a new file only; nothing else in the repository). Include:

1. The completed Task A table and answers 1 to 4.
2. The Task B walkthrough.
3. A short **Options** section, clearly marked as a proposal and not a finding:
   (a) one shared channel for all Calibration tabs, (b) independent channels per tab but
   with the channel shown in each tab's title/results, (c) something else. For each,
   list what would get easier and what would get harder for a student calibrating
   several SiPMs in one session. Don't pick one.
4. Anything that looked broken or confusing that is not about channels.

Keep it factual and short. Screenshots go in a new folder next to the report.
