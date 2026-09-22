# RADIOROC 33 — Live-visual-check the channel-select grids and Autocalibration tab, hardware-validate F08, or pick up T1/T2/TQ enable bits / F11-F13

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 32 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 32 entry for full detail. Summary:

1. **Channel selection redesigned across the whole app**, prompted by the
   operator finding free-text channel entry confusing. Reverse-engineered
   the vendor's own "set ignore channel" slide panel from its compiled
   `.pyc` files (colors, mechanism, and confirmed along the way that the
   vendor's own scan loop masks/unmasks channels exactly like this
   codebase already does — not a lab invention).
2. **New shared widget**, `radioroc.gui.channel_select.ChannelSelectGrid` —
   a collapsible 64-button grid matching the vendor's real blue
   (`#007990`/`#024167`), `Select all`/`Select none`, one-line summary when
   collapsed.
3. **`ProbesMasksPanel` restyled** to the same button look (drop-in swap,
   same API, existing tests unchanged).
4. **All four scan windows** (S-curve, Threshold, Hold-scan, Autocalibration)
   now use `ChannelSelectGrid` instead of a "4,5"-style text field.
5. **Survived a mid-session Pi restart** that killed a delegated agent
   before it could report back — recovered by checking the working tree
   directly rather than assuming anything was lost, reviewing the diff
   against the original spec, and re-running the full suite fresh.

357/357 offline tests, `tools/check_development.py` clean under a hard
`timeout` with confirmed process exit.

## What's explicitly still missing

1. **No live visual/screenshot check of the new channel-select grids** in
   any of the four scan windows, or of the `AutocalibrationWindow` tab from
   RADIOROC 31 (that check was already deferred once — don't defer it
   again). Do this first: launch the app for real
   (`PYTHONPATH=src:. .conda-radioroc/bin/python -m radioroc.gui` with
   `DISPLAY` set, screenshot with `scrot`) — but **check for signs of an
   active operator session first** (e.g. `ps aux` for an already-running
   `radioroc.gui` you didn't start) before launching or interacting with
   one yourself, same discipline as RADIOROC 31.
2. **`ProbesMasksPanel` still has no hardware read-back.** Its grid always
   shows "all enabled" regardless of real ASIC state — this is *why*
   scan-window channel selection couldn't just reuse it directly this
   session, and remains open in `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04
   backlog. Worth revisiting once/if read-back is built.
3. **`AutocalibrationJob` has never run against real hardware.** Every test
   at every layer (job, CLI, worker, GUI) uses a scripted fake transport.
   The main *new* hardware-facing risk: the calibration-DAC force/restore
   sequencing around the reference channel, and the dynamic DAC-range
   computation between steps. A first real-hardware test should focus
   narrowly on those two things, not a full production calibration run.
4. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, untouched since.
5. **F11–F13 (DAQ trigger logic/acquisition orchestration/spectra GUI)
   are still entirely unstarted**, and all of M5 (Windows-comparison bench,
   performance, packaging/release) hasn't begun. See
   `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full list.

## Suggested next task (pick with judgment, same as always)

1. **Live-visual-check the channel-select grids and Autocalibration tab**
   (item 1) — cheap, fast, overdue twice now.
2. **If the operator is present with the board**, do the narrow, deliberate
   first hardware test described in item 3 — the calibration-DAC
   force/restore sequencing and dynamic range computation are the specific
   things worth watching, not a full production run.
3. **Or start F11–F13** if there's more appetite for a new vertical slice —
   larger and less scoped, expect real scoping time before delegating any
   of it.

## Standing discipline (unchanged, plus one addition)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead. Reverse-engineer vendor UI/behavior from the
extracted `.pyc` files (`marshal.loads` + `dis`) when the question is "what
does the real app actually do" rather than guessing — this session's
channel-select colors/mechanism and the earlier confirmation that vendor
scans mask channels the same way this codebase does both came from that
technique, not inference.

**New this session:** a delegated background agent can be interrupted by
the environment itself (this session's Pi restarted mid-task). A "stopped"
task with no completion record does not mean the work is lost — check the
working tree directly first (`git status`/`git diff`) before assuming
anything needs redoing, then review whatever is there against the original
delegation spec exactly as carefully as a normal completion report, and
re-run the full test suite fresh regardless of what the (now unavailable)
agent might have already checked.

Record what you did, what's next, and any real findings in
`IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before you stop.
