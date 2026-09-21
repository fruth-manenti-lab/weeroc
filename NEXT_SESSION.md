# RADIOROC 26 — Physically validate S-curve GUI, or shared connection shell (pending screenshots)

Read `AGENTS.md` first for the full safety/authorization discipline this project
runs on (fresh authorization per exact action, independent verification,
stop-on-fault, no silent repair). Read `IMPLEMENTATION_STATUS.md`'s RADIOROC 24
and RADIOROC 25 entries in full before touching anything — same continuous
session, two bounded migrations: hold scan (24, physically validated) then
S-curve (25, offline-only so far) onto the shared-job architecture, plus a
project-wide preset-defaults bug sweep and a Raspberry Pi environment rebuild.

Branch: `feat/desktop-hardware-threshold`. Verify current commit and working
tree before touching anything — confirm whether RADIOROC 24/25's work has
actually been committed by the time you read this rather than assuming so.

**Bench state at handoff:** PSU CH1 was left on (5V/1A), the signal generator's
output was left on (PULSE/burst/external-trigger config from RADIOROC 23,
re-applied and confirmed in RADIOROC 24), and the RADIOROC board was connected.
Re-verify all of this fresh — do not assume it still holds. This session ran on
a Raspberry Pi reached over SSH/AnyDesk/X11-forwarding from the operator's own
machine; confirm which access path is in use at the start of the next session.

**What's established:**
- Threshold, hold-scan, and S-curve scans all now share one job architecture
  (cancellation, durable manifest, exact ASIC/FPGA snapshot-restore-verify) and
  all three have a GUI tab. Hold scan's GUI path is physically validated on
  hardware (RADIOROC 24: 21/21 points, verification passed, matching the known-
  good reference curve). **S-curve's GUI path is not yet physically validated**
  — only offline/simulated so far (RADIOROC 25).
- A project-wide bug class (`apply_preset_defaults()` silently losing preset
  fields to hardcoded CLI defaults) was found, root-caused, and fixed
  everywhere it existed across all 8 affected scripts plus the shared
  connection/config-path helpers.
- The operator identified a real architecture gap during live GUI use:
  `ThresholdWindow`/`HoldScanWindow`/`ScurveWindow` each independently own a
  connection/channel-config panel instead of sharing one, unlike the "one
  shell" design `CROSS_PLATFORM_REBUILD_PLAN.md` M3 already calls for. The
  operator intends to provide Windows vendor-app screenshots to design the
  shared page against the real reference UI — check whether they've arrived.

**Next bounded task:** ask the operator directly which they want (do not
assume):
1. Physically validate the S-curve GUI path on real hardware, the same way
   RADIOROC 24 did for hold scan — needs a channel/DAC range and injection
   setup the operator picks, with fresh authorization per action.
2. If the Windows screenshots have arrived: design and build the shared
   connection/channel-config shell all three windows should draw from instead
   of duplicating.
3. Another independent feature-parity slice from
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3.

Whatever is chosen: keep the standing discipline. Fresh authorization for any
hardware action, independent verification, stop immediately on any fault or
implausible result, record the outcome here and in `IMPLEMENTATION_STATUS.md`
at the next handoff. No push or change to `main`.
