# Hardware task: calibrate one SiPM, then take a finger plot in the app

For an AI assistant that controls the RADIOROC desktop app visually, **with the real
board connected and the operator present at the bench.** The operator is the one
person allowed to touch the board. They have chosen to let you drive the app, and they stay
responsible for the hardware. Stop and ask them whenever this file says STOP.

Read first: `docs/plint_calibration_procedure.md` (Steps 1 and 2),
`docs/bench_runbook.md` (sections 1 to 3 and 8) and `docs/offline_app_test_guide.md`
(Layout). Don't repeat their theory; follow them.

## Ground rules

- **Only you and the app talk to the board.** No other scripts, no other app window, no
  other assistant. Port `/dev/cu.usbserial-RD3_320`. If the app says the board is busy,
  STOP.
- **Do not touch the signal generator, the bias supply or any cable.** The operator
  owns the LED settings (pulse level, width, rate) and changes them themselves.
- **Never press Apply on ASIC config. > Main without first editing the thresholds.**
  Its Threshold1/2/Q start at 0 / 2 / 520, which breaks the trigger (the chip's real
  defaults are 512 / 512 / 512). If you must use Main, set Threshold1 480,
  Threshold2 512, ThresholdQ 512 first.
- **Don't change code or git state.** Don't delete or edit anything in `radioroc_runs/`.
- **Faults:** if the app shows a fault, a timeout or "board hang", STOP. Do not retry
  automatically. The operator power-cycles the board; afterwards the ASIC is at power-on
  values, so defaults must be applied and verified (the runbook says how) and the
  calibration redone.
- **Probe:** the analog probe must be off for these measurements. On
  Probes/Masks press **Off, all channels** before you start. The Acquisition page also
  switches a routed probe off before each run and says so in its result.
- Don't exceed 2.5 V into IO6 (the operator's cabling; just don't change it).

## Which SiPM

Ask the operator which channel to use (for example channel 32, a 6 mm SiPM, or
channel 38, a 1 mm SiPM) and confirm the bias is on. Use that one channel. Don't calibrate others.

## Task 1: calibrate the channel

1. Connect (ASIC config. > Hardware connection > Connect). Confirm the status shows
   connected and the firmware status is shown.
2. **Pedestal/noise (procedure Step 1):** Calibration > Threshold scan, hardware mode,
   Ctest off, your one channel, `dac_min 0, dac_max 1023, dac_step 10-20,
   window 100 ms, pat_gain 1`. Run it. Record the DAC at which the noise curve reaches
   its clean floor. If the curve is dead, noisy or clipped, STOP and report.
3. **Threshold alignment (procedure Step 2):** Calibration > Autocalibration. Select your
   channel and the reference channel as the procedure describes. If the procedure needs
   at least two channels, ask the operator which second channel to use. Run it and
   record the result.
4. Report to the operator: the floor DAC, the chosen operating threshold (floor plus a
   margin, say how big) and the autocalibration result. Then continue.

## Task 2: finger plot acquisition

Settings (Acquisition page), for the same channel:

- Channel = trigger channel (T1 slot) = your channel. Trigger type Simple trigger.
- High-gain shaper code **15** (ask the operator before choosing a lower gain), trigger
  preamp gain 1, threshold 520 unless Task 1 gave a better value.
- **Hold delay 35 ns** (external-trigger runs peaked at about 25 to 50 ns; the 110 ns
  figure is for self-triggered dark counts only). Conversion delay 400 ns.
- Tick **Use external ASIC acquisition trigger (IO_FPGA6)** and **Reset-n manual**.
- 200 acquisitions per batch, batches = 15 (3000 events), timeout 60 s.
- Output folder: a new one under `radioroc_runs/`.

Before starting, ask the operator to confirm: bias on, LED pulsing, generator CH2 into
IO6. Then run, and show the HG spectrum with Bins about 200. Describe what you see:
pedestal position, whether discrete peaks separate, spacing between them in ADC counts,
and whether the pedestal moved compared with the plain gain 8 value (about 100).
If the histogram is a single hump or sits at the pedestal, say so. Don't change the LED.

## Task 3: hand over

When the first run is finished, **stop acquiring**. Tell the operator the run folder, the
settings used and what the plot showed. The operator will change the LED settings
themselves and ask you to repeat the same run. Repeat it with settings unchanged, in a
new output folder each time, and report what changed in the histogram. Don't
adjust gain, hold or thresholds between repeats unless the operator asks.

## While you work, also note (short, factual)

- Whether the selected channel stayed the same when you switched between Calibration tabs
  and the Acquisition page. This is a known question: each tab has its own channel
  selector. Say what you saw; don't change anything.
- Anything confusing about the order of steps.
