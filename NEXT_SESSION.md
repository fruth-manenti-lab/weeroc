# RADIOROC 35 — Hardware-validate F08 if operator's present, or pick up T1/T2/TQ enable bits / F11-F13

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 34 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 34 entry for the full account.
Short (~30 min) session. Summary:

1. **Live-visual-checked the GUI** — the item deferred twice since
   RADIOROC 31/32. Launched the real app on the shared display, screenshotted
   with `scrot` (installed `xdotool` to drive tab clicks). Confirmed the
   Probes/Masks channel-select grids (T1/T2/TQ, 64 channels each) and the
   Autocalibration workflow tab both render correctly, matching what was
   built. No layout issues found. App closed cleanly afterward; no hardware
   touched, no board connection attempted.
2. Both of the "explicitly still missing" visual-check items from the prior
   two handoffs are now closed out. Nothing else in the backlog changed.

## What's explicitly still missing

1. **`check_installed_package.py --gui` still isn't part of routine local
   checks** (`tools/check_development.py`) — it only runs in CI's separate
   wheel-verification stage. Worth deciding whether to fold a lightweight
   version into routine checks so a future GUI-default change can't hide the
   same way again (this is what let RADIOROC 33's first CI bug go
   undetected locally for as long as it did).
2. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
3. **`AutocalibrationJob` has never run against real hardware.** The main
   *new* hardware-facing risk: the calibration-DAC force/restore sequencing
   around the reference channel, and the dynamic DAC-range computation
   between steps. A first real-hardware test should focus narrowly on
   those two things, not a full production calibration run.
4. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, untouched since.
5. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.
6. **Minor, not urgent:** the CI run's own annotations flag
   `actions/checkout@v4`/`actions/setup-python@v5` as targeting a
   deprecated Node.js version. GitHub is handling it automatically for now;
   worth bumping to newer action versions at some point regardless.

## Suggested next task (pick with judgment, same as always)

1. **If the operator is present with the board**, do the narrow hardware
   test described in item 3 (`AutocalibrationJob` force/restore + DAC-range
   sequencing) — this is now the single most valuable hardware-facing test
   left undone.
2. **Otherwise, start F11–F13** if there's appetite for a new vertical
   slice, or pick up the T1/T2/TQ enable bits (item 4, small and
   well-scoped).
3. Folding `check_installed_package.py --gui` into routine checks (item 1)
   is a good small task to delegate if a session wants to close it out.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead.

`gh` is installed and authenticated on this machine — use it
(`gh run list --branch <branch>`, `gh run view <id>`, `gh run view --log-failed`)
to check CI status directly after any push, instead of asking the operator
to check the Actions UI manually.

**Before pushing anything** (not just after a packaging change, per
`AGENTS.md`'s existing "verify an installed wheel" rule): actually
reproduce CI's *environment*, not just its commands. Build a from-scratch
venv with only the exact extras a given CI step installs, confirm the
thing that's supposed to be absent (e.g. `import PySide6`) genuinely fails
in it, then run the real command there. `.conda-radioroc` or any other
long-lived dev environment with every extra already installed cannot catch
a missing-extra-only failure no matter how many times it's used. When a
local repro does fail, root-cause it before assuming your own current
changes caused it — reproducing against an earlier commit in an isolated
`git worktree` (cheap, doesn't disturb the working tree) is what
distinguished "pre-existing bug" from "something I just broke" in a past
session. And never state a CI run "probably passed" as a substitute for
checking — say what you actually verified and what you didn't.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
