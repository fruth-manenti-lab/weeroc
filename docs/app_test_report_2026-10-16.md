# Offline app test report — 16 October 2026

Tester: ChatGPT, following `docs/offline_app_test_guide.md`, on branch
`lab/newest-app-test` with no hardware. The tester made no source or git changes,
and the GUI was closed afterwards. The operator relayed the report verbatim and it
is preserved below for triage. **Status: not yet triaged; no fixes started.**

Triage note (Claude): the two simulation runs in finding 2 sit under
`radioroc_runs/hardware/` but contain **simulated** data. Do not delete or
move them, but don't mistake them for bench measurements:
`radioroc_runs/hardware/20261016-214305-63d99808` (Acquisition simulation) and
`radioroc_runs/hardware/20261016-214839-913164fd` (Threshold simulation).

## Reproduced findings

1. **Blocks a student — documented 1024×768 layout is not usable.** The window
   would not shrink below roughly 926 px high. At about 1024 px wide,
   labels/fields are clipped, plot titles lose leading text, and status text
   truncates across Acquisition/Calibration.
2. **Blocks a student — stale hardware output path after switching to
   Simulation.** Fresh tabs start in Hardware. After changing to Simulation,
   "New run directory" remains `radioroc_runs/hardware/...` until the first run
   finishes. The UI says SIMULATION while it displays and saves into a hardware
   path. Reproduced with actual Acquisition and Threshold simulation runs; Hold
   and S-curve previews also kept hardware paths. Evidence:
   - `radioroc_runs/hardware/20261016-214305-63d99808` (Acquisition simulation)
   - `radioroc_runs/hardware/20261016-214839-913164fd` (Threshold simulation,
     ch4-6, 41 points/123 windows)
3. **Annoying — saved Autocalibration result conflicts with left-side
   controls.** Opened
   `radioroc_runs/hardware/20261016-155312-11f4dd6c/autocalibration_metadata.json`.
   The manifest and plot correctly show channels 4, 6, 32 with Ctest=true and
   final 86 points, while the controls still show Channels: 4-5 and Ctest
   unchecked. Provenance is ambiguous.
4. **Annoying — Internal Hold mode keeps nanosecond labels.** Switching Hold
   Simulation from External to Internal and pressing Preview gives a valid
   0..255 ASIC code scan, but the labels still say First/Last hold code /
   delay (ns).
5. **Cosmetic** — the S-curve and Autocalibration gain override value
   "Keep current" has its leading K clipped, and calibration forms show a
   horizontal scrollbar even at the normal full-size window.

## Successful checks

- Hardware run buttons stayed disabled offline.
- Acquisition simulation completed 500 events.
- The real saved acquisition reopened as HARDWARE completed with 100 events/100
  rows.
- Threshold simulation ch4-6 completed with cleanup restored and a correct plot.
- Hold external/internal previews and the S-curve preview validated without
  output.
- The saved Autocalibration result plotted correctly.

## Relation to earlier claims

Finding 1 contradicts the RADIOROC 42 claim that the Acquisition plot keeps its
size at 1024×768. That claim rested on offscreen tests and an offscreen 1024×768
`grab()` screenshot, which never ran into the window's real minimum height. The
real-display check had been recorded as pending.
