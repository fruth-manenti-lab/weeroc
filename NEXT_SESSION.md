# RADIOROC 08 — Investigate desktop pre-scan timeout

RADIOROC 07 is stopped after the first long-window GUI case faulted before a
complete pre-scan snapshot. Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`,
`DEVELOPMENT.md`, and `docs/hardware/desktop_threshold_validation.md`. Review
the saved evidence under
`radioroc_runs/physical_desktop_20260911T015835Z/` offline.

The branch is `feat/desktop-hardware-threshold`, based on handoff `086d304`
and implementation `e6cddf4`, version `0.5.0`. RADIOROC 07 changes documentation
only. Verify the current local commit and working tree before editing.

Next task: investigate the pre-scan timeout and improve local phase-wait fault
detection/evidence. Use saved JSON, event logs, screenshots, fake transports,
and offline tests only. Do not access hardware, auto-retry scans, or change
device configuration. Also assess the stale saved-result banner visible in the
T2 terminal capture. End with a concrete status-only recovery card; physical
recovery requires fresh operator authorization.

Acceptance for RADIOROC 08:

- Confirm the timeout path, phase-marker gap, fault latching, disconnect and
  shutdown evidence from the saved run without touching the board.
- Keep harness fixes local unless production changes are independently justified;
  preserve old CLI entry points and shared behavior.
- Run the relevant offline development checks; do not run hardware discovery or
  the environment diagnostic script.
- Record checks, limitations, and one status-only recovery task. No physical
  retry, wider scan, repair, persistent write, push, or change to `main`.

RADIOROC 07 evidence and the exact physical procedure remain in
`docs/hardware/desktop_threshold_validation.md`. Word 60 readback semantics,
analog performance, wider scans, acquisition/calibration migration, register
editing, platform parity and bundling remain separate tasks.

The preceding chat name is **RADIOROC 07 — Physical desktop threshold validation**.
