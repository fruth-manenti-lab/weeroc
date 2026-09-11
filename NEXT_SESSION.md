# RADIOROC 12 — Decide and authorize the next physical step

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, and `docs/hardware/desktop_status_recovery.md`.
The preceding chat is **RADIOROC 11 — Evidenced status-only re-verification**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree. RADIOROC 11 reran the RADIOROC 09 status-only harness
after the operator's reported power-cycle recovery, with fresh authorization
and a pre-Connect USB-presence check. It **passed**: two matching status-100
reads (value 5) and a clean Disconnect/shutdown, meeting the status-only
card's acceptance criteria for the first time since the RADIOROC 07 fault.
Evidence is local under `radioroc_runs/physical_status_20260911T070909Z/`.
Source hashes for the transport/connection-worker code are unchanged from the
faulting run, so the recovery is attributed (as support, not proof) to the
operator's power-cycle rather than a code fix.

What remains unverified: configuration restoration after the RADIOROC 07 fault
(the earlier interrupted `t1_cancel_window` job's cleanup was recorded as
"restored" but never independently confirmed by readback), scan/threshold
behavior on the recovered board, and whether the recovery is durable (only one
status-only pass has been run since the power-cycle).

Next bounded task: with the designated operator, decide the next physical
step and get fresh, explicit authorization for exactly that scope before doing
anything. Reasonable options, in increasing order of scope:

1. A second status-only pass after some idle time, to check the recovery is
   stable and not itself intermittent.
2. A bounded physical threshold-scan validation (the option already queued in
   `IMPLEMENTATION_STATUS.md`'s general backlog — "physical threshold
   restoration checks") now that status communication is evidenced-recovered.
3. Further offline work only (no new hardware access) if the operator wants
   more confidence first.

Do not default to the largest-scope option without the operator's explicit
choice. Whatever is chosen, follow the same discipline as RADIOROC 09-11:
confirm board/app preconditions, get an explicit authorization statement
(operator, host, UTC start time, scope), run through a bounded, evidenced
harness (reuse/extend existing scripts under `radioroc_runs/` rather than
writing new ones from scratch where they already fit), and stop immediately on
any error or unexpected value rather than retrying or improvising.

Acceptance: the chosen next step is authorized, run (or explicitly deferred),
and its outcome — pass, stop, or offline-only findings — is recorded with the
same evidence rigor as RADIOROC 09-11 in both `IMPLEMENTATION_STATUS.md` and
this file, along with the next task. No ASIC/FIFO access, verifier, scan,
configuration write, defaults, repair, or power-cycle beyond what is
explicitly authorized for that exact action; no push or change to `main`. Use
a smaller-model agent for bounded, well-scoped pieces (drafting an evidence
checklist, adapting a harness script offline) while the lead retains protocol
reasoning, authorization tracking, and the physical-run decision itself.
