# RADIOROC 20 — GUI wiring for input DAC/TQ mask, or resume Stage C/D

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 19 — First physical validation of input DAC/TQ mask (PASSED)**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**RADIOROC 17-19 summary:** recovered the input DAC (value/enable/impedance)
and TQ mask register mapping from the vendor's compiled GUI bytecode,
implemented four `RadiorocDevice` methods, wired them into
`scripts/radioroc_channel_config.py` (`--tq-mask`, `--input-dac-enable`,
`--input-dac-value`/`--value`, `--input-dac-impedance`, `--verify`,
`--restore`), then physically validated a bounded case (TQ mask + input DAC
value + impedance on a bare board) — passed on the first attempt, 65 rows
independently verified written and then restored, 0 mismatches either way.
Evidence under `radioroc_runs/physical_channel_config_20260914T035857Z/`.
Input DAC *enable* specifically wasn't exercised yet (only value/impedance/
TQ mask were), and nothing has been run without `--restore` (the genuinely
persistent mode, which is the real calibration use case).

**Hardware state (Stage C, unchanged since RADIOROC 16):** IO1 (mux index 5)
confirmed at ~10-13ms period, ~1.44V amplitude. Stage D (pulse generator)
hasn't started.

The operator asked for GUI wiring for input DAC/TQ mask next (a real UI
feature addition — new panel/tab in the desktop app, not a small change).

Next bounded task: implement GUI wiring for input DAC (value/enable/
impedance) and TQ mask, following this codebase's existing GUI patterns
(`src/radioroc/gui/threshold_window.py` and its `ConnectionWorker` usage) —
read that file first to decide whether this fits as a new tab/panel on the
existing window or a separate window, and whether it should reuse
`ConnectionWorker` (one owner per session, same ownership discipline as
everything else) or needs its own worker. Mirror the safety posture already
established: any control that persists a hardware change should be visually
distinct from the transient threshold-scan controls, and the vendor's own
"Note that... these changes persist" framing (already documented for
`apply_defaults`/FPGA init) applies here too — input DAC/TQ mask writes
persist by default in the CLI (`radioroc_channel_config.py`), so the GUI
should make that clear rather than implying auto-restore. Add offline/GUI
tests following `tests/test_threshold_gui.py`'s existing pattern (offscreen
Qt tests) before any physical exercise of the new GUI path.

After GUI wiring is implemented and offline-tested, decide with the operator
whether to physically validate the new GUI controls in the same session or
defer that to a later bounded card, and/or resume the Stage C/D hardware
track (extend Stage C on IO1/other lines, or move to Stage D if a pulse
generator is available — bigger step, needs an attenuator and its own setup
review).

Whatever is chosen, follow the RADIOROC 09-19 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, and treat any new GUI hardware path as a
first-of-its-kind script/action needing its own bounded physical card, not
an extension of an already-authorized one.

Acceptance: the chosen work is completed/authorized/scoped, and its outcome
recorded with the same evidence rigor as RADIOROC 09-19 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write (without
explicit authorization as such), defaults, repair, power-cycle, signal
injection, or detector connection beyond what is explicitly authorized for
that exact action; no push or change to `main`.
