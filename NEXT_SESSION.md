# RADIOROC 06 — Desktop hardware threshold workflow

RADIOROC 05 completed the authorized physical threshold restoration card on
`test/physical-threshold-restoration`, based on `3c0f82a` and verifier code
`4c6d254`, version `0.5.0`. Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`,
`DEVELOPMENT.md`, and `docs/hardware/bare_board_threshold_validation.md`.
Verify the local branch/checkpoint and working tree before editing.

Next task: enable the desktop hardware threshold workflow through the existing
shared ThresholdJob and owned connection/session model. The GUI currently supports
hardware connect/status/disconnect but keeps hardware Run disabled. Review the
physical evidence and define the session ownership contract before implementing.
Delegate bounded implementation/tests/docs to Sol/Terra and Luna with focused
context and non-overlapping ownership; lead owns contracts and integration.

Physical card passed all four cases: T1/T2 two-point scans, cancellation during
an enabled long-window phase, and cancellation after a persisted point. All
130 ASIC rows and FPGA 0/1/6 matched; cleanup and close succeeded. Evidence stays
ignored at `radioroc_runs/physical_threshold_20260910T042911Z/`. Cancellation used
process-local SIGINT instrumentation around the real CLI; see the card for phase
evidence and limitations. No production source changed in RADIOROC 05.

Acceptance checks for this next slice:

- One worker/session owner handles connected hardware jobs, cleanup, restoration
  verification and disconnect; no UI-thread device logic or competing workers.
- Preview stays offline. Distinguish temporary changes from explicit persistent
  preparation; keep conservative hardware defaults (skip FPGA init, no defaults
  application), and require restoration verification for hardware jobs.
- Support live points, responsive cancel, truthful errors/partial results, saved
  run reopening and safe shutdown. Block overlapping connection/job commands.
- Treat mismatch, incomplete readback, cleanup/storage/close failure as a visible
  fault that prevents another scan until reviewed. Never silently repair it.
- Use fake transports for automated checks; run
  `.venv-foundation/bin/python tools/check_development.py`. Check installed artifacts after packaging changes.
  Physical GUI validation requires a separately summarized card within the new
  scope. The previous authorization covered the completed CLI card; do not infer
  authorization for broader scans or persistent initialization/default writes.
- Keep data/vendor files/environments local and intact. Commit explicit source/docs
  paths locally on a bounded branch; do not push or change `main`.
- Record checks, limitations, physical hardware state and one next task, and
  increment the handoff number.

Historical port/status observations must be refreshed for any future hardware
check. Only the designated lead accesses hardware; workers remain offline.
Word 60 readback semantics, analog performance, wider scan configurations,
acquisition/autocalibration migration, automatic interface detection, register
editing, Windows parity expansion, Linux USB and bundling remain separate tasks.

The preceding chat name is **RADIOROC 05 — Physical threshold restoration checks**.
