# RADIOROC 11 — Evidenced re-verification after operator power-cycle recovery

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, and `docs/hardware/desktop_status_recovery.md`.
The preceding chat is **RADIOROC 10 — Investigate status-only timeout**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current commit
and working tree. RADIOROC 10's own work was offline only: it reverified the
RADIOROC 09 evidence inventory, compared that run's exact request/timing/error
evidence against prior successful status reads (a 2026-09-10 CLI check and
RADIOROC 07's native GUI session), and used `pmset -g log` to rule out an OS
sleep/USB-reset cycle as the cause of the gap between RADIOROC 07's fault and
RADIOROC 09's failed reconnect. No hardware was touched by the lead in that
session.

**Since then, the designated operator reported acting outside this harness:**
immediately after the RADIOROC 09 timeout was found, they power-cycled the
board, then connected through the native desktop GUI and got firmware status
`0x05` (5) on `/dev/cu.usbserial-RD3_320` (operator screenshot only — no saved
run directory, timestamps, request trace, repeat status read, or
Disconnect/shutdown result exists for this action). This strongly supports
hypothesis H1 (the board/bridge was stuck and needed a power-cycle) over H2,
but by this document's own evidence standard it is not yet an accepted,
evidenced recovery. See `docs/hardware/desktop_status_recovery.md`, "Operator
power-cycle recovery (post-RADIOROC 10)" and the still-open "RADIOROC 11
candidate" card.

Next bounded task: with the designated operator, freshly authorize and run the
existing status-only card (Connect, then the gated single repeat status-100
read, then explicit Disconnect/shutdown) through the bounded evidence harness,
now that the board is reported to be communicating again, to get a properly
evidenced two-read acceptance and confirm the recovery holds. Prefer running
the "RADIOROC 11 candidate" card's USB-presence-before-Connect step too, since
it is still informative even though the power-cycle result already leans
toward H1. Do not skip straight to threshold scans or configuration
restoration checks; status-only acceptance under this harness comes first.

Acceptance: a fresh, authorized, evidenced status-only run (matching or
exceeding this document's "Evidence to save" list) either confirms two matching
successful status reads and a clean Disconnect/shutdown, updating the
hypothesis assessment and closing this recovery question, or it stops on a new
fault, which must be recorded with the same rigor as RADIOROC 09. Update
`IMPLEMENTATION_STATUS.md` and this file with the result and next task before
ending the session. No ASIC/FIFO access, verifier, scan, configuration write,
defaults, repair, or further power-cycle without its own separate, explicit
authorization; no push or change to `main`. Use a smaller-model agent for
bounded, well-scoped pieces (for example, preparing the run harness script or
drafting the evidence-capture checklist) while the lead retains protocol
reasoning, authorization tracking, and the physical-run decision itself.
