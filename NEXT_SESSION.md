# RADIOROC 03 — Desktop hardware connection

RADIOROC 02 completed Delivery 4's simulation desktop slice on
`feat/desktop-threshold-simulation`, package version `0.4.0`. Read `AGENTS.md`,
`IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md` and Delivery 4 in
`CROSS_PLATFORM_REBUILD_PLAN.md`, then verify the recorded branch/commit and
working tree before editing.

Keep this chat bounded to the desktop hardware connection and session boundary.
Build on the same GUI/worker contracts without adding device logic to widgets.
Start with read-only discovery, explicit control-port selection, connect/status,
disconnect and truthful errors. The hardware session must be created, owned and
closed on its worker thread and must use the existing cross-process board lock.
Simulation must remain available and visibly distinct. Core/CLI installs must
remain headless and all legacy entry points must keep working.

Acceptance checks:

- Port refresh uses the existing discovery API without opening a device. The user
  explicitly selects a candidate; VID/PID alone is not presented as proof of a
  RADIOROC control interface.
- Connect performs the existing read-only status-word check through an owned
  worker/session. Busy, timeout, protocol, I/O and close errors remain distinct.
- Widgets stay on the UI thread. Device/session create, status read and close all
  occur on the worker thread. Closing the window waits for session release and
  keeps close failures reviewable.
- Hardware threshold Run remains disabled during this slice unless the physical
  scan test card below has first been reviewed and its checks can be completed.
- Add offline tests with fake discovery/transports and fault injection. Tests must
  never enumerate real hardware. Run `python tools/check_development.py`, build
  and verify core-only and GUI-installed wheels, and record a native desktop launch.
- Update `IMPLEMENTATION_STATUS.md`, replace this handoff and commit locally.
  Do not push or change `main`.

Prepare an opt-in bare-board threshold validation card as a separate reviewable
document. It must state the exact temporary registers captured/restored, intentional
preparation behavior, wiring/equipment, expected observations, cancellation points,
cleanup/readback checks and abort conditions. Do not run a hardware threshold scan
merely to test the GUI. Enabling desktop hardware Run can follow in its own bounded
checkpoint after this card is reviewed.

Historical hardware context only: status word 5 was previously read from
`/dev/cu.usbserial-RD3_320`, USB serial `RD3_32`. The board was powered with no
SiPM or pulse generator connected. Treat this as stale until a new read-only check.
Only the designated operator may access the board. Agent workers use fakes/saved
data and must not run discovery or hardware diagnostics.

Keep acquisition/autocalibration migration, automatic interface detection,
full register editing, Windows parity expansion, Linux USB validation and release
bundling outside this chat. Record discoveries instead of expanding scope.

The preceding chat name is **RADIOROC 02 — Desktop threshold simulation**.
