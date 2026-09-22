# RADIOROC 34 — Live-visual-check the GUI, hardware-validate F08, or pick up T1/T2/TQ enable bits / F11-F13

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 33 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 33 entry for the full account,
including two corrections made along the way. Summary:

1. **`local_artifacts/` is now documented in `AGENTS.md` itself**, loaded
   every session automatically, plus a memory entry.
2. **Three separate, real CI bugs found and fixed, one push at a time**,
   each one only found by actually checking the result rather than trusting
   the previous fix was enough:
   - An installed-wheel GUI probe still assumed Simulation was the default
     scan-window mode after an earlier commit changed it.
   - `tests/test_channel_select.py` imported a "pure, no Qt needed"
     function from a module that unconditionally imports PySide6 at the
     top — invisible locally because every check this session ran used an
     environment (`.conda-radioroc`) that already has PySide6 installed.
     The same class of bug RADIOROC 28 fixed once before, one level deeper.
   - GitHub's `ubuntu-24.04` runner image is missing `libEGL.so.1` and
     other Qt6 runtime libraries that `PySide6.QtWidgets` needs even under
     the `offscreen` platform plugin — not a code bug at all, a missing
     system package in the workflow's Linux job.
3. **`gh` CLI installed and authenticated this session** (`sudo apt install
   gh`, operator ran `gh auth login`). This is what finally let the last
   fix be *directly confirmed* rather than inferred: `gh run view` on the
   push containing the Qt-libraries fix shows **all four matrix jobs green**
   (`ubuntu-24.04`/`macos-14` × `3.11`/`3.13`). Use `gh` for this from now
   on — no more asking the operator to paste Actions UI screenshots.

354/354 offline tests. CI genuinely green on `origin/feat/desktop-hardware-threshold`, confirmed via `gh run view`, not assumed.

**The real lesson from this whole saga:** reproducing CI's *commands*
locally is not the same as reproducing CI's *environment*. An environment
with every optional extra already installed can never catch a
missing-extra-only failure, no matter how many times you re-run it
correctly. And "I verified X" is only a fact once you've actually checked
the output that proves X — two separate claims this session that CI would
probably pass turned out to be wrong, and the only reason that got caught
was asking for real output each time instead of re-asserting confidence.

## What's explicitly still missing

1. **No live visual/screenshot check of the channel-select grids** (RADIOROC
   32) or the `AutocalibrationWindow` tab (RADIOROC 31) — deferred twice
   now for legitimate reasons each time (an active operator session on the
   shared display), but genuinely overdue. Launch the app for real
   (`PYTHONPATH=src:. .conda-radioroc/bin/python -m radioroc.gui` with
   `DISPLAY` set, screenshot with `scrot`) — check for signs of an active
   operator session first (`ps aux` for an already-running `radioroc.gui`
   you didn't start) before touching the display yourself.
2. **`check_installed_package.py --gui` still isn't part of routine local
   checks** (`tools/check_development.py`) — it only runs in CI's separate
   wheel-verification stage. This is *why* the first CI bug this session
   had zero local signal for as long as it did. Worth deciding whether to
   fold a lightweight version into routine checks so a future GUI-default
   change can't hide the same way again.
3. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
4. **`AutocalibrationJob` has never run against real hardware.** The main
   *new* hardware-facing risk: the calibration-DAC force/restore sequencing
   around the reference channel, and the dynamic DAC-range computation
   between steps. A first real-hardware test should focus narrowly on
   those two things, not a full production calibration run.
5. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, untouched since.
6. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.
7. **Minor, not urgent:** the CI run's own annotations flag
   `actions/checkout@v4`/`actions/setup-python@v5` as targeting a
   deprecated Node.js version. GitHub is handling it automatically for now;
   worth bumping to newer action versions at some point regardless.

## Suggested next task (pick with judgment, same as always)

1. **Live-visual-check the GUI** (item 1) — cheap, fast, overdue twice.
2. **If the operator is present with the board**, do the narrow hardware
   test described in item 4.
3. **Or start F11–F13** if there's more appetite for a new vertical slice.

## Standing discipline (unchanged, plus this session's additions)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead.

**`gh` is now installed and authenticated on this machine** — use it
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
distinguished "pre-existing bug" from "something I just broke" this
session. And never state a CI run "probably passed" as a substitute for
checking — say what you actually verified and what you didn't.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
