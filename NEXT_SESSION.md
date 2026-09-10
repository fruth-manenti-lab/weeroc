# RADIOROC 07 — Physical desktop threshold validation

RADIOROC 06 implements the desktop hardware threshold workflow on
`feat/desktop-hardware-threshold` at `e6cddf4`, based on `b10cf57`, version `0.5.0`.
Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`, and
`docs/hardware/desktop_threshold_validation.md`. Verify the local checkpoint and
working tree before editing or using equipment.

Next task: review and, after fresh operator authorization, execute the bounded
physical desktop threshold card. The previous authorization covered the completed
RADIOROC 05 CLI card; it does not authorize new GUI scans or persistent writes.
First summarize the exact new card and confirm the present equipment/ownership
conditions. No broader acquisition, calibration, initialization or defaults writes.

The desktop now uses one persistent ConnectionWorker for connect/status, hardware
ThresholdJob, mandatory restoration verification and disconnect. Normal job or
Cancel completion keeps the session open after cleanup/verification. Shutdown
requests cancellation and releases the session after cleanup; a newly discovered
job fault holds shutdown for review. Faults block scans/reconnect until explicit
disconnect and acknowledgement; failed close retains ownership for retry.
Preview remains offline. Hardware entry defaults initialization/defaults off.

Acceptance for this physical slice:

- One designated lead operates the board; all smaller-model workers use saved
  evidence, fake transports or documentation. Prefer Sol/Terra for bounded code
  or evidence review, Luna for docs; give focused context and concise outputs.
- Refresh identity/control port/status. Historical USB `RD3_32`, port
  `/dev/cu.usbserial-RD3_320` and status 5 are not current evidence.
- Follow the separate GUI card exactly: powered bare board, USB only, no SiPM or
  pulser; T1/T2 channel 4, DAC 0..1 step 1, 10 ms, one average, masks on,
  Ctest off, gain unchanged, no FPGA initialization/default application.
- Record live/terminal GUI results, manifests/CSV, exact snapshots and verifier
  results, cancellation during a long window and after a persisted point, and
  close-during-run behavior. UI running alone does not prove counter-window
  timing; establish instrumentation evidence or state the limitation.
- Stop on mismatch/incomplete readback, cleanup/storage/close failure or other
  unexpected behavior. Never silently repair configuration or continue scans.
- Save evidence under ignored `radioroc_runs`; preserve all data and environments.
  Run offline development checks for any source fixes, and installed-wheel
  checks for packaging changes. Never enumerate hardware as an offline test.
- Commit explicit source/docs paths locally; do not push or change `main`.
  Record checks, limitations, hardware state and one next task; increment the
  handoff number. If equipment/authorization is unavailable, keep the card pending.

RADIOROC 05 evidence remains at
`radioroc_runs/physical_threshold_20260910T042911Z/`. Word 60 readback semantics,
analog performance, wider scans, acquisition/calibration migration, register
editing, platform parity and bundling remain separate tasks.

The preceding chat name is **RADIOROC 06 — Desktop hardware threshold workflow**.
