# RADIOROC 37 — Build F13's acquisition-run reader (offline), or resume F13's GUI, or pick up T1/T2/TQ

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (a grant given in one conversation is for that
conversation only — don't assume it forward to a new chat).

## What RADIOROC 34/35 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 35 entry for the full account (it
grew across a long solo overnight session — read the whole entry). Summary:

**RADIOROC 34** (short session, operator present but not at the board):
live-visual-checked the GUI (Probes/Masks grids, Autocalibration tab — both
render correctly, closing items deferred since RADIOROC 31/32); reviewed an
operator-run real-hardware `AutocalibrationJob` test found mid-session
(genuinely passed — force/restore, dynamic DAC-range narrowing, tight
per-channel S-curve alignment all checked); re-investigated and
re-confirmed the T1/T2/TQ enable-bit blocker from RADIOROC 30 still holds
(vendor tooltip has no per-bit position, PDF doesn't mention the register).

**RADIOROC 35** (operator went home, explicitly authorized continuing
unattended and offline-only — this session declined a request to weaken
the present-operator hardware rule itself; see the conversation record):
1. Closed the `check_installed_package.py --gui` routine-checks blind spot:
   added `tests/test_scan_window_defaults.py`, verified it actually catches
   the RADIOROC 33 failure mode.
2. **Landed F12** — ported `scripts/radioroc_acquire.py` from calling
   `RadiorocDevice` primitives directly into a proper `AcquisitionJob`
   (`src/radioroc/application/acquisition.py`), matching every other scan
   workflow's snapshot/restore/cancellation/verification contract, with a
   deliberately wider (safer) register snapshot than the old ad-hoc script
   had. Implementation delegated with a fully-specified contract, then
   reviewed line-by-line — found and fixed one real bug in the new
   `AcquisitionRunWriter`'s append mode (a CSV missing from an interrupted
   prior run would never get its header written). Independently verified:
   391/391 in the reviewed worktree, 394/394 after merge, a real end-to-end
   job run against the new simulator, a register-count hand-check (132,
   exact), and the untouched `plot_acquisition_spectrum.py` reading the
   job's own output correctly. CI confirmed green via `gh` (not assumed).
3. **Recovered the real vendor acquisition file format from `adc.pyc`**
   (previously unexamined — a dedicated per-feature vendor module,
   sibling to `radioroc2UI.pyc`) as F13 groundwork: the vendor's
   `readable_adc_acq.txt` is a **wide** format (`#Acq,HG0,LG0,...,HG63,LG63`,
   one row per event), structurally different from F12's tall
   `batch,event,channel,hg,lg` schema. F12's schema is not being revisited
   (it's intentionally normalized and already matches the existing
   `plot_acquisition_spectrum.py`) — the vendor format only matters for
   *reading* a real Windows-app-collected file for comparison, which is
   exactly what M5's "Windows-comparison bench" needs. See the full
   disassembly-backed reconstruction in `IMPLEMENTATION_STATUS.md` before
   touching this — it's precise, not a guess, and re-deriving it would waste
   real time.

**F13's implementation was deliberately not started.** After landing and
thoroughly reviewing F12, a second large implementation thread this deep
into an unattended session risked spreading review attention too thin —
the research above was worth finishing and recording regardless, so this
is a clean, well-evidenced stopping point rather than a rushed one.

## What's explicitly still missing

1. **F13's actual implementation is next**: a `SavedAcquisitionRun` reader
   (`src/radioroc/data/acquisition_reader.py`) adapting
   `data/threshold_reader.py`'s defensive manifest-vs-CSV cross-validation
   pattern to acquisition's different (non-fixed-grid, tall) schema, plus a
   vendor-format *reader* for `readable_adc_acq.txt` (not a writer — no
   evidenced consumer for vendor-formatted export yet), then eventually the
   GUI itself (spectra display, HG/LG channel and event views,
   selection/visibility/clear, bins/scales, live updates). Read
   `threshold_reader.py` and the RADIOROC 35 write-up before scoping this;
   both are needed to get the contract right on the first pass the way F12's
   was.
2. **`ProbesMasksPanel` still has no hardware read-back** — open in
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04 backlog, unchanged.
3. **T1/T2/TQ *enable* bits still unimplemented** (address 65, subaddress
   7) — carried over from RADIOROC 30, re-confirmed blocked in RADIOROC 34.
   Needs either a genuinely new evidence source or a narrow
   authorized-operator hardware test: write one candidate bit pattern,
   observe which physical threshold/channel responds. Do not guess and ship
   a write for this byte.
4. **F11 is largely covered by F12's `AcquisitionConfig`** (trigger_type/
   trigger_source/adc_window_ns/adc_nb_trig are the same primitives F11
   asks for), but hasn't been explicitly validated as "done" against F11's
   own row in `CROSS_PLATFORM_REBUILD_PLAN.md` §3 — worth a deliberate
   check rather than assuming, since the plan's "full source/combination
   coverage unverified" note predates F12 landing.
5. All of M5 (Windows-comparison bench, performance, packaging/release)
   hasn't begun. See `CROSS_PLATFORM_REBUILD_PLAN.md` §3/§4 for the full
   list.
6. **Minor, not urgent:** the CI run's own annotations flag
   `actions/checkout@v4`/`actions/setup-python@v5` as targeting a
   deprecated Node.js version. GitHub is handling it automatically for now;
   worth bumping to newer action versions at some point regardless.

## Suggested next task (pick with judgment, same as always)

1. **Build F13's acquisition-run reader + vendor-format reader** (item 1)
   — fully offline, well-evidenced, the natural next bounded slice. The GUI
   itself is a good follow-on once the reader contract is settled and
   reviewed; consider whether GUI work should wait for the operator to be
   able to glance at a screenshot rather than being designed fully blind
   overnight.
2. **If the operator is present with the board and wants to resolve
   T1/T2/TQ (item 3)**, the narrow hardware test described there is the
   only path left to unblock it — do not attempt it without a specific
   operator-authorized action per `AGENTS.md`.
3. A quick pass confirming F11 is actually satisfied (item 4) is small and
   worth doing before or alongside F13.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action. Never run
`radioroc_env_check.py` as an offline check. Run `tools/check_development.py`
after every meaningful change — wrap it in a hard `timeout` and confirm the
process itself exits. A7585 (F15) is permanently out of scope. Delegate
bounded, well-specified implementation/test work to subagents per
`AGENTS.md`; keep shared contracts, uncertain hardware/register reasoning,
and integration for the lead. When delegating to an isolated worktree,
review the actual diff line-by-line against the contract before merging —
RADIOROC 35's F12 review is a concrete example of why: a real bug (a
headerless CSV after an interrupted append) only surfaced from reading the
code, not from trusting the subagent's own passing test count.

`gh` is installed and authenticated on this machine — use it
(`gh run list --branch <branch>`, `gh run view <id>`, `gh run view --log-failed`)
to check CI status directly after any push, instead of asking the operator
to check the Actions UI manually. Watch for the occasional stale/transient
`gh run list` result (RADIOROC 35 saw one) — re-list with a larger `--limit`
if the top row looks implausible, rather than trusting a single query.

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
