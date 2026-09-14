# RADIOROC 21 — Validate the GUI channel-config path, or resume Stage C/D

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 20 — Input DAC/TQ mask GUI wiring** (non-hardware).

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**RADIOROC 17-20 summary:** recovered the input DAC/TQ mask register mapping
from vendor bytecode (17), wired it into a CLI script with a shared
`radioroc.application.channel_config` core (18), physically validated the
CLI path on a bare board — passed first try, 65 rows independently verified
written and restored (19), then wired the same shared core into the GUI: a
new `ConnectionWorker.apply_channel_config`/`channel_config_snapshot`
("configuring" busy state, faults on mismatch same as threshold jobs) and a
new "Input DAC / TQ mask" panel in `ThresholdWindow` (20). The GUI wiring
also fixed a real bug the CLI never hit: the worker never loaded
`device.i2c_rows`, so a GUI channel-config write would have silently
no-opped; fixed by reusing `ThresholdJobConfig.load_rows`'s exact loading
convention. Full suite (129 tests) passes; the panel was visually verified
offline (screenshots). **Only the CLI path has physical evidence — the GUI
path itself has never been run against real hardware.**

**Hardware state (Stage C, unchanged since RADIOROC 16):** IO1 (mux index 5)
confirmed at ~10-13ms period, ~1.44V amplitude. Stage D (pulse generator)
hasn't started.

Next bounded task: with the designated operator, pick a direction:

1. **Physically validate the GUI channel-config path** — connect via the
   real desktop GUI (not the CLI script) and exercise the new "Input DAC /
   TQ mask" panel with `Restore after` checked, on a bare board, same
   discipline as RADIOROC 19: confirm preconditions, explicit authorization
   (operator, host, UTC time, exact scope), small scope (e.g. TQ mask
   channel 4, input DAC value 200 channel 4, impedance low), stop on any
   error or fault. This is the one remaining unverified path for this
   feature.
2. **Resume the Stage C/D hardware track**: extend Stage C (pulse
   width/rise-time on IO1, an untermination-corrected amplitude, other IO
   lines) or move to Stage D if a pulse generator is available (bigger
   step: needs an attenuator, injects a signal into the ASIC, needs its own
   setup review).
3. **Other deferred items**: persistent defaults/FPGA init (item 7, still
   explicitly deferred), the already-queued branch/CI review, or the
   Windows-parity inventory backlog item.

Whatever is chosen, follow the RADIOROC 09-20 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, and treat the GUI channel-config path as a
first-of-its-kind physical exercise (like RADIOROC 19 was for the CLI path)
needing its own bounded card, not an automatic extension of an
already-authorized one.

Acceptance: the chosen work is completed/authorized/scoped, and its outcome
recorded with the same evidence rigor as RADIOROC 09-20 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write (without
explicit authorization as such), defaults, repair, power-cycle, signal
injection, or detector connection beyond what is explicitly authorized for
that exact action; no push or change to `main`.
