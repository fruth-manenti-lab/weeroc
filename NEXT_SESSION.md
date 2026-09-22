# RADIOROC 34 — Confirm the GitHub Actions run *actually* passed this time, live-visual-check the GUI, hardware-validate F08, or pick up T1/T2/TQ enable bits / F11-F13

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 33 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 33 entry for full detail. Summary:

1. **`local_artifacts/` is now documented in `AGENTS.md` itself** (loaded
   every session automatically) plus a memory entry, so its value as a
   reverse-engineering evidence source doesn't need rediscovering each time.
2. **Found and fixed one real, currently-broken CI step before pushing**
   (an installed-wheel GUI probe still assuming Simulation was the default
   mode after an earlier commit changed it) — but **the push still failed**,
   confirmed by the operator watching the Actions UI directly. All four
   matrix jobs failed in ~1m21s, too fast to have even reached that fix.
3. **Found and fixed the actual failure** by asking the operator for the
   real step output instead of guessing again: `tools/check_development.py`
   itself failed, because `tests/test_channel_select.py`'s
   `FormatChannelsTests` imported a "pure, no Qt needed" function from a
   module that unconditionally imports PySide6 — invisible locally because
   every local run used `.conda-radioroc`, which already has PySide6
   installed. The same class of bug RADIOROC 28 already fixed once, one
   level deeper. Fixed by moving the function to `radioroc_client.py`
   (dependency-free), verified this time in an actual from-scratch venv
   with only `[analysis,dev]` installed (confirmed PySide6 genuinely
   absent) — not just by re-running the same already-GUI-capable
   environment more times. Pushed: `86b0760..d4e2852` on
   `origin/feat/desktop-hardware-threshold`.

**The real lesson:** reproducing CI's *commands* locally is not the same
as reproducing CI's *environment*. Every check this session ran, however
many times, used an environment with every optional extra already
installed — it could never have caught a missing-extra-only failure. See
`IMPLEMENTATION_STATUS.md`'s RADIOROC 33 entry (with its own correction)
for the full account, including exactly what was claimed too confidently
the first time and why.

354/354 offline tests, reproduced both in the regular dev environment and
in a from-scratch `[analysis,dev]`-only venv matching CI's actual
condition, both clean.

## What's explicitly still missing

1. **GitHub Actions result on `d4e2852` has not been checked yet.** Last
   time this exact statement was made (about `9abfbbd`), the push had
   actually failed for a reason this session's own environment could not
   have caught. Don't repeat that mistake: this time the fix was verified
   in an actual from-scratch `[analysis,dev]`-only venv with PySide6
   confirmed absent, which is a materially stronger check than last time —
   but it is still not the same as watching the real Actions run go green.
   **Check this first, and actually look at the result** — either ask the
   operator to glance at the Actions tab (fast), or use `gh` if it's
   available in a future environment. If it's still red, get the real
   step output before proposing anything, the same way the actual fix in
   this session only came from asking for that instead of guessing twice.
2. **`check_installed_package.py --gui` still isn't part of routine local
   checks** (`tools/check_development.py`) — it only runs in CI's separate
   wheel-verification stage. This is *why* RADIOROC 33's bug had zero local
   signal for as long as it did. Worth deciding whether to fold a
   lightweight version into routine checks so a future GUI-default change
   can't hide the same way again — a real gap, not just a one-off fix.
3. **No live visual/screenshot check of the channel-select grids** (RADIOROC
   32) or the `AutocalibrationWindow` tab (RADIOROC 31) — deferred twice
   now for legitimate reasons each time (an active operator session on the
   shared display), but genuinely overdue. Do this first among the GUI
   items: launch the app for real
   (`PYTHONPATH=src:. .conda-radioroc/bin/python -m radioroc.gui` with
   `DISPLAY` set, screenshot with `scrot`) — check for signs of an active
   operator session first (`ps aux` for an already-running `radioroc.gui`
   you didn't start) before touching the display yourself.
4. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
5. **`AutocalibrationJob` has never run against real hardware.** The main
   *new* hardware-facing risk: the calibration-DAC force/restore sequencing
   around the reference channel, and the dynamic DAC-range computation
   between steps. A first real-hardware test should focus narrowly on
   those two things, not a full production calibration run.
6. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, untouched since.
7. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.

## Suggested next task (pick with judgment, same as always)

1. **Confirm the GitHub Actions run actually passed** (item 1) — quick,
   and closes the loop on the operator's explicit ask this session.
2. **Live-visual-check the GUI** (item 3) — cheap, fast, overdue twice.
3. **If the operator is present with the board**, do the narrow hardware
   test described in item 5.
4. **Or start F11–F13** if there's more appetite for a new vertical slice.

## Standing discipline (unchanged, plus one addition)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead.

**New this session:** before pushing anything (not just after a packaging
change, per `AGENTS.md`'s existing "verify an installed wheel" rule) —
actually reproduce the CI workflow locally when the operator flags a
history of failed runs, rather than assuming local test-suite passes are
enough. `tools/check_development.py` and `.github/workflows/python.yml`
are not the same coverage: the installed-wheel/GUI-probe steps only run in
CI's separate stage and can silently rot with zero local signal, exactly
as happened here. When a local repro fails, root-cause it before assuming
your own current changes caused it — reproducing against the pre-session
commit in an isolated `git worktree` (cheap, doesn't disturb the working
tree) is what distinguished "pre-existing bug" from "something I just
broke" here.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
