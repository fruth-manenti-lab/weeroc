# RADIOROC 09 — Status-only desktop recovery

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`, and
`docs/hardware/desktop_status_recovery.md` before continuing. The preceding
chat is **RADIOROC 08 — Investigate desktop pre-scan timeout**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify the current
commit and working tree. RADIOROC 08 started at `a1b17e6`, audited the saved
failure offline, improved local phase waits and corrected stale GUI provenance.
The original 49 inventoried evidence files are intact under
`radioroc_runs/physical_desktop_20260911T015835Z/`.

Next bounded task: obtain fresh designated-operator authorization for the exact
status-only card, then execute only that authorized card. The prior scan
permission does not carry forward. Until authorization, use saved evidence,
fake transports and offline checks only; do not discover or access hardware.

Acceptance: fresh setup/identity and owner recorded; Connect's single status-100
read and one explicit repeat pass as specified; explicit Disconnect and shutdown
release the owner with no close error; timestamped evidence is preserved.
Stop on the first error or unexpected status. No automatic retry, scan, ASIC
FIFO access, verifier, initialization/defaults, repair, persistent configuration
write, power-cycle, wider scan, push or change to `main`.

Local harness/report: `radioroc_runs/radioroc08_offline/`. Its derivative is a
scan harness, not the status-only procedure; do not run it for this task.

The pre-scan timeout cause and exact failed serial request remain unresolved.
Successful status reads would establish communication only, not configuration
restoration or permission to resume the pending GUI cancellation/close cases.
Record results, limits and one subsequent bounded task in the status document.
