# RADIOROC 23 — Continue Stage C (io2-4, SMA pair, baseline-shift question), or move on

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 22 — IO0 sync-pulse characterization (PASSED)**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**Hardware state:** both IO1 (RADIOROC 15/16) and IO0 (RADIOROC 22) are now
characterized: mux index 5 carries a real ~10 ms period, ~1.44 Vpp pulse
train on both — the same signal, routed to whichever physical IO line is
selected. Indices 0-3 show nothing on either line; indices 4/6/7 show a
static baseline-level shift with no pulsing, a real and repeatable but
**unexplained** effect, not investigated this session. io2, io3, io4, and
the documented `IO_FPGA6`/`IO_FPGA7` SMA connectors have never been probed.
Pulse width/rise-time and an untermination-corrected (open-circuit)
amplitude are also still open on both io0 and io1.

The input DAC/TQ mask feature (RADIOROC 17-21) is complete and evidenced on
both the CLI and GUI paths — nothing further planned there unless new gaps
turn up.

Next bounded task: with the designated operator, pick a direction:

1. **Continue Stage C** — reuse `hold_mux_index.py <io_name> <index>` (now
   generalized to take any IO name) to characterize io2, io3, io4 the same
   way, and/or investigate what the mux 4/6/7 baseline-shift artifact
   actually is (for example, by reading back FPGA/ASIC state at that mux
   index to see what changed, rather than only watching the scope).
2. **Probe the `IO_FPGA6`/`IO_FPGA7` SMA connectors** (documented "External
   Synchro"/"External Hold", 2.5V TTL) if they're identifiable as separate
   physical connectors from io0-io4 on the board.
3. **Move to Stage D** if a pulse generator becomes available — the bigger,
   still-untouched step (needs an attenuator, injects a signal into the
   ASIC, needs its own setup review before authorization).
4. **Non-hardware work**: persistent defaults/FPGA init (item 7, still
   explicitly deferred), branch/CI review before publishing, or the
   Windows-parity inventory expansion (both already queued).

Whatever is chosen, follow the RADIOROC 09-22 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement for the exact action, reuse the existing per-index hold script
rather than writing a new one, and record operator observations precisely
(distinguish "nothing," "baseline shift only," and "real pulses," as this
session did) rather than collapsing them into a single pass/fail.

Acceptance: the chosen direction is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-22 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write, defaults,
repair, power-cycle, signal injection, or detector connection beyond what is
explicitly authorized for that exact action; no push or change to `main`.
