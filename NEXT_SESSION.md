# RADIOROC 10 — Investigate status-only timeout

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, and `docs/hardware/desktop_status_recovery.md`.
The preceding chat is **RADIOROC 09 — Status-only desktop recovery**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current commit
and working tree. RADIOROC 09 executed from `b31d024`; only documentation and
ignored local harness/evidence changed. Preserve existing edits and all data.

Freshly authorized native GUI recovery stopped at Connect's first status-100
read: request `aa00e40055`, 115200 baud, 0.5 s timeout, no response. Exactly one
request was sent. The worker automatically released the session, reported no
close error, and shut down successfully. No repeat, scan, FIFO access, verifier,
configuration write, repair or power-cycle occurred. Two-read acceptance failed;
configuration restoration and both timeout causes remain unresolved.

Evidence: `radioroc_runs/physical_status_20260911T051700Z/`. Actual timestamps in
its logs are 2026-09-11 05:16:21–05:16:25 UTC; the directory suffix is a label.
Local harness/fake checks: `radioroc_runs/radioroc09_offline/`. Do not execute
that harness physically under the prior authorization.

Next bounded task: compare this exact request and saved timing/error evidence
with prior successful status reads and the production transport, offline only.
Separate established facts from hypotheses. Produce one concrete diagnostic
proposal with expected observations, stop/release rules and required setup.
Use a smaller-model agent for a bounded saved-evidence audit if useful; the lead
owns protocol reasoning. Avoid repeated broad repository exploration.

Acceptance: evidence inventory verified; successful/failing status evidence
compared without claiming a root cause that the traces do not establish; one
reviewable next test card prepared; findings, limitations and next task recorded.
No hardware discovery/open, status retry, ASIC access, verifier, scan, defaults,
repair, power-cycle, push or change to `main`. Further physical access needs
fresh authorization for the resulting exact card. Do not resume pending GUI
cancellation/close cases based on USB enumeration or historical status 5.
