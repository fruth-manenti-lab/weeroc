# RADIOROC bench runbook

How to run the RADIOROC board, signal generator and SiPM/plint setup safely and
reproducibly, written from what actually happened on the bench. Session-by-session
evidence is in `IMPLEMENTATION_STATUS.md`, and the next task list is in
`NEXT_SESSION.md`. This file holds the procedures and lessons that stay true from
one session to the next.

Last updated: 16 October 2026 (RADIOROC 42).

## 1. Equipment and connections (as of October 2026)

| Item | Connection | Notes |
|---|---|---|
| RADIOROC 2 board | `/dev/cu.usbserial-RD3_320` (control), `…_321` (second FTDI interface) | Needs USB **and** the external 5 V/1 A supply to run. |
| Aim-TTi TGF4162 generator | `/dev/cu.usbmodemDA20FE0E1` (pyvisa, `.conda-radioroc`) | **Use channel 1 only** (see §4). |
| SiPMs | On channels 4, 6 and 32 of the plint | Bias from a separate supply that this Mac cannot see (≈29–29.5 V used so far). Record the voltage for every run. |
| LED | Flush against the plint, driven by generator CH1 | Its connection is loose: the light output flickers. |
| Keysight PSU, Tektronix scope | Not visible over USB from the macOS host used for this 16 October procedure | Other dated sessions reached both over VISA; verify the current host rather than assuming. |

Only one program may own the board. Close the desktop app before running any
script, and the other way round. Check with `lsof /dev/cu.usbserial-RD3_32*`.

## 2. Start-of-session checklist

1. **Power.** Board on USB and 5 V. Record the SiPM bias voltage, or "off".
2. **Status check (read-only):**
   `PYTHONPATH=src:. .venv-foundation/bin/python scripts/radioroc_check_connection.py --port /dev/cu.usbserial-RD3_320`
   It should report `address 100 = 00000101`. Also read `--address 0`, which
   should be `00111111`. If word 0 has bit 1 set (`01111111`), an I2C transfer
   was interrupted, so power-cycle the board.
3. **After every power cycle, apply defaults before any scan.** A power cycle
   resets the ASIC to its power-on registers, which are *not* the vendor defaults.
   Scans run without defaults give meaningless results (we got a flat HG of 704
   instead of a pulse shape). Apply and verify defaults with
   `radioroc_runs/bench_harnesses_RADIOROC42/defaults_traced.py`, which writes
   the table, then verifies all 677 rows in 64-row reads.
4. **Then redo autocalibration.** The power cycle also wipes the threshold trims.
5. Only then run the scan you actually want.

## 3. Known board hang (open problem)

The board sometimes stops answering, with `TransportTimeoutError: no response…`
or `i2c FIFO transaction timed out`. Only a power cycle (USB + 5 V) recovers it.

- It happened 4 times on 16 October, each time on a large I2C operation:
  the full 677-row defaults write, a full "Read all", or a multi-chunk read.
- Our I2C FIFO sequence matches the vendor app's exactly, confirmed from its
  bytecode (`local_artifacts/generated_notes/radioroc_i2c_pydisasm.txt`). The
  cause is therefore not established.
- Correlations seen, not proven: the first large operation after ≥20 minutes
  idle, and once right after the operator handled the setup near the board.
  Fresh after a power cycle, reads of every size worked.
- **Shared USB hub made it much worse (operator, 19 October).** The board was on a
  hub with other devices and hung 11 times that day, after as few as 1-6
  acquisitions. After the operator moved it to a port of its own, about 34
  acquisitions ran clean (a 23-point `hold_series.py` on one connection, then a
  10-step amplitude series), then it hung a 12th time on the direct port, at the
  first request after a generator `OUTPUT OFF` (output relay switching). So the hub
  was a major contributor but not the only one. Keep the board on its own port;
  suspect electrical transients from the generator (output on/off, remote writes)
  and ground/cabling next. Count hang-free acquisitions here as they accumulate.
- **Soft recovery to try first (19 October):** if the board still *answers* but the
  readback is garbage (a defaults verify with hundreds of mismatches whose values are
  bit-shifted copies of the expected ones, e.g. `10001000` read as `01000100`), the
  I2C controller was left in a bad state by an earlier timeout. `initialize_fpga()`
  followed by `apply_default_config()` cleared it (0 mismatches) without a power cycle.
  If requests get no response at all, that is the real hang: power-cycle.
  After a truncated ADC readback (`expected N bytes, received M`) the stream is out of step
  (replies start with `aa 01 ..` data); wait ~15 s for the dump to drain, then the same
  recovery works. Dark-count finger plots need `Reset-n manual` ON (hold 110 ns, threshold
  340-420, LED dark via `AMPL 0.2`, not `OUTPUT OFF`).
- The app handles it correctly: a visible fault, cleanup reported, the next run
  blocked until review. Do not retry automatically. Power-cycle, re-apply
  defaults, then continue.

## 4. Signal generator rules

- **Touch channel 1 only.** `CHN 2` switches the front panel to channel 2 and
  confuses the operator.
- Every remote command puts the generator in REMOTE (front panel locked). Send
  `LOCAL` as the last command. `bench_harnesses_RADIOROC42/gen.py ON|OFF` does
  `CHN 1`, `OUTPUT ON/OFF`, `LOCAL`.
- Burst/trigger-source commands (`BST…`) are unsupported over USB on this
  firmware (error −111). Trigger mode can only be set on the front panel.
- Settings cannot be read back (`EER?` only says a command parsed). So results
  that depend on the pulse (Ctest, LED) need the operator to confirm the actual
  output on a scope, or at least confirm that it is pulsing and in which trigger
  mode.
- Tell the operator before changing any generator setting they configured.

## 5. Test-pulse (Ctest) path

- Signal path: generator CH1 → 20 dB attenuator → `in_test1`. The target at the
  board is ~50 mV, ~100 ns (`AMPL 1.0`, `ZLOAD OPEN`; a 50 Ω load halves the
  open-circuit value).
- Ctest on channel *n* is bit 3 of ASIC register (*n*, 7) (default `00001111` →
  `00011111`). The Acquisition tab has no Ctest control. Set it with the
  Registers tab's single-register **Write**, and write the original value back
  afterwards. Avoid "Read all" (see §3).
- If the generator free-runs (internal trigger), Ctest events trigger on the
  channel's own discriminator, so hold delay is measured from the discriminator.
  That is the same reference the plint experiment uses.
- Result recorded on 16 October (channel 4, threshold 450, conversion 400 ns):
  peak at hold 60–80 ns, then undershoot below the pedestal from ~400 ns.
  **Provisional**: later runs with the same settings gave a saturated or flat HG,
  apparently because the generator state changed. Re-check with a scope.

## 6. SiPM and LED work

- **Check the bias is actually on.** Biased SiPMs raise the above-pedestal rate
  2–5× compared with unbiased (channel 4 at DAC 400: ~1.4×10⁵ Hz biased against
  ~3×10⁴ Hz unbiased). A whole afternoon of LED tests was void because the bias
  was off.
- **Interference:** whenever the bias supply (and the generator/scope) is
  cabled, SiPM channels trigger at 2–5×10⁵ Hz *below* the pedestal, even when
  unbiased. Channels without a SiPM stay clean. It comes in through the cabling
  or ground paths: one ground point, a floating bias supply, and no scope or
  generator ground on the board during SiPM runs. Fix it before photoelectron
  work.
- **LED check:** a threshold scan with CH1 on, then CH1 off, then CH1 back on,
  run back to back with nobody touching the setup. On 16 October, with the
  generator pulsing continuously, the LED was clear at DAC ~480: channel 6
  1.5×10⁵ Hz on against 230 Hz off.
- **LED pulses are small in the ADC** at default shaper gains (~5–15 counts
  above the pedestal), too small to resolve photoelectron peaks.
- **HG/LG swap (fixed 2026-10-19):** `high_gain_code=15` changed the *low-gain*
  reading because `set_energy_shaper_gain` had the nibbles reversed. The vendor
  map is HG gain bits `[3:0]`, LG gain bits `[7:4]`; code and a regression test
  now follow it. Not yet re-confirmed on the bench (HG response with code 15).

## 7. Calibration procedure status (plint MVP)

The procedure itself is in `docs/plint_calibration_procedure.md`. Status:

| Step | Status |
|---|---|
| 1 Pedestal/noise | Unbiased scans done (floors DAC 320 for ch 4/6, 450 for ch 32). Biased floors still contaminated by interference. |
| 2 Threshold alignment | Autocalibration works in the app (operator), but trims are lost at every power cycle. |
| 3 Operating threshold | DAC 575 chosen in RADIOROC 40; revisit once biased floors are clean. |
| 4 Relative gain | Blocked: needs the HG/LG mapping check and a usable signal size. |
| 5 Hold timing | Ctest 60–80 ns provisional. Needs confirmation with real SiPM/LED pulses. |
| 6 Calibration record | Tool exists and accepts autocalibration runs; not yet written for real. |

## 8. Driving the app from scripts (bench harnesses)

The scripts in `radioroc_runs/bench_harnesses_RADIOROC42/` (local, not
committed) drive the real `MainWindow` offscreen, so runs go through exactly the
same code a student uses. They are configured with `CARD_*` environment variables:

```bash
CARD_CHANNELS=4,6,32 CARD_TAG=my_run_ \
  PYTHONPATH=src:. .venv-foundation/bin/python radioroc_runs/bench_harnesses_RADIOROC42/mainwindow_card.py
```

- `mainwindow_card.py`: connect, then a Threshold scan (`CARD_DAC_MIN/MAX`,
  `CARD_STEP`, `CARD_GAIN`, `CARD_DEFAULTS=1` to apply defaults).
- `holdscan_card4.py`: Hold scan (`CARD_TRIGGER`, `CARD_THRESHOLD`,
  `CARD_HOLD_MIN/MAX/STEP`, `CARD_ACQ`, `CARD_CTEST=0/1`, `CARD_SYNC=0/1`,
  `CARD_HG`).
- `acq_card.py`: enables Ctest through the Registers tab, runs an Acquisition,
  reopens it, and restores the register (`CARD_REG47=<original value>`).
- `defaults_traced.py`, `i2c_trace_probe.py`: defaults and I2C diagnostics with
  a per-request trace.

Each run writes an evidence folder under `radioroc_runs/` (events, screenshots,
saved data). Never delete those folders.

## 9. Software environment on this Mac

- Development and the GUI: `.venv-foundation` (PySide6 6.11). Run checks with
  `PYTHONPATH=src QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg .venv-foundation/bin/python tools/check_development.py`
  and rely on its final test summary; the suite grows over time.
- `.conda-radioroc` has **no PySide6 here**: the same check "passes" while
  skipping GUI tests. Use it only for pyvisa/generator scripts and legacy tools.
- Launch the app: `.venv-foundation/bin/radioroc-desktop`.

## 8. External-trigger acquisition rate (19 October)

With `external_trigger` on (generator CH2 into `IO6`), the board delivered only about **20 events per second**,
whatever the generator rate (200 Hz during these runs; 100 events took ~5 s and 200 events ~11 s). Cause not known
(probably a fixed per-event handshake in the ADC sequence). Consequences: use batches of at most 100 events or
set `timeout_s` to 60 s or more, otherwise a 200-event batch sits right at a 10 s timeout and fails
intermittently with `ADC acquisition timed out waiting for FPGA word 4 bit 5`; budget about 100 s per 2000 events.
Self-triggered (discriminator) acquisition is much faster (100,000 events in a few minutes).
The LED saturates: with a 40 ns pulse, `HILVL` 4 V and 5 V gave identical light (median 119.0 vs 119.2),
so apparent trends over a descending sweep were baseline drift (pedestal 103 to 106); use shorter pulses or lower
levels and alternate the order as a control.
