# RADIOROC 04 — Bare-board threshold validation

RADIOROC 03 added the desktop hardware connection/session slice on
`feat/desktop-hardware-connection` at `9235fb8`, package version `0.5.0`. Read `AGENTS.md`,
`IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md` and
`docs/hardware/bare_board_threshold_validation.md`, then verify the branch,
checkpoint and working tree before editing.

Keep numbered `RADIOROC NN — <bounded task>` session names. Delegate most code,
tests and documentation to smaller models: Luna for straightforward docs/tests,
Sol or Terra for bounded coding. The lead defines contracts, reviews, integrates
and handles uncertain hardware reasoning. Give workers focused context and
non-overlapping files; avoid redundant exploration and repeated broad checks.

The desktop now offers explicit candidate selection, read-only connection/status
and disconnect. Hardware threshold Run remains disabled. The connection slice
was tested with fakes; this session did not enumerate or open the physical board.
Historical status word 5 and `/dev/cu.usbserial-RD3_320` are stale context, not a
current connection guarantee.

The next bounded task is to make the physical threshold validation card executable
and reviewable. Define and implement an opt-in verification helper using the
existing session owner and threshold job. It must independently compare captured
FPGA/ASIC state after cleanup and restore any temporary state introduced by its
own I2C readback. The card records the exact register set and unresolved readback
semantics; settle those contracts before delegating implementation. Preserve
primary, cleanup, verification and close failures separately. Do not claim
physical verification from successful writes or fake tests.

Acceptance checks:

- Default preview is offline: no discovery, serial opening or output creation.
- Fake tests cover exact read/write ordering, same-owner verification, T1/T2,
  complete/cancelled jobs, mismatch, incomplete readback, and verifier cleanup
  failures without inventing missing values.
- Update the card with exact commands and cancellation points. Explicitly review
  it with the user before any physical scan; only the designated operator accesses
  the board. Other agents use fakes/saved data and never run hardware diagnostics.
- Run the development check and verify installed wheels if packaging changes.
  Record completed checks, hardware state, limitations and one next task.
- Keep desktop hardware Run disabled until the reviewed physical checks actually
  pass. If bench authorization/equipment is unavailable, checkpoint the offline
  helper and mark physical validation outstanding.
- Commit locally on a bounded feature branch. Do not push or change `main`.

Keep acquisition/autocalibration migration, automatic interface detection,
full register editing, Windows parity expansion, Linux USB validation and
application bundling outside this session.

The preceding chat name is **RADIOROC 03 — Desktop hardware connection**.
