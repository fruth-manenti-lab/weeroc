# RADIOROC 25 — Shared connection shell (pending screenshots) or next feature slice

Read `AGENTS.md` first for the full safety/authorization discipline this project
runs on (fresh authorization per exact action, independent verification,
stop-on-fault, no silent repair). Read `IMPLEMENTATION_STATUS.md`'s RADIOROC 24
entry in full before touching anything — it covers a large session: an
environment rebuild on a new Raspberry Pi machine, a project-wide preset-defaults
bug sweep (8 CLI scripts plus shared connection-args helpers), a full hold-scan
migration onto the shared-job architecture (mirroring threshold scans'
cancellation/manifest/snapshot-restore/verification rigor), a new hold-scan GUI
tab, and the first-ever physical hardware validation of that GUI path.

Branch: `feat/desktop-hardware-threshold`. Verify current commit and working tree
before touching anything — RADIOROC 24 was **not yet committed** at handoff; the
operator asked to record and commit, but confirm the actual git state at session
start rather than assuming that happened.

**Bench state at RADIOROC 24's end:** PSU CH1 was left on (5V/1A), the signal
generator's output was left on (PULSE/burst/external-trigger config from
RADIOROC 23, re-applied and confirmed this session), and the RADIOROC board was
connected. Re-verify all of this fresh — do not assume it still holds, per every
prior handoff's standing instruction. This session also ran entirely on a
Raspberry Pi reached over SSH/AnyDesk/X11-forwarding from the operator's own
machine, not a machine Claude was sitting at physically; confirm which access
path is in use at the start of the next session too.

**What RADIOROC 24 established:**
- Hold scan now has full parity with threshold scan's job architecture — CLI,
  API, and GUI all share one `HoldScanJob` implementation. First physical
  hardware hold scan through the new GUI tab passed: 21/21 points, cleanup
  restored, verification passed, peak shape matching the CLI and the 2026-06-26
  known-good result.
- A real, project-wide bug class (`apply_preset_defaults()` silently losing
  preset fields to hardcoded CLI defaults) was found, root-caused, and fixed
  everywhere it existed — not just where it was first noticed.
- The operator identified a real architecture gap during live GUI use:
  `ThresholdWindow` and `HoldScanWindow` each independently own a
  connection/channel-config panel instead of sharing one, unlike the "one shell"
  design `CROSS_PLATFORM_REBUILD_PLAN.md` M3 already calls for. The operator
  intends to provide Windows vendor-app screenshots to design the shared page
  against the real reference UI (not yet provided as of this handoff — check
  whether they arrived).

**Next bounded task:** ask the operator directly which of these they want first
(do not assume):
1. If the Windows screenshots have arrived: design and build the shared
   connection/channel-config shell both windows should draw from instead of
   duplicating. This is real, already-identified rework, not exploratory.
2. If not yet available: pick an independent feature-parity slice from
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that doesn't depend on the shared shell —
   S-curves GUI (`F07`) is a reasonable default (core/CLI already exist, no GUI
   yet), but confirm with the operator rather than assuming.

Whatever is chosen: keep the standing discipline. Fresh authorization for any
hardware action, independent verification, stop immediately on any fault or
implausible result, record the outcome here and in `IMPLEMENTATION_STATUS.md` at
the next handoff. No push or change to `main`.
