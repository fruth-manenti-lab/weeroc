# Implementation status

## RADIOROC 34 — Live-visual-checked the GUI (Probes/Masks grids, Autocalibration tab), both items deferred since RADIOROC 31/32

Short session (~30 min), operator present but not at the board; offline only.

**Did the live visual check deferred twice before.** Checked `ps aux` first
for an already-running `radioroc.gui` (none), then launched the real app on
the shared display (`DISPLAY=:0`, `PYTHONPATH=src:. .conda-radioroc/bin/python
-m radioroc.gui`) and screenshotted with `scrot`. Installed `xdotool`
(`sudo apt-get install -y xdotool`, reversible, standard package) to drive
tab/menu clicks since no window-control tool was present.

Confirmed by screenshot (saved to session scratchpad, not committed):
- **Probes/Masks tab (RADIOROC 32 channel-select grids)**: "Enable T1" /
  "Enable T2" / "Enable TQ" grids of 64 channel buttons each render cleanly,
  correctly aligned, teal styling matches the vendor look established in
  RADIOROC 32. No layout or overlap issues.
- **Calibration → Autocalibration tab (RADIOROC 31 `AutocalibrationWindow`)**:
  all fields render correctly -- Connection, Channels, Discriminator, Mask
  other channels, Enable Ctest, S-curve clock index, Count trigger level,
  Optional gain override (Trigger preamp gain code dropdown), Preview / Run
  autocalibration / Cancel / Open saved result buttons, "HARDWARE — no data
  yet" plot placeholder, and the hardware-safety banner text. No layout
  issues.
- Main / Channel config / Threshold scan tabs also spot-checked in passing;
  all rendered as expected, nothing broken.

Closed the app cleanly afterward (`kill` on the launched PID, confirmed no
`radioroc.gui` process remained). No hardware touched, no board connection
attempted -- `Connect` was never clicked.

**Both of the "explicitly still missing" visual-check items from
RADIOROC 33/32/31's handoffs are now done.** Remaining backlog (T1/T2/TQ
enable bits, F11-F13, `check_installed_package.py --gui` not in routine
checks, `ProbesMasksPanel` hardware read-back, `AutocalibrationJob` never
run against real hardware) is unchanged -- this session only closed out the
visual-check item, nothing else.

## RADIOROC 33 — Documented local_artifacts in AGENTS.md; three real CI bugs found and fixed, confirmed green via gh

Continuing on `feat/desktop-hardware-threshold`, operator present and directing.

**Durable reminder that `local_artifacts/` is evidence, not just archives.**
Added a bullet to `AGENTS.md` (auto-loaded every session in this repo) and
a memory entry describing the extraction path, the `marshal.loads`/`dis`
technique, and what each subdirectory holds -- prompted by this session's
own repeated use of it (register maps, the channel-select panel mechanism
and colors, confirming vendor scan behavior) making clear it wasn't
reliably surfacing to a fresh session otherwise.

**Found and fixed a real, currently-broken CI step before pushing**, per
the operator's explicit request not to reproduce past failed GitHub Actions
runs. Rather than push and hope, reproduced every `.github/workflows/
python.yml` step locally end to end: built the wheel, installed it in a
clean venv, and ran `tools/check_installed_package.py --gui --plot`
exactly as CI does. It failed. Root-caused before assuming it was this
session's fault: reproduced the identical failure against the pre-session
commit in an isolated `git worktree`, confirming it predates every change
made this session.

The actual cause: an earlier commit (`be042b7`, "Default scan windows to
Hardware mode", already on `main` before this session started) changed
every scan window's default mode from Simulation to Hardware. The regular
GUI test suites were updated for this at the time (each now explicitly
selects Simulation in its own `setUp`), but `tools/check_installed_package
.py`'s own hardcoded `GUI_PROBE` script was not -- it still assumes
Simulation is the default and never explicitly selects it, so its first
`window.start_run()` silently falls into the (unconnected) hardware branch
and no-ops instead of running the simulated job, and the probe fails
downstream trying to read output that was never written. Nothing in
`tools/check_development.py`'s own test suite exercises this script, so
this has been silently broken since that commit with no local signal --
very likely the actual cause of prior failed GitHub Actions runs, since
this exact step runs on every push across the full ubuntu/macos x
python 3.11/3.13 matrix.

Fixed with one line (`window.mode.setCurrentIndex(0)` before the probe's
first run), mirroring the regular test suites' own fix for the same
default-mode change. Re-verified the complete sequence locally afterward --
build, wheel install, `check_installed_package.py` bare/`--plot`/`--gui
--plot`, and `unittest discover -p test_threshold_gui.py` against the
installed wheel -- all pass. This also incidentally confirmed this
session's own channel-select changes are packaging-correct: every new
module (`channel_select.py`, `autocalibration.py`,
`autocalibration_window.py`, `autocalibration_reader.py`,
`radioroc_autocalibrate.py`) is present in the built wheel and importable
outside the checkout.

**Evidence:** 357/357 offline tests via `tools/check_development.py`,
clean under a hard `timeout` with confirmed process exit (one unrelated
load-sensitive flake -- `test_abrupt_process_exit_leaves_durable_
nonterminal_run`, a real-subprocess 10s-timeout test -- reproduced failing
only under the heavy concurrent build/venv load this verification itself
created, confirmed passing instantly in isolation; not a regression). Full
CI sequence reproduced locally as described above, all green. Pushed to
`origin/feat/desktop-hardware-threshold` (`86b0760..9abfbbd`).

**Correction, checked minutes later with the operator watching the Actions
UI directly: that push still failed, all four matrix jobs, in ~1m21s --
too fast to have reached the wheel-check step just fixed above.** The
earlier "if it still fails, it is not this specific gap" framing was
correct in substance but should not have been stated with that much
confidence without a way to actually confirm the push landed green; this
session had no `gh` CLI/auth to check, and said so, but then still implied
the fix was probably sufficient. It was not the same bug. The operator
shared the failing step directly: `tools/check_development.py` itself,
36 seconds in -- the exact command this session had run successfully well
over a dozen times. Root cause, found by asking for the real output instead
of guessing again: `tests/test_channel_select.py`'s `FormatChannelsTests`
(added this session, testing `format_channels()` with no
`skipUnless(GUI_AVAILABLE)` guard, matching that function's own "pure, no
Qt needed" docstring claim) imported it from `radioroc.gui.channel_select`
-- a module that unconditionally imports PySide6 at the top for its own
`ChannelSelectGrid` widget. CI's offline job never installs `[gui]`, so the
import itself raised `ModuleNotFoundError` before any test body ran.
Reproduced exactly by poisoning `sys.modules['PySide6'] = None` locally
before touching anything. This is the identical class of bug RADIOROC 28
already fixed once (a Qt-dependent module-level import breaking test
collection without the `[gui]` extra) -- at the function-extraction level
this time instead of the test-file level, and not caught by this session's
own repeated `tools/check_development.py` runs because those always ran in
`.conda-radioroc`, which already has PySide6 installed.

Fixed by moving `format_channels` into `radioroc_client.py` (next to the
existing, differently-shaped `format_channels_for_path`) -- the
established dependency-free home for this kind of utility -- and moving
its test to `tests/test_radioroc_core.py` alongside that module's other
pure-function tests. This time verified precisely rather than by pattern-
matching against the workflow file: built a **from-scratch venv**, ran
`pip install '.[analysis,dev]'` (confirmed `import PySide6` genuinely
fails in it), and ran `tools/check_development.py` in *that* environment --
the actual condition that had been missed. Also swept every other test
file for the same risk pattern (a non-`GUI_AVAILABLE`-guarded test class in
a file that imports `radioroc.gui.*` at module level) and found none; the
one file that looked suspicious by that grep
(`test_connection_panel.py`'s `ConnectionWorkerSharedAcrossWindowsTests`)
uses a different, already-correct guard (`setUpClass` raising `SkipTest`),
matching what the operator's CI log actually showed for it (skipped, not
errored) -- confirming the sweep methodology against a known-good case,
not just trusting it.

**The actual lesson, not the one recorded the first time:** "reproduce the
CI workflow's commands" is not the same as "reproduce CI's environment."
Every verification this session ran used `.conda-radioroc`, an environment
that already has every optional extra installed -- it could never have
caught a missing-extra-only failure no matter how many times it ran
correctly. A genuine repro needs a venv built the same way CI builds one,
checked to confirm the thing that's supposed to be absent actually is.

**Third fix, and final confirmation.** After the `format_channels` fix
above landed, the operator checked the Actions UI again directly: macOS
jobs (both Python versions) now passed cleanly, confirming that fix was
real -- but both Ubuntu jobs still failed, with a completely different,
unrelated error: `ImportError: libEGL.so.1: cannot open shared object
file`, raised just importing `PySide6.QtWidgets`. Not a bug in this repo
at all -- a well-known PySide6/Qt6-on-headless-Linux-CI issue (Qt6
dynamically loads EGL/OpenGL libraries during `QtGui` initialization
regardless of which QPA platform plugin is selected, and GitHub's
`ubuntu-24.04` runner image doesn't ship them; `macos-14`'s image
apparently does, or Qt's macOS backend doesn't need them, which is why
only Linux hit this). Fixed by adding a Linux-only step to
`.github/workflows/python.yml` installing `libegl1` (confirmed via
`dpkg -L` to be the exact package providing `libEGL.so.1`) plus the
commonly-needed xkbcommon/xcb/dbus runtime libraries Qt6 typically needs
even under "offscreen", to avoid a fourth round-trip discovering one more
missing `.so`. Package names verified against Debian's own package pool
(this environment can't run an actual x86 `ubuntu-24.04` runner locally),
since Ubuntu tracks these particular base libraries closely.

**This session also installed and authenticated the `gh` CLI** (`sudo apt
install gh`, then the operator ran `gh auth login` interactively) --
`gh` wasn't available for any of the earlier checks above, which is why
each one relied on the operator manually reading the Actions UI and
pasting output back. With `gh` now authenticated, `gh run list --branch
feat/desktop-hardware-threshold` / `gh run view <id>` directly confirmed
the fix: **all four matrix jobs (`ubuntu-24.04`/`macos-14` x
`3.11`/`3.13`) passed** on the push containing this fix
(`7e69776`) -- an actual, direct confirmation this time, not the
inference-based claim made (and shown wrong) twice earlier in this same
CI saga. `gh` should remove the need for that manual back-and-forth in
future sessions.

**Not done:** the same "regular test suite never exercises this script"
gap could hide a similar issue again in the future for any GUI-default
change -- worth considering whether `check_installed_package.py --gui`
should run as part of routine `tools/check_development.py` checks (it
currently only runs in CI's separate wheel-verification stage) so this
class of bug surfaces locally next time, not just on push. The CI run's
own annotations flagged `actions/checkout@v4`/`actions/setup-python@v5`
as targeting a deprecated Node.js version (GitHub is handling this
automatically for now, per the linked changelog) -- not urgent, but worth
bumping to `@v5`/latest at some point rather than waiting for it to become
a hard failure.

## RADIOROC 32 — Channel selection redesigned to match the vendor app; survived a mid-session Pi restart (offline)

Continuing on `feat/desktop-hardware-threshold`, operator present and directing.

**The problem, raised by the operator:** every scan window (S-curve,
Threshold, Hold-scan, Autocalibration) asked for channels as free text
("4,5" or "0-15") -- easy to typo, no visual feedback, and disconnected
from the Probes/Masks tab's own per-channel grid, which raised the
reasonable question of why scanning didn't just reuse that. Investigation
found `ProbesMasksPanel` is write-only with no hardware read-back (its
grid always shows "all enabled" regardless of real ASIC state, a
pre-existing gap already flagged in `CROSS_PLATFORM_REBUILD_PLAN.md`'s F04
backlog), so tying scan channel selection to it directly wasn't viable
without first building that read-back.

**Found the real answer in the vendor's own compiled app instead.** The
operator recalled a "slide popup" for choosing channels in the original
Windows app. Reverse-engineered directly from the extracted PyInstaller
`.pyc` files (`marshal.loads` + `dis`, the same technique used throughout
this project's register-recovery work):
- `scurves.pyc`/`thresholdscan.pyc`: a `pushButton_setignorescurves`
  toggles `groupBox_setignorescurves` open/closed via
  `Radioroc2.slide_groupbox` (`main.pyc`, outside the PYZ) -- a
  `QPropertyAnimation` sliding the groupbox's height, not a `QDialog`/
  `QMenu` popup. `pushButton_ignoreallscurves`/`pushButton_plotallscurves`
  call `Radioroc2.set_all_checked`, which just finds every checkable
  `QAbstractButton` child and sets it.
- The channels themselves are `WCheckBox` instances (`uiroc/weedgets.pyc`)
  whose `draw_checked` paints pen `QColor(2,65,103)` (`#024167`) and fill
  `QColor(0,121,144)` (`#007990`) -- confirmed against the Probes/Masks
  screenshot, which shows the same solid-blue-when-enabled buttons, not
  checkbox tickmarks.
- Also confirmed (separately, answering "does the vendor even do this
  masking automatically" along the way): yes -- `scurves.pyc`/
  `thresholdscan.pyc`'s own scan loop masks every channel, then unmasks
  one at a time per DAC point, exactly matching this codebase's
  `use_mask`/`prepare_trigger_masks` behavior. Not a lab invention; a
  faithful port of real vendor behavior.

**Built to match:** new `radioroc.gui.channel_select.ChannelSelectGrid`
(`src/radioroc/gui/channel_select.py`) -- a collapsible 64-button grid
(`#007990` fill / `#024167` border when selected), `Select all`/
`Select none`, collapsed by default showing a one-line summary (e.g.
`"Channels: 4-7,63"` -- `format_channels()` collapses consecutive runs,
tested directly). The vendor's own 200ms slide animation was deliberately
not reproduced: a plain show/hide toggle gives the same "collapsed by
default, one click to edit" behavior without adding animation-timing
surface to test.

`ProbesMasksPanel`'s three mask grids were restyled to the same button
look in place (`QCheckBox` -> checkable `QPushButton` with the shared
stylesheet), keeping the exact `isChecked()`/`setChecked()` API so no
other code or existing test needed to change -- confirmed by the six
existing Probes/Masks tests passing unmodified.

All four scan windows' free-text "Channels (comma separated)" field was
replaced with `ChannelSelectGrid`, each `operation()` now reading
`selected_channels()` instead of parsing text. A malformed or duplicate
channel string is now structurally impossible (each channel is one
toggle), so the three tests that used to cover `"4,"`/`"4,4"` now cover
"no channels selected" instead -- the one way this input can still be
invalid -- asserting against `validate_channels`'s actual "at least one
channel is required" message rather than a guessed one.

**Survived a mid-session interruption.** The scan-window wiring was
delegated and the Raspberry Pi running this session restarted partway
through (unrelated to this work) before the agent could report back. Its
task showed as "stopped" with no completion record. Rather than assume
anything was lost, checked the working tree directly: all nine intended
files already had complete, correct changes sitting there uncommitted.
Reviewed every diff against the original delegation spec line by line (not
just the earlier session's memory of having sent it) and ran the full
offline suite fresh before trusting any of it, exactly as if it were a
newly-completed delegation.

**Evidence:** 357/357 offline tests (3 new: one `test_operation_uses_
selected_channels` per S-curve/Threshold/Hold-scan window, confirming
`operation()` reflects the grid's selection end-to-end), plus 10 tests for
`ChannelSelectGrid` itself (collapsed-by-default state, toggle/select-all/
select-none, `set_channels`/`selected_channels`, the theme color, and
`format_channels`'s range-collapsing). `tools/check_development.py` clean
under a hard `timeout` with confirmed process exit, independently re-run
after reviewing the full diff (not just trusting the delegated agent's
now-unavailable final report).

**Not done:** `ProbesMasksPanel` still has no hardware read-back (the
pre-existing gap that ruled out directly reusing it for scan channel
selection) -- still tracked as open in `CROSS_PLATFORM_REBUILD_PLAN.md`'s
F04 backlog, unchanged by this session. No live visual/screenshot check of
the new channel-select grids in any of the four windows -- worth doing
alongside the still-outstanding Autocalibration-tab visual check from
RADIOROC 31.

## RADIOROC 31 — Hover hints wired everywhere; F08 autocalibration job + CLI + GUI built end to end (offline)

Continuing the same session as RADIOROC 30, per operator direction to keep
going after the "Main" tab/window-sizing work landed.

**Hover hints (RADIOROC 29/30's other open item) are done.** Delegated,
reviewed diff-by-diff against the actual panel files (not just the report):
`MainWindow` and all six ASIC-config panels (`ConnectionPanel`, `MainPanel`,
`ChannelConfigPanel`, `InputDacGridPanel`, `ThresholdCalibrationPanel`,
`ProbesMasksPanel`, `RawRegisterPanel`) now report hover text into a shared
`HintBar` over `MainWindow.statusBar()`, the same way the three scan windows
already did. Each panel gained an `attach_hints(hint_bar)` method (one shared
hint per 64-cell grid, not 64 distinct strings); `RawRegisterPanel.table` was
correctly skipped (not hoverable per-cell). 321/321 offline tests (16 new)
after this piece, independently re-run clean.

**Extracted the pure half of F08 (automatic threshold calibration).**
`scripts/radioroc_standard_scurves.py`'s `RadiorocOps.autocalibrate_scurve`/
`_estimate_crossings` (a legacy standalone script that duplicates its own
copy of the ASIC/FPGA primitives rather than sharing `radioroc_client.py`)
implements a real, complete algorithm:
1. Pick a reference channel; run one coarse S-curve with its calibration
   trim DAC forced to 0, another forced to 63; restore it afterward. Use
   each run's 50%-crossing point to estimate `lsb_ratio` (how many DAC
   codes one trim-DAC LSB shifts the threshold).
2. Run one shared, finer S-curve across every selected channel; find each
   channel's crossing point; average them (`mean_pos`).
3. For each channel, compute `correction = round((crossing - mean_pos) /
   lsb_ratio)` and write `current_trim - correction` (clamped 0..63) as its
   new calibration trim DAC — aligning every channel's threshold crossing
   to the same DAC value.
4. Run one final, narrow S-curve across all channels to verify alignment.

The crossing-estimation half (`_estimate_crossings`: linear interpolation
to find where an S-curve first crosses a target percentage) is pure
numeric analysis with no hardware dependency once it's handed parsed rows,
so it moved to `radioroc_analysis.py` as `estimate_scurve_crossings(rows,
channels, *, target_percent=50.0)` — decoupled from CSV file I/O (it takes
rows shaped like `radioroc.data.scurve_reader.SavedScurveRun.rows`, so it
can run on a live job's in-memory rows or a saved run, not just a file
path) and directly unit-tested (`tests/test_radioroc_core.py`'s
`test_estimate_scurve_crossings`: normal crossing, no-crossing-found ->
`None`, channel absent -> `None`, exact-match short-circuit, non-default
`target_percent`).

**The orchestration half is now built too** (operator confirmed continuing
rather than deferring it). New `AutocalibrationJob`/`AutocalibrationJobConfig`
/`AutocalibrationResult` in `src/radioroc/application/autocalibration.py`
implement the full 4-step sequence against real hardware, per the settled
design below. Built and tested directly by the lead (not delegated): this is
exactly the "uncertain hardware reasoning" work `AGENTS.md` asks the lead to
own, given the non-reentrant session-lock composition and the safety-critical
restoration requirement (see below).

**Design (what was actually built):**
- `AutocalibrationJobConfig` mirrors `ScurveJobConfig` (`src/radioroc/
  application/scurve.py`): `channels`, `t1`, `use_mask`, `use_ctest`,
  `clock_index`, `trigger_level`, `out_dir`, `config_path`,
  `initialize_fpga`, `apply_defaults`, plus autocalibration-specific
  fields (coarse/fine DAC step sizes, the step-1 probe range).
- **Locking:** `session_lock(transport)` (`src/radioroc/application/
  jobs.py`) is an explicitly non-reentrant `threading.Lock` shared across
  a transport session. `ScurveJob.run()` acquires it itself, so
  `AutocalibrationJob` cannot call that public entry point four times
  without releasing exclusivity between sub-scans - another job could
  interleave mid-calibration. The correct composition, matching this
  codebase's existing lock-once-per-job-run convention: `AutocalibrationJob`
  acquires the session lock a single time for the whole 4-step sequence,
  then drives each sub-scan through `ScurveJob()._run_locked(...)` directly
  (the method `ScurveJob.run()` itself calls internally after acquiring the
  lock) - reusing the already-hardware-validated per-point scan/restore
  logic verbatim, not reimplementing it. This needs each sub-scan's own
  `ScurveResult`/`total`/`rows` setup (the same few lines `ScurveJob.run()`
  does before calling `_run_locked`), which is inherent to running four
  genuinely separate scans (each with its own CSV/manifest/out_dir), not
  avoidable duplication.
- **Manifests:** each of the four sub-scans writes its own manifest/CSV via
  the existing, proven `ScurveRunWriter` (no new writer class needed).
  `AutocalibrationJob` additionally writes one small top-level
  `autocalibration_metadata.json` under its own `out_dir` recording: the
  operation config, each sub-run's directory name, the computed
  `lsb_ratio`, per-channel crossing positions and `mean_pos`, the
  before/after calibration trim DAC values actually applied, and overall
  status/timing - a plain JSON write (atomic, mirroring how other
  manifests in this codebase are written), not a new bespoke format.
- **Restoration discipline** must match every other job in this codebase:
  the reference channel's calibration DAC is a *temporary* probe value
  during step 1 (force 0, force 63, restore original) even on
  cancellation/failure mid-step - this is the one place in the whole
  algorithm where "restore on any exit path" is safety-critical, since an
  interrupted step 1 that leaves a channel's calibration DAC stuck at 0 or
  63 would silently corrupt every later scan against that channel. The
  final corrected values written in step 3 are the job's intentional,
  persistent output (like `set_calibration_dac_for_channel`'s existing
  contract) and are not restored.

**A real bug was found and fixed while writing the restoration path.** The
first draft restored the reference channel's calibration DAC directly inside
a bare `finally:` block with no exception guard of its own. Since a `return`
statement's value (or a propagating exception) from the `try` block is
silently replaced by anything the `finally` block itself raises, an
unrelated restore-write failure there would have masked the *actual* scan
failure that triggered the restore in the first place -- exactly the
cleanup-clobbers-primary-error class of bug `ScurveJob`'s own `cleanup_call`
helper exists to prevent. Fixed by wrapping the restore (and its optional
verification read) in their own try/except, recording any failure as a
warning on the result instead of letting it propagate. Caught in self-review
before any test ran, not by a failing test -- worth remembering that a
"looks right" `try/finally` restoration pattern still needs this check.

**Evidence:** new `tests/test_autocalibration_jobs.py` (6 tests, reusing
`test_scurve_jobs.ScurveTransport` -- the same scripted fake ASIC/FPGA
transport `ScurveJob` itself is tested against, not a lighter-weight
double) drives the real `AutocalibrationJob` through a complete, worked
4-step sequence with hand-computed expected values at every stage: exact
`lsb_ratio`/crossings/`mean_position`, exact before/after calibration DAC
values for two channels (including the reference channel itself, which is
also one of the calibrated channels -- its *final* value is its own
correction, not its temporarily-restored probe value, a distinction the
first draft of this test got backwards before being corrected), reference-
channel restoration on a mid-sequence cancellation, `verify_restoration`,
dry-run touching nothing, session-lock rejection of a concurrent job (this
end-to-end run is what actually proves the non-reentrant lock composition
works, not just that it compiles), and invalid-config rejection before any
hardware/file access. 327/327 offline tests total this session (6 new here),
independently re-run clean under a hard `timeout` with confirmed process
exit.

**`AutocalibrationJob` now has a CLI command**, `scripts/radioroc_autocalibrate.py`,
built the same session by the lead following `scripts/radioroc_scurve.py`'s
exact pattern (shared `radioroc_cli_common` helpers, `--execute`/dry-run-by-
default write safety, `AutocalibrationJob.preview()` -- a new static method
mirroring `ScurveJob.preview()` -- for the dry-run JSON report, the same
SIGINT-requests-cancellation handling, the same error-chain printer). Exposes
every `AutocalibrationJobConfig` field as a flag, including
`--transition-dac-floor`/`--transition-dac-cap` (needed so a CLI invocation
can exactly reproduce any config, not just the common fields). 3 new tests
(`tests/test_autocalibration_jobs.py`): dry-run touches no serial/files;
CLI and direct-API calls with equivalent settings produce byte-identical
transport command traces (proves the CLI wiring adds no hidden behavior
difference, not just that it runs); invalid configuration is rejected before
any hardware access. 330/330 offline tests (17 legacy CLI help checks, up
from 16), independently re-run clean under a hard `timeout` with confirmed
process exit.

**`AutocalibrationJob` is now wired into the shared `ConnectionWorker`**
(lead-owned: `run_autocalibration`/`cancel_autocalibration`/
`autocalibration_snapshot`, mirroring the existing `run_scurve`/
`run_hold_scan`/`run_threshold` pattern exactly) **and has a full GUI window**,
`AutocalibrationWindow` (delegated, reviewed diff-by-diff), wired into
`MainWindow` as a fourth Calibration tab alongside Threshold/Hold/S-curve.

Deliberately **hardware-only** by design, not an oversight: unlike the other
three scan workflows, there is no standalone simulation mode/worker/mode
combo box here. Building a believable synthetic 4-step calibration-
convergence simulator (matching what `ScurveSimulationConfig`/
`scurve_simulator.py` do for a single S-curve) was judged out of scope for
this pass; autocalibration is a maintenance procedure only meaningful
against real hardware anyway, unlike S-curve/threshold which get used for
offline preview routinely. Confirmed with the operator before proceeding on
this basis. If simulation-mode parity is wanted later, it is a separate,
scoped follow-up, not a gap in what was attempted here.

New `AutocalibrationWorkerSnapshot` (in `connection_worker.py`) tracks which
of the four sub-scans is currently active, inferred from the fixed step
order and each sub-scan's own "preparing" state event rather than threading
step identity through `JobEvent`; its `rows` buffer resets on every step
change, since the four sub-scans are separate CSVs that shouldn't be
plotted as one concatenated series. New `read_autocalibration_run`
(`src/radioroc/data/autocalibration_reader.py`) composes the existing
`read_scurve_run` for each of the four named sub-run directories, for the
window's "Open saved result" feature.

**A second real bug caught via the new worker-level test** (not by
inspection this time): `AutocalibrationJob._run_sub_scan` never set its
`ScurveResult`'s initial `status` to `"preparing"` before handing it to
`ScurveJob`'s internals (`ScurveJob.run()` always does this itself;
composing `_run_locked` directly, as this job does, skipped it silently).
Every sub-scan's first state event therefore carried the dataclass default
(`"completed"`) instead of `"preparing"` -- the exact status the new
step-tracking logic above watches for -- so it would have silently stayed
on `"step1_zero"` forever, undetected by the job-level tests (which only
check *final* result status, insensitive to this). Fixed in
`autocalibration.py`; the worker-level test that caught it is now a
permanent regression guard.

**Evidence:** 344/344 offline tests total this session (12 new across the
worker wiring, reader, and GUI window), `tools/check_development.py` clean
under a hard `timeout` with confirmed process exit, independently re-run
(not just trusting the delegated report) after reviewing the full diff.

**Not done:** never run against real hardware -- only scripted
fake-transport tests throughout every layer (job, CLI, worker, GUI). No
live visual/screenshot check of the new GUI tab this time (unlike the
window-sizing fix earlier this session) -- the operator appeared to be
actively using the app on the shared display when this was ready, so it was
left untouched rather than risking disruption or an accidental hardware
action; worth a live check next session, especially given this tab has more
form fields (13) than any existing ASIC-config/scan-window tab and could in
principle have its own scroll/layout surprises the offscreen tests can't
see. The T1/T2/TQ enable bits (address 65 subaddress 7) from RADIOROC 30
are still unimplemented for the same reason as before. `HintBar`'s wording
across this whole session's work (own text, not verbatim vendor tooltips
beyond a few specific one-liners) hasn't been read over by the operator.

## RADIOROC 30 — Hold-scan diagnosis confirmed; A7585 descoped; "Main" (F02) register map recovered (offline)

Continuing on `feat/desktop-hardware-threshold`, operator present and directing.

**Hold-scan noise-self-trigger diagnosis (RADIOROC 29) is confirmed, not just
recommended.** A re-run at `threshold_dac=250` already existed locally
(`radioroc_runs/hardware/20260922-105500-056b6058/`, `created_at`
2026-09-22T00:59:16Z, ~5 minutes after the diagnosed 150-DAC run) but had not
been picked up when RADIOROC 29's handoff was written. Comparing the two
runs directly: at `threshold_dac=150`, `ch4_count` was 21-22 against a
requested 10 and `ch4_hg_stdev` peaked at ~419 in the 475-625 ns
transition/peak region; at `threshold_dac=250`, `ch4_count` is exactly 10 at
every hold point and the same region's stdev tops out at ~24. This is a
clean confirmation of the diagnosis (per-channel-discriminator ADC arming on
its own noise-triggered crossings at 150, not just the FPGA synchro pulse,
roughly doubling and corrupting the batch). No further action needed on
this item; nothing to re-run.

**A7585 (F15) is out of scope, permanently**, per explicit operator
decision: this lab does not use or own a CAEN A7585 supply module. Removed
it from `CROSS_PLATFORM_REBUILD_PLAN.md`'s parity table, bench-validation
stage table, and M4 slice order. Do not build, simulate, or plan validation
for it going forward.

**Correction to prior status: the "Main" tab (F02) register map was never
actually blocked on missing source.** Prior sessions (RADIOROC 30 handoff,
RADIOROC 27) described it as needing "more time on reverse-engineering," which
was true, but the framing that it was waiting on new material was wrong — the
same vendor extraction already used for the threshold-calibration/input-DAC/
mask registers (`local_artifacts/extracted/RadiorocUI_2_2_0_5.exe_extracted/
PYZ-00.pyz_extracted/radioroc2UI.pyc`, read via `marshal.loads()` on the raw
`.pyc` bytes past the 16-byte header, no decompiler needed since this
machine's CPython 3.13 matches the bundled bytecode exactly) has held the
"Main" tab's register map all along, including the harder common-block
(`add >= 64`) registers RADIOROC 27 ran out of time on. This session mined
`Ui_MainWindow.retranslateUi`'s ~1400 string constants (tooltips embed
`add: N - subadd: M - bit: [a:b]` directly after each control's plain-English
description, and the raw-register-view labels at `add: 64-66` separately name
every bit field, e.g. `dac1[7:0]`, `hysteresis1,hysteresis2, EN_delay,
selHoldExt, selTrig[3:0]`) and recovered:

- **Trigger preamplifier (paT), per channel** (`add`=channel 0-63, `subadd`=1):
  compensation = bits `[7:6]`, gain = bits `[5:0]` (1=max gain, 63=min gain,
  0=open loop).
- **Energy measurement, per channel** (`add`=channel, `subadd`=2 for gain,
  `subadd`=3 for shaping, `subadd`=7 for LSB select): HG gain bits `[3:0]`,
  LG gain bits `[7:4]` of subadd 2; HG shaping bits `[3:0]`, LG shaping bits
  `[7:4]` of subadd 3 (shaping time = 20 ns x code or 120 ns x code depending
  on the LSB select bit); HG shaping LSB = subadd 7 bit 6, LG shaping LSB =
  subadd 7 bit 7 (same byte already used per-channel for Ctest connect/bit 4
  and injection-capacitor bit 5 - four independent flags packed into one row).
- **Threshold DACs T1/T2/TQ, common/ASIC-wide, not per-channel** (`add`=65):
  three 10-bit DAC codes packed across three shared bytes - `dac1[7:0]` at
  subadd 1, `dac1[9:8]`+`dac2[5:0]` sharing subadd 2, `dac2[9:6]`+`dacQ[3:0]`
  sharing subadd 3, `dacQ[9:4]` (+2 unused bits) at subadd 4. Enable bits
  (`EN_th1`, `EN_th2`, `EN_thQ`, plus bandgap `EN_bg` and `vref[3:0]`) live
  together at subadd 7.
- **Trigger selection, common** (`add`=65, `subadd`=12): one shared byte -
  `hysteresis1`, `hysteresis2`, `EN_delay`, `selHoldExt`, `selTrig[3:0]` - the
  combo box's six options (`External`=0000, `Local T1`=0001, `Local T2`=0010,
  `Local TQ`=0011, `Global T1`=0100, `Global T2`=1000, `Global TQ`=1100) map
  directly onto `selTrig[3:0]`.
- **Delay/slope, common** (`add`=65): delay code = `subadd`=8 bits `[7:0]`
  (`delay[7:0]`), slope trim = `subadd`=9 bits `[7:4]` (`slopeTrim[3:0]`,
  sharing the byte with an internal bias current `ibi_discri_delay[3:0]` that
  is not a user control and must be preserved on write).

Every shared-byte field above (HG/LG shaping LSBs on the per-channel subadd-7
byte; the T1/T2/TQ DAC split across subadd 1-4; trigger-selection's five
packed fields; delay/slope's shared subadd-9 byte) follows the exact
read-row/modify-one-slice/write-row pattern this codebase already uses in
`RadiorocDevice.set_mask_for_channel`/`set_tq_mask_for_channel`/
`set_calibration_dac_for_channel` - no new RMW mechanism needed, just applying
the existing one to new bit positions. Cross-checked bit widths and shared-byte
membership against the corresponding `add: 64-66` raw-register-view labels (a
second, independent source inside the same binary) before trusting them, and
against the packaged default-config CSV (`configs/radio_default_i2c.csv`):
channel 0's default trigger-preamp compensation decodes to 0 (matches the
vendor guide's "keep to 0" recommendation exactly), and address-65
subaddress-12's default byte (`11100100`) decodes `selTrig[3:0]` to `0100` -
exactly the "Global T1" code enumerated from the "Trigger selection" combo
box's own tooltip text, an independent numeric match that confirms both the
bit position and the enumerated codes at once. The two shaping-LSB bits'
polarity (bit=1 means 120 ns/code, bit=0 means 20 ns/code) is inferred from
the paired checkbox's shaping-time formula rather than cross-checked against
a default (both HG/LG default to 0 = 20 ns either way, so the default can't
distinguish the two directions) - flagged as the one still-soft assumption
here. Not yet independently verified against real hardware, same caveat as
every other register recovered this way in this codebase.

**Built on this:** added 15 new `RadiorocDevice` setters
(`radioroc_client.py`) covering every register above: per-channel trigger-
preamp gain/compensation, HG/LG gain/shaping/shaping-LSB, and common (ASIC-
wide) T1/T2/TQ threshold DACs, trigger selection, and delay code/slope. Each
follows the existing docstring/style convention (recovered-register
provenance, explicit range, RMW side effects, not-yet-hardware-verified
caveat). Two new test methods in `tests/test_radioroc_core.py`
(`test_main_tab_per_channel_front_end_bit_positions`,
`test_main_tab_common_threshold_and_trigger_selection`) check every bit
position, every shared-byte preservation, and the two default-value
cross-checks above.

**Evidence:** 298/298 offline tests (2 new), `tools/check_development.py`
clean under a hard `timeout` with confirmed process exit.

**Built on top of that, same session (delegated, reviewed):** the
application layer and GUI panel that make F02 actually usable.
`ChannelConfigOperation`/`apply_channel_config` (`src/radioroc/application/
channel_config.py`) gained 14 new fields (8 per-channel dicts, 6 common
scalars/string) mirroring the existing `t1_calibration_dac_values`/
`input_dac_impedance` patterns exactly, with matching validation and
touched-register tracking for every shared byte. New `MainPanel`
(`src/radioroc/gui/main_panel.py`) reproduces the vendor "Main" tab layout —
a channel selector (0..63), "Trigger preamplifier (paT)" and "Energy
measurement" (High/Low gain) groups for the per-channel front end, and a
"Common thresholds and timing" group for `Threshold1`/`Threshold2`/
`ThresholdQ`/`Trigger selection`/`Delay`/`Slope` — following
`ThresholdCalibrationPanel`'s async apply/poll/show_snapshot pattern. Since
this tab shows one channel at a time with no per-channel readback path
(unlike the 64-cell grid panels), edited values are accumulated per-channel
in memory as the operator switches channels (seeded from the packaged
defaults on first visit) and every visited channel is included when Apply
is pressed. Wired into `MainWindow` as the first `asic_config_tabs` tab
("Main"), matching the vendor's own tab order. Reviewed directly against
the diff (not just the delegated report): default-value arithmetic
independently re-derived from `configs/radio_default_i2c.csv` and confirmed
correct (T1=0, T2=2, TQ=520, delay=255, slope=4, trigger selection=Global
T1, per-channel gains=8/shaping=4/compensation=0), RMW preservation checked
register-by-register, and `MainWindow` wiring matches the established
per-panel convention with no shortcuts taken.

**Evidence:** 312/312 offline tests (14 new: 3 application-layer, 10 panel,
1 `MainWindow` wiring), independently re-run clean under a hard `timeout`
with confirmed process exit (not just the delegated report's own claim).

**Not done:** hover-hints for the new panel (see RADIOROC 29/30's other open
item) and hardware validation - nothing in this session touched real
hardware. The T1/T2/TQ *enable* bits (`EN_th1`/`EN_th2`/`EN_thQ`/`EN_bg`,
address 65 subaddress 7) remain intentionally unimplemented: their bit
order inside that shared byte wasn't independently cross-checked to the same
confidence as everything else above (the default value's grouping doesn't
resolve enable-bit order the way the trigger-selection default resolved
`selTrig`), and shipping a wrong enable-bit write is worse than leaving that
one control out of a future GUI pass until it's confirmed the same way.

**Real usability bug found and fixed via a live visual check, same session.**
The operator reported they couldn't see the bottom of the window and didn't
know whether a hint/status bar existed there at all. Launched the actual
desktop app against the real X display (`DISPLAY=:0`, screen confirmed
1600x900 via `xrandr`) rather than guessing, and screenshotted it. Confirmed
two compounding causes:
1. `MainWindow.resize(1280, 900)` requested a window exactly as tall as the
   full 1600x900 screen, leaving zero margin for the window manager's own
   title bar and top panel - guaranteed to push the window's bottom off
   the visible screen on this display (and any screen the same size or
   smaller).
2. The new `MainPanel` (this session's own F02 GUI work, above) stacks three
   full group boxes vertically with no scrolling; it is taller than the
   space every other ASIC-config tab was built to fit in, so its own Apply
   button and status label - where a future hint would show - were
   completely unreachable even once the window itself fit on screen.

Screenshot evidence before the fix: `Trigger selection`/`Delay`/`Slope`/
`Apply`/status label were all rendered below the visible screen edge, with
no scrollbar to reach them. Fixed both causes in `src/radioroc/gui/
main_window.py`: (1) the initial window size is now clamped to
`QApplication.primaryScreen().availableGeometry()` (with a margin) instead
of a bare literal, so it fits whatever screen it opens on; (2) every
ASIC-config tab's panel (not just `MainPanel`) is now wrapped in its own
`QScrollArea` via a new `_scrollable()` helper, so a panel taller than the
available window height scrolls instead of clipping - general, future-proof
protection for every current and future ASIC-config tab, not a `MainPanel`-
specific patch. Re-screenshotted after the fix: the window now fits the
screen (desktop/taskbar visible around all four edges) and the Main tab
shows a working vertical scrollbar. Updated the one test that asserted a
tab's widget identity directly (`test_main_panel_is_the_first_asic_config_tab`
in `tests/test_main_window.py`) to account for the new `QScrollArea` wrapper.

**Evidence:** 312/312 offline tests (no count change - existing test updated,
not added), independently re-run clean under a hard `timeout` with confirmed
process exit. Visually confirmed via two real screenshots (before/after)
against the actual display, not just headless/offscreen test coverage.

**Not done:** an actual `HintBar` (hover-tooltip status line) for
`MainWindow`/any ASIC-config panel still does not exist - this session fixed
a *visibility* bug (content and the existing persistent connection-status
strip were unreachable), not the separate, still-open feature gap. Do not
conflate the two: `MainWindow` does have one permanent bottom status strip
(`self.status_strip`, connection state only, unrelated to hover-hints) which
was simply invisible before this fix and is now visible; it is not a
`HintBar`.

## RADIOROC 29 — Hardware-first default mode; hover-hint status line; hold-scan log diagnosis (offline)

**Hold-scan log diagnosis (no code change).** The operator ran a real hold
scan (`radioroc_runs/hardware/20260922-105042-43d9bc20/`) at
`threshold_dac=150` and asked why the result looked weird: `ch4_count` was
~21–22 against a requested 10 acquisitions, and stdev was huge (up to ~420)
specifically in the 475–625 ns transition/peak region while small elsewhere.
Diagnosis: 150 sits inside the noisy region this session's earlier threshold
scan mapped (trigger rate peaked around there); this run's external-hold ADC
config used `trigger_source=3` (individual per-channel discriminator), so the
ADC also arms on the channel's own noise-driven T1 crossings, not only the
FPGA synchro pulse — roughly doubling the count and mixing randomly-timed
noise-triggered samples into the batch, which explains both anomalies
together. Recommended re-running at `threshold_dac=250` (the validated
preset value) as a cheap confirmation; not yet re-run.

**Hardware is now the default mode**, not Simulation, in all three scan
windows (`ThresholdWindow`, `HoldScanWindow`, `ScurveWindow`) — operator
request, since the desktop app is now used against real hardware routinely.
Changed `_accepted_mode` and the mode combo box's initial index from 0 to 1
in each window, and made the initial "New run directory" default match
(`hardware/...` instead of `simulation/...`) so it isn't misleading at
launch. The three GUI test suites (`test_threshold_gui.py`,
`test_hold_scan_gui.py`, `test_scurve_gui.py`) are simulation-only by design
(they assert `serial.Serial` is never touched) and now explicitly select
Simulation mode in `setUp` instead of relying on the old default. Added
`test_scan_windows_default_to_hardware_mode` to `test_main_window.py` to
guard the new default explicitly.

**Hover-hint status line**, mirroring the vendor app's help line at the
bottom of the window. New `radioroc.gui.hint_bar.HintBar`: a small
`QObject` that wires Enter/Leave events on arbitrary widgets to a
`QStatusBar` (or anything with `showMessage()`/`clearMessage()`), showing a
one-line description of whatever control the mouse is over and falling back
to a window-level default otherwise. All three scan windows use their own
`QMainWindow.statusBar()` and attach a description to every field, checkbox,
dropdown and button — including a plain-language explanation of what
Ctest and the FPGA synchro-trigger pulse actually do, since the operator
asked. `MainWindow` and the ASIC-config panels (channel config, input DAC
grid, probes/masks, threshold calibration, raw registers) do not yet have
hints wired in — flagged as the next bounded task, see below.

**Evidence:** 296/296 offline tests (6 new: `test_hint_bar.py` unit tests
for the helper itself, plus the new default-mode regression test), full
suite re-run clean; `tools/check_development.py` passes.

**Not done:** hints on `MainWindow`'s own controls (tab bar, the shared
`ConnectionPanel`) and the five ASIC-config panels; re-running the hold
scan at `threshold_dac=250` to confirm the noise-self-trigger diagnosis.

## RADIOROC 28 (continued) — Two real bugs the operator hit live, using the actual app

Same conversation, after RADIOROC 28's other work. The operator actually
launched `radioroc-desktop` and used it, twice, and found two real bugs
neither offline unit tests nor this session's own end-to-end reasoning had
caught.

**Bug 1 — port dropdown empty until Refresh clicked once.** MainWindow
starts the shared `ConnectionWorker` eagerly at construction (unlike a
standalone scan window, which stays lazy on purpose), but nothing then
triggered discovery — the operator had to click Refresh once before any USB
candidate appeared at all. Fixed: `MainWindow.__init__` now calls
`connection_panel.refresh()` right after starting the worker. Verified
against the real board's discovery (not just a fake) before committing.

**Bug 2 — a scan tab's "Device / mode" selector stuck on Simulation,
greyed out, after connecting via the shared ASIC-config page.** This is
the normal order of use in the shared shell (Threshold/Hold-scan/S-curve
don't own a connection to connect from themselves), and it was completely
blocked: `_mode_switch_locked()` and `_update_connection_controls()` in all
three scan windows read the *shared* worker's own "connected" state as a
reason to lock/grey out this window's mode selector — correct for a window
that owns its connection (switching away from Hardware mid-session would
orphan a session it's responsible for), wrong here, since the window never
owns the shared connection's lifecycle at all. Fixed by keying both checks
off this window's own `_hardware_running` flag instead of the shared
worker's state, when `_connection_panel is None` (shared mode). The
existing regression test for RADIOROC 27's connection-propagation fix
switched mode to Hardware *before* connecting, which never exercised this
order; added a new test connecting first, confirmed it fails without the
fix (reproducing exactly what the operator saw) and passes with it.

**Responding to the operator's direct question — "can your test try to run
basic things like this?"** — added two more MainWindow-level tests that
actually run a full scan (not just check a button's enabled state) through
the real `ThresholdWindow`/`ScurveWindow` classes after connecting via the
shared page, against a session backed by a faithful fake ASIC/FPGA
transport. Tried the same for Hold scan; it hung against that fake
transport, which this session judged to be a fake-fidelity gap rather than
a live bug (Hold scan already has real-hardware GUI evidence from
RADIOROC 24, and the fake transport in question was built for the
threshold job's specific interaction sequence) — left as a known gap
instead of forcing a misleading pass or chasing it further.

**Evidence:** 290/290 offline tests (5 new), 3 clean full-suite runs.

**Not done:** figuring out why the shared fake ASIC/FPGA transport hangs
against a real Hold-scan run, or building a better one — flagged for a
future session, not urgent since Hold scan itself is already validated on
real hardware.

## RADIOROC 28 — CI fix; raw-register view (F06); a real async-race bug fix (offline)

Same conversation as RADIOROC 27, continuing after the operator asked two
unrelated questions: how to keep working reliably from a train with
unstable internet (answered directly, not recorded here — no code change),
and why every push has been triggering a GitHub Actions "all runs failed"
email.

**CI fix.** `tests/test_main_window.py` (written during RADIOROC 26)
imported PySide6 at module level instead of guarding it behind the
`GUI_AVAILABLE` skip pattern every other GUI test file in this repo uses.
`.github/workflows/python.yml`'s main job never installs the `[gui]` extra,
so `unittest`'s test *loader* failed to even import that module — one
failing import fails the entire `unittest discover` invocation, which fails
`tools/check_development.py`, which fails the whole job, on every single
push since that file was first committed, across the whole
ubuntu/macos × python 3.11/3.13 matrix. Reproduced the exact CI steps
end-to-end in a clean venv on this machine (`pip install '.[analysis,dev]'`,
`check_development.py`, `python -m build`, wheel install with each extra) to
confirm this was really the cause before fixing it.

**Raw-register view (`F06`)**, the next-task suggestion from RADIOROC 27's
handoff. New `src/radioroc/application/raw_registers.py`
(`RawRegisterWrite`/`RawRegisterResult`, `read_all_registers`/
`write_raw_register` — generic `(add, subadd, byte)` access, batching the
full-table re-read through the existing multi-row `read_fifo` rather than
one round trip per register), two new `ConnectionWorker` commands mirroring
`apply_channel_config`'s exact pattern, and a new `RawRegisterPanel` GUI
sub-tab ("Registers", fifth on the ASIC-config page): a table of every
loaded register plus a single-register write field set with verify.

Found while testing the core: the shared `ThresholdTransport`/
`OwnedThresholdTransport` test fixture's synthetic ASIC map (add 0..66,
subadd 0..63) doesn't cover every row the packaged default config CSV
carries (reserved `add=66 subadd>=64` probe-block rows, `add=67`) — fine for
every existing test, which only ever touches specific requested channels,
but this feature's bulk multi-row read hits it directly. Worked around with
a small controlled row set rather than extending a fixture shared by
unrelated test files; flagged inline for whoever touches this next.

**A resurfaced SIGSEGV, fixed for real this time.** Adding the above tests
made the same `QObject::killTimer` crash RADIOROC 26 partially fixed
reproduce deterministically (3/3, via a hard-`timeout`-wrapped
`tools/check_development.py`, not just eyeballing "OK"). Root-caused with
`PYTHONFAULTHANDLER=1` to a native stack: a leftover Qt object from an
*earlier, unrelated* GUI test getting garbage-collected — on a background
thread — in the middle of a later, purely-Python test's `Thread.join()`
call. RADIOROC 26 fixed this for the four `QMainWindow`-based test files but
explicitly flagged the standalone-panel test files as pending follow-up
(`test_channel_config_panel.py` and this session's own new
`test_input_dac_grid_panel.py`/`test_probes_masks_panel.py`/
`test_threshold_calibration_panel.py`): none of them called `deleteLater()`
on the bare `QWidget` panels they construct, relying entirely on Python's
cyclic GC, which can run on any thread. Fixed by registering
`panel.deleteLater()` + `app.processEvents()` via `addCleanup` in each
file's `make_panel()` helper — 8 clean full-suite runs after (was 0/3
before, deterministically, once this session's new tests shifted GC timing
enough to expose it).

**A real, confirmed (not theoretical) bug found by direct empirical
testing, not just code reading:** built `RawRegisterPanel` to poll for
command completion (since a full-table read can take a while) rather than
assume the result is ready the instant it's submitted — the same shape as
the scan workflow windows' own submit-then-poll pattern. This prompted
checking whether the four *existing* channel-config-family panels
(`ChannelConfigPanel`, `InputDacGridPanel`, `ProbesMasksPanel`,
`ThresholdCalibrationPanel`, all following the same "submit, then
immediately call `show_snapshot()`" shape) had the same problem. They did:
`apply_channel_config` on `ConnectionWorker` only enqueues the operation and
returns immediately, so calling `show_snapshot()` right after reliably reads
a stale or empty result. Confirmed end-to-end against a real
`ConnectionWorker` with a faithful fake transport before touching any
code — 0/50 correct with the pre-fix panel, 50/50 after — ruling out this
being an artifact of an incomplete test double. Standalone on MainWindow's
ASIC-config page, nothing else re-polls these panels afterward either, so
this was not self-correcting (unlike the same panels embedded in a scan
window that owns its own `ConnectionPanel`, where that panel's own
perpetual 100ms timer happens to paper over it within about a tick — a
minor, mostly-imperceptible blip there, not a permanent staleness). Fixed
all four with the same submit-then-poll pattern `RawRegisterPanel` already
needed, and updated each panel's `FakeWorker` test fixture to answer
`snapshot()` (previously absent entirely — these fakes completed
"synchronously" from the panel's point of view, which is exactly why the
existing unit tests never caught this).

**Evidence:** 286/286 offline tests (24 new: 7 raw-registers core, 2
`ConnectionWorker`-level, 8 `RawRegisterPanel`, plus fixture/assertion
updates to the four existing panels' tests), 5 clean full-suite runs.
Offscreen screenshot of the new "Registers" tab. Not physically validated
against real hardware (same caveat as the rest of this session's non-Main
register work — this feature's registers are generic, not ASIC-semantic,
so there is no register-mapping-confidence question here, only the usual
"not yet run for real" one).

**Not done:** "Main" tab register mapping (see RADIOROC 27's entry — still
deferred, method proven but not yet applied there); full vendor F06 parity
(`read/write all` beyond the loaded table, `default reset`, config
import/save/drag-drop, embedded field help) — this pass built the narrow
version deliberately, as scoped in the RADIOROC 27 handoff.

## RADIOROC 27 — Threshold-calibration DAC register mapping recovered; grid built (offline)

Same day, continuing from RADIOROC 26 with the operator now present and
directing (not autonomous). The operator asked whether the "Main"/"Threshold
calibration" register documentation flagged as missing at the end of
RADIOROC 26 might already be sitting in `local_artifacts` or findable online,
rather than needing a fresh vendor request.

**Found real source, not a guess.** `local_artifacts/downloads/Radioroc2
User Guide - 2_1_0_6(0125).pdf` (already in the repo, not previously read
fully) documents every Main-tab parameter's *behavior* (ranges, step sizes)
but explicitly defers register addresses to "the datasheet," which isn't
included. The actual register map turned out to be recoverable a different
way: `local_artifacts/extracted/RadiorocUI_2_2_0_5.exe_extracted/` is a full
PyInstaller extraction of the vendor's own Windows app, and its bundled
`.pyc` files are genuine CPython 3.13 bytecode — matching this machine's
interpreter exactly, so `marshal.loads()` + `dis` reads them directly with no
decompiler needed (decompilers largely don't support 3.11+ bytecode, but
"disassemble and read the constants" doesn't require one). This is the exact
method this codebase already used previously for the input-DAC/TQ-mask
registers (see `RadiorocDevice.set_tq_mask_for_channel`'s existing docstring,
"recovered from the vendor GUI's compiled widget properties") — tonight
extended the same technique to the registers that hadn't been done yet.

`radioroc2UI.pyc`'s `Ui_MainWindow.setupUi` embeds every control's tooltip
text as adjacent string constants, many literally spelling out `add: N -
subadd: M - bit: [a:b]` right after a field's bit-layout description (e.g.
`NC*2, calibDacT1[5:0]` immediately followed by `add: 0 - subadd: 4`) —
`strings` on the raw `.pyc` surfaces these without even needing the full
disassembly. Cross-checked three ways before trusting it: (1) independently
re-derived bit positions for TQ mask (bit 2), T1 mask (bit 4), T2 mask (bit
3), and input-DAC enable (bit 6) from this same source and confirmed they
exactly match this codebase's existing, already-hardware-adjacent
implementations — not a coincidence, since both were reverse-engineered from
the same vendor binary; (2) the packaged default config CSV's channel-0 rows
for subadd 4 and 5 both already carry `00100000` (decimal 32), matching the
vendor GUI's default "Calibration DAC T1"/"T2" display value of 32 exactly;
(3) `uiroc/i2c.py`'s own `set_value`/`get_bits` functions (also disassembled)
confirm the same MSB-first bit-string addressing convention this codebase
already uses. Result: per channel, subadd 4 bits `[5:0]` = T1 calibration
trim DAC (6-bit, 0-63), subadd 5 bits `[5:0]` = T2 (top 2 bits of each byte
unused/`NC`). "Main" tab register addresses were *not* pinned down with the
same confidence in the time available (its controls are a mix of per-channel
and shared/common registers, and the "common block" register semantics
weren't as cleanly self-describing in the strings found) and remain
deferred, but the reverse-engineering method itself is now demonstrated and
reusable for a future session that wants to spend more time on it.

**Built on this:** `RadiorocDevice.set_calibration_dac_for_channel`
(`radioroc_client.py`) mirrors `set_input_dac_value`'s exact style/docstring
convention. `ChannelConfigOperation` gained
`t1_calibration_dac_values`/`t2_calibration_dac_values`
(`dict[channel, 0..63]`, mirroring the existing `input_dac_values` pattern)
in `src/radioroc/application/channel_config.py`. New `ThresholdCalibrationPanel`
(`gui/threshold_calibration_panel.py`, delegated, reviewed) adds the vendor
app's fourth ASIC-config sub-tab — two 64-channel T1/T2 trim-DAC grids with a
"Set all" per grid — wired into `MainWindow` alongside the three sub-tabs
RADIOROC 26 already built.

**Evidence:** 268/268 offline tests (8 new over RADIOROC 26's 260: 1
device-level bit-position test, 1 core-operation test, 6 panel tests), 3
clean full-suite runs of `tools/check_development.py`. Offscreen screenshot
of the new tab matches the vendor screenshot's layout. Not independently
verified against real hardware (same caveat as every other register
recovered this way in this codebase).

**Then: first-ever physical hardware run through the S-curve GUI path**,
the item RADIOROC 25 left pending. Operator confirmed the board still
connected/powered from a prior session and explicitly authorized hardware
use. `scripts/radioroc_check_connection.py --port /dev/ttyUSB0` read the
same known-good `00000101 (5)` status word RADIOROC 24 saw. Reused the exact
settings from `radioroc_runs/diag_scurve_ch4_defaults_20260921/` (a CLI
diagnostic run from earlier the same day, found already sitting in the repo
rather than needing to be re-derived: channel 4, trigger preamp gain code 1,
T1, mask on, no Ctest, clock index 3, DAC 80..160 step 5 — no signal
generator needed, since this is the bare-board internal-noise pedestal
turn-off curve), driving the real `MainWindow`/`ScurveWindow` production
classes directly (not a bespoke harness) via a one-off offscreen-Qt script,
not committed to the repo.

**Found and fixed two real bugs this surfaced, both now covered by a new
regression test:**
1. After connecting through the shared `ConnectionPanel`, none of the three
   embedded scan windows' run buttons ever became enabled. Each window's own
   `status_changed -> poll_connection_worker` wiring (`gui/scurve_window.py`
   and siblings) only self-connects when the window owns its own
   `ConnectionPanel`; with an injected worker (the whole point of RADIOROC
   26's shared shell) nothing told the window the connection changed state.
   Fixed in `MainWindow.__init__` by wiring the shared panel's
   `status_changed` to each scan window's `poll_connection_worker` directly.
2. `tests/test_main_window.py`'s `_FakeSession` fixture returned a bare
   `RadiorocMemoryTransport` from `__enter__` instead of matching the
   session contract every other GUI test fixture in this codebase already
   uses (`__enter__` returns `self`, which answers `read_word`/`close`
   directly). Nothing in that file had ever actually connected through it
   before the new test below did, so it was a latent bug: it left
   `ConnectionWorker`'s background thread stuck in `"close_failed"` instead
   of `"stopped"` on shutdown, hanging the whole test process at interpreter
   exit — reproduced and confirmed directly with a small non-Qt repro script
   before touching any test file, isolating it from Qt/threading noise.

New `test_scan_windows_reflect_a_shared_connection_reaching_connected`
(`tests/test_main_window.py`) reproduces the original bug and guards both
fixes. 269/269 offline tests, 3 clean full-suite runs, and confirmed the
full suite's own process now exits cleanly (it silently hadn't been,
before — `tools/check_development.py`'s subprocess call happens to wait for
the child regardless, so this had not been visibly breaking CI-equivalent
runs, but any direct/manual single-test invocation would hang forever).

**Physical result:** `status: completed`, `cleanup: restored`,
`verification.status: passed` (zero mismatches), 17/17 DAC points. Measured
curve: 100% through DAC 115, 98.5% at 120, 36.5% at 125, 3.5% at 130, 0%
from 135 — same shape and same DAC 120-130 transition window as the CLI
diagnostic run from earlier the same day (99.5%/60.0%/6.0% at the same
three points), the difference being ordinary shot-noise variation between
two independent measurements of a statistical trigger-efficiency curve, not
a discrepancy. Evidence local under
`radioroc_runs/hardware/20260922-075139-52019b25/` (uncommitted, per policy).
Board left connected but idle afterward (disconnected cleanly via the same
script), matching every prior session's handoff discipline. No push to
`main`.

**Not established:** hardware validation for anything beyond this one
S-curve case (Threshold/Hold-scan GUI hardware paths were already validated
in earlier sessions); whether the same shared-connection-state gap affects
any other not-yet-hardware-tested control on the ASIC-config page tabs
built earlier this session (input DAC grid, mask grids, threshold
calibration grid) — plausible given the shared root cause, worth a
targeted follow-up rather than assuming either way.

## RADIOROC 26 — Shared connection/channel-config shell; GUI-test SIGSEGV fix (offline)

Autonomous overnight session (no operator present; scope explicitly limited to
software-only work per that session's `NEXT_SESSION.md` — see the standing
per-action hardware-authorization rule in `AGENTS.md`, which this session did
not relax). Continuing on `feat/desktop-hardware-threshold` from the previous
(uncommitted) session's work.

**Committed the shared-shell refactor built the previous session** (built
against real Windows vendor-app screenshots, `local_artifacts/app_pics/image
(13-28).png`): `MainWindow` (`src/radioroc/gui/main_window.py`) is the new
app shell — a sidebar ("ASIC config." / "Calibration"), one shared
`ConnectionPanel` (`gui/connection_panel.py`) + `ChannelConfigPanel`
(`gui/channel_config_panel.py`) on the ASIC-config page, and the three scan
workflows (`ThresholdWindow`/`HoldScanWindow`/`ScurveWindow`) as sub-tabs of
Calibration, all sharing one real `ConnectionWorker` instance instead of each
window owning its own connection + channel-config UI. The three scan windows
now accept an injected `connection_worker` (falling back to owning one
standalone, so each remains independently usable/testable) and their
`closeEvent` handling was extended with a third branch: when a
`connection_worker` was injected from outside (not owned by this window),
closing must not shut that shared worker down — it only waits for this
window's own in-flight scan to reach a terminal state, mirroring the existing
SIMULATION-mode close-wait path. `gui/__main__.py` now just constructs
`MainWindow` instead of hand-rolling a `QTabWidget` shell with its own
busy-polling close logic.

**Found and fixed a real, reproducible-but-intermittent SIGSEGV in the test
suite**, along with the previous session (partially fixed then): `QObject::
killTimer: Timers cannot be stopped from another thread`. Root cause: GUI
test teardown called `window.close()` but never `window.deleteLater()`; the
window's leftover Python reference cycle (via Qt signal/slot connections)
could then be collected by Python's *cyclic* garbage collector on any
thread — including a `ConnectionWorker`'s background thread — which crashes
destroying a `QTimer` whose thread affinity is the main thread. Applied the
same `window.deleteLater()` + `app.processEvents()` fix (already used in the
previous session's new `tests/test_connection_panel.py`) to the four
pre-existing GUI test files that shared the identical latent pattern in their
final-teardown path: `tests/test_threshold_gui.py`,
`tests/test_hold_scan_gui.py`, `tests/test_scurve_gui.py`,
`tests/test_connection_gui.py` (each has other `.close()` calls mid-test that
exercise close-while-busy behavior and are not the final teardown, so those
were left alone). Swept the `*_worker.py` test files
(`test_threshold_worker.py`, `test_hold_scan_worker.py`,
`test_scurve_worker.py`, `test_connection_worker.py`) and the session's own
new `test_channel_config_panel.py`/`test_main_window.py`: none construct a
bare `QWidget` without an existing `deleteLater()` path, so no further change
needed there.

**Evidence:** `tools/check_development.py` (242 offline tests + 16 legacy CLI
`--help` checks) run 8 times in a row on `.conda-radioroc`, all clean — no
SIGSEGV, no test failures, no warnings from the killed-timer path.

**Expanded the ASIC-config page with two more of the vendor app's sub-tabs**
(`local_artifacts/app_pics/image (13-16).png`): its "ASIC config." area has
four sub-tabs (Main, input DAC, Threshold calibration, Probes/Masks); only
two were buildable tonight without inventing unconfirmed register mappings —
"Main" (trigger/energy-measurement/gain/threshold settings, `F02`) and
"Threshold calibration" (T1/T2 calibration DAC trims, `F04`) have no backend
support at all in this codebase yet, and guessing at their register layout
autonomously would be exactly the kind of uncertain hardware reasoning this
project reserves for the lead working carefully, not for an unsupervised
overnight pass. The "input DAC" grid and the mask side of "Probes/Masks",
by contrast, are fully backed by already-validated primitives
(`set_input_dac_value`, `set_mask_for_channel`, `set_tq_mask_for_channel`),
so those two were built.

First (shared-contract) step, done directly rather than delegated: extended
`ChannelConfigOperation`/`apply_channel_config`
(`src/radioroc/application/channel_config.py`) with `input_dac_values`
(`dict[channel, code]`, independent per-channel raw DAC codes) and
`tq_mask_states`/`t1_mask_states`/`t2_mask_states` (`dict[channel, enabled]`,
independent per-channel mask bits) alongside the existing uniform
tuple-of-channels-plus-one-value fields — needed because a 64-cell grid
generally holds 64 different values/states in one submit, which the existing
fields couldn't express. Reuses the existing primitives; no new register
mapping, no hardware-reasoning risk. 4 new core tests (10/10 in
`test_channel_config.py`).

Delegated the two grid widgets to parallel agents (each handed the relevant
vendor screenshot, the extended core, and `ChannelConfigPanel` as the pattern
to mirror, with non-overlapping files and explicit hardware/scope
constraints): `InputDacGridPanel` (`gui/input_dac_grid_panel.py`, 64
per-channel `QSpinBox`, a HiZ-impedance checkbox, "All ON"/"All OFF" as the
input-DAC *enable* bit for every channel — documented as a judgment call
since the vendor screenshot doesn't disambiguate what those two buttons
drive) and `ProbesMasksPanel` (`gui/probes_masks_panel.py`, three 64-checkbox
Enable-T1/T2/TQ grids with per-grid Enable-all/Enable-none; the vendor tab's
analog/digital probe *routing* radio groups are explicitly out of scope, same
reasoning as Main/Threshold-calibration above). Both wired into
`MainWindow`'s ASIC-config page as new tabs alongside the existing
`ChannelConfigPanel` (now labeled "Channel config"), sharing the same
injected `ConnectionWorker` as everything else on that page. Reviewed both
agents' output directly against their spec before integrating.

**Evidence:** 260/260 offline tests (14 new panel tests + 4 new core tests),
3 clean full-suite runs. Offscreen-rendered screenshots of both new tabs
(`/tmp/asic_input_dac.png`, `/tmp/asic_probes_masks.png` — not saved into the
repo) show the grids laid out correctly with no overlap, matching the vendor
screenshots' shape. **Not physically validated on hardware** — this session
had no hardware authorization (see above).

**Not done this session:** the hardware-validation item from the previous
handover (physically validating the S-curve GUI path) was explicitly left for
an operator-present session — this session's authorization did not cover
hardware. Main/Threshold-calibration sub-tabs remain unbuilt pending real
register documentation. See a fresh `NEXT_SESSION.md` for what's next.

## RADIOROC 25 — S-curve job migration and GUI tab (offline; physical validation pending)

Same session/branch as RADIOROC 24, continuing immediately after it (not yet a
new chat handoff). Migrated S-curve scans onto the same shared-job architecture
as threshold and hold scans, following the exact pattern established in
RADIOROC 24 — the same day's second application of the same playbook, this
time with no bugs found in the core migration (the delegated test pass reviewed
`scurve.py` line-by-line against the pre-migration function and both sibling
jobs and found none), likely because the register-footprint reasoning from
hold scan directly informed this one.

New `ScurveJob`/`ScurveJobConfig` (`src/radioroc/application/scurve.py`) mirror
`ThresholdJob`/`HoldScanJob`: cancellation (per-DAC-point checkpoint plus the
automatic per-transaction one), durable manifest + `ScurveRunWriter` CSV
(`src/radioroc/data/scurve.py`, single `scurve.csv`, one value per
channel/DAC point — no averaged-attempts concept, unlike threshold), exact
ASIC/FPGA snapshot-restore (registers: `(66,ch)`×64 always, `(65,2)`/`(65,1 or
3)` unconditionally since DAC is this scan's own variable, `(ch,6)`/`(ch,7)`×64
if mask/Ctest used, preamp-gain registers if set; FPGA words `1`/`3`/`6`), and
opt-in restoration verification via the same generalized `verify_restoration`
(`fpga_addresses=(1,3,6)`). `configure_scurve_firmware` (clock index,
trigger-level bit — both persist, matching the module's own "preparation is
intentional, temporary settings are restored" convention already used for
`initialize_fpga`/`apply_defaults`) now runs during preparation, snapshotted
*after* being set — so cleanup restores word 1 to the post-configure baseline,
not the pre-run default; this is deliberate, flagged explicitly by the test
agent for review, and confirmed correct on inspection. Added the same
duplicate-channel check to `ScurveConfig.validate()` that was missing (mirrors
the same gap found and fixed in `HoldScanConfig` during RADIOROC 24).
`ScurveResult` extended with the same status-tracking fields as
`HoldScanResult`. Legacy `RadiorocDevice.run_scurve()` and
`scripts/radioroc_scurve.py` rewired onto the new job (added
`--verify-restoration`, SIGINT-cancellation, matching the other two CLI
scripts' contract exactly).

**GUI layer added** (delegated, reviewed): `ScurveWorker`
(`application/scurve_worker.py`, mirrors `HoldScanWorker`), `ScurveWindow`
(`gui/scurve_window.py`, mirrors `HoldScanWindow` but with S-curve's smaller
config surface — no hold-mode/sync-IO/ADC-timing/gain-override groups, a plain
per-channel turn-on-percentage-vs-DAC plot instead of hg/lg mean+stdev error
bars), a synthetic-but-physically-motivated S-curve simulator
(`transport/scurve_simulator.py`, reusing `ThresholdSimulationTransport`'s
already-validated logistic-curve math rather than inventing new math, since
unlike hold scan's synthetic bump this scan type has a legitimate precedent in
the codebase), a minimal saved-run reader (`data/scurve_reader.py`, same v1
scope reduction as `hold_reader.py`), hardware-mode wiring into
`ConnectionWorker` (additive `run_scurve`/`cancel_scurve` trio, mirroring the
hold-scan trio exactly), and a third "S-curve" tab in the app shell
(`gui/__main__.py`), alongside Threshold and Hold Scan. Curve
fitting/50%-point extraction (`F08`) and data export beyond the durable
CSV/manifest were explicitly scoped out of this pass.

**Evidence:** 222/222 offline tests (46 new: 23 job tests, 9 verification
tests, 8 worker tests, 6 GUI tests) plus 16 CLI `--help` checks, all passing.
GUI launches offscreen with all three tabs; a manual simulated run produces the
expected monotonic turn-on-percentage curve. **Not yet physically validated on
hardware** — RADIOROC 24's hold-scan GUI work was hardware-validated same-day;
this S-curve work has not been, pending the operator's decision on whether to
do that now or move on.

## Next bounded task

Ask the operator directly:
1. Physically validate the new S-curve GUI path on real hardware now (mirrors
   how RADIOROC 24 validated hold scan) — needs a channel/DAC range and
   injection setup the operator picks, following the same
   fresh-authorization-per-action discipline.
2. Or move to the shared connection/channel-config shell once Windows
   vendor-app screenshots arrive (still pending as of this entry).
3. Or something else from `CROSS_PLATFORM_REBUILD_PLAN.md` §3.

## RADIOROC 24 — Hold-scan job migration and first physical GUI hardware validation (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `04054ff774abc35d075c6f7f114f1a6510fbd162`
(clean tree before this run), on a **Raspberry Pi** — the first physical run of this
codebase on Linux. `.conda-radioroc` did not exist on this machine; rebuilt it from
`environment-radioroc.yml` (aarch64) and added `pyvisa-py` (not in the yml, matching
RADIOROC 23's mac session). All four bench instruments confirmed present and
responding: RADIOROC board (`/dev/ttyUSB0` control interface, matching the
`...320`-suffix macOS convention), Aim-TTi TGF4162, Tektronix MSO56B, Keysight
EDU36311A, all reached via `pyvisa`/`pyusb`.

**First-boot anomaly, resolved:** an initial read-only board status check returned
non-protocol garbage (`f7 ff c0 00 00 ...`, not the documented `AA...55` frame) on
two separate attempts via two different code paths (raw `pyserial`, VISA ASRL).
Root cause was not a Linux/driver issue: the PSU's CH1 5V/1A rail was off (matching
how RADIOROC 23 left it), so the board was running on USB power only. Enabling CH1
(operator-authorized) fixed it immediately — `radioroc_check_connection.py` then
returned the expected `00000101 (5)`, matching the known-good macOS value.

**Preset-defaults bug found and fixed, then swept project-wide.** Running the
known-good external track-and-hold Ctest config
(`configs/presets/hold_external_track_ctest_ch4.json`, `hold_min=440,
acquisitions=30`) produced a scan that used `hold_min=0, acquisitions=10` instead —
silently wrong, no error. Root cause: `apply_preset_defaults()` (`radioroc_cli_common.py`)
applies a preset via `parser.set_defaults(**preset)`, but any `add_argument(...,
default=X)` call for the same field always wins over an earlier `set_defaults()` in
argparse, regardless of call order — so any preset field whose CLI flag also carried
a hardcoded default was silently dropped. Fixed in `radioroc_hold_scan.py` by
removing the redundant hardcoded defaults and adding explicit `None`-fallback
resolution after `parse_args()` (per the operator's explicit choice over reordering
the `apply_preset_defaults()` call). A follow-up audit (delegated) swept all 7 other
scripts using the same helper (`apply_defaults`, `sync_pulse`, `acquire`,
`io_mux_scan`, `threshold_scan`, `scurve`, `channel_config`) and found the identical
defect in all of them — two were live, not just latent: `sync_pulse`'s `pulses`
default (1000) was silently overriding its preset's `100`, and `acquire`'s
`threshold_dac` default (530) was silently overriding its preset's `100`. Also
closed the same gap in the shared `add_connection_args`/`add_write_safety_args`
helpers (`port`/`baud`/`timeout`/`config`), previously flagged but unfixed by the
audit as a broader cross-cutting change — fixed centrally in
`connection_config_from_args`/`prepare_device` plus the two scripts
(`hold_scan`/`threshold_scan`) that read `args.config` directly. Verified with a
synthetic preset overriding port/baud/timeout end-to-end.

**Hold scan migrated onto the shared-job architecture** (previously only threshold
scans had this rigor; hold scan was still a synchronous legacy function). New
`HoldScanJob`/`HoldScanJobConfig` (`src/radioroc/application/hold_scan.py`) mirror
`ThresholdJob` exactly: cooperative cancellation (checkpointed per hold point, plus
automatically on every `read_word`/`write_word`/FIFO call via `device._job_checkpoint`),
a durable JSON manifest + CSV writer (`HoldRunWriter`), an exact pre-scan ASIC/FPGA
snapshot-restore (register footprint: `(66,ch)`×64 always, `(ch,6)`/`(ch,7)`×64 if
mask/Ctest used, gain/preamp/threshold-DAC registers if set; FPGA words
21/22/23/24/25/26/27/30/31/77/78), and opt-in independent restoration verification.
Generalized `verify_threshold_restoration` → `verify_restoration`
(`application/verification.py`) to take an explicit `fpga_addresses` parameter
instead of a hardcoded `(0,1,6)`, so both jobs share it — caught and fixed a real
bug while doing so: the verifier's word-0 restore-around-FIFO-read step assumed `0`
was always in the caller's own address set, which would `KeyError` for hold scan's
different footprint. `HoldScanResult` extended with the same status-tracking fields
`ThresholdScanResult` already had (`status`, `cleanup_status`, `cleanup_errors`,
`persistence_errors`, `error`, `execution_mode`, `verification`). Legacy
`RadiorocDevice.run_hold_scan()` and `scripts/radioroc_hold_scan.py` rewired onto
the new job (added `--verify-restoration`, SIGINT-cancellation, matching
`radioroc_threshold_scan.py`'s CLI contract exactly).

A delegated test pass (`tests/test_hold_scan_jobs.py`,
`tests/test_hold_scan_verification.py`, 33 tests, fake ADC-batch transport) found
one more real bug before any hardware ran: `HoldScanJobConfig.registers()` omitted
the ASIC threshold-DAC registers `(65,2)`/`(65,1 or 3)` even when `scan.threshold_dac`
was set, so any hold scan with an explicit threshold DAC would silently leave it
unrestored after cleanup with no error or verification mismatch reported. Fixed
(mirrors `ThresholdJobConfig.registers()`, which already covered this). Also added
the missing duplicate-channel check to `HoldScanConfig.validate()` (present on
`ThresholdScanConfig`, absent here) and fixed `radioroc_hold_scan.py` validating
outside its `try` block (unhandled traceback on bad input instead of a clean error).

**GUI layer added** (delegated, reviewed): `HoldScanWorker`
(`application/hold_scan_worker.py`, mirrors `ThresholdWorker`), `HoldScanWindow`
(`gui/hold_scan_window.py`, mirrors `ThresholdWindow`), a synthetic (explicitly
non-physics-validated) hold-scan simulator (`transport/hold_scan_simulator.py`), a
minimal saved-run reader (`data/hold_reader.py`, a deliberate v1 scope reduction vs.
`threshold_reader.py`'s full fault-tolerance), hardware-mode wiring into the
existing `ConnectionWorker` (additive only, existing threshold path untouched), and
a `QTabWidget` shell (`gui/__main__.py`) hosting both workflows as independent tabs.
While driving it live with the operator, found and fixed one more gap: the window
had no field for `sync_io`/`sync_io_mux_index` — without it, the FPGA sync trigger
routing to the signal generator (`IO1` mux index `5` in this bench setup) could only
work by coincidence, relying on whatever the mux happened to already be set to.
Added the missing controls. (Initially misdiagnosed the fault-review workflow as a
second bug — reverted that: `Disconnect` → `Acknowledge fault review` →
`Connect` is the intended sequence, not a stuck button; the review action is
correctly restricted to non-connected states, and disconnect is already enabled
while faulted.)

**Physical confirmation:** CLI hold scan via `RadiorocSerial`/`RadiorocDevice`
directly (first with the still-buggy defaults — clean shape but noisier, 10
acquisitions; then corrected — 21 points, 440-640ns, 30 acquisitions), then the
**first-ever physical hardware run through the new GUI path**: 21/21 points,
`status: completed`, `cleanup: restored`, `verification: passed`, peak
796-798 at hold_delay 500-550ns falling to baseline ~127 by 440-450ns and ~299 by
640ns — matching the CLI run and the 2026-06-26 known-good shape closely (peak
location and baseline both consistent). Generator config from RADIOROC 23
(PULSE, 100ns, external-triggered single-cycle burst, `AMPL 1.0`/`ZLOAD OPEN`,
20dB attenuator into `in_test1`/Ctest) re-applied and confirmed with `EER?` after
every write before the first CLI run.

**Known gap, deferred:** the operator noted that `ThresholdWindow` and
`HoldScanWindow` each own an independent connection/channel-config panel instead of
sharing one — exactly the "one shell, one connection" architecture
`CROSS_PLATFORM_REBUILD_PLAN.md` M3 already calls for but was never actually built
that way. Deferred pending Windows vendor-app reference screenshots the operator
will provide, so the shared page is designed against the real reference UI rather
than guessed.

**Evidence:** all 176 offline tests + 16 CLI `--help` checks pass after every
change (re-verified repeatedly through the session, including after the final
connection-args fix). No hardware scans run as CI/offline tests, per standing
policy — every hardware-touching step above was interactively authorized.

## Next bounded task

Two independent options, operator's choice:
1. Design and build the shared connection/channel-config shell once Windows
   vendor-app screenshots are available (`ThresholdWindow`/`HoldScanWindow` each
   currently duplicate this instead of sharing one connected session).
2. Continue the feature-parity backlog (`CROSS_PLATFORM_REBUILD_PLAN.md` §3) with a
   slice independent of the shared-shell work, e.g. S-curves GUI (`F07`, core/CLI
   exists, no GUI yet) or full DAQ trigger/visualization (`F11`-`F13`).

Whichever is chosen, keep the same discipline: fresh authorization per hardware
action, stop on any implausible result, record commit/checks/limitations here and
in `NEXT_SESSION.md` at the next handoff.

## RADIOROC 23 — First Stage D signal-injection confirmation (PASSED)

Continuation on `feat/desktop-hardware-threshold` at
`10ae3060a3469a2892770044ffd47d0de088488c` (clean tree before this run), on a
lab machine with the RADIOROC board, a Tektronix MSO56B oscilloscope, a
Keysight EDU36311A power supply, and an Aim-TTi TGF4162 signal generator all
connected over USB. Reached over VISA (`pyvisa` + `pyvisa-py`, installed this
session; USBTMC via `pyusb`/`libusb`, already present).

**DSO housekeeping (prerequisite):** the scope's disk was full enough that
`SAVe:SETUp` failed with "insufficient space." Investigation found the large
data trees (`cryo`, `triplecoin`, ~532k PNGs total) are unrelated prior
projects (SiPM cryo/gain characterization, a muon coincidence search), each
PNG paired with a same-timestamp `.wfm` binary, not a `.csv` as first assumed.
With the operator's scope narrowed to `cryo` only, verified pairing by
per-folder PNG/WFM count equality plus sub-second timestamp proximity (not
filename match — the two files' timestamps differ by tens to hundreds of ms),
flagging any folder that didn't cleanly satisfy both checks. Deleted PNGs in
small throttled batches (batch of 5, `*OPC?` sync, sleep between batches);
this still triggered two real USB faults (an `I/O Error` and the scope fully
dropping off the USB bus once, self-recovering after the operator power-cycled
it) — no data loss in either case, `.wfm` counts verified intact throughout,
and deletion paused rather than retried aggressively. Final count: **11,388
PNGs deleted** out of 24,216 identified as safe; the disk-space fault is
resolved (`SAVe:SETUp` now succeeds; `komal_20260918.set` saved for the other
user). Untouched: `triplecoin` entirely, one folder with a PNG/WFM count
mismatch, and the remainder of the largest `cryo` folder.

**Power supply:** the vendor user guide (`local_artifacts/downloads/Radioroc2
User Guide - 2_1_0_6(0125).pdf`, section 2) confirms the board needs an
external 5V/1A supply at its top-right connector in addition to USB — this
was the reason the operator asked for the PSU, not SiPM bias. Configured and
enabled CH1 at 5V/1A; measured draw 306 mA (healthy, not current-limited).

**Signal generator:** the TGF4162's SCPI command set (fetched from Aim-TTi's
published `TGF4000_Series_Instruction_Manual-Iss3.pdf`) has no query form for
most settable parameters (`WAVE`, `AMPL`, `PULSWID`, `BST*`, `OUTPUT`, `ZLOAD`
are set-only on this firmware; only `CHN?`/`CLKSRC?`/`CNTRVAL?`-style commands
query); verification instead used the `EER?` execution-error register after
every write. Applied the "known lab setup" documented in `README.md` /
`REFACTOR_CHECKLIST.md`: PULSE waveform, 100 ns width, external-triggered
single-cycle burst (trigger source = FPGA `IO1` at mux index 5), output
through the existing 20 dB attenuator into `in_test1`/Ctest.

**Physical confirmation (first Stage D physical result under this rebuild):**

1. Ran `hold_mux_index.py io1 5` (the RADIOROC 15/22 script, reused as-is)
   with the DSO in single-sequence acquisition, edge-triggered on the actual
   pulse: exactly **3000/3000** triggered acquisitions matched the script's
   3000 commanded FPGA sync pulses — unambiguous proof the generator fires
   reliably on every real sync pulse, not just occasionally.
2. Pulse width from that same clean single-shot capture: **100.05 ns** —
   matches the documented 100 ns spec almost exactly.
3. Amplitude required one correction: the generator's `ZLOAD OPEN` setting
   means `AMPL` is an open-circuit value, and an earlier T-split to a 1 MΩ
   DSO tap was independently distorting the fast edge (reflections off the
   unterminated stub). Setting `AMPL 1.0` (compensating for the halving a
   real 50 Ω load causes) and terminating the DSO channel in true 50 Ω (no
   T-split — direct connection) gave a stable **~49-50 mV peak-to-peak**
   reading across multiple samples taken *during* an active burst, matching
   the documented ~50 mV post-attenuation spec.

Evidence is local under
`radioroc_runs/physical_stage_d_first_pulse_20260918/` (the reused hold
script, its console logs across several runs). No push or change to `main`
occurred. At handoff: signal generator output OFF, PSU CH1 output OFF, board
still on USB (data only, no external 5V rail) — a safe idle state before
switching to a different physical machine (Raspberry Pi) for the next
session.

**Not established:** the actual Stage D measurement itself. This session
confirmed the *injection setup* works; the proposed next action — a
`radioroc_hold_scan.py --execute --preset
hold_external_track_ctest_ch4.json` run (the same known-good external
track-and-hold Ctest configuration from the 2026-06-26 logbook, channel 4,
threshold DAC 250, 440-640 ns hold sweep) — was authorized in discussion but
not yet run before the session ended. Also not established: why the
generator's amplitude reading was initially so unstable across trigger/scope
configurations before landing on the 50 Ω/single-sequence method; the root
cause of the two DSO USB faults during batch deletion.

## RADIOROC 22 — IO0 sync-pulse characterization (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `dfc8d339ee5ab950cbdb5d31108fd7f9b63cea5d`
(clean tree before this run). The operator moved the oscilloscope from IO1
to IO0 and asked to characterize it the same way. The fast automated
`radioroc_io_mux_scan.py --sync-io io0` sweep (run twice) made it hard to
attribute a signal to a specific mux index, so a new script,
`hold_mux_index.py <io_name> <index>` (generalizing RADIOROC 15's
single-purpose `hold_mux_index5.py`), held each of the 8 indices
individually for ~15 s while the operator watched.

Result: indices 0-3 showed nothing; indices 4, 6, and 7 showed a static
baseline-level shift with no pulsing (a real, repeatable but unexplained
effect — not investigated further this session); **index 5 showed real
pulses**. A longer hold at index 5 (~30 s) let the operator measure
amplitude: **1.44 Vpp, ~10 ms apart** — matching IO1's RADIOROC 16 result
almost exactly, at the same mux index. This is now independent Stage-C
evidence from a second signal path, both consistent with mux index 5
selecting the same internal synchro-trigger signal regardless of which
physical IO line it's routed to.

Evidence is local under `radioroc_runs/physical_scope_io0_20260914T044151Z/`.
Full narrative in `docs/hardware/stage_c_io_sync_validation.md` under "IO0
characterization (RADIOROC 22)". No push or change to `main` occurred.

Not established: what the indices 4/6/7 baseline shift actually corresponds
to internally; io2-io4; the documented `IO_FPGA6`/`IO_FPGA7` SMA connectors;
pulse width/rise-time; an untermination-corrected (open-circuit) amplitude.

## RADIOROC 21 — First physical validation of the GUI channel-config panel (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `7e9174d3b8ce393802bd3fbf9587150666672ceb`
(clean tree before this run). With the board confirmed powered/bare and
competing software closed, the user authorized driving the actual desktop
GUI (not the CLI script) through Connect -> the new "Input DAC / TQ mask"
panel with Restore checked -> Disconnect: TQ mask channel 4, input DAC value
200 on channel 4, impedance switch to low.

**Passed on the first attempt.** A new harness
(`radioroc21_gui_channel_config_card.py`, modeled on the RADIOROC 07/12/13/14
GUI harnesses) drove `ThresholdWindow` directly: connected (status 5),
filled in the panel fields exactly as authorized, clicked Apply, and watched
the worker transition `connected -> configuring -> connected` cleanly (no
fault). The published `channel_config_snapshot()` result matched RADIOROC
19's CLI outcome exactly: 65 rows touched, 0 verify mismatches, restored,
0 restore mismatches. Explicit Disconnect and worker shutdown both completed
normally. Evidence (15 files: screenshots at each step, event/console logs,
`terminal_summary.json`, `source_provenance.json`) is local under
`radioroc_runs/physical_gui_channel_config_20260914T041722Z/`.

This closes the one gap left open by RADIOROC 20: both the CLI and the GUI
paths through the shared `channel_config` core now have independent physical
evidence, using the same authorization and evidence discipline as every
other physical card in this project. No push or change to `main` occurred.

Next: with the designated operator, decide the next hardware slice — extend
Stage C (other IO lines, pulse width/amplitude follow-up) or move to Stage D
if a pulse generator is available, or continue with deferred non-hardware
items (persistent defaults/FPGA init, branch/CI review, Windows-parity
inventory).

## RADIOROC 20 — Input DAC/TQ mask GUI wiring (offline)

Non-hardware work, at the operator's request to finish GUI wiring alongside
the CLI. Refactored first: the CLI script's inline apply/verify/restore logic
moved into a new shared core, `src/radioroc/application/channel_config.py`
(`ChannelConfigOperation`, `ChannelConfigResult`, `apply_channel_config`),
matching this project's stated "shared core for both UI and CLI" principle
instead of duplicating the logic a second time for the GUI.
`scripts/radioroc_channel_config.py` now calls this shared function; its
dry-run output is byte-identical to before the refactor.

The shared core also fixed a real gap: unlike the CLI (which loads the ASIC
config table via `prepare_device`), the GUI's `ConnectionWorker` never loaded
`device.i2c_rows` at all, so a channel-config write from the GUI would have
silently no-opped (`find_i2c_row` returns `None` on an empty table, and the
RADIOROC 17 setters return early without writing or raising). Added
`ChannelConfigOperation.load_rows`/loading step (mirroring
`ThresholdJobConfig.load_rows`'s exact convention: reuse already-loaded rows,
or load the packaged default CSV) so this now works correctly from either
caller.

`ConnectionWorker` gained a new `"configuring"` busy state,
`apply_channel_config(operation)`, and `channel_config_snapshot()`, mirroring
`read_status`'s shape: on success, published `"connected"` with the result
stored; on a verify/restore mismatch, latches a fault and publishes
`"faulted"` (same "any fault blocks further work until reviewed and
disconnected" policy as threshold-job faults) — not silently reported.

`ThresholdWindow` gained a new "Input DAC / TQ mask (persists unless Restore
is checked)" group box: a shared channel selector, TQ mask/input-DAC-enable/
input-DAC-value checkboxes with value controls, a global impedance combo, a
"Restore after (bounded validation, does not persist)" checkbox, an Apply
button, and a status label reporting applied writes plus verify/restore
results. The persistence framing intentionally matches this codebase's
existing "(persists)" labels on `initialize`/`defaults`. The panel is only
enabled when connected, idle, and fault-free, reusing the exact same
condition as the existing "Run hardware threshold" button.

Tests: `tests/test_channel_config.py` (6, offline core logic against a fully
round-tripping fake ASIC transport — including a genuine forced-mismatch
case, not just the happy path), 2 new `tests/test_connection_worker.py`
cases (apply/verify/restore through the real threaded worker; a mismatch
correctly faults and blocks further commands until disconnect+review), 2 new
`tests/test_connection_gui.py` cases (button enable state, operation
construction from widget state, status text, and input validation before
submission). Full suite: 129 tests pass. The panel was also visually
verified by rendering the real window offline (screenshots, no hardware) —
layout, labels, and the disabled-when-disconnected Apply button all confirmed
correct.

Not done: physical validation of the new GUI path specifically (RADIOROC 19
validated the CLI path only). No push or change to `main` occurred.

## RADIOROC 19 — First physical validation of input DAC/TQ mask (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `3e9e188c3aadeb68d7e85d1df1778906ea245ae8`
(clean tree before this run). With the board confirmed powered/bare and
competing software closed, the user authorized the bounded first card:
`scripts/radioroc_channel_config.py --execute --skip-fpga-init --tq-mask 4
--tq-mask-value 1 --input-dac-value 4 --value 200 --input-dac-impedance low
--verify --restore`.

**Passed on the first attempt.** Firmware status word 5. All three writes
(TQ mask on channel 4, input DAC value 200 on channel 4, impedance switch to
low across all channels) independently read back correctly via a real
hardware I2C read (65 touched rows, 0 mismatches) — not just trusting
in-memory state. All 65 rows were then restored to their pre-run values and
independently re-verified (0 mismatches). This is the project's first
physical evidence for the RADIOROC 17 register mapping (input DAC
value/enable/impedance, TQ mask), recovered from the vendor's compiled GUI
bytecode. Evidence is local under
`radioroc_runs/physical_channel_config_20260914T035857Z/`. No push or change
to `main` occurred.

Not established by this run: input DAC enable (only value/impedance/TQ mask
were exercised; enable uses the same mechanism and register, so risk is low,
but it hasn't specifically been run), behavior without `--restore` (a
genuinely persistent change, which is the eventual real-world use case for
input DAC calibration), or GUI wiring.

## RADIOROC 18 — Input DAC/TQ mask CLI wiring (offline)

Continuation of RADIOROC 17's non-hardware work, following the existing
`scripts/radioroc_*.py` package pattern (`radioroc_cli_common`'s shared
connection/write-safety args, preset loading, `prepare_device`) exactly as
`radioroc_apply_defaults.py` does. New script:
`scripts/radioroc_channel_config.py`, exposing all four RADIOROC 17 methods:
`--tq-mask`/`--tq-mask-value`, `--input-dac-enable`/`--input-dac-enable-value`,
`--input-dac-value`/`--value`, `--input-dac-impedance {low,high}` (channel
selectors reuse the existing `parse_channels` syntax: `4`, `0-15`, `all`).

These are configuration-state writes meant to persist, like
`apply_defaults`/`initialize_fpga` — not transient scan settings that
auto-restore. The script defaults to persisting (same as `apply_defaults`)
and adds an explicit `--restore` flag for bounded validation runs: snapshot
every touched register before writing, then write, then (with `--verify`)
independently read back and compare against the in-memory expected value,
then (with `--restore`) write the snapshot back and independently verify
that restoration too. `--verify` performs a real hardware I2C read in
`--execute` mode (not just trusting the in-memory row state), matching this
project's established independent-verification discipline.

Offline-only: `--execute` was never passed. Dry-run smoke tests exercised
every option combination (missing-argument errors, out-of-range `--value`
raising cleanly, a combined `--tq-mask`+`--input-dac-value`+
`--input-dac-impedance --verify --restore` run reporting 65 touched rows, 0
mismatches, 0 restore mismatches). Full test suite unchanged at 119 passing;
no dedicated CLI-script test file was added, matching this repo's existing
convention that `scripts/radioroc_*.py` CLI entry points aren't unit-tested
directly (their underlying `RadiorocDevice` methods are, in
`tests/test_radioroc_core.py`). No hardware was touched; no push or change
to `main` occurred.

Not done: GUI wiring (a separate, larger scope decision — not started without
checking first) and any physical validation of these four methods or this
script (would be the first hardware evidence for either control).

## RADIOROC 17 — Input DAC and TQ mask: register mapping recovered, implemented offline

Non-hardware work while the operator was away. Two of Stage B's previously
"no existing code" gaps — per-channel input DAC value/enable/impedance and
the TQ mask — had no register-level specification anywhere in this repo (the
vendor user guide describes the UI behavior but not register bits, and the
existing `*_pydisasm.txt` notes for `ndevice`/`device`/`i2c` don't cover
them). Guessing register bits for real hardware writes was rejected as too
risky; instead, the lead recovered the mapping directly from the vendor
application's own compiled bytecode.

The vendor's PyInstaller-extracted `.pyc` files carry a Python 3.13-era
marshal format that the current interpreter (3.13.14) loads and disassembles
natively (`marshal.load` + `dis`), so no decompiler was needed. Searching
`radioroc2UI.pyc`'s `Ui_MainWindow.setupUi` (the Qt-Designer-generated widget
layout) for the relevant widget names found each control's register mapping
encoded as literal `setProperty(add=..., subadd=..., nbbits=..., position=...,
all_channels_add=..., all_channels_subadd=...)` calls, and `uiroc/i2c.pyc`'s
`set_value` docstring gives the authoritative convention: `position` is the
**LSB-numbered** bit position in the register byte. Recovered mapping (all on
the existing per-channel `(channel, 6)` register except the DAC value):

| Control | Vendor `position` (LSB) | This codebase's row-string index (MSB-first) |
|---|---|---|
| T1 mask (existing `set_mask_for_channel`) | 4 | 3 |
| T2 mask (existing `set_mask_for_channel`) | 3 | 4 |
| TQ mask (new) | 2 | 5 |
| Input DAC enable (new) | 6 | 1 |
| Input DAC impedance (new, `all_channels_add=True`: written identically to channels 0-63) | 7 | 0 |
| Input DAC value (new, register `(channel, 0)`, `nbbits=8`) | 0 (whole byte) | whole byte |

The T1/T2 rows are not new discoveries — they're a cross-check: the vendor's
own `position=4`/`position=3` convert to string indices 3/4 exactly matching
`set_mask_for_channel`'s already hardware-validated bit choices (RADIOROC
07/12/13), which is why the new TQ/input-DAC bits are recorded with
reasonable confidence rather than as a guess, while still being explicitly
**not yet independently verified against real hardware**.

Implemented in `radioroc_client.py`: `set_tq_mask_for_channel`,
`set_input_dac_enable_for_channel`, `set_input_dac_impedance`,
`set_input_dac_value`, mirroring `set_mask_for_channel`/`set_ctest_for_channel`'s
existing style exactly (each is a no-op if the loaded config lacks the target
row, same as the existing methods). One new offline test,
`test_tq_mask_and_input_dac_bit_positions` in `tests/test_radioroc_core.py`,
exercises all four against `RadiorocMemoryTransport`/dry-run, including value
validation (`0..255`) and confirming untouched bits on the shared register are
left alone. Full suite: 119 tests pass (`python -m unittest discover -s
tests`). No hardware was touched; `pip install decompyle3` (unused in the
end — wrong Python era) and `brew install poppler` (used earlier, RADIOROC
15) are local environment additions, not repo changes.

Not done: CLI script and GUI wiring for these four methods (the plan requires
every control to be reachable from API, CLI, and GUI — this is API-only so
far), and any physical validation. Both are natural next steps once the
operator wants to authorize a bounded card for them — this needs its own
review before hardware access, same as every other new capability.

## RADIOROC 16 — IO1 sync-pulse amplitude follow-up (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `88974e7584b13f6a026bfa880c9bb7f586b68d04`
(clean tree before this run). With the oscilloscope already connected from
RADIOROC 15, the operator held `io1` at mux index 5 again
(`hold_mux_index5.py`, 3000 pulses; measured mean period again ~12.62 ms,
consistent with RADIOROC 15) and read the pulse amplitude.

First reading: **14.4V under 50-ohm termination** — about 6x the vendor
guide's documented "2.5V TTL" figure for the board's FPGA sync connectors,
and suspiciously close to a 10x multiple of a plausible value. Rather than
record this as a real 14.4V signal, the operator checked the scope channel's
probe-attenuation setting: it was **10X** while the physical connection was a
direct 1x cable. Corrected amplitude: **14.4V / 10 = 1.44V** under 50-ohm
termination.

This ~1.44V figure doesn't exactly match the vendor guide's 2.5V TTL number
either, but that number is documented for a different, separately-named
connector pair (`IO_FPGA6`/`IO_FPGA7`), not confirmed to be the same signal
path as `io1`'s mux-selected output, and 50-ohm termination can load a
non-negligible-impedance source down from its open-circuit level. Recorded as
the current empirical reading, not as a contradiction requiring further
action right now. Evidence is local under
`radioroc_runs/physical_scope_amplitude_20260914T030258Z/`. Full narrative in
`docs/hardware/stage_c_io_sync_validation.md` under "Amplitude follow-up
(RADIOROC 16)". No push or change to `main` occurred.

Next: with the designated operator, decide whether to keep extending Stage C
(other IO lines, pulse width/rise time, an untermination-corrected reading)
or move toward Stage D (pulse generator, per
`CROSS_PLATFORM_REBUILD_PLAN.md` section 5) — a materially bigger step
requiring an attenuator and actual signal injection into the ASIC, needing
its own setup review before authorization.

## RADIOROC 15 — First Stage-C oscilloscope validation (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `af90e576c59de4586273c14930d7c0e116544bee`
(clean tree before this run). The operator connected an oscilloscope to the
board's IO1 output (bottom-right corner) — the project's first move from
Stage B (bare board, USB only) to Stage C (oscilloscope/probe). No signal
generator or injection is involved; this is a passive observation only, so no
attenuator was needed.

Reran RADIOROC 14's `scripts/radioroc_io_mux_scan.py --execute --sync-io io1`
sweep (mux indices 0-7) while the operator watched the scope, then a small
new script (`hold_mux_index5.py`) isolated mux index 5 so the operator had a
stationary target to observe, mirroring `pulse_synchro_trigger`'s exact write
sequence and restoring the original mux state afterward.

The operator's first observation (~500 ms apparent pulse spacing) was 50x off
the requested 10 ms period. Rather than guess, the script was instrumented to
independently measure the actual `write_word`-level pulse timing: **12.66 ms
mean period** (min 10.31, max 15.36) — confirming the code/hardware side was
correct and ruling out a timing bug. The discrepancy was attributed to the
oscilloscope's own trigger/timebase configuration; after the operator
adjusted it, they confirmed pulses genuinely ~10 ms apart, matching both the
request and the independent measurement.

This corroborates a 2026-06-26/2026-06-29 logbook finding (IO1, mux index 5 =
verified sync output) on the **current** board/software, addressing the
plan's own caution against trusting historical wiring notes blindly. Evidence
is local under `radioroc_runs/physical_scope_20260914T025434Z/`. Full
narrative in the new `docs/hardware/stage_c_io_sync_validation.md`.

Not established: exact voltage/amplitude (no independent voltage reading was
taken), pulse width/signal integrity, or any other FPGA IO signal (io0,
io2-io4, or the separate `IO_FPGA6`/`IO_FPGA7` SMA connectors). No push or
change to `main` occurred.

Next: with the designated operator, decide whether to extend Stage-C work
(other IO signals, voltage/amplitude measurement, timing on a second scope
channel) or move toward Stage D (pulse generator) for S-curve/hold-scan
signal-response validation, per `CROSS_PLATFORM_REBUILD_PLAN.md` section 5.

## RADIOROC 14 — Stage-B completion sweep (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `e08c0819104099ce90ffa08582909e51ba8d9415`
(clean tree before this run). The user asked to finish every remaining
Stage-B item (bare board over USB only, no new equipment) in one session,
authorized the whole day's work, and separately confirmed including a
first-ever forced-trigger ADC acquisition while explicitly deferring
persistent defaults/FPGA initialization to a later session.

**Part 1 (GUI, `ConnectionWorker`/`ThresholdJob` path):** a new sweep card
(drafted by a coding sub-agent, reviewed before running) exercised four
dimensions no prior physical case had touched: Ctest enabled, non-zero
trigger preamp gain (32), a wider/coarser DAC sweep (0..1000 step 100, 11
points), and all 64 ASIC channels in one scan. All four passed with
`cleanup=restored` and `verification.status=passed` (exact match), using the
same live pre-scan-snapshot verifier as every prior card — independently
re-confirmed by reading `threshold.py` that Ctest/gain variation doesn't
change what "expected" restoration means. Evidence (57 files) is local under
`radioroc_runs/physical_sweep_20260914T020107Z/`.

**Part 2 (CLI tools, not on the GUI job path):** HG/LG shaper gain codes, a
first-ever forced/synchro-triggered ADC acquisition (40 real events, channel
4, plausible bare-board noise-floor HG/LG values, no detector attached), and
an FPGA IO-mux readback/restore — via the existing `scripts/radioroc_acquire.py`
and `scripts/radioroc_io_mux_scan.py`, wrapped in a new script that adds an
independent before/after register-readback check neither tool has built in.
A first attempt stopped before any hardware write on a wrapper bug (`read_word`
returns a bit-string, compared directly against an int); fixed and rerun
under the same authorization. The rerun passed: independent readback matched
exactly before and after both subprocess calls. Evidence (7 files) is local
under `radioroc_runs/physical_cli_20260914T020329Z/`.

Full narrative in the new `docs/hardware/stage_b_completion.md`. Not
attempted: applying persistent defaults/FPGA init (item 7, deferred by
explicit operator choice) and per-channel input DAC/impedance, a TQ mask, and
USB self-test writes (no existing code for any of these — real feature
development needed first, not just a test card). With this session, every
Stage-B item with existing, non-persistent-change code now has physical
evidence. No push or change to `main` occurred.

Next: remaining work needs either Stage C/D/E equipment (oscilloscope, pulse
generator, or SiPM — see `CROSS_PLATFORM_REBUILD_PLAN.md` section 5) or is
non-hardware (persistent-defaults card design, the input-DAC/TQ-mask feature
gaps, branch/CI review, Windows-parity inventory).

## RADIOROC 13 — First physical multi-channel threshold scans (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `df606cf0c5ba0b2a0d32c823dca5327038abbe38`
(clean tree before this run). With the board confirmed powered/bare (no
SiPM/pulser) and competing software closed, the user authorized two new T1
scans reusing the RADIOROC 07/12 conservative settings but varying the
`channels` field beyond the single hardcoded channel (4) every prior physical
case used: adjacent channels `[4, 5]`, then boundary channels `[0, 31, 63]`
(first, middle, last of the 64-channel ASIC). The lead wrote a small new
harness adapted from the RADIOROC 07/12 script and was sole software operator.

A first attempt stopped on a mismatched expected `attempts` count in the new
harness itself (attempts scale as `channels x DAC points`, not just DAC
points) — the board's own scan, cleanup, and verification were unaffected and
the session closed cleanly. The harness was corrected and rerun immediately
under the same authorization/settings (no new physical scope). Both cases
then passed: `cleanup.status == "restored"` and `verification.status ==
"passed"` (exact FPGA/ASIC match) for channels `[4, 5]` and for `[0, 31, 63]`,
with a populated rate column per channel in each saved CSV. Source hashes
confirm no code change from RADIOROC 12. Evidence is local under
`radioroc_runs/physical_multichannel_20260914T013419Z/` (failed harness
validation, board state unaffected) and
`radioroc_runs/physical_multichannel_20260914T013527Z/` (passed). Full
narrative in `docs/hardware/desktop_threshold_validation.md` under "RADIOROC
13 multi-channel execution record".

This is the first physical evidence that multi-channel scans work correctly,
including at the ASIC's channel-index boundaries. Not covered: channels other
than 0, 4, 5, 31, 63; more than 3 channels in one scan; wider DAC ranges; or
any cancellation/close-during-run case with multiple channels. No ASIC/FIFO
misuse, defaults, repair, power-cycle, push, or change to `main` occurred.

Next: with the designated operator, choose the next bounded hardware slice —
for example a modest wider-range DAC scan, or moving toward first detector
(SiPM) connection (which needs a new safety card, not just a rerun) — or pivot
to non-hardware backlog items (branch/CI review, Windows-parity inventory).

## RADIOROC 12 — Desktop threshold validation card complete (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `33fb47a26323b6babc29ff8b8b717abd4fcdb81f`
(clean tree before this run). With preconditions confirmed (powered bare
board, no SiPM/pulser, no competing software) and explicit authorization to
run `docs/hardware/desktop_threshold_validation.md`'s full case set exactly as
written, the lead reran the unmodified RADIOROC 07 harness
(`radioroc07_gui_card.py`, byte-identical) as sole software operator.

All five required cases passed: `t1_normal`, `t2_normal` (2/2 points each, as
before), and — the exact scope RADIOROC 07 never reached —
`t1_cancel_window` (cancel during a 60000 ms window), `t1_cancel_after_point`
(cancel after one persisted point, 1000 ms window), and `t1_close_window`
(native window closed mid-scan, 60000 ms window). Every case reported
`cleanup.status == "restored"` and `verification.status == "passed"` with
empty mismatches/missing/errors against the expected FPGA words 0/1/6 and all
130 ASIC snapshot rows; the harness itself raises on any mismatch, so these are
checked results, not self-reports. The worker reached `stopped` cleanly with
no `close_failed` state at any point. `source_provenance.json` for this run
confirms the transport/threshold-job source is unchanged from RADIOROC 07, so
the successful outcome is attributable to the board/bridge recovery
(RADIOROC 11), not a code change.

Evidence (77 files) is local and ignored under
`radioroc_runs/physical_desktop_20260911T075002Z/`. This completes the
desktop threshold validation card's required case set for the first time.
Not covered: wider DAC/scan ranges, Ctest/gain variation, FPGA
initialization/defaults, or any detector (SiPM/pulser) connection — the board
remained bare throughout, and each of those needs its own bounded,
separately authorized card. No push or change to `main` occurred.

Next: with the designated operator, decide the next bounded hardware slice —
for example a small wider-range DAC scan, or moving toward first detector
(SiPM) connection — and get fresh, exact-scope authorization before running
it, following the same discipline as RADIOROC 09-12.

## RADIOROC 11 — Evidenced status-only re-verification (PASSED)

Continuation on `feat/desktop-hardware-threshold` at `b4706777fed7a8380dc5baa8f84dc683cb630a62`
(clean tree before this run; no source changes). The user confirmed the board
powered/bare with no SiPM/pulser and closed the manual GUI session used for
their earlier power-cycle test, then authorized exactly the existing
status-only sequence (refresh/select, Connect, one gated repeat, explicit
Disconnect, shutdown; stop on any error/unexpected value). The lead acted as
sole software operator.

Before Connect, `system_profiler SPUSBDataType` (no port opened) confirmed
`PCB_RADIOROC` / `RD3_32` still enumerated. The lead then reran the unmodified
RADIOROC 09 harness (`status_card.py`, same hash as before) against a new
output directory. Result: **passed**. Status-100 read #1 at
`07:09:24.140-07:09:24.154 UTC` and read #2 at `07:09:24.247-07:09:24.249 UTC`
both returned `00000101` (5); Disconnect and shutdown completed with no error
and no close error (`terminal_summary.json`: `status: passed`,
`accepted: true`). `source_provenance.json` for this run matches RADIOROC 09's
transport/connection-worker hashes exactly, ruling out a source-code
explanation for the improved outcome.

This meets the status-only card's "Acceptance" criteria for the first time
since the RADIOROC 07 fault, and is further evidence for **H1** (the board or
USB bridge was in a stuck state that the operator's power-cycle cleared) over
**H2** (unrelated transient fault) — support, not formal proof, since no
controlled A/B isolating the power-cycle was run. Evidence, including the
pre-Connect USB snapshot, screenshots, request/event traces, and a
12-file `complete_inventory.json`, is local under
`radioroc_runs/physical_status_20260911T070909Z/`. Full narrative in
`docs/hardware/desktop_status_recovery.md` under "RADIOROC 11 evidenced
re-verification (PASSED)".

No ASIC/FIFO access, verifier, scan, configuration write, defaults, repair,
power-cycle, push, or change to `main` occurred in this session. Configuration
restoration, scan behavior, and cancellation/close-during-run behavior remain
unverified and out of scope for this card.

Next: with the designated operator, decide whether to proceed to a fresh,
separately authorized physical threshold restoration/scan check now that
status-only communication is evidenced-recovered, or to run further
verification (for example, a repeated status-only pass after a longer idle
period) before trusting the board for scan work.

## RADIOROC 10 — Investigate status-only timeout (offline, STOPPED card unchanged)

Offline-only continuation on `feat/desktop-hardware-threshold`, working tree
clean at `9fd8665`. No hardware discovery/open, status retry, ASIC access,
verifier, scan, defaults, repair, power-cycle, or push/change to `main`
occurred; the RADIOROC 09 stopped card and its acceptance state are unchanged.

The lead reverified the RADIOROC 09 evidence inventory: all 11 tracked files
under `radioroc_runs/physical_status_20260911T051700Z/` (12 including
`complete_inventory.json` itself) match the SHA-256 hashes in
`evidence_manifest.json`, consistent with Luna's prior `offline_audit.json`.

The lead compared that run's exact request/timing/error evidence against prior
successful status reads on the same port/parameters: a 2026-09-10 CLI status
check (`status.json` in `physical_threshold_20260910T042911Z`, status 5) and
RADIOROC 07's native GUI session (`physical_desktop_20260911T015835Z`), whose
Connect and initial status read succeeded (status 5) and which then completed
two full threshold scans before a later job (`t1_cancel_window`) hit the known
`read_fifo` timeout at `02:07:27.651 UTC`. RADIOROC 09's fresh Connect, about
3 h 9 min after that fault, timed out on its very first status-100 request with
no prior successful transaction on that session. Source hashes in each run's
`source_provenance.json` show unchanged transport/connection-worker code across
all three, so a framing/software regression is unlikely on current evidence but
not excluded. A host-level offline check (`pmset -g log`) found no actual
Sleep/Wake transition between the 07 fault and the 09 attempt, ruling out an OS
sleep/USB-reset cycle as an explanation for the gap; a deeper unified-log
USB/FTDI trace could not be obtained offline in this session (`log show`:
"Operation not permitted", no Full Disk Access), which is a limitation, not a
finding.

No root cause is established. Two open, unproven hypotheses and one concrete
next test card (status-only, no power-cycle, evidence requirements, and
stop/release rules) are recorded in
`docs/hardware/desktop_status_recovery.md` under "Offline comparison and
diagnostic proposal (RADIOROC 10)". That card is a proposal only; it is not
authorized to run.

**Addendum, reported after this session's offline analysis:** the designated
operator power-cycled the board immediately after the RADIOROC 09 timeout was
found, and a subsequent native-GUI Connect succeeded (firmware status `0x05`/5
on `/dev/cu.usbserial-RD3_320`), per an operator-provided screenshot. This was
not run through the bounded evidence harness, so it lacks timestamps, a
request-level trace, an explicit repeat status read, and a recorded
Disconnect/shutdown; it does not satisfy this document's evidence standard or
the status-only card's two-read acceptance. It does strongly support **H1**
(stuck board/bridge state cleared by power-cycle) over H2. Details are in
`docs/hardware/desktop_status_recovery.md` under "Operator power-cycle
recovery (post-RADIOROC 10)".

Next: **RADIOROC 11 — <fresh authorization for the proposed status-only card,
or further offline diagnosis>**. This session does not authorize further
physical access; the existing RADIOROC 09 stopped state and two-read acceptance
gap remain current.

## RADIOROC 09 — Status-only desktop recovery (STOPPED)

On 2026-09-11 the user freshly confirmed the powered bare USB board, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the exact status-only card. Native Cocoa execution on
`feat/desktop-hardware-threshold` at `b31d024` stopped on Connect's first read.
Fresh candidates were `PCB_RADIOROC`, identity `usb:0403:6010:serial:RD3_32`;
the explicitly selected control port was `/dev/cu.usbserial-RD3_320`, baud
115200, timeout 0.5 s.

The trace records exactly one status-100 request, `aa00e40055`, beginning at
`05:16:23.144650 UTC`. It raised `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried`, with transfer elapsed
0.501775458 s. No status value or response frame was returned. Unlike the older
FIFO fault, this request is identified exactly; its cause remains unresolved.
No repeat status read, scan, FIFO access, verifier, configuration write,
initialization/defaults, repair or power-cycle occurred.

Connect's error path released the session through its owning worker. The
`05:16:25.164920 UTC` snapshot records `error`, cleared port/status and no close
error. Because the session was already released, there was no explicit
Disconnect or second close attempt. Shutdown recorded `stopped`, worker not
alive, and no close error at `05:16:25.257612 UTC`; process exit was 1.
The two-read acceptance did not pass, and configuration restoration is unknown.

Evidence is local and ignored under
`radioroc_runs/physical_status_20260911T051700Z/`: exact executed harness,
setup/authorization, fresh candidates, timestamped snapshots and request trace,
three native widget screenshots, terminal summary, console, source hashes and
SHA-256 inventory. The directory suffix is a label; actual execution was
05:16:21–05:16:25 UTC. Native GUI methods were driven programmatically with
human controls disabled; evidence does not include independent electrical
observation. The standard production transport and board lock were retained.

Sol prepared the local harness; the lead reviewed and strengthened its guards.
Five offline fake cases passed: success, unexpected first status, first-read
timeout, repeat-read timeout and failed close with live ownership retained and
no close retry. Compilation, help and default refusal passed. No production
source or packaging changed, so no development-suite or wheel rerun was needed.
Luna independently audited the saved sequence and verified all seven original
inventory entries. The lead preserved that manifest and verified an expanded
11-file inventory including console, source provenance and audit summary.
`git diff --check` passed; no push or change to `main` occurred.

Next: **RADIOROC 10 — Investigate status-only timeout**, an offline comparison of
this exact request with prior successful status evidence and the existing
transport, followed by one concrete diagnostic proposal. This stopped card
does not authorize further physical access or resuming GUI scan acceptance.

### Preparation history

Continuation started on `feat/desktop-hardware-threshold` at clean `b31d024`.
Offline source review identified that Connect/status exceptions already attempt
owner-mediated close. The recovery card now counts that attempt and explicitly
prohibits Disconnect/window-close/shutdown after `close_failed` without review,
because those actions can retry close. Successful automatic release is recorded
before shutdown; the normal success path still requires explicit Disconnect.

Documentation-only preparation; `git diff --check` passed. No hardware discovery,
open, status read, scan or configuration operation occurred. Physical acceptance
remains pending fresh setup confirmation and designated-operator authorization
for the exact card. Next task remains execution of that status-only card; the
RADIOROC 09 handoff in `NEXT_SESSION.md` remains current.

Continuation review on 2026-09-11 found HEAD still at `b31d024` with the two
existing documentation edits above, which were preserved. A bounded Luna
offline review confirmed the card matches current worker APIs and error-path
release behavior. Unexpected status values require the operator to stop;
`close_failed` retry restrictions are procedural, not enforced by the API.
`git diff --check` passed again. No source changes or hardware access occurred;
fresh setup confirmation and authorization remain the next required step.

## RADIOROC 08 — Investigate desktop pre-scan timeout

Offline investigation continued on `feat/desktop-hardware-threshold` from clean
`a1b17e6`. Version remains `0.5.0`. No hardware discovery/open, configuration
change, scan retry, repair, push or change to `main` occurred.

All 49 files in the original RADIOROC 07 SHA-256 inventory match their recorded
hashes and sizes. Source ordering and saved evidence place the failure inside
ASIC `read_fifo`, after FPGA 0/1/6 reads and before complete snapshot assignment
or any measurement. The transport error means no response bytes were received
for one unidentified read within 0.5 s. Initial word-0 read, status polling and
final FIFO read remain possible sites; there is no per-request trace to decide
which, or establish a board/USB/firmware root cause. The 60000 ms measurement
window was never reached and does not explain this pre-scan failure.

The failed manifest finished at 02:07:02.013701 UTC with 0 points/windows.
The verifier had no complete snapshot (all 3 FPGA and 130 ASIC expected entries
missing); successful cleanup commands do not establish verified restoration.
The harness recorded the latched fault at 02:07:27.651320 after SIGINT interrupted
its marker-only wait. Disconnect recorded idle with port/status cleared and no
close error at 02:07:29.171427; shutdown recorded stopped at 02:07:29.297004.
Neither GUI cancellation nor an in-window close occurred.

Local-only fixes and their report are preserved under ignored
`radioroc_runs/radioroc08_offline/`. `phase_wait.py` detects terminal outcomes,
faults, disconnect and shutdown before accepting a marker, including simultaneous
marker/fault delivery. `radioroc08_gui_card.py` integrates this for window and
first-point waits and adds a separate request trace without Qt widget access.
The original harness is unchanged. Six deterministic wait tests passed, as did
compilation, help and default refusal (exit 2). Physical execution is gated by
an explicit flag and remains unvalidated/unauthorized; the derivative runs the
scan card and must not be used for the next status-only task. Request tracing
cannot reconstruct the missing historical request and has not been tested on
a board.

The saved T2 screenshot independently confirms the previous T1 saved-result
banner above current T2 data. The minimal production UI change replaces saved
provenance when starting a new run; device logic and shared APIs are unchanged.

Checks: `.venv-foundation/bin/python tools/check_development.py` passed all
**118 offline tests**, compile checks and **15 legacy CLI help checks**, including
the new saved-result/new-run/rejected-submission GUI regression. Log:
`/private/tmp/radioroc08-development.log`. Packaging metadata is unchanged, so
no new installed-wheel check was needed. `git diff --check` passed.

The concrete next task is **RADIOROC 09 — Status-only desktop recovery**, using
`docs/hardware/desktop_status_recovery.md`. Fresh operator authorization is
required before hardware access. Connect's status read, one explicit repeat,
disconnect and shutdown are the entire card; success does not establish restored
configuration or authorize a scan. Physical cancellation/close acceptance,
word-60 semantics, wider scans and analog performance remain pending.

## RADIOROC 07 — Physical desktop threshold validation (STOPPED)

On 2026-09-11, the user confirmed the powered bare board, USB only, no
SiPM/pulser and competing software closed, and authorized the lead as sole
software operator for the five-case desktop card. Starting tree was clean on
`feat/desktop-hardware-threshold` at handoff `086d304` (implementation `e6cddf4`).
Sol prepared a local harness and reviewed saved evidence; workers used no hardware.
No production source or packaging changed; version remains `0.5.0`.

Native macOS Cocoa GUI discovery/connect/repeat status/disconnect passed using
`.venv-foundation`. Fresh identity was `usb:0403:6010:serial:RD3_32`, control port
`/dev/cu.usbserial-RD3_320`, baud 115200, timeout 0.5 s; both status reads returned
5. Status is not a decoded firmware version. Five actual offscreen GUI previews
passed without creating a worker or run directory before physical execution.
Config was the explicit `configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

| Native GUI case | Points / windows | Result | Verification |
| --- | --- | --- | --- |
| T1, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T2, channel 4, DAC 0..1, 10 ms | 2 / 2 | completed | passed |
| T1, DAC 0, 60000 ms, intended in-window Cancel | 0 / 0 | failed before measurement | incomplete |
| T1, DAC 0..2, 1000 ms, Cancel after first point | — | not executed | — |
| T1, DAC 0, 60000 ms, close during run | — | not executed | — |

All submitted cases used one average, masks on, Ctest off, gain unchanged,
FPGA initialization/default application off and mandatory verification. Normal
T1/T2 terminal displays and saved reopening passed; the session stayed connected.
Their 130 ASIC rows exactly match snapshot/expected/observed values. FPGA words
0/1/6 were `00111111` / `00000000` / `00000000`, matching both verifier passes.
Manifest/CSV counts agree; all four measured rates were 0 Hz. No cleanup,
persistence or verifier errors occurred in these two cases.

The third job recorded `TransportTimeoutError: no response from
/dev/cu.usbserial-RD3_320 within 0.5s; request not retried` during snapshot
acquisition. Status, preparation and FPGA 0/1/6 reads completed; the 130-row
ASIC `read_fifo` did not return a complete snapshot. No trigger-mask, DAC,
channel-selection or counter operation was reached. The exact failed serial
request within `read_fifo` is not recorded. Cleanup commands succeeded (`restored`), but verification was
`incomplete` because all snapshot entries were absent. This does not establish
verified restoration. No counter-window phase marker or GUI Cancel request
occurred; the intended cancellation test did not reach measurement.

The GUI latched the fault. The local harness was still waiting for its phase
marker, so the lead interrupted that wait with SIGINT after the job had already
failed. Its error handler explicitly disconnected through the owning worker:
state became idle with port/status cleared and no close error, then stopped on
window shutdown; process exit was 1. This SIGINT is not GUI cancellation evidence.
No subsequent scan, repair, initialization/default write or retry occurred.
Hardware configuration was not re-verified after the fault.

Evidence remains local and ignored under
`radioroc_runs/physical_desktop_20260911T015835Z/`: setup and previews, native
widget screenshots/text, timestamped GUI/worker records, three manifests and CSV
pairs, console log, exact local harnesses, two-run equality audit, stopped
summary and SHA-256 inventory. Native controls were driven programmatically;
there was no continuous screen recording or independent electrical observation.
Completed plots were captured, but intermediate point display was not separately
captured. An observed UI issue remains: starting hardware Run after reopening a
saved result leaves the prior saved-result banner visible over the new plot.
The harness phase wait also needs immediate fault detection before future use.

Checks: actual GUI previews, native connection preflight, two successful physical
runs/reopens, exact offline saved-data audit, and `git diff --check`. No new
production-source suite or wheel check was needed; prior 117-test evidence below
is unchanged. Main, lab environments and all measurements were preserved.

Next: **RADIOROC 08 — Investigate desktop pre-scan timeout**. Review the saved
failure offline, improve fault/evidence handling, and prepare a bounded
status-only recovery card before further physical access. The timeout cause is
unresolved; cancellation and close-during-run acceptance remain pending.

## Current checkpoint

**RADIOROC 06 — Desktop hardware threshold workflow** is implemented on
`feat/desktop-hardware-threshold` at `e6cddf4`, based on `b10cf57`. Version remains `0.5.0`;
packaging metadata and legacy entry points are unchanged.

- The persistent `ConnectionWorker` owns the transport, device, shared
  `ThresholdJob`, mandatory restoration verification, disconnect and close retry
  on one thread. Hardware Run uses this owner rather than a competing worker.
- Preview stays offline. Entering hardware mode defaults FPGA initialization
  and ASIC defaults application off; their controls identify persistent changes.
  Temporary scan settings are restored and independently verified.
- Live points, cancellation, saved results and shutdown use the shared job.
  Normal terminal delivery retains the connection after cleanup/verification.
  Shutdown cancels and waits; a new job fault holds shutdown for visible review.
- Job, cleanup, persistence, verification and close faults block another scan.
  Disconnect and explicit fault-review acknowledgement are required before a
  new connection. Failed close retains ownership for an explicit retry.
- Reopening a manifest with failed/incomplete verification preserves its data
  and shows an incomplete result, even if the primary scan completed/cancelled.

Sol implemented/tested the owner, Terra implemented/tested the GUI, and Luna
updated workflow documentation and the separate pending physical GUI card. The
lead reviewed ownership/publication contracts and integrated saved-reader and
installed-artifact checks. No hardware discovery/open/scan, environment diagnostic,
persistent configuration write, push or change to `main` occurred.

Validation on macOS ARM64 / Python 3.13:

- `.venv-foundation/bin/python tools/check_development.py`: **117 offline tests**,
  compile checks and all **15 legacy CLI help checks** passed. New coverage
  includes same-thread session/job/verifier ownership, cancellation and queued
  shutdown, fault latching/review, defensive snapshots, GUI gating and terminal
  delivery order, and saved verification-fault visibility.
- Source distribution and `0.5.0` wheel built with `python -m build --no-isolation`.
  Installed core-only checks passed with Qt absent in `.venv-wheel-core`.
  Installed GUI/plot checks passed outside the checkout using a temporary venv
  with development dependency paths; the wheel itself was installed there.
  The GUI check completed/reopened simulation and exercised the persistent
  hardware job route with a fake transport and passing mandatory verification.
- `git diff --check` passed. Logs and built artifacts remain local under
  `/private/tmp/radioroc06-*`; no generated files or measurement data are committed.
  The foundation editable installation and lab environment were preserved.

Hardware state was not refreshed: the last physical evidence is RADIOROC 05
below, whose historical port/status must not be treated as current. Native GUI
hardware behavior and physical GUI restoration remain unvalidated. Fake transport
tests establish software behavior only; word 60 semantics and analog performance
remain outside this slice.

Next: **RADIOROC 07 — Physical desktop threshold validation**, using
`docs/hardware/desktop_threshold_validation.md`. Its fresh equipment summary and
operator authorization are separate from the completed CLI card.

## RADIOROC 05 — Physical threshold restoration checks

The physical threshold restoration card passed on 2026-09-10 in
**RADIOROC 05 — Physical threshold restoration checks**, on
`test/physical-threshold-restoration`, based on authorization handoff `3c0f82a`
and verifier implementation `4c6d254`. Package version remains `0.5.0`.
Desktop hardware Run was disabled at that checkpoint; RADIOROC 06 above enables it.

The lead was the sole software board operator, using the authorization recorded
in the preceding handoff: powered bare board over USB, no SiPM/pulser, competing
vendor software and terminals closed. Sol reviewed cancellation instrumentation
and audited saved evidence offline; Luna updated the physical card.

Physical evidence is preserved locally and ignored under
`radioroc_runs/physical_threshold_20260910T042911Z/`: discovery/status JSON,
exact preview/execution arguments, preview logs, full console output, exit codes,
four manifests and CSV pairs, process-local cancellation launcher, audit summary
and SHA-256 evidence inventory.
No measured data is committed. Host: macOS 15.1 ARM64. Fresh USB identity:
`usb:0403:6010:serial:RD3_32`; control port `/dev/cu.usbserial-RD3_320`,
115200 baud, 0.5 s timeout. Status word 100 read `00000101` (5), and close
succeeded. This is a status value, not a decoded firmware version. Board revision
was not independently identified; ambient conditions were not measured.

| Physical case | Completed points / windows | Exit | Restoration verification |
| --- | --- | --- | --- |
| T1, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T2, DAC 0..1, 10 ms | 2 / 2 | 0 | passed |
| T1, DAC 0, 60000 ms window, cancel during window | 0 / 0 | 130 | passed |
| T1, DAC 0..2, 1000 ms, cancel after first point | 1 / 1 | 130 | passed |

Every command was previewed offline before execution, used channel 4, one average,
mask isolation, `--skip-fpga-init` and `--verify-restoration`, and omitted
`--apply-defaults`. Each run captured 130 ASIC rows (the variant's two DAC rows,
64 discriminator rows and 64 masks) plus FPGA 0/1/6. Exact FPGA snapshots in every
case were `00111111` / `00000000` / `00000000`; both verifier FPGA passes and
ASIC comparison matched. Job/verifier cleanup succeeded, manifests and CSV row
counts agreed, and there were no persistence or CLI close errors. All completed
windows had zero counts (0 Hz). Configuration:
`configs/radio_default_i2c.csv`, SHA-256
`8ccad20a95c0564e3465a32791348035defeed0231f63c8f7f5702dba13d195e`.

Cancellation used a process-local launcher around the unchanged CLI. The window
hook raised SIGINT after the first 10 ms delay slice, which the production loop
reaches after counter enable and before stop/read. The point hook raised SIGINT
from the event callback after the first point and manifest were persisted. Phase
markers and exit 130 establish the real CLI signal-handler/cancellation path;
this was programmatic SIGINT, not a human keystroke. Window phase evidence is
software call ordering, not independent observation of a counter-active signal.

Checks: all four physical acceptance cases and saved-evidence assertions passed.
An independent offline audit confirmed byte-for-byte snapshot/expected/observed
equality, exact variant row coverage, preview/manifest agreement and CSV counts.
`git diff --check` passed; evidence is ignored and `main` remains at `b77f76d`.
No production source or packaging changed; no new development-suite or wheel run
was required (preceding 108-test offline checkpoint remains below). The lab Python
does not have an installed `radioroc` module, so discovery used the preserved
`scripts/radioroc_list_ports.py` entry point after module invocation failed before
hardware access. All physical scans used the documented legacy script entry point.

Limits: word 60 is verified only as a successful idle write; ASIC readback protocol
semantics and analog behavior are not independently established by equality alone.
Ctest/gain changes, other channels, wider DAC ranges, detector measurements,
Linux/Windows USB and native desktop hardware ownership remain outside this card.
Next: **RADIOROC 06 — Desktop hardware threshold workflow**, with explicit
preparation choices, shared job ownership, cancellation and readback verification.

Delivery 2 remains at `6c44092` on `feat/transport-ownership`; `782014f` recorded
its validation and threshold-job handoff.

All commits are local; no push, PR or remote CI run has been performed.
`main` remains at the original `b77f76d` baseline. The development branch
contains the preceding checkpoints:

- `e3d3b3d`: acquisition, scan and analysis workflows, preset and tests.
- `352418a`: June/July lab notes and their result figures.
- `603c69b`: rebuild plan and exclusions; tag `pre-desktop-rebuild` on
  `chore/lab-baseline`.
- `81ee287`: installable package, CLI and offline development checks on
  `build/python-foundation`.

The five experiment folders were recovered from local Git snapshot
`9c1da1e65fe2384f39c680f5b29add8ca341d2b6`: 27 files verified against blob hashes.
They are present locally and ignored. Other saved runs remain in `radioroc_runs`.
No separate external backup has been configured. Recovery verifies snapshot
bytes, not any unrecorded later changes.

## Threshold restoration verifier: implemented and checked offline

- `ThresholdJob.run(..., verify_restoration=True)` and the existing CLI's
  `--verify-restoration` opt in to independent readback after scan cleanup,
  under the same transport owner and job lock. Unflagged behavior is preserved.
- The verifier compares measured FPGA words 0/1/6 and all configured T1/T2 ASIC
  snapshot rows. It captures post-job FPGA state before ASIC reads, then idles
  word 60, restores exact observed word 0 (including its I2C active bit), and
  rereads FPGA state. It never repairs or hides a scan-restoration mismatch.
- Missing snapshots and incomplete payloads cannot pass; no missing value is
  supplied from the configuration table. Verification is a separate report in
  the result and manifest, preserving primary/scan-cleanup/persistence errors.
  Close errors are separately printed even when other failures coexist. Save
  console output: close occurs after the manifest's terminal write.
- The reviewed offline implementation and updated card are ready for operator
  review. The physical card was not executed at this offline checkpoint; see the
  RADIOROC 05 results above. Desktop hardware Run remains disabled; no new UI or device workflow was enabled.

Validation on macOS ARM64 with `.venv-foundation`:

- `python tools/check_development.py`: **108 offline tests** passed, with compile
  checks and all **15 legacy CLI help checks**. The 13 new verifier tests cover
  T1/T2 full register sets, exact transport ordering, active-bit restoration,
  same-session locking, completed/in-window/after-point cancellation, missing
  snapshots, short readback, FPGA/ASIC mismatches, verification/read/cleanup/close
  failures and CLI exit statuses/offline isolation.
- The card's two-point T1 preview passed with `.conda-radioroc/bin/python`, using
  a placeholder port; it created no output directory. This was a dry-run only.
- `git diff --check` passed. No packaging configuration changed, so a new wheel
  build/install check was not required. The development environment now uses an
  editable checkout; the lab environment and measured data were preserved.
- No hardware scans, discovery, physical open, diagnostic enumeration, push or
  remote CI occurred. `main` remains unchanged.

Limits: fake tests establish software behavior, not physical register semantics.
Word 60 readback remains unresolved; its idle-write success is recorded without
claiming readback verification. A passing verifier does not erase job cleanup
errors. Manual CLI Ctrl-C timing does not prove cancellation inside a counter
window because that phase has no explicit start event; establish phase evidence
before accepting the physical cancellation case. Bare-board rates cannot establish
analog response or detector performance. The subsequent RADIOROC 05 physical
acceptance results are recorded above.

## Delivery 4 connection slice: implemented and checked

- Lazy, Qt-independent connection worker with a bounded command mailbox and
  immutable snapshots. Discovery, transport creation/open, status reads and close
  stay on its own thread; no startup discovery occurs.
- Explicit USB candidate refresh/selection, baud/timeout settings, connect,
  status-word 100 read and disconnect. Candidates are labelled unverified;
  simulation and hardware session controls cannot overlap in one window.
- Existing serial transport and board lease are reused. Invalid overlapping
  operations are rejected atomically. Busy, timeout, protocol, I/O and close
  errors retain their exception names. Failed close retains the owned session
  for explicit retry, including failure during partial open. Window shutdown
  waits for session release and leaves close failures visible.
- Hardware threshold Run is disabled. The separate card at
  `docs/hardware/bare_board_threshold_validation.md` specifies the exact register
  boundary, preparation, cancellation and independent restoration checks. It is
  **not executed**; a verification helper that restores its own I2C side effects
  is the next implementation task.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **95 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 14 new tests cover
  connection ownership, command gating, partial-open/close retry, real transport
  framing/lease integration with fake serial, GUI selection, error presentation
  and responsive shutdown. No hardware is enumerated by these checks.
- Source distribution and 0.5.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for simulation/reopen, fake connection/disconnect,
  disabled hardware Run and headless plotting outside the checkout.
- Native macOS Cocoa launch passed fake connect/status and owned shutdown. Visual
  inspection found clipped controls; the corrected layout was launched and
  inspected again. Screenshot remains local at
  `/private/tmp/radioroc-connection-native.png`.
- `git diff --check` passes. No physical board discovery/open or configuration
  writes occurred. Lab data and environments were preserved; development wheel
  environments were updated. No push, PR or remote CI run was performed.

Limits: physical desktop connection/disconnect has not been exercised on the
board. Native validation used a clearly labelled fixture. Linux/Windows GUI,
USB behavior and bundling remain unvalidated; status bits are not decoded into
unverified firmware capabilities. Readback-based scan restoration remains pending.

## Delivery 4 simulation slice: implemented and checked

Committed at `ef92eeb` on `feat/desktop-threshold-simulation`, version `0.4.0`;
handoff at `cf35315`.

- Optional PySide6/Matplotlib desktop entry point `radioroc-desktop`, while the
  core/CLI wheel remains importable and usable without Qt or a display server.
- Configure channels, DAC range/step, counter window, averages, T1/T2, mask,
  Ctest, gain and preparation options; offline preview exposes persistent versus
  temporary settings and creates no output/session.
- A deterministic, configurable logistic threshold simulator drives the actual
  `ThresholdJob.run` device/register path. Every screen, plot and reopened run
  labels synthetic data as simulation; model parameters are saved in metadata.
- A worker owns session create/run/close on one background thread. The UI polls
  a bounded/coalesced display mailbox while the shared writer independently saves
  every completed counter window and DAC row. Cancellation and window close wait
  for cleanup and session release; cleanup/storage/close failures remain visible.
- Saved-run reading validates manifest/CSV schema, channels, DAC order, point
  counts and finite nonnegative rates. It salvages only a valid prefix, labels
  nonterminal/inconsistent runs incomplete and opens legacy CSVs with unknown
  provenance. It never resumes or rewrites a run.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **81 offline tests** pass, plus compile checks and all 15 legacy CLI help
  checks through `python tools/check_development.py`. The 26 added tests cover the
  simulator, worker/session ownership, coalescing of all 1024 DAC rows, cancellation,
  close faults, saved-run validation and Qt workflows.
- Source distribution and 0.4.0 wheel build with `python -m build --no-isolation`.
  Core-only installed-wheel checks pass in `.venv-wheel-core` with Qt absent.
  Installed GUI checks pass for configure/preview/run/plot/reopen using Qt offscreen.
- A native macOS Cocoa launch displayed, completed and reopened a 41-point,
  two-channel simulation. The window remained responsive and was captured for
  local visual inspection; the temporary run and screenshot were not added to Git.
- No physical device was enumerated or opened. Ignored experiment folders and
  `radioroc_runs` were preserved. No remote CI, push or PR was performed.

Limits: the simulator is a deterministic workflow exerciser, not an analog/noise
model. Desktop hardware mode is visibly unavailable. Linux desktop launch,
application bundling and Windows GUI execution remain unvalidated. The saved-run
reader is for truthful display, not crash repair or resume.

## Delivery 3: implemented and checked

- `ThresholdJob` / `ThresholdJobConfig` provide a synchronous worker-friendly API.
  The existing threshold CLI and `device.run_threshold_scan` use that runner.
  Existing arguments, counter sequences, DAC encoding and result columns/rates
  are retained; validation now rejects invalid DACs, duplicate channels and
  nonfinite/nonintegral settings before device access or file creation.
- Structured state/point events, cooperative cancellation including I2C ready
  polling and counter windows, Ctrl-C exit handling, and immediate rejection of
  overlapping jobs on one transport session (including multiple device wrappers).
- A manifest exists before preparation. Completed windows and DAC points are
  appended/flushed/fsynced to compatible CSVs. Atomic manifests record status,
  effective table/configuration, snapshots, firmware, source fingerprint, units,
  version, board identity when available and separate cleanup/storage errors.
  Existing run files are never truncated by a new job.
- Captured temporary threshold/gain/mask/Ctest/discriminator and FPGA settings
  are restored; uncaptured ASIC settings are never invented. Cleanup errors do
  not replace the primary failure. Explicit initialization/default application
  remains intentional preparation and persists; interrupted preparation is
  labelled unknown/possibly partial. Memory-transport results are simulated.
- Threshold dry-run validates/previews without serial construction/discovery,
  measurements or output files. Other workflows are unchanged.

Validation on macOS ARM64 / Python 3.13 using `.venv-foundation`:

- All **55 offline tests** pass (30 preceding, 25 threshold lifecycle tests),
  plus compile checks and all 15 legacy CLI help checks through
  `python tools/check_development.py`.
- Tests compare complete API/CLI fake-device command traces and CSV bytes; check
  known rates/counts, T1/T2, multiple channels, Ctest, gain, explicit preparation,
  complete captured-state restoration and legacy source execution.
- Fault tests cover cancellation before acquisition, during I2C polling, during
  a long counter window, mid-point and after a point; CLI SIGINT; timeout and
  disconnect; cleanup failure alone/with a primary error; snapshot/preparation
  failure; disk/manifest failure; output collisions; callback failure; concurrent
  session jobs. A subprocess abrupt exit retains a readable point and leaves
  status running with cleanup pending. Existing subprocess board-lock tests pass.
- Source distribution and wheel build with `python -m build --no-isolation`.
  The 0.3.0 wheel is installed in `.venv-foundation`; isolated installed-wheel
  checks outside the checkout pass for resources, all 15 commands, an executed
  synthetic threshold job, genuinely offline preview and headless PNG rendering.
- No physical device was opened in this session. The lab environment, ignored
  experiment folders and `radioroc_runs` were preserved. No remote CI/push/PR.

Delivery 3 limits and follow-ups:

- Physical snapshot/restore behavior, scan timing and throughput remain untested.
  `restored` means restoration commands succeeded, not verified readback. I2C
  control word 60 is idled instead of replaying its command strobe.
- Persistent storage failure can prevent terminal metadata; the result reports
  persistence errors, while the last manifest may lag. Crashed/incomplete runs
  must not be shown as completed; recovery readers should validate any unconfirmed
  CSV tail. There is no resume/recovery service yet.
- The caller owns transport open/close and must surface connection/close failures.
  The whole-job lock covers threshold jobs only; unmigrated workflows and direct
  primitive calls must not run concurrently. Cancellation waits for bounded I/O;
  cleanup can require many transactions and is not instantaneous.
- The memory backend and scripted test transport are not an analog simulator.
  Delivery 4 needs a labelled threshold simulator and a UI worker adapter with
  a bounded/coalesced event queue. No Qt/UI code is included in this delivery.
- Existing T1/T2 shared-register write encoding and table-based mask/gain updates
  were preserved. Compare those semantics with the vendor before broader register
  refactoring. Other commands' offline dry-run, acquisition/autocalibration jobs,
  HG/LG mapping, Windows parity and Linux hardware checks remain separate work.
- Local commit identity follows preceding commits (Tengiz Ibrayev,
  `tengiz@agqhcqjdw32.tail819d22.ts.net`); confirm it before publication.

## Earlier deliveries: implemented

- Installable shared Python package, retaining original script paths and core
  imports. `radioroc` / `python -m radioroc` now dispatch 15 commands, including
  the new read-only port candidate listing.
- Packaged default configuration and presets, independent of working directory.
  Base dependencies are pySerial and filelock; plotting/build tools are optional.
- One framed serial transport used by the core, legacy autocalibration and
  serial-probe scripts. Exact existing request bytes and write chunking retained.
- Validated request bounds, bounded fragmented reads/output waits, explicit
  timeout/protocol/I/O errors and no automatic request retries. Failed ASIC
  readback raises instead of returning unmeasured defaults.
- Cooperative OS-backed ownership across both USB interfaces of a board, keyed
  by USB identity, acquired before opening serial. Normal close and process exit
  release ownership; failed close retains ownership for a later close attempt.
- Offline source and installed-wheel checks; GitHub Actions configuration for
  Ubuntu/macOS and Python 3.11/3.13; development and agent instructions.

## Delivery 2 validation (historical)

Local platform: macOS ARM64, Python 3.13. Development uses `.venv-foundation`.
The existing `.conda-radioroc` lab environment received the new filelock
dependency (3.32.6); the source checks pass there as well.

- All 30 unit tests pass (nine existing, 21 new), including malformed/fragmented
  replies, embedded frame delimiters, timeouts/disconnects, no retries, failed
  readback, open/close cleanup and real subprocess ownership/release after kill.
- Compile checks and all 15 CLI help commands pass.
- Source distribution and wheel build successfully. Editable installation was
  checked; `.venv-foundation` had the built 0.2.0 wheel at that checkpoint
  (now updated to 0.3.0 above).
- Installed-wheel checks pass outside the checkout: imports/transport aliases,
  default table byte equality/677 rows, presets, version and all CLI help pages.
  A synthetic threshold CSV renders to PNG with the headless Matplotlib backend.
- Read-only hardware status on `/dev/cu.usbserial-RD3_320` returned address 100
  as `00000101` (5). While that connection was held, a second process targeting
  `/dev/cu.usbserial-RD3_321` received `DeviceBusyError` before opening serial.
  The owner then closed and released the lease. No configuration writes were
  issued. See `logbooks/2026-09-09.md`.

## Limits and outstanding work

The earlier planning-time status-read failure did not recur; its cause was not
established. Successful status and lock checks do not validate scans or Windows
feature parity. The board is powered, with no SiPM or pulse generator connected
according to the user; the connection was closed after testing.

CI has not run remotely. Linux/Debian installation, physical USB behavior on
Linux and desktop bundling remain unvalidated. The desktop supports the threshold
workflow in simulation. Desktop hardware connection/status is implemented but
physically unvalidated; hardware scan execution remains disabled. The feature
inventory is preliminary and still needs comparison with the actual
Windows 2.2.0.5 application.

Ownership coordinates participating programs for the same OS user with a local
home filesystem. It cannot exclude vendor D2XX programs or other nonparticipating
clients. Missing USB metadata can prevent grouping both interfaces; duplicate
USB serial numbers conservatively collide. Candidate discovery does not identify
the control interface automatically. See `DEVELOPMENT.md` for the full contract.

Response metadata bytes 1–2 remain opaque. Without verified correlation fields,
same-shaped stale replies cannot reliably be rejected. The 65536-byte request
boundary is tested offline only; the vendor wrapper caps it at 65535.

Transaction locking and the threshold job lifecycle are implemented. Other
workflows still need whole-job migration; some legacy dry-run commands still
open ports. HG/LG nibble mapping and state restoration outside threshold scans
remain tracked migration concerns. Do not mix workflows on one session.

## Next bounded tasks

1. Done as of RADIOROC 12: physical threshold restoration checks (including
   both cancellation cases and close-during-run) passed on the desktop GUI
   workflow with independent readback verification. See RADIOROC 12 above and
   `docs/hardware/desktop_threshold_validation.md`.
2. Review/integrate the local branches and run configured CI when publishing is
   authorized; check the intended Git author identity before publication.
3. Expand the Windows parity inventory into control-level acceptance criteria.
4. Done: the desktop hardware threshold workflow is enabled (`e6cddf4`) and its
   full required case set now has physical evidence (RADIOROC 12). Remaining
   desktop-hardware work is wider DAC/scan ranges, Ctest/gain variation, and
   any detector (SiPM/pulser) connection — each needs its own bounded,
   separately authorized card.

At each checkpoint, record the commit, checks, hardware state, limitations and
one next task. Move unrelated discoveries into this backlog.
