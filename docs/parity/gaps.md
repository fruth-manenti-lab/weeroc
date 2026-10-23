# Parity gaps

Date: 2026-10-22. Source: `parity_table.md` (leaf rows). Counts: 41 leaf rows = 17 Delivered, 13 Partial, 6 Needs
hardware, 4 Not started, 1 Excluded (F15).

## Doable offline

| Row | What is missing |
|---|---|
| F01c | Firmware version display, board identity beyond the status word, reconnect behavior; the USB self-test needs a safe target (hardware side). |
| F02c | Hold-source bit and TQ/delay/slope paths have no unit evidence of vendor parity; Main tab cannot read the chip back, and Apply writes the whole tab. |
| F05c | Digital probe routing and discriminator output select (`(66,ch)`) are not implemented in API, CLI or GUI. |
| F06b | No standalone Reset-to-defaults button in the GUI (only CLI and scan-window checkbox). |
| F06c | Vendor configuration file import/save, masked partial import, drag-drop, embedded field help; the vendor file format is unknown. |
| F07b | S-curve fitting and 50% extraction display/export in the S-curve tab; CLI plot for S-curves is unknown. |
| F10c | Peak-sensing path and HG/LG statistics plots have no evidence beyond the checkbox. |
| F11d | Trigger selection (selTrig) combo exists on Main; no test evidence of vendor-equivalent coverage of local/global/external. |
| F12b | Continuous acquisition mode is not found; finite batches only. |
| F13b | Separate per-acquisition / event view (vendor Figure 29) is not built. |
| F13c | Bin and scale controls, clear button, and update-rate controls are only partly present. |
| F13d | Export in the vendor acquisition file format. |
| F14b | Trigger indicators and validation-event control (not documented in UG section 3.4; needs the Windows audit). |
| F16b | Persistent settings (no `QSettings`), full shortcut set, plot controls parity. |
| F17b | Finger-spectrum view, derivative/error plots and scan comparisons in the GUI. |

## Needs the board

| Row | What is missing |
|---|---|
| F05b | Scope confirmation of the analog-probe node order. |
| F06a | First physical run of the raw Registers tab (Read all, Write). |
| F07c | Injection S-curve with a synchronized pulser (2026-10-16 Step 5 had unusable generator setup). |
| F10b | Internal hold scan: no dated hardware run found. |
| F11c | N-triggers-in-a-window trigger on the board. |
| F16c | Windows screen-by-screen walkthrough of vendor 2.2.0.5 (needs the Windows machine; not board-only). |
| F01c, F02c, F03 (grid), F04a (panel), F04b (grid), F11a (NORT sources), F14a (IO2-IO4) | Parts of these Delivered/Partial rows have no board run; see their Hardware cell. |

## Beyond the plan

Features built that no row of the plan covers (they are not in `parity_table.md`):

- Calibration bar (`gui/calibration_file_bar.py`): Save/Load calibration file, Operating threshold, shared Trigger gain
  and Hold delay (Log: RADIOROC 44).
- Calibration file format (`application/calibration_file.py`, JSON schema_version 1).
- Shared channel selection model and panel (`gui/calibration_selection.py`, `calibration_selection_panel.py`).
- Muon detector page (`gui/muon_view.py`, `data/muon_*.py`): SiPM/plint layout editor, event replay, coincidence
  analysis (Log: RADIOROC 45).
- Plint calibration procedure and record saving (`docs/plint_calibration_procedure.md`,
  `scripts/radioroc_save_calibration_record.py`).
- Acknowledge-fault-without-disconnect in `ConnectionWorker` (Log: RADIOROC 44).
