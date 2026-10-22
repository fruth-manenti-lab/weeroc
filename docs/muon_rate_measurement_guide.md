# RADIOROC muon rate measurement guide

For the operator and the students who follow. Last updated 2026-10-21.

Items marked **FILL IN** are facts about the detector that this guide cannot know. Fill them in once and keep them.

## 1. What this guide is for

By the end you will have one number: **accepted muon events per minute** from a detector of known area, read out through the RADIOROC 2 board, and a verdict on whether the board sees what it should.

The detector for this experiment is **two Luxium plastic scintillator plints, each with one SiPM attached**. The SiPMs plug into the board through our custom edge connector board. The board, the edge connector, the SiPMs and the test LED all sit inside the **dark box**.

The idea is simple. A flat detector at sea level is crossed by roughly **1 muon per cm² per minute** (about 70 per m² per second per steradian from overhead). The rule of thumb is good to a factor of about 1.5 and depends on thickness, orientation, altitude and what is above the bench. So a plint of area A cm² should count roughly A muons per minute when the electronics work and the efficiency is high. If our board reports a rate close to what a trusted readout reports for the same detector, the board is good.

Work in this order:

1. Gather equipment and check it (section 2).
2. Connect everything (section 3).
3. Start the software and confirm the board answers (section 4).
4. Calibrate: find the noise floor, align thresholds, choose the operating threshold (section 5).
5. Acquire data and turn counts into a rate per minute (sections 6 to 8).

**Four rules that save days of work**

- **The board gets a USB port of its own.** Never share a hub with other devices. On a shared hub the board hung 11 times in one day; on its own port it ran about 34 acquisitions clean.
- Only one program may talk to the board. Close the desktop app before running any script, and the other way round.
- After every power cycle the board forgets its settings. Re-apply defaults, then redo the calibration, before measuring anything.
- Write every setting and every voltage in the lab log (section 10) at the time. A measurement without its settings cannot be reused.

## 2. Equipment and pre-checks

Gather everything before you start. Tick each item.

| Item | What it is for | Check before use |
| --- | --- | --- |
| RADIOROC 2 evaluation board | The readout under test | In the dark box. 5 V / 1 A supply and USB both available |
| Custom edge connector board | Carries the SiPM signals into the board | Seated fully in the board's SiPM input connector |
| Two Luxium plints, one SiPM each | The detector | **FILL IN:** plint size (length × width × thickness), SiPM type and serial numbers, SiPM operating voltage from its datasheet |
| Bias supply | Powers both SiPMs through the board | Output off, set to 0 V, current limit set. Cable goes to the board's **HV** connector |
| Computer with the RADIOROC app | Controls the board, saves data | A USB port used **only** by the board, no hub |
| Pulse generator (Aim-TTi TGF4162) | Calibration test signals, LED, external trigger | CH1 for test pulse or LED; CH2 for the IO6 trigger (2.5 V TTL maximum). Set by hand on the front panel |
| 20 dB attenuator | Between generator CH1 and the board test input | Fitted for every Ctest and hold scan |
| Test LED (inside the dark box) | Optional light check | Flush against a plint, driven by generator CH1 |
| Oscilloscope (optional) | Shows the real pulse shape and amplitude | Ground clip not connected to the board's ground |
| Tape measure | Records plint area | Measure the sensitive plastic, not the wrapping |
| Lab log (section 10) | Records every setting | Printed or open in another window |

**Care**

- SiPMs are damaged by bright light while biased. **Close the dark box before you switch bias on**, and keep it closed while bias is on.
- Raise the bias slowly to the datasheet voltage and never above it.
- Switch bias **off** before opening the dark box, or connecting or disconnecting the SiPMs.
- Handle the board by its edges and touch a grounded metal surface first. Do not touch the board or cabling while the app runs a large register read or write; handling the setup coincided with board hangs.

**Facts about the detector to write down now (needed in section 7)**

- Area A of each plint in cm²: **FILL IN** (length × width of the plastic).
- How the two plints are arranged (stacked one above the other, or side by side): **FILL IN**. If stacked, A is the overlap area that both plints see.
- Orientation: flat and horizontal.
- Where the bench is (floor of the building, what is above it). Concrete above the detector removes some muons.
- A rate for this detector from a trusted readout, if one exists: **FILL IN** (this is the reference for section 8).

## 3. Connections

**One USB port for the board only. No hub. No other device on that port.**

### What goes where

| Connector on the board | What connects | When |
| --- | --- | --- |
| Power input (top right) | 5 V / 1 A supply | Always |
| USB | Computer, port used only by the board | Always |
| **HV** | Bias supply output | Always; bias stays off until section 4 passes |
| SiPM input connector | Custom edge connector board, with the two SiPMs | Always |
| **IN_TEST1** (SMA) | Generator CH1 **through the 20 dB attenuator** | Calibration: Ctest, S-curves, autocalibration, threshold scans with a test signal, hold scans |
| **IO1** (SMA output) | Generator **external trigger input** (TRIG IN) | Calibration with a test pulse: Ctest scans, autocalibration, hold scans. The board sends its synchro trigger on IO1 (FPGA mux index 5), so each generator pulse lands inside an acquisition window. Not used for the muon run |
| **IO6** (SMA, IO_FPGA6, External Synchro) | Generator CH2 (2.5 V TTL maximum) | Hold scans and any acquisition that uses the external trigger, including LED acquisitions. Not used for the muon run |
| IO7 (SMA, IO_FPGA7, External Hold) | Nothing | Not used |
| Analog_Probe (SMA) | Oscilloscope | Optional, for looking at the shaper output |

Check the labels against the printing on your board before connecting. The names above come from the vendor user guide and the bench notes.

### Signal path

```
  Bias supply ---------------------------------> board HV connector
  5 V / 1 A supply ----------------------------> board power input
  Computer ---- USB (its own port, no hub) ----> board USB

  Two SiPMs (one per plint) --> custom edge connector board --> board SiPM input, channel N and channel M

  Pulse generator (set by hand on its front panel):
    CH1 --> 20 dB attenuator --> board IN_TEST1     (Ctest, hold scan)
    board IO1 (output) --> generator external trigger input   (fires CH1 in step with the board)
    CH1 --> LED inside dark box                      (LED light, move the cable here when needed)
    CH2 --> board IO6                                (external trigger: hold scans and LED acquisitions)
```

Generator CH1 has one output. It drives either IN_TEST1 or the LED at a time, so move the cable, do not split it.

### Step by step

Everything is **off** while you connect.

1. Put the two plints flat and horizontal in the dark box, in the arrangement you wrote down in section 2. Check that each SiPM is firmly attached to its plint.
2. Plug the two SiPMs into the custom edge connector board. Note which SiPM is on which edge-board position, and so which board channel it reads. Call them **channel N** (plint 1) and **channel M** (plint 2) and write them in the log. The existing bench has used channels 4, 6 and 32.
3. Seat the edge connector board in the board's SiPM input connector.
4. Connect the bias supply to the board's **HV** connector. Set the supply to 0 V with the output off and the current limit at the datasheet maximum.
5. Connect the 5 V / 1 A supply to the board's power input. Leave it switched off.
6. Connect the board's USB cable to the computer, in a port that has nothing else on it.
7. Connect the pulse generator by hand with SMA cables. CH1 goes through the 20 dB attenuator to **IN_TEST1**. The board's **IO1** output goes to the generator's external trigger input. CH2 goes to **IO6** if you will use the external trigger. Keep CH2 at 2.5 V TTL or below. Leave both outputs off.
8. The generator stays connected for the muon run too, with its outputs off, so nothing changes between calibration and measurement.
9. **Close the dark box.** Check that no light gets in.
10. Power up in this order: close the dark box first, then switch on the 5 V supply, then start the app (section 4), and only after the board answers switch on the bias.

### Grounds (what not to connect)

SiPM channels pick up false triggers when other equipment adds extra ground paths to the board. The SMA cable shields already join the grounds, so add nothing on top:

- Do not connect the separate ground connector, ground clip or earth terminal of the generator to the board's ground.
- Do not connect the oscilloscope's ground clip or earth terminal to the board's ground. Probe the Analog_Probe SMA only.
- Do not connect the bias supply's ground or earth terminal to the board's ground, the generator or the oscilloscope. It reaches the board only through the HV cable.
- Do not put other equipment on the board's USB port.

If noise appears anyway, see the troubleshooting table.

### Connection checklist

- [ ] Plint areas measured and logged
- [ ] SiPM 1 on the edge connector, reading board channel N; SiPM 2 reading channel M (both logged)
- [ ] Edge connector board seated in the board
- [ ] Bias supply on the board's HV connector, output off, at 0 V
- [ ] 5 V supply on the board, switched off
- [ ] Board on a USB port of its own, nothing else on it
- [ ] Generator CH1 through the 20 dB attenuator on IN_TEST1; board IO1 to the generator's external trigger input; CH2 on IO6 if needed; outputs off
- [ ] No extra ground leads from generator, oscilloscope or bias supply to the board
- [ ] Dark box closed before any power or bias

## 4. Software start-up and first-light checks

**Quick map of the app**

| Sidebar page | What lives there |
| --- | --- |
| **ASIC config.** | **Hardware connection** box (**Refresh**, **Port**, **Connect**, **Read status**, **Disconnect**, **Acknowledge fault review**, **Connection status**, **Firmware status**) and the chip settings tabs (**Main**, **Channel config**, **input DAC**, **Probes/Masks**, **Registers**) |
| **Calibration** | Save/Load calibration bar, the one shared channel selection, then the tabs **Threshold scan**, **Autocalibration**, **Hold scan**, **S-curve** (section 5) |
| **Acquisition** | The data run: trigger type, threshold, batches, timeout (section 6). It reads its channels from the Calibration page |

Goal: prove the board answers before any bias is applied. The app shows the board's firmware status. It does not show the bias voltage or current: read those on the bias supply's own display.

1. Confirm the dark box is closed and nothing else is using the board (`lsof /dev/cu.usbserial-RD3_32*` lists nothing).
2. Switch on the 5 V supply.
3. Launch the app: `.venv-foundation/bin/radioroc-desktop` from the `weeroc` folder.
4. Switch pages by clicking **ASIC config.**, **Calibration** or **Acquisition** in the left sidebar. Just click the sidebar. (The **Page** menu shortcuts are Cmd+1/2/3 on a Mac, Ctrl+1/2/3 elsewhere, but you do not need them.)
5. Click **ASIC config.** in the sidebar. In the **Hardware connection** box click **Refresh**. In **Port** pick the one ending `RD3_320`. Click **Connect**.
6. Look at the two lines under the buttons:
   - **Connection status** says it is connected.
   - **Firmware status** shows `0x05 (5)`. That means the board is answering.
7. Click **Read status** to check again at any time. If Firmware status shows `—`, or Connection status shows an error, the board is not answering: power-cycle the 5 V supply and USB, then repeat step 5.
8. Only now switch on the SiPM bias on the supply, with the dark box closed. Raise it slowly to the datasheet voltage, wait 2 minutes, and write voltage and current from the supply's display in the log.

Defaults are not applied here. The first scan after every power cycle applies them (section 5, Step 1), because a power cycle leaves the chip at power-on values and scans without defaults are meaningless.

**If the board stops answering** (the app shows "no response" or "i2c FIFO transaction timed out"):

- Do not retry in a loop, and do not touch the cabling during scans or acquisitions.
- After a fault, scans stay blocked until you act. On **ASIC config.** click **Acknowledge fault review**. You do not need to disconnect. The app re-checks the board.
- If the board answers (**Firmware status** shows `0x05 (5)` again), scans work again. Re-check with a threshold scan before trusting the trims.
- If it does not answer: switch off the bias, power-cycle the 5 V supply and USB, click **Disconnect** then reconnect (step 5), then redo the defaults (first threshold scan, section 5 Step 1) and the autocalibration (Step 2). You can use **Load calibration…** to restore the settings, but the trim re-apply is untested; check with a threshold scan afterwards.

**Pass criteria for this section:** Firmware status shows `0x05 (5)` after Connect, and the bias supply's own display shows the datasheet voltage with a steady current.

## 5. Calibration

Calibration answers one question: at what threshold does the board count real muon pulses but not noise? Repeat the whole section after any power cycle, bias change or detector change. Each run writes a folder under `radioroc_runs/` (shown in **New run directory**); never delete these.

The **Calibration** page has four tabs, in this order: **Threshold scan**, **Autocalibration**, **Hold scan**, **S-curve**. Work through them left to right. **S-curve** is optional and is not needed for the muon run.

Everything above the tabs is shared by all of them (and by the **Acquisition** page):

- The **Save/Load calibration** bar: **Operating threshold**, **Trigger gain (paT)**, **Hold delay (ns)**, **Save calibration…**, **Load calibration…**. These three values are shared: every scan tab and the **Acquisition** page use them, so you set each once. **Bias (V)** and **Note** are asked for in the dialog when you click **Save calibration…**.
- One **channel selection**: the **Channels** button (click it to open the 64-channel grid, with **Select all** and **Select none**), **Trigger channel (T1)**, **Trigger channel (T2)**, and the tick box **Choose trigger channels automatically**.

While **Choose trigger channels automatically** is ticked, T1 is the lowest selected channel and T2 is the next one (or T1 again if you select only one channel). If you type a trigger channel by hand, the tick box switches itself off. Leave it ticked unless you have a reason.

The scan tabs have no channel grids of their own. Choose the channels once, here.

**Saving your work.** Click **Save calibration…** to write a JSON file (default folder `radioroc_runs/calibration/`). It holds the channels, trigger channels, **Operating threshold**, **Trigger gain (paT)**, **Hold delay (ns)**, **Bias (V)**, **Note**, and the trims from the last verified autocalibration run. **Load calibration…** puts all of these back. If the board is connected it can offer to write the trims into the chip again. That re-apply path is **untested on hardware**: after using it, always run a threshold scan to check the result. **What the file does not hold.** It does not save the whole chip. The other registers (gains, masks, input DACs, probe settings) and the threshold the chip is using right now are not in it. After a power cycle the chip is back at its defaults, so to get ready again: (1) run the first Threshold scan with **Initialize FPGA (persists)** and **Apply defaults (persists)** ticked; (2) click **Load calibration…** and let it re-apply the trims (untested on hardware); (3) run a quick threshold scan to check the channels look aligned. If only the app crashed and the board stayed powered, the chip is probably still calibrated: reconnect and check with a threshold scan. Save at three points:

1. Right after autocalibration (Step 2).
2. Again after you choose the operating threshold (Step 5).
3. Before any long run.

If you save without a verified autocalibration in this session, the file holds settings only, and a status line appears under the buttons and says so.

### Step 0: Choose the channels

1. Click **Calibration** in the sidebar.
2. Click the **Channels** button. In the grid click **Select none**, then click the buttons for channels N and M. Close the grid by clicking the **Channels** button again.
3. Check **Trigger channel (T1)** and **Trigger channel (T2)**. With **Choose trigger channels automatically** ticked, T1 is the lower of N and M and T2 is the other. That is fine.
4. Check that **Trigger gain (paT)** on the bar is 1. When you click **Save calibration…** later you will be asked for the bias voltage and a short note (for example the date and "plints 1 and 2").

### Step 0b: Check the analog signal (gain and shaping time; optional but recommended)

Every scan, the threshold and the hold delay depend on the chip's gain and shaping time. Before calibrating, look at a real pulse on the oscilloscope and judge whether they suit the muon pulses. The chip has an **Analog probe** output on the **Analog_Probe** SMA that shows one channel's amplifier outputs.

**Gain and shaping settings (per channel, on the Main tab).** The defaults below are what the chip starts with, and the bench has used them so far:

| Setting (**Main** tab) | Default | Range |
| --- | --- | --- |
| **Gain** under **Trigger preamplifier (paT)** | 8 | 1 (highest gain) to 63 (lowest) |
| **Gain (paHG)** under **High gain** | 8 | 1 to 15 (about 0.5 to 8) |
| **Shaping time** under **High gain** | 4 | 1 to 15; time = code × 20 ns (default 80 ns) |
| **Gain (paLG)** under **Low gain** | 8 | 1 to 15 (about 5 to 80) |
| **Shaping time** under **Low gain** | 4 | 1 to 15; time = code × 20 ns |
| **shaping LSB = 120 ns** (each gain) | Unticked | Ticked makes each shaping code worth 120 ns instead of 20 ns |

High gain is for small pulses and low gain is for large ones. A muon pulse from a plastic scintillator is many photoelectrons tall, much bigger than the single-photoelectron dark pulses.

**What you need.** Oscilloscope, one SMA or BNC cable from **Analog_Probe** to a scope channel, SiPM bias on, dark box closed. Use only the cable shield for the scope's ground (section 3).

1. Click **ASIC config.** in the sidebar, then the **Probes/Masks** tab.
2. In the **Analog probe** box set **N° channel** to N. Choose **Shaper output, high gain**. Click **Apply probe**. The probe output is shared: routing one channel switches the others off.
3. On the scope trigger on the pulses just above the baseline noise (normal trigger mode). Dark pulses come many times a second, so you will see them straight away. Muon pulses come about A per minute for a plint of A cm², so wait for a few. The muon pulses are the tall ones.
4. Judge what you see:

| What you see on the scope | Meaning | What to do |
| --- | --- | --- |
| One clean peak that returns to the baseline; muon pulses clearly taller than noise and dark pulses | Gain and shaping are suitable | Keep the settings |
| Muon pulses barely above the baseline noise | High gain too low | Raise **Gain (paHG)** |
| Peaks flat-topped or all stopping at the same height | Clipping | Lower **Gain (paHG)**, and rely on the low-gain output for large pulses |
| Pulses long and often overlapping | Shaping time too long | Lower the high-gain **Shaping time** |
| Pulses very short and ragged | Shaping time too short | Raise the high-gain **Shaping time** |
| Large noise on the baseline between pulses | Interference | Check the grounds (section 3) |

5. Repeat with **Shaper output, low gain**: the large muon pulses should not clip there.
6. To change a setting: **ASIC config.** > **Main** tab, set **N° channel**, edit the values, click **Apply**. This is per channel, so repeat for channel M. It is kept until the board is power-cycled, and **Apply defaults (persists)** resets it. Then repeat the probe check.
7. **When you are done, switch the probe off:** **Probes/Masks** tab > **Off, all channels**. Leaving the probe on degrades the chip's performance, so it must be off for every scan and for the muon run.
8. Write the gain and shaping codes you ended with in the log (section 10).

If you change **Gain (paT)** (the trigger preamplifier), type the new code into **Trigger gain (paT)** on the bar (see "Trigger gain must match", section 6). If you change any gain or shaping time, redo Step 1 onwards: the noise floor, trims and hold delay all move with them.

### Step 1: Noise floor (Threshold scan tab, no test signal)

Dark box closed, bias on, generator outputs off.

1. Click the **Threshold scan** tab.
2. Set **Device / mode** to **Hardware connection**.
3. Set the values in the table below.
4. Click **Run hardware threshold**. The plot shows **Trigger rate (Hz)** against **Threshold DAC code**, live. Tick **Log Y** to see the whole range. Wait for the status to say completed. If it says failed or reports mismatches, power-cycle and start again.
5. Read the curve (see "How to read the noise curve" below). Write down the DAC where each channel reaches its floor.

**Threshold scan tab settings**

| Setting | Value to use | Why / leave alone |
| --- | --- | --- |
| **Device / mode** | Hardware connection | **Change.** The tab opens on Hardware connection, but check: Simulation shows a fake curve. |
| **First DAC** | 0 | **Change** (default is 0). Start at the bottom so the noise peak is visible. |
| **Last DAC** | 1023 | **Change** (default is 1000). Covers the full range. |
| **DAC step** | 10 | **Change** (default is 25). Finer steps show the shoulder. Use 5 for the plateau scan in Step 5. |
| **Counter window (ms)** | 100 | **Change** (default is 50). Longer window, less scatter in the rate. |
| **Averages** | 1 | Leave at default. |
| **Discriminator** | T1 | Leave at default. |
| **Trigger gain code** | 1 (follows the bar) | Leave alone: it follows **Trigger gain (paT)** on the bar, so every scan and the Acquisition page use the same gain (see "Trigger gain must match" in section 6). 1 is the highest trigger gain; the bench noise floors were measured at 1. |
| **Mask other channels** | Ticked | Leave at default. Only the selected channels count. |
| **Enable Ctest** | Unticked | Leave unticked: this is a noise scan with no test signal. |
| **Initialize FPGA (persists)** | Ticked on the first scan after every power cycle only | Later scans: unticked. |
| **Apply defaults (persists)** | Ticked on the first scan after every power cycle only | Later scans: unticked. It resets the chip, so it also wipes autocalibration trims. Never tick it after autocalibration. |
| **ASIC CSV (optional)** | Empty | Leave alone (packaged defaults). |
| **New run directory** | As proposed | Leave alone; note the name in the log. |

Channels and trigger channels come from the shared selection above the tabs.

**How to read the noise curve**

At low DAC the rate is huge (electronic noise, the pedestal). It falls steeply, then flattens into a **floor** (single-photoelectron dark counts from the SiPM, then almost nothing).

On the 2026-10-21 bench data, channels 6 and 32 with SiPMs fitted showed:

- a pedestal peak near DAC 100 to 150;
- then a dark-count shoulder;
- then a floor near 10² Hz by DAC about 400 to 480.

| Curve looks like | Meaning | Action |
| --- | --- | --- |
| Pedestal peak, shoulder, floor near 10² Hz by DAC 400 to 480 | Healthy SiPM channel | Use its floor in Step 5 |
| No shoulder; the rate drops to zero by DAC about 210 | Probably no bias or no SiPM connected on that channel | Check the bias supply, the HV cable, the edge connector and the SiPM |
| Flat, near zero at every DAC | Dead channel | Check the edge connector, SiPM and bias before blaming the chip |
| A shoulder near 10⁶ Hz that reaches DAC 500 or more | Light leak, interference or a loose connector | Check the dark box, the grounds (section 3) and the connectors |
| Floor arrives much later than the other channel | Noisy channel | Check the grounds (section 3); compare with its peer |
| Clipped or flat-topped, no smooth roll-off | Saturated | Lower gain or exclude the channel |
| Rates of 2 to 5 × 10⁵ Hz **below** the pedestal | Interference from extra ground paths | Remove the extra ground leads (section 3) |

Check the bias is really on: a biased SiPM shows a rate 2 to 5 times higher than an unbiased one at the same DAC. If it does not, the bias is off or disconnected.

### Step 2: Align thresholds (Autocalibration tab)

1. Switch on generator CH1 through the 20 dB attenuator into **IN_TEST1**. The target at the board is about 50 mV and 100 ns (`AMPL 1.0`, `ZLOAD OPEN`). Set it by hand on the front panel: pulse waveform, 100 ns width, burst mode with one cycle per trigger, trigger source external. The board's **IO1** output must go to the generator's external trigger input, so each pulse is fired by the board and lands inside an acquisition window. If the generator free-runs instead, pulses arrive at random times and the results are unreliable. Confirm on the scope that one pulse appears per board trigger.
2. Click the **Autocalibration** tab. This tab has no **Device / mode** box; it uses the connected board. It needs at least two selected channels.
3. Tick **Enable Ctest**. Leave everything else as in the table.
4. Click **Run autocalibration**. Wait for it to finish. It scans each channel, trims each threshold so the crossings line up, and does a final verification scan.
5. Switch the generator output off. The trims are written into the chip and stay there while the board stays powered. They are not saved to the board's memory, so a power cycle erases them: redo this step after one.
6. Click **Save calibration…** now, so the trims are kept in a file.

**Autocalibration tab settings**

| Setting | Value to use | Why / leave alone |
| --- | --- | --- |
| **Discriminator** | T1 | Leave at default. |
| **Mask other channels** | Ticked | Leave at default. |
| **Enable Ctest** | Ticked | **Change.** Autocalibration needs the internal test charge to find each channel's crossing. |
| **S-curve clock index (0..3)** | 3 | Leave at default. |
| **Count trigger level instead of rising edge** | Unticked | Leave at default. |
| **Trigger preamp gain code** (in **Optional gain override**) | 1 (follows the bar) | Leave alone: it follows **Trigger gain (paT)** on the bar. Trims depend on the gain, so redo autocalibration if you change it. |
| **Step 1: reference-channel LSB-ratio probe**: **First DAC code**, **Last DAC code**, **DAC step** | 0, 1000, 50 | Leave at default. |
| **Step 2: transition scan across selected channels**: **DAC step**, **Upper-bound margin**, **Upper-bound floor**, **Upper-bound cap** | 10, 150, 300, 1023 | Leave at default. |
| **Final: verification scan window**: **Codes before mean crossing**, **Codes after mean crossing**, **DAC step** | 50, 120, 2 | Leave at default. |
| **Initialize FPGA (persists)** | Unticked | Leave unticked. |
| **Apply defaults (persists)** | Unticked | Leave unticked. Ticking it wipes the trims. Apply defaults only on the first Threshold scan after power-up, before autocalibration. |
| **ASIC CSV (optional)**, **New run directory** | As proposed | Leave alone. |

### Step 3: Hold timing (Hold scan tab; optional but recommended)

This scan finds the **hold delay**: the time after the trigger at which the chip's shaped pulse is at its peak. The ADC must sample at that moment. A hold scan steps the hold delay from the first to the last value, records the pulse height in ADC counts at each step, and plots counts against hold delay. The curve rises, peaks and falls. **The hold delay at the top of the peak is the right value for pulser (Ctest) data fired by the synchro trigger.** Note it in the log. It is not the value for the muon run (section 6).

Setup first:

1. Generator CH1 through the 20 dB attenuator into **IN_TEST1**, output on, with the same pulse and external-trigger settings as in Step 2, and the board's **IO1** output on the generator's external trigger input.
2. In the shared selection pick the channels you want to record (bench test: channels 6 and 32). **Trigger channel (T1)** must be one of the selected channels, otherwise Preview and Run fail. The hold scan uses T1 as its trigger channel (bench test: 6). It is the channel whose Ctest pulse crosses the discriminator and starts the acquisition; the hold delay is measured from that moment. The other selected channels are read out at the same time.
3. Click the **Hold scan** tab. Set **Device / mode** to **Hardware connection**.

Then set the values below, click **Preview** to check them, and click **Run hardware hold scan**.

**Hold scan tab settings** (values verified working on the bench on 2026-10-21)

| Setting | Value to use | Why / leave alone |
| --- | --- | --- |
| **Device / mode** | Hardware connection | **Change** if it shows Simulation. |
| **Hold mode** | External (FPGA delay, ns) | Leave at default. The hold delay is set by the FPGA in nanoseconds. |
| **First hold delay (ns)** | 0 | Leave at default. |
| **Last hold delay (ns)** | 800 | Leave at default. |
| **Hold step (ns)** | 25 | Leave at default. Smaller steps give a finer peak but take longer. |
| **Acquisitions per point** | 10 | Leave at default. |
| **Per-batch timeout (s)** | 5.000 | Leave at default. |
| **Discriminator** | T1 | Leave at default. |
| **Set threshold DAC before scan** | Ticked, with **Threshold DAC** 450 | **Change.** Optional, but if used the value must be below the Ctest pulse height. 450 worked. The operating threshold (about 540) is too high for the Ctest pulse. |
| **Mask other channels** | Ticked | Leave at default. |
| **Enable Ctest** | Ticked | **Change.** Without it there is no pulse. It is enabled on the trigger channel only. |
| **Pulse FPGA synchro trigger per ADC batch** | Ticked | **Change.** This makes the board send its trigger out on IO1 so the generator fires. If unticked the generator never fires and the scan fails with "ADC acquisition timed out waiting for FPGA word 4 bit 5". |
| **Initialize FPGA (persists)** | Unticked | Leave unticked. |
| **Apply defaults (persists)** | Unticked | Leave unticked. Ticking it would wipe the autocalibration trims. |
| **Sync IO** | io1 | Leave at default. |
| **Set sync IO mux index before scan** | Ticked, with **Sync IO mux index** 5 | **Change** the tick only. Index 5 is the value found to work in bench testing: it routes the FPGA synchro-trigger pulse to IO1, which fires the generator. Do not change the 5. |
| **Conversion delay (ns)** (in **External hold mode ADC timing**) | 400 | Leave at default. |
| **Trigger type** (same group) | 0 | Leave at default. |
| **Trigger source**, **ADC window (ns)**, **ADC trigger count** (same group) | 3, 50, 1 | Leave at default. |
| **Reset-n manual**, **Use external ASIC acquisition trigger**, **Use vendor peak-sensing path** | Unticked | Leave at default. |
| **Optional gain overrides** (**Trigger preamp gain code**, **High-gain shaper code**, **Low-gain shaper code**) | Keep current | Leave alone. A hold scan needs no gain setting: it records both high gain and low gain automatically from the gains now in the chip. |
| **ASIC CSV (optional)**, **New run directory** | As proposed | Leave alone. |

**Bench result, 2026-10-21 (channels 6 and 32 selected, trigger channel 6).** The run completed 33 points. The channel 6 high-gain curve peaks near **525 ns**, at about 820 ADC counts above a pedestal near 100 counts. Channel 32 stays flat, because Ctest is enabled only on the trigger channel. That flat curve is expected, not a fault.

**How to read the result.** Look at the high-gain curve of the trigger channel. Find the hold delay where the counts are highest. Read that value off the plot (or from the saved result: use **Open saved result…**). Write it in the log. **Careful:** this scan is fired by the external synchro pulse, so its peak (about 525 ns on the 2026-10-21 bench) is measured from that pulse. The muon run triggers on the channel's own discriminator, which needs a much shorter hold delay. Choose that one as described in section 6, "Choose the hold delay for the muon run". With 25 ns steps the peak is known to within about 25 ns; rerun with a smaller **Hold step (ns)** and a narrower first and last delay if you need more.

After the hold scan, for a light check with real SiPM pulses, move the CH1 cable from the attenuator to the LED in the dark box. For LED acquisitions also connect generator CH2 to **IO6** and tick **Use external ASIC acquisition trigger (IO_FPGA6)** on the Acquisition page.

Switch the generator outputs **off** afterwards.

**Hold delay (ns) on the bar.** After you choose the hold delay for the muon run (section 6), type it into **Hold delay (ns)** on the Save/Load bar. It is saved in the calibration file and restored by **Load calibration…**, and the **Acquisition** page's **Hold delay (ns)** takes the same value (changing either one changes the other). The app starts at 530, which is wrong for muon runs: change it.

### Step 4: S-curve (optional)

The **S-curve** tab measures the transition of each channel against test-pulse amplitude. It is not needed for the muon run. Skip it unless the operator asks for it. If you run it, use the same generator and IN_TEST1 setup as in Step 2 and leave its settings at their defaults.

### Step 5: Choose the operating threshold, then check it with a plateau scan

Pick a DAC just above the common noise floor from Step 1, with a margin of about 40 to 70 codes. For the 2026-10-21 data this gives about 520 to 550. This is **not** a universal value: write down the number and which noise floor you took the margin from. Type it into **Operating threshold** on the Save/Load bar.

Then check it. Generator outputs off. On the **Threshold scan** tab repeat Step 1 with **Initialize FPGA (persists)** and **Apply defaults (persists)** unticked, and set **First DAC** and **Last DAC** to about 100 codes either side of your choice, and **DAC step** 5. For example, if you chose 540, set **First DAC** 440 and **Last DAC** 640. The rate should show a **plateau**: a range of thresholds where the rate changes slowly. Choose the operating threshold in the middle of the plateau and update **Operating threshold** if it moved. A rate that keeps falling steeply means you are cutting into real pulses or are still in noise.

Now click **Save calibration…** again.

### Step 6: Save the calibration record

Write in the log: noise floor DAC per channel, trims (the saved calibration file name), hold delay, chosen threshold and why, gain setting, bias voltage and current, date, who ran it. Keep the path of each run folder.

**Calibration is done when** every used channel has a reviewed noise curve, the threshold is chosen with a written reason, the calibration file is saved, and the record is in the log. Switch the generator outputs off before the muon run.

## 6. Data acquisition

You take two kinds of run: a **signal run** (muons present) and a **background run** (same settings, noise estimate). The background run tells you how many counts are noise, so the muon rate is the difference.

**Decide first: what counts as a muon event?**

A single SiPM channel above threshold is not proof of a muon, because dark counts and electronic noise also cross a low threshold. We have two plints with a SiPM each, so two cleaner options exist:

- **Coincidence of the two channels:** the Acquisition page offers **Trigger type: 2 channels coincidence**, with a **Coincidence/time window (ns)**. Whether this really requires two distinct channels inside the window is still being verified in the project (see `PLINT_STUDENT_MVP_DIRECTIVE.md`, Priority 0). Until that is confirmed, record both channels and apply the coincidence **offline** from the saved data, and say so in the report. Offline cuts after a looser trigger carry dead-time effects, so keep the trigger rate low.
- **Amplitude cut:** a muon crossing a plastic scintillator gives a pulse many photoelectrons tall, far above single-photoelectron dark counts. Choose a threshold (or an offline cut on the recorded amplitude) above the single-photoelectron level. Check the amplitude histogram: a broad muon peak should stand clear of a noise spike at low amplitude.

Call the result **accepted events**. Do not call it "muon rate" until the detector's known rate has been reproduced (section 8). Two SiPMs seeing a light pulse does not by itself prove the event was a muon.

**Trigger settings for the two-plint coincidence**

Use exactly these values on the **Acquisition** page. The rest stay at their defaults.

| Setting | Value | Why |
| --- | --- | --- |
| **Trigger type** | 2 channels coincidence | Both plints must fire together. |
| **Trigger source (T1 slot)** | Individual trigger | T1 is the discriminator of channel **T1** (the first channel). |
| **Trigger source (T2 slot)** | Individual trigger | **Change from the default NORT1.** T2 must be the discriminator of channel **T2** (the second channel). NORT1 is the OR of all channels and would make it a coincidence with any channel. |
| **Coincidence/time window (ns)** | 50 | Both pulses must arrive within this time. Start with 50; see below. |
| **Time-window trigger count** | 1 | Only used by the **Time window** trigger type. Leave it. |
| **Threshold DAC** | Follows **Operating threshold** on the bar | Leave alone. There is no Keep current here any more. |
| **Mask other channels** (tick box lower on the page) | Ticked (the default) | With both sources on Individual trigger, the app unmasks exactly the two named channels and no others. |
| **Trigger preamp gain code** | 1 (follows the bar) | The same gain as the scans (see below). |
| **Use external ASIC acquisition trigger (IO_FPGA6)** | Unticked | Muon runs use the self-trigger. |

The coincidence needs both channels to cross threshold inside the window, so the rate is much lower than a single channel's. **Check that it works:** after a short run click **Open saved run…** and look at the spectra and the events: in every event both channels should be above their pedestal. If many events show only one channel above pedestal, the coincidence is not being enforced, so keep both channels recorded and apply the coincidence offline (the open Priority 0 item in the project).

**Trigger gain must match.** **Trigger gain (paT)** on the Calibration bar is used by every scan and by the Acquisition page, so they cannot disagree. Keep it at 1. If you ever use an older version of the app, or the scripts, make sure each place uses the same code: on 2026-10-21 the scans ran at gain 1 while an acquisition left on **Keep current** ran at the chip's own value (8). The threshold DAC means a different pulse height at each gain, so a threshold chosen at gain 1 is far too high at gain 8: no pulse crosses it and no batch ever fills (the app got zero batches in 105 s). Trims also depend on gain, so redo autocalibration if the gain you use changes.

**Choose the hold delay for the muon run**

The hold delay is when the chip freezes the shaped pulse to be measured. A muon run is fired by the channel's own discriminator, so the delay is counted from that moment. The Hold scan in section 5 is fired by the external synchro pulse and gives a different number (about 525 ns), which is **wrong** for muons: with 525 ns the chip freezes the signal long after the pulse is gone, and every event reads the pedestal.

Find it with the muons themselves, using the trigger settings above (coincidence, Threshold DAC at your operating threshold):

1. On the **Acquisition** page set **Acquisitions per batch** to 10, **Batches** to 1 and **Timeout (s)** to 150.
2. Run once for each **Hold delay (ns)** of 10, 20, 30, 40, 55, 70, 100 and 130. Each run takes about 30 to 60 s.
3. After each run click **Open saved run…** and note where the high-gain spectrum of each channel sits (the mean of the **hg** values is easiest).
4. Choose the delay in the middle of the plateau where the pulses are tallest.

Bench result, 2026-10-21 (channels 6 and 32 in coincidence, threshold 540, 10 events per point, so about ±15% scatter):

| Hold delay (ns) | 10 | 20 | 30 | 40 | 55 | 85 | 100 | 130 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Channel 6 mean hg | 257 | 243 | 237 | 193 | 202 | 163 | 164 | 121 |
| Channel 32 mean hg | 558 | 636 | 707 | 652 | 637 | 417 | 338 | 265 |

The pedestal is about 90 to 100. The pulses are tallest around 20 to 55 ns and fall off beyond about 70 ns. Use about **30 ns** as the starting value and confirm it with your own sweep. At 525 ns every event sat on the pedestal.

**Signal run, step by step**

1. Confirm sections 4 and 5 are done in this power-on session, with the calibration saved, the generator outputs are off, and the dark box is closed.
2. Click **Acquisition** in the sidebar. Set **Device / mode** to **Hardware connection**.
3. Check the line at the top of the page. It reads "Channels … · trigger T1=…, T2=… (set on the Calibration page)". The channels and trigger channels come from the shared selection on the **Calibration** page: T1 is the first channel and T2 is the second. If they are wrong, go back to **Calibration** and change them there. This page has no channel grid of its own.
4. Set the trigger as in the table above. **Threshold DAC** and **Trigger preamp gain code** follow the bar: check they read your operating threshold and 1.
    - **Hold delay (ns)** and **Conversion delay (ns)** are on this page too. Set **Hold delay (ns)** to the value you chose above (the app starts at 530, which is wrong for muon runs). Leave **Conversion delay (ns)** at 400.
5. Set **Acquisitions per batch** and **Batches**. Events requested = acquisitions per batch × batches. Aim for at least **400 accepted events** (see the table below).
6. Set **Timeout (s)** longer than the time one batch needs to fill. The default 5 s is far too short for muons and the run will fail with a timeout. At about 1 muon per cm² per minute a plint of A cm² gives about A events per minute in single mode, and fewer in coincidence (only muons through both plints), so a batch of 10 events can take 10 / A minutes or more. Use at least three times your estimate, and keep **Acquisitions per batch** small (about 10) so a timeout loses little. Worked example for a 5 × 5 cm plint (about 25 per minute alone; assume 10 to 20 per minute in coincidence with the other plint stacked on top of it): a batch of 10 events takes about 30 to 60 s, so use **Acquisitions per batch** 10, **Timeout (s)** 300 and **Batches** 40 for 400 events (about 16 to 40 minutes). If the plints are side by side instead of stacked, almost no muon crosses both, and every batch will time out. If a batch times out at 300 s, do not just raise the timeout: first run a short single-channel acquisition to check each plint sees about 25 per minute alone.
7. Check **New run directory** and note its name in the log. Name it `plintID_chN-chM_thrDAC_biasV_signal_YYYYMMDD` if you can edit it.
8. **Write down the wall-clock start time**, click **Run hardware acquisition**, and write down the stop time when the status says completed. The rate is counts divided by elapsed time, so these times matter more than anything else.
9. Do not touch the board, cables or dark box during the run. If the app shows a fault, stop; do not retry automatically (section 4).
10. When it ends, click **Open saved run…** and check that the file reopens and the number of physical events matches the screen. The app distinguishes physical events from channel rows; use events.

**Background run**

Repeat steps 1 to 10 with the same settings and the same duration. A true no-muon background is hard to make at sea level, so use the best of these and record which:

- **Offline estimate (best):** with the coincidence or amplitude cut applied, count the events outside the coincidence window or below the muon peak and scale them to the same range. This gives the noise level under the muon signal.
- **Shielded run:** put thick lead or iron over the plints. This removes soft particles but not hard muons, so it gives only an upper bound on the non-muon background.
- **Not valid:** switching the bias off. It removes the dark counts that are part of the noise you are trying to measure.

**How long should a run be?**

Counting is random, so the uncertainty is about the square root of the number of counts. For about 5 percent uncertainty you need 400 counts.

| Detector area (cm²) | Expected rate (muons per minute, ≈ area × 1) | Run length for 400 counts |
| --- | --- | --- |
| 10 | about 10 | about 40 min |
| 50 | about 50 | about 8 min |
| 100 | about 100 | about 4 min |
| 400 | about 400 | about 1 min |

For small areas split the run into blocks of 5 to 10 minutes. The blocks show whether the rate drifts, which checks the stability of the board and the bias.

**Hardware speed limits**

Self-triggered acquisition is fast (100,000 events in a few minutes). External-trigger acquisition through IO6 delivers only about 20 events per second in tests, so do not use it for muon counting. If you must, keep batches to 100 events or fewer and set the timeout to 60 s or more.

## 7. From counts to a rate per minute

The rate is accepted events divided by elapsed minutes, after removing the background. Do it by hand first so you understand it.

1. Count accepted events in the signal run: N_s. Elapsed time from your wall-clock times: T_s in minutes.
2. Do the same for the background run: N_b and T_b.
3. Compute the rates and subtract.

```latex
R_s = \frac{N_s}{T_s}, \qquad R_b = \frac{N_b}{T_b}, \qquad R = R_s - R_b \quad \text{(per minute)}
```

4. Uncertainty. Counts are Poisson, so each count has an uncertainty of its square root:

```latex
\sigma_R = \sqrt{\frac{N_s}{T_s^2} + \frac{N_b}{T_b^2}}
```

5. Rate per area, the number you compare with the reference detector and with the cosmic-ray rule of thumb:

```latex
\Phi = \frac{R}{A} \quad \text{(per cm}^2\text{ per minute)}
```

A is the active area in cm² from section 2. Report R ± σ_R per minute and Φ ± σ_R/A per cm² per minute.

**Worked example (invented numbers, for practice only)**

A 100 cm² detector gives N_s = 480 in T_s = 5.0 min, and N_b = 20 in T_b = 5.0 min.

- R_s = 96.0, R_b = 4.0, so R = 92.0 per minute.
- σ_R = √(480/25 + 20/25) = √20 = 4.5 per minute.
- Φ = 0.92 ± 0.045 per cm² per minute, consistent with the rule of thumb of about 1.

**Check stability across blocks.** Split the run into blocks of equal length and compute R for each. If the blocks scatter by much more than their σ_R, something drifted (bias, temperature, board state, interference). Note it and do not average it away.

**Save the analysis.** Put the numbers in the lab log and keep the raw run folders. Do not edit the raw data.

## 8. Judging the board

The board is good if its rate for the known detector agrees with the detector's reference rate within the combined uncertainty, and stays steady from block to block. Compute the ratio of board rate to reference rate and look it up in the table. The cut-offs are proposals; the operator should confirm or change them before the first real verdict.

```latex
r = \frac{R_{\text{board}}}{R_{\text{reference}}}
```

| Ratio r | Verdict | What to do |
| --- | --- | --- |
| 0.9 to 1.1, blocks steady | Pass | Record and move on |
| 0.7 to 0.9 | Board loses events | Check threshold too high, dead time, edge connector, hold timing; repeat |
| Above 1.1 | Extra counts | Threshold too low, noise, interference, dark counts; raise threshold and recheck the background |
| Below 0.7 | Fail | Check connections, bias, calibration, then compare channel by channel |
| Blocks scatter widely | Unstable | Check bias, cabling, board hangs; do not accept the result |

Where the reference rate comes from, in order of preference:

1. **Best:** the same detector read out at the same time by a trusted system, or by that system just before and just after on the same day, in the same place and orientation.
2. **Good:** an earlier measurement from this lab at the same location and orientation: **FILL IN**.
3. **Rough check only:** about 1 muon per cm² per minute times the active area. It cannot show the board is good to better than a few tens of percent, because the real value depends on efficiency, thickness, orientation, altitude and what is above the bench. It does catch gross faults such as a rate ten times too high or too low.

**Efficiency caveat.** A detector never counts every muon. If the reference rate came from a different readout, differences in threshold and efficiency cause real differences. Use the same threshold in photoelectrons where possible, and state the threshold used.

**Also report** the number of board hangs during the measurement, whether the app reported any faults, the noise floor per channel, and the block-to-block scatter. These decide whether the board is trustworthy, not only whether the rate matches.

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Acquisition never fills a batch although the plints are fine | Trigger gain on the Acquisition page differs from the gain used for the scans, so the threshold is too high | Set **Trigger gain (paT)** on the bar to the value used for the scans (1) and redo autocalibration |
| App cannot connect | Another program owns the port, or board unpowered | Close other programs (`lsof /dev/cu.usbserial-RD3_32*`), check 5 V and USB |
| "no response" or "i2c FIFO timed out", or scans blocked after a fault | Known board hang, often when the board shares a USB hub | Click **Acknowledge fault review** on **ASIC config.** (no disconnect needed). If the board answers, scans work again. If not: bias off, power-cycle 5 V and USB, disconnect and reconnect, re-apply defaults, redo autocalibration. Move the board to a USB port of its own |
| Trims lost after loading a calibration file | Trim re-apply is untested on hardware | Run a threshold scan to check; if it looks wrong, redo autocalibration |
| Channel drops to zero by DAC about 210 with no shoulder | No bias or no SiPM on that channel | Check bias, HV cable, edge connector |
| Defaults verify shows hundreds of mismatches | I2C controller left in a bad state | Initialize FPGA, apply defaults again; if no reply, power-cycle |
| Truncated ADC readback | Data stream out of step | Wait about 15 s for the dump to drain, then recover as above |
| Scan curve flat at a meaningless value | Defaults not applied after a power cycle | Tick **Apply defaults (persists)** for the next threshold scan, then redo autocalibration |
| 2 to 5 × 10⁵ Hz triggers below the pedestal | Cabling interference | Remove extra ground leads and earth terminals (generator, scope, bias supply) from the board's ground; keep the USB port to the board alone |
| Rate the same with bias on and off | Bias not reaching the SiPMs | Check the supply output, the current reading, the HV cable and the edge connector |
| Rate far too high | Threshold in the noise, light leak | Raise the threshold, check the dark box is closed and light-tight, take a background run |
| Rate far too low | Threshold too high, wrong channel, dead channel | Redo the plateau scan, check the channel numbers in the log |
| Rate drifts during the run | Temperature, bias drift, board state | Keep the room steady, log bias and current, compare blocks |
| External-trigger run times out | Board delivers about 20 events per second on that path | Use self-trigger, or batches of 100 events at 60 s timeout |

When anything looks wrong, change one thing at a time and write down what you changed.

## 10. Lab log template

Copy this into a new entry for every session. Fill it as you go, not afterwards.

```markdown
# Muon rate session — YYYY-MM-DD

Operator:
Board ID / firmware:
Plints (2 x Luxium) size / area A (cm2):
SiPM 1 and SiPM 2 type / serial:
Arrangement (stacked / side by side) / location / floor:

## Setup
Board channel N (plint 1) / channel M (plint 2):
Bias voltage (V) / current (mA):
Dark box closed before power? yes/no
Bias on at (time):
Board on its own USB port? yes/no
Generator outputs off and no extra ground leads on the board? yes/no

## Start-up
Firmware status after Connect (expect 0x05):
First scan after power-up run with Initialize FPGA and Apply defaults ticked? yes/no

## Calibration
Noise-floor DAC per channel:
Autocalibration run folder:
Operating threshold (DAC) and why:
Plateau scan folder:
Hold delay at peak (ns):
Gain and shaping codes used (paT, paHG, paLG, shaping HG/LG):
Calibration file saved (name):

## Signal run
Run name / folder:
Start time / stop time / elapsed T_s (min):
Accepted events N_s:
Event definition (coincidence / amplitude cut):

## Background run
Run name / folder:
Elapsed T_b (min) / events N_b:
Background method:

## Result
R = R_s - R_b (per min):   +/- sigma_R:
Phi = R / A (per cm2 per min):
Reference rate and its source:
Ratio r = R_board / R_reference:
Block-to-block scatter:

## Problems
Hangs, faults, power cycles, interference seen:

## Verdict and next step
```

**Before you leave:** bias to 0 V and off, generator output off, run folders left in place (never delete them), log saved.
