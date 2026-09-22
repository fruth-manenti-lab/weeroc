# RADIOROC 38 — Build F13's GUI on the now-landed reader, or think through the main-merge question with the operator

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 34/35/36 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 35 and 36 entries for the full
account (both are long — read them in full, not just this summary).

**RADIOROC 34/35** (see prior handoffs for the full list): live-visual-check
of the GUI; reviewed a real operator-run hardware `AutocalibrationJob` test;
re-confirmed the T1/T2/TQ enable-bit blocker still holds; closed the
`check_installed_package.py --gui` routine-checks blind spot; **landed F12**
(`AcquisitionJob`, matching every other scan workflow's snapshot/restore/
cancellation/verification contract); recovered the real vendor acquisition
file format from `adc.pyc` disassembly as F13 groundwork.

**RADIOROC 36** (new conversation continuing directly from RADIOROC 35's
handoff — operator asked to continue and to think about main-merge timing):
1. **Thought through, but did not act on, when to merge `feat/desktop-
   hardware-threshold` into `main`.** `main` hasn't moved since 2026-06-29;
   this branch has diverged by 88+ commits and is what's actually used for
   real lab work already. Recommended targeting the plan's own M3 gate
   rather than the much-further-out M4/M5. **No merge decision was made**
   — this needs the operator's input on what `main` needs to represent
   (other consumers? a release process?) before picking a real trigger
   point.
   **Correction, caught by the operator directly:** this session initially
   also claimed M3's "one shell, one connection" gate was unmet, citing a
   stale RADIOROC 24 note without checking whether a later session had
   already fixed it -- RADIOROC 28 did, and this was wrong to repeat. See
   `IMPLEMENTATION_STATUS.md`'s RADIOROC 36 entry for the correction and
   the exact source lines confirming the shared-connection shell
   (`main_window.py`'s single `ConnectionWorker` passed into all four scan
   windows) has existed since RADIOROC 28. **This M3 gate is met, not
   open.** A useful, general lesson from this mistake: a "known gap" note
   found via grep in `IMPLEMENTATION_STATUS.md` is a snapshot from
   whichever session wrote it, not necessarily still true -- check the
   current source (or at least scan for a later session's fix) before
   repeating a status claim from an old entry, the same discipline this
   file already applies to memory recommendations.
2. **Landed F13 Phase A**: `src/radioroc/data/acquisition_reader.py`
   (`read_acquisition_run`) and `src/radioroc/data/vendor_acquisition.py`
   (`read_vendor_acquisition_file`). Delegated with a full contract, then
   reviewed line-by-line — **found and fixed one more real bug**, the same
   pattern as F12's review: the original row parser raised on any CSV row
   whose channel wasn't in the *current* manifest's channel set, which
   silently destroyed a later append segment's genuinely valid data
   whenever an *earlier* segment (legitimately, since nothing prevents a
   `--channels` change across `--append` runs) used a different channel
   set — reproduced the data loss empirically before fixing. Also caught
   the delegated agent's own verification gap: it ran `check_development.py`
   under a `.venv-dev` missing PySide6/matplotlib, silently skipping 128 GUI
   tests and reporting that as "OK". Re-verified under `.conda-radioroc`
   (the project's real environment): 416/416, no skips, both before and
   after merging.

**F13's GUI is still not started.** Phase A (the data-reading foundation)
is done and reviewed; the interactive parts (spectra display, HG/LG channel
and event views, selection/visibility/clear, bins/scales, live updates) are
next.

## What's explicitly still missing

1. **F13's GUI**: an `AcquisitionWindow` (or similar), using the now-landed
   `read_acquisition_run`/`SavedAcquisitionRun` as its data source, following
   the established window pattern (`ThresholdWindow`/`HoldScanWindow`/
   `ScurveWindow`/`AutocalibrationWindow`) for connection handling, run/save/
   reopen, and live updates during a run. This is GUI-layout work that
   benefits from a live visual check the way RADIOROC 34's did — consider
   whether to wait for the operator to be able to glance at a screenshot
   rather than designing it fully blind in another unattended session, per
   RADIOROC 35/36's own judgment call to hold off on exactly this.
2. **Decide the `main`-merge trigger point with the operator** (see above) —
   this is a conversation to have, not a unilateral call, but it shouldn't
   be left open indefinitely either; the branch only gets bigger and riskier
   to eventually reconcile the longer this goes unaddressed. Note M3's own
   readiness picture is better than RADIOROC 36 first (incorrectly)
   reported — the shared-connection gate is already met — though the rest
   of M3's gate criteria haven't been separately re-verified either.
3. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
4. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, re-confirmed blocked in RADIOROC 34.
   Needs either a genuinely new evidence source or a narrow
   authorized-operator hardware test: write one candidate bit pattern,
   observe which physical threshold/channel responds. Do not guess and ship
   a write for this byte.
5. **F11 is largely covered by F12's `AcquisitionConfig`** (trigger_type/
   trigger_source/adc_window_ns/adc_nb_trig are the same primitives F11
   asks for), but hasn't been explicitly validated as "done" against F11's
   own row in `CROSS_PLATFORM_REBUILD_PLAN.md` §3 — worth a deliberate
   check rather than assuming.
6. All of M5 (Windows-comparison bench, performance, packaging/release)
   hasn't begun. See `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full
   list.
7. **Minor, not urgent:** the CI run's own annotations flag
   `actions/checkout@v4`/`actions/setup-python@v5` as targeting a
   deprecated Node.js version.

## Suggested next task (pick with judgment, same as always)

1. **Build F13's GUI** (item 1) if there's appetite for another vertical
   slice — the reader contract underneath it is now settled and reviewed.
   Consider the screenshot-timing question above before diving in solo.
2. **Raise the main-merge question with the operator** (item 2) — a short,
   direct conversation, not something to resolve alone.
3. **If the operator is present with the board and wants to resolve
   T1/T2/TQ (item 4)**, the narrow hardware test described there is the
   only path left to unblock it.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
under `.conda-radioroc` (the project's actual GUI-capable environment) after
every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A self-created venv without the `[gui]` extra will
silently skip every GUI test and look green when it isn't — RADIOROC 36 saw
a delegated agent do exactly this. A7585 (F15) is permanently out of scope.
Delegate bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead. When delegating to an isolated worktree,
review the actual diff line-by-line against the contract before merging —
both F12 and F13 Phase A found a real bug this way, not by trusting the
subagent's own passing test count.

`gh` is installed and authenticated on this machine — use it
(`gh run list --branch <branch>`, `gh run view <id>`, `gh run view --log-failed`)
to check CI status directly after any push, instead of asking the operator
to check the Actions UI manually. Watch for the occasional stale/transient
`gh run list` result — re-list with a larger `--limit` if the top row looks
implausible, rather than trusting a single query.

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
