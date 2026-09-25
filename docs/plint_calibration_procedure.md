# Plint calibration procedure (Priority 2, `PLINT_STUDENT_MVP_DIRECTIVE.md`)

This is the calibration procedure a student runs before collecting plint
data, using tools already built into the RADIOROC desktop app (no new
software required for any step below except recording the results). It
does not invent automatic gain/bias equalization or a position-calibration
model — every step below has a documented, existing tool behind it.

Read `PLINT_STUDENT_MVP_DIRECTIVE.md` first for why each step exists.
Prerequisite: SiPMs biased to their operating voltage (see the bench's own
HV supply notes — RADIOROC 39 biased 3 test channels at 29.5V/10mA as a
worked example, not a universal setting for every SiPM batch).

Every step below writes its own output directory under `radioroc_runs/`;
Step 6 is where those get tied together into one saved record.

## Step 1 — Pedestal, noise, and dead/noisy/saturated channel identification

**Tool**: Threshold scan (`ThresholdWindow` in the GUI, or
`scripts/radioroc_threshold_scan.py`), **Ctest disabled**, on every
selected channel together.

**What it measures**: with no injected signal, sweeping the threshold DAC
and counting crossings gives each channel's dark-count-rate curve — a
large peak at low DAC (pure electronic/thermal noise dominating), falling
to a clean, stable low/zero floor at higher DAC. RADIOROC 39's worked
example: channels 4/6/32 all showed noise falling to a clean floor by
DAC ~460 (unbiased test) — biasing SiPMs changes this curve and it must
be re-measured with SiPMs actually biased, not assumed from an
unbiased/Ctest-only scan.

**Suggested settings**: `dac_min=0, dac_max=1023, dac_step=10-20,
window_ms=100, pat_gain=1` (or whatever gain the calibration ultimately
settles on — redo this step if gain changes later). A finer `dac_step`
resolves the pedestal shape better; a coarser one is faster. Start coarse,
re-scan narrower around anything that looks wrong.

**What to look for, per channel**:
- **Dead channel**: no noise peak at all, flat near-zero across the whole
  range (the discriminator never sees anything, even pure electronic
  noise) — check the physical connection and bias before assuming it's
  the ASIC.
- **Noisy channel**: the clean floor never actually arrives, or arrives
  far later (much higher DAC) than its peers — compare against the other
  channels on the same scan, not an absolute number.
- **Saturated channel**: consistently pinned at the DAC range's edge
  behavior, or a curve shape that looks clipped/flat-topped rather than a
  smooth roll-off.

**Acceptance**: every selected channel has a reviewed curve, and the
operator has agreed which channels (if any) are excluded as dead/noisy/
saturated before proceeding. Record the DAC value where each channel's
curve reaches its clean floor — Step 2 and Step 5 both need it.

## Step 2 — Threshold alignment

**Tool**: `AutocalibrationWindow`/`AutocalibrationJob`. This already does
exactly this: probes a reference channel's calibration-trim response,
scans every selected channel's S-curve crossing, and adjusts each
channel's trim DAC so their crossings align to the group mean, then
verifies with a final narrow scan.

**Prerequisite**: run on the channels Step 1 didn't exclude. If a channel
was excluded in Step 1, exclude it here too — don't let a dead/saturated
channel skew the group's mean crossing.

**Acceptance**: the final verification scan (already part of the job)
shows every included channel's crossing aligned within an agreed
tolerance — operator picks the tolerance, since it depends on what the
gamma/muon discrimination work downstream can tolerate; not invented here.

## Step 3 — Threshold operating point

Not a separate tool — a decision, informed by Steps 1 and 2. Pick an
actual threshold DAC comfortably above every included channel's Step-1
clean-noise floor (with margin — RADIOROC 39 used roughly +50-250 DAC
codes of margin above the observed floor, not a universal number), low
enough to still catch real SiPM pulses. **Do not hardcode a single
"correct" value in code or in this document** — the directive is explicit
that threshold/window/cuts are unsettled until the operator decides them
for the actual experiment; record whatever is chosen, and why, in Step 6.

**Acceptance**: a specific DAC value, with the reasoning (margin above
which channel's noise floor) written down, not just a number.

## Step 4 — Relative gain/response characterization

**Tool**: Ctest injection (available on every channel already), using
either `AcquisitionWindow` or `scripts/radioroc_acquire.py` with
`use_ctest`-equivalent per-channel enable (currently: enable one
channel's Ctest at a time via the channel-config panel/`
set_ctest_for_channel`, inject the same known pulse, record the ADC
HG/LG response — repeat per channel). There is no dedicated "gain scan"
feature; this is the directive's own allowed fallback ("using the
available supported measurement method") rather than a missing feature to
build under deadline pressure.

**What it measures**: with the *same* injected charge on each channel in
turn, differences in the resulting HG/LG amplitude reflect each channel's
relative response (preamp gain, SiPM gain variation, coupling) — not an
absolute calibration to photoelectrons, which needs a characterized
reference pulse this procedure does not assume is available.

**Acceptance**: one recorded HG (and LG) response value per included
channel, for the same nominal injected charge, comparable side by side.
Flag (don't silently exclude) any channel whose response is a clear
outlier — that's calibration evidence for Step 6, not grounds to drop the
channel without the operator's decision.

## Step 5 — Hold/conversion timing

**Tool**: `HoldScanWindow`/`HoldScanJob`, external mode, same trigger
configuration Priority 0 settled on (RADIOROC 39: `trigger_type=1`, both
coincidence slots "Individual," the two selected channels — or whatever
configuration is actually in use for the real experiment). Sweep
`hold_delay_ns` around a broad range first (RADIOROC 39's worked example
found a clean peak within 100-900ns at 50ns steps for one specific
setup), then narrow.

**Acceptance**: a `hold_delay_ns`/`conversion_delay_ns` pair with the
scan showing a clear, unambiguous peak (not a flat or ambiguous curve) —
record which point was chosen and why (e.g. "peak center," not "first
point above baseline").

## Step 6 — Save an attributable calibration record

No dedicated tool exists yet for this step (a real gap — see
`NEXT_SESSION.md`). Until a saved-calibration-record feature exists in the
app, record the following by hand, dated and attributed, alongside the
run(s) it applies to:

- Excluded channels from Step 1, and why.
- Threshold DAC (Step 3) and the margin reasoning.
- Trigger preamp gain code and any HG/LG shaper gain codes used.
- Hold delay / conversion delay (Step 5).
- Per-channel relative response from Step 4.
- Who ran the calibration and when.
- Output directory paths for every sub-scan above (Steps 1/2/5 already
  save their own `radioroc_runs/.../metadata.json`; list them here so the
  calibration is reconstructible from its own evidence, not just this
  summary).

**Acceptance** (directive's own words): "all channels used in the
experiment have reviewed calibration results and saved settings; the
student can repeat the procedure without developer code edits." Every
step above already meets that using existing tools; only this step's
record-keeping is currently manual rather than a saved artifact.
