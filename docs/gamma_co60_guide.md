# Gamma run with a Co-60 source

How to take a self-triggered gamma spectrum on one plint (plastic scintillator + SiPM) with the
RADIOROC desktop app, and how to read it. Use it for bench checks, for choosing a hold delay quickly
(see Step 4d of `muon_rate_measurement_guide.md`), and to see whether a channel is healthy.

Follow your lab's rules for handling and storing sealed sources. This guide and the app say
nothing about radiation safety.

## What to expect

Co-60 emits two gamma lines, 1173 keV and 1332 keV. In a plastic scintillator the gammas almost
only Compton-scatter, so there is **no sharp photopeak**. You get a smooth continuum that falls off
near the two Compton edges, about **0.96 MeV** and **1.12 MeV** (computed from the line energies;
the edges are blurred by the detector resolution, so in the plot you see one broad shoulder, not
two steps). The pulses are real scintillation pulses, but smaller than a muon's (a muon deposits
about 2 MeV per cm of plastic).

On the bench (2026-10-27, ch6 and ch32, SiPMs biased, paT gain 1) the source gave about **15 to 18
events per second** on ch6 at thresholds 400 to 560, with pulses 30 to 60 high-gain counts above
the pedestal. Your numbers will differ with source activity and distance; use them as a sanity
check, not a target.

## Before you start

1. **SiPM bias on** and dark box closed. Without bias there is nothing to see: the threshold-scan
   rate drops to zero by DAC 360 and every trigger is noise.
2. Source in place on the plint, at a fixed, repeatable position. Note the position in the log.
3. Calibration done (autocalibration, trims saved) and **Trigger gain (paT) = 1**.
4. **Pedestals measured.** On the **Calibration** page run the **Pedestals** step for the channel
   you will use. The Acquisition page shows "Pedestals: ..." in orange until you have done this.
5. Select the channel on the Calibration page and set **Trigger channel (T1)** to it. A gamma run
   triggers on that one channel only, so run each plint on its own.
6. Connect the board **directly to a USB port** on the computer, not through a hub. Hub sharing is
   a suspected cause of board hangs.

## Step 1: Choose the threshold

The threshold decides what you record. Too low and the dark counts flood the board (a
self-triggered channel at a low threshold can run at hundreds of events per second, mostly noise,
and the board may stop answering). Too high and you lose the small gamma pulses.

1. On the **Calibration** page open **Threshold scan**, with the source in place, and look at the
   trigger rate against threshold DAC.
2. Dark counts form a floor of roughly 100 to 150 Hz above DAC 420 on the bench; the source adds to
   it. Pick a threshold just above the dark-count shoulder where the rate is a few to about 20
   events per second.
3. Enter it as the **Operating threshold** in the bar at the top. The Acquisition and Hold scan
   windows follow that value.

## Step 2: Hold delay

The hold delay is counted from the trigger. For self-triggered gamma and muon runs use about
**30 ns** (the default). On the bench the peak was tallest at 20 to 50 ns, with no visible shift
with threshold. To check it for your channel, use the Hold scan tab's **Gamma source preset
(single channel)**, then read the plateau (Step 4d of the muon guide). The Acquisition page warns
if the hold delay is long for a self-triggered run.

## Step 3: Take the run

1. Open **Acquisition**. **Device / mode**: Hardware connection.
2. Set:

   | Setting | Value |
   | --- | --- |
   | Trigger type | Simple trigger |
   | Trigger source (T1 slot) | Individual trigger |
   | Discriminator | T1 |
   | Threshold DAC | the value from Step 1 (follows the top bar) |
   | Hold delay (ns) | 30 |
   | Acquisitions per batch | 10 |
   | Stop after | Acquisition time, for example 10 min |

   Keep the batch small. On the bench a run with 50 acquisitions per batch lost the board mid-reply
   after a minute or two; 10 per batch ran without problems. A smaller batch means shorter replies
   from the board, which seems to be what it tolerates.
3. **Do a short test first**: Stop after "Number of batches", 10 batches. Click **Preview**, then
   run. Check the status line: a batch should take seconds, not a fraction of a second. If batches
   come at several per second, the channel is triggering on noise: raise the threshold and repeat.
4. Run the long measurement. In **Acquisition time** mode the progress bar fills by elapsed time
   (`m:ss / m:ss · N batches`).
5. If a batch reply is cut off, the app discards it and reads that batch again (up to 2 times).
   Each retry is listed in the run's warnings and in `metadata.json` under `batch_retries`. If the
   retries fail the run stops with a fault: reconnect, and see Troubleshooting.

The run folder has `metadata.json` and `events.csv` (one row per event and channel). Keep the
folder path in the log.

## Step 4: Read the spectrum

The **Spectra display** on the Acquisition page is built from `events.csv` while the run goes.

- **Gain**: High gain (HG) for the main spectrum. Low gain (LG) reaches larger pulses without
  saturating.
- **Subtract pedestal**: shows counts above the channel's pedestal instead of raw ADC counts. Use
  it for the gamma plot. A dashed line marks the pedestal either way.
- **Auto range / X min / X max**: untick Auto range to zoom on a region; the bins are re-spread
  over your range, so zooming gives finer resolution. Changing Subtract pedestal switches back to
  auto range because the axis units change.
- **Bins**: 100 to 200 for a smooth continuum. **Log Y** helps to see the tail.

What to look for:

- A continuum rising from the threshold, flattening, then falling off at the Compton shoulder.
  The shoulder is the nearest thing to an energy calibration point (about 1 MeV); treat it as a
  rough check, since the edges are blurred and the HG gain and shaping settings change the scale.
- A narrow spike at the low end is usually noise or pedestal events, not gammas. A spike at the
  top of the range means saturation: use LG or lower the gain.

## What the trigger actually does

With **Simple trigger** and **Individual trigger** the ADC fires when the selected channel crosses
its threshold. The **Discriminator** field (T1 or T2) chooses which threshold the Threshold DAC is
written to and which mask bit the app opens. Which discriminator level the board's "Individual
trigger" mode taps internally has **not been established** from the vendor software or on the
bench, so do not rely on it meaning "T1 only". The Coincidence window and Time-window trigger count
fields are unused in this mode.

## Optional: trigger on the charge discriminator (TQ), experimental

T1 and T2 look at the fast trigger preamp and fire on the pulse edge, so dark counts (single
photoelectrons) cross a low threshold. **TQ** looks at the slow low-gain shaper output, so it
responds to pulse size and can reject small dark pulses. Its threshold has its own wider range
(about 75 mV to 1.1 V, 1 mV per step) against T1/T2 (about 270 to 530 mV, 0.25 mV per step).

This path is **not verified on the board**. Take it one step at a time, and keep the T1 run you
already have as the reference. Gamma pulses are small (30 to 60 counts above pedestal on the
bench), so the TQ threshold may sit above many of them: expect a lower rate than T1.

**A. Set the TQ threshold** (ASIC config, Main tab)

1. Open **ASIC config**, then the **Main** tab.
2. Find **ThresholdQ** under "Common thresholds and timing" (default 512).
3. Start with the default. Click **Apply** and wait for the status line to say it is done.
   The Threshold DAC on the Acquisition page never sets this; only this field does.

**B. Open the TQ mask for your channel only** (ASIC config, Probes/Masks tab)

1. Open the **Probes/Masks** tab.
2. In the **Enable TQ** grid click **Enable none**, then tick only your channel.
3. Apply the masks. The Acquisition run does not touch the TQ mask, so this must be done by hand.
   Any other channel left ticked adds its noise to the trigger.

**C. Set up the run** (Acquisition page)

1. Same settings as the T1 run, except **Trigger source (T1 slot)** = **NORTQ**.
2. Acquisitions per batch 10, hold delay 30 ns for now.
3. Run 10 batches. A batch should take seconds. If none finish (timeouts), the TQ threshold is
   too high: lower ThresholdQ in steps of about 20 and repeat A.

**D. Compare with the T1 run**

1. Note the rate (events per second) and look at the spectrum with Subtract pedestal on.
2. A good TQ result: lower rate than T1, with the dark-count spike gone and the continuum intact.
3. TQ fires later than T1, so the pulse may be sampled at the wrong point. **Repeat the hold scan
   with TQ** (same trigger source) and use the plateau it shows instead of 30 ns.

**E. Go back to T1**

Set **Trigger source (T1 slot)** back to Individual trigger, and re-enable your usual T1/T2 masks
on Probes/Masks. Record in the log that TQ was used, with ThresholdQ and the hold delay.

## Troubleshooting

| Symptom | Likely cause and action |
| --- | --- |
| Hundreds of events per second, flat spectrum | Threshold too low: noise triggering. Raise it. |
| Batch times out | Threshold too high for the source, or source too far. Lower it or move the source. |
| "reply cut off" warnings, or a fault `expected N bytes, received M` | The board stopped sending mid-batch. A few retried batches are harmless. Repeated ones: raise the threshold (lower rate), use a direct USB port, power-cycle the board. |
| "Cancelling" for a long time, or "Connection error ... no response" | The board is not answering. The app now skips the remaining cleanup after the first timeout. Power-cycle the board, reconnect, then **Apply defaults** or load your saved config, because the run's temporary settings may not have been restored. |
| No pedestal line, or the Subtract pedestal box does nothing | Run the **Pedestals** step for this channel on the Calibration page. |

## Log checklist

Date, who ran it, source and its position, channel, bias voltage and current, threshold DAC and
why, hold delay, paT gain, HG/LG settings, run folder path, rate (events per second), and anything
unusual (retries, faults, board power-cycles).
