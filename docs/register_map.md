# RADIOROC register map (compact)

Written for someone driving the board from a copy of this project. Source: the vendor GUI's
bytecode (`local_artifacts/`, widget tooltips and `send_*` handlers), `radioroc_client.py`, and bench
tests on the real board. Tags: **[HW]** exercised on the board in a measurement that worked,
**[VB]** recovered from the vendor bytecode only, **[?]** uncertain. Where the vendor text and the
code disagree, the code is quoted.

**Bit notation.** `[7:0]` with bit 7 the *leftmost* character of the 8-bit string. The Python code
indexes those strings left to right (`data[0]` is bit 7), and the vendor texts and some error
messages ("FPGA word 4 bit 5") also use string indices; a string index `i` is bit `7-i`.

## 1. Serial link (USB, FTDI, 115200 8N1) [HW]

| Frame | Bytes |
|---|---|
| write 1..256 bytes to FPGA word `A` (0..127) | `AA, n-1, A, data..., 55` |
| read `n` bytes (1..65536) from `A` | request `AA, (n-1)&FF, A|80, (n-1)>>8, 55`; reply = `n + 4` bytes, payload = reply[3:-1] |

One FPGA word = 8 bits. "Rows" below are ASIC I2C registers reached only through the I2C FIFO.

## 2. ASIC I2C access (through FPGA words) [HW]

A row is `(add, subadd)` plus one data byte. On the FIFO each row is **4 bytes**: chip id (`1`),
`add` and `subadd` as one big-endian 16-bit field (8+8 bits), data byte. Sequence for a transaction:
`word0` bit 6 set; write the FIFO (word 56, chunks of at most 256 bytes); word 60 = `00000000`
then `00000010`; poll word 4 bit 0 (string idx 7) until 1; word 60 = `00000100`; read results
from word 55 (one byte per row for reads); restore `word0` bit 6. Always idle word 60 afterwards.
Full defaults = 677 rows in `configs/radio_default_i2c.csv`, written in one 70-request transaction.

## 3. ASIC per-channel rows `(ch, subadd)`, ch = 0..63

| Row | Bits | Meaning | Notes |
|---|---|---|---|
| `(ch,0)` | `[7:0]` | input DAC DC value | [HW] |
| `(ch,1)` | `[7:6]` | trigger-preamp (paT) feedback compensation | [VB] keep 0 unless slowing the preamp |
| | `[5:0]` | **paT gain code** | **inverted: 1 = max gain, 63 = min, 0 = open loop (unbiased)** [HW] |
| `(ch,2)` | `[3:0]` | **HG** energy gain code | higher = more gain; V/V = 5 pF / (62.5 fF x (16 - code)); default 8 [HW] |
| | `[7:4]` | **LG** energy gain code | V/V = 500 fF / (62.5 fF x (16 - code)) [VB]; (earlier code had HG/LG nibbles swapped; fixed and bench-confirmed 2026-10-19) |
| `(ch,3)` | `[3:0]` / `[7:4]` | HG / LG shaping time code | time = 20 ns x code, or 120 ns x code if the matching slow flag in `(ch,7)` is set [VB] |
| `(ch,4)` | `[5:0]` | T1 calibration (trim) DAC, default 32 | bits `[7:6]` unused, preserve [HW] |
| `(ch,5)` | `[5:0]` | T2 calibration DAC, default 32 | [HW] |
| `(ch,6)` | `[7]` | input DAC low-impedance (~150 ohm) select | [HW] |
| | `[6]` | input DAC enable | [HW] |
| | `[4]` / `[3]` / `[2]` | **T1 / T2 / TQ trigger mask bits, 1 = channel passes (unmasked), 0 = masked** | the name says "mask", the polarity is "enable" [HW] |
| `(ch,7)` | `[4]` | Ctest connect (default row `00001111` -> `00011111`) | [HW] |
| | `[5]` | 1.5 pF injection capacitor connect | [VB] |
| | `[6]` / `[7]` | HG / LG shaping slow flag (x120 ns steps) | [VB] |
| `(ch,66)` | `[3:0]` | **analog probe select**: `{shaper HG, shaper LG, preamp HG, preamp LG}`, `0000` = no probe | one-hot per vendor `send_aprb`; scope-unverified [VB]. Probe degrades analog performance; keep off for measurements |

Per-channel discriminator output select: `(66, ch)`, `ch` = 0..63 = `{cm[1:0], lvdsOut[1:0], outPad2[1:0], outPad1[1:0]}`; the scans write `00010000` for T1, `00100000` for T2 (default `00010000`) [HW].

## 4. ASIC common blocks

**`(64, 0..14)`** bias currents (`ibi_*`, `ibo_*`, `ib_*` nibble pairs), `(64,13)` = `ON_*` enables for the
input DACs, paT, HG/LG preamps and shapers, peak detector; `(64,14)` = `ON_calibDac, ON_discriCharge,
ON_pdBuffer, ON_discri1, ON_discri2`. Leave at defaults [VB].

**`(65, *)` thresholds, delay, trigger select:**

| Row | Layout (MSB first) | Notes |
|---|---|---|
| `(65,1)` | `dac1[7:0]` | **T1 threshold DAC** low byte [HW] |
| `(65,2)` | `{dac2[5:0], dac1[9:8]}` | |
| `(65,3)` | `{dacQ[3:0], dac2[9:6]}` | |
| `(65,4)` | `{NC*2, dacQ[9:4]}` | **TQ threshold DAC** top bits |
| `(65,0)` | `{NC*2, bg[5:0]}` | bandgap trim |
| `(65,5..6)`, `(65,10..11)` | threshold-DAC and delay-DAC bias currents | leave |
| `(65,7)` | `{vref[3:0], EN_th1, EN_th2, EN_thQ, EN_bg}` | |
| `(65,8)` | `delay[7:0]` | peak-detector hold delay, = code x 0.85 ns x slope |
| `(65,9)` | `{slopeTrim[3:0], ibi_discri_delay[3:0]}` | preserve the low nibble |
| `(65,12)` | `{hysteresis1, hysteresis2, EN_delay, selHoldExt, selTrig[3:0]}` | default `11100100` |

The three 10-bit DACs all default to **512**: `(65,2)=00000010` and `(65,3)=00001000`, `(65,4)=00100000`
decode that way with the layout above, a mid-scale default. The packaged defaults are the quickest check
of a layout. The scans' `set_threshold_dac` writes T1 as `(65,1)=dac[7:0]` and `(65,2)[1:0]=dac[9:8]`, T2
as `(65,2)[7:2]=dac[5:0]` and `(65,3)[3:0]=dac[9:6]` [HW]. Note it rewrites all of `(65,2)`/`(65,3)`, so setting T2
clears `dac1[9:8]`; set one DAC at a time or read-modify-write.
**Fixed 2026-10-19:** the separate per-field setters (`set_t1/t2/tq_threshold_dac`, used by the Main-tab
"Apply") had the sub-fields swapped relative to this layout. If your copy predates that fix, use
`set_threshold_dac` or update it.

`selTrig[3:0]`: `0000` external, `0001` local T1, `0010` local T2, `0011` local TQ, `0100` global T1,
`1000` global T2, `1100` global TQ. `selHoldExt` (bit 4): 1 = external hold. A trigger channel
is chosen by unmasking only that channel's mask bit in `(ch,6)`.

**`(66, 64..70)` output and probe section:** `(66,64)={extendedOutput, delayPE[1:0], bufSize[4:0]}`,
`(66,65)={bufSizeClps[3:0], bufSizePE[3:0]}`, `(66,66)={NC*2, cmProbe[1:0], cmLG[1:0], cmHG[1:0]}`,
`(66,67..69)` buffer biases, `(66,70)={NC*3, ON_outing, ON_aBuffer, EN_probe, EN_aMuxHG, EN_aMuxLG}`,
default `00011111` (probe enables already on; the per-channel `(ch,66)` nibble chooses the node) [VB].

## 5. FPGA words (7-bit addresses, 8-bit data)

| Word | Use |
|---|---|
| 0 | I2C FIFO enable, bit 6; `initialize_fpga` writes `00111111` |
| 1 | init `01000000`; S-curve sync-clock index in bits `[3:2]` |
| 2 | ADC start strobes: pulse bit 6, then bit 7 (set 1, 0, 1, 0 per batch) |
| 4 | status: bit 0 = I2C FIFO ready, bit 2 = ADC ready (string idx 7 and 5) |
| 20 | ADC frame port (read) |
| 21 | events per batch, 1..255 |
| 22 | `[5:0]` trigger channel; bit 7 = synchro-trigger pulse strobe |
| 23 | `[5:0]` second coincidence channel; bit 6 = peak-sensing flag |
| 24 | ADC window / 5 ns |
| 25 | `[7:5]` trigger source, `[4]` reset-n manual, `[3]` = 1, `[2]` peak-or-external trigger, `[1:0]` trigger type |
| 26 | hold code `[7:0]`; hold code = hold ns / 5, 12 bits |
| 27 | `[5:0]` number of triggers in window |
| 28, 29 | acquisition count: events = `(w29<<8 \| w28) / 256` |
| 30 | hold code `[11:8]` and second trigger source (3 bits) packed |
| 31 | conversion delay / 40 ns |
| 55, 56 | I2C FIFO read and write ports |
| 60 | I2C control: `00000000` idle, `00000010` start, `00000100` finish |
| 77, 78 | IO mux, 3 bits per IO: io0 = `w77[2:0]`, io1 = `w77[5:3]`, io2 = `{w78[0], w77[7:6]}`, io3 = `w78[3:1]`, io4 = `w78[6:4]` |
| 100 | firmware status (reads `00000101`) |

IO mux values, recovered from the vendor GUI's FPGA config combo boxes (`radioroc2UI.pyc`, `retranslateUi`): 0 = Single trigger channel (the default), 1 = NORT1, 2 = NORT2, 3 = NORTQ, **4 = S-curves clock**, **5 = Synchro trigger** (sync a pulse generator; confirmed on the scope on io1 and io0), 6 = Digital probe, 7 = not recovered. The vendor guide (section 3.4) says IO0 is by default the S-curve sync clock and IO1 the synchro trigger for the external hold scan; the GUI labels IO1 as 3V3 and IO5 as 2V5. So IO0 at mux 0 outputs a channel trigger, not the clock: index 4 outputs the S-curves clock: confirmed on the scope 2026-10-27 as a square wave, 0 to about 1.4 V into a 1 MOhm scope with a 50 Ohm termination, silent (0 V) until a scan starts; at S-curve clock index 3 the period is 1.2 us (about 833 kHz, 50% duty). The vendor GUI offers clock indices 0, 1, 2 = 1 kHz, 10 kHz, 100 kHz. With IO0 = 4, clock index 1, Ctest on and a generator in external triggered burst (1 cycle) on TRIG IN, the S-curve turn-on appears at the pulse height (ch6 404, ch32 412 at paT gain 1, generator 100 mV displayed into the 20 dB attenuator). Board SMAs:
`IO6` (= `IO_FPGA6`) = External Synchro input, `IO7` = External Hold input, both 2.5 V TTL.
Internal-hold/external-hold control words are constants in `radioroc_client.py`.

## 6. ADC data (word 20) [HW]

Per event, 64 channels in order 0..63, **4 bytes each: LG (2 bytes big endian) then HG (2 bytes)**; value = raw x 0.25
(vendor ADC units, pedestal ~100). The batch of `N` events is `N x 256` bytes.

## 7. Inversions and conversions to watch

- **paT gain code is inverted**: 1 = most gain, 63 = least, 0 = open loop.
- **Mask bits are enables**: `(ch,6)` bits 4/3/2 = 1 let the channel trigger; the "mask all but the trigger channel" step writes 0 elsewhere.
- **HG sits in the low nibble, LG in the high nibble** of `(ch,2)` and `(ch,3)`; gain rises with code, but the capacitor in the gain formula uses `16 - code`.
- **Threshold DACs are split across four rows** (`(65,1..4)`); the order of the sub-fields is easy to swap. Check against the defaults (512 each).
- **Hold delay**: external hold code = ns / 5; conversion delay = ns / 40; ADC window = ns / 5; delay slope x 0.85 ns.
- **Count word**: events = word / 256, not the raw word.
- **HG gain 15 = 8x default (8)** in V/V: 5 pF / 62.5 fF is 80, against 10 at code 8.
- **Generator note:** `AMPL` only sets the amplitude around a fixed DC offset; use `LOLVL`/`HILVL` for a pulse that idles at 0 V.
