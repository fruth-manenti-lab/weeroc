# RADIOROC 24 — Run the first Stage D hold scan (channel 4)

**Handoff note (2026-09-18):** this session continues on a **Raspberry Pi**,
a different physical machine from the one RADIOROC 23 ran on. The bench
hardware (RADIOROC board, Tektronix MSO56B, Keysight EDU36311A, Aim-TTi
TGF4162, attenuator) may be the same physical instruments, but do not assume
anything about them carries over automatically: USB device paths will very
likely differ (RADIOROC 23 used `/dev/cu.usbserial-RD3_320` and
`/dev/tty.usbmodemDA20FE0E1` on macOS; on Linux/Raspberry Pi expect something
like `/dev/ttyUSB0`/`/dev/ttyACM0` instead), and `pyvisa`/`pyvisa-py`/`pyusb`
may need installing fresh in whatever environment this session uses. Re-discover
and re-verify everything rather than reusing RADIOROC 23's paths verbatim.
Read `AGENTS.md` first for the full safety/authorization discipline this
project runs on (fresh authorization per exact action, independent
verification, stop-on-fault, no silent repair) — this matters *more*, not
less, on an unfamiliar machine. The standing principle also still applies:
**stay focused on what the app and end user actually need** — no
open-ended/completionist hardware or code exploration unless it serves a
concrete feature-parity row in `CROSS_PLATFORM_REBUILD_PLAN.md`.

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md` (especially the RADIOROC 23
entry), `CROSS_PLATFORM_REBUILD_PLAN.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 23 — First Stage D signal-injection confirmation (PASSED)**.

Branch: `feat/desktop-hardware-threshold`. Verify current commit and working
tree before touching anything.

**What RADIOROC 23 established:** the physical signal-injection setup for
Stage D works. `IO1` at mux index 5 reliably fires the TGF4162 (external
trigger, single-cycle burst, 100 ns pulse) through a 20 dB attenuator into
`in_test1`/Ctest, giving ~49-50 mV peak-to-peak at the board — confirmed by
an exact 3000/3000 triggered-acquisition match plus a clean single-shot
width/amplitude reading. That took a lot of back-and-forth to get right (see
RADIOROC 23 for the pitfalls: T-split reflections, `ZLOAD`/`AMPL`
open-circuit-vs-terminated-load confusion, DSO trigger level sitting outside
the actual DC baseline, stale AUTO-trigger acquisitions being read after a
burst had already ended). **Do not assume that calibration still holds** —
the generator's settable parameters have no query form on this firmware
(`EER?` only confirms a command parsed, not that the analog output is
correct), and the front panel can be touched locally between sessions. Treat
the injection setup as needing a fresh sanity check, not as a known-good
constant.

At RADIOROC 23's end: signal generator output OFF, PSU CH1 output OFF, board
on USB only (no external 5V rail). The vendor user guide
(`local_artifacts/downloads/Radioroc2 User Guide - 2_1_0_6(0125).pdf`)
confirms the board needs both USB and an external 5V/1A supply to actually
run — don't forget the PSU when re-powering.

**Next bounded task:** with the designated operator, and after
reconfirming preconditions (board powered/bare, no SiPM/pulser beyond the
authorized generator+attenuator path, competing software closed, injection
setup re-verified), get explicit authorization to run:

```
scripts/radioroc_hold_scan.py --execute \
  --preset configs/presets/hold_external_track_ctest_ch4.json \
  --out-dir radioroc_runs/stage_d_hold_scan_ch4_<date>
```

This is the same known-good external track-and-hold Ctest configuration from
the 2026-06-26 logbook (channel 4, threshold DAC 250, Ctest on, 440-640 ns
hold sweep, IO1/mux-5 sync) — real feature-parity work for `F10` (hold
scans) in the plan's feature table, with backend code that already exists
but no physical evidence under this rebuild yet. `F07` (S-curves,
`scripts/radioroc_scurve.py` / `radioroc_standard_scurves.py`) is the other
open Stage D item if the operator prefers that instead.

If the operator wants something else entirely (non-hardware app work,
Windows-parity inventory, etc.), ask directly rather than defaulting to more
hardware work.

Whatever is chosen, follow the RADIOROC 09-23 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, and stop immediately on any error, fault, or
mismatch — including a measurement result that looks physically implausible,
which on this setup has repeatedly turned out to mean a scope/generator
configuration mistake, not a real ASIC behavior.

Acceptance: the chosen action is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-23 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write, defaults,
repair, power-cycle, signal injection, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
