# Development

The lab baseline is tagged `pre-desktop-rebuild` (`603c69b`). The first rebuild
branch is `build/python-foundation`; transport work continues on
`feat/transport-ownership`, followed by threshold jobs on `feat/threshold-jobs`.
These commits are local until pushed.

## Install

Use Python 3.11 or later (CI targets 3.11 and 3.13). Create a separate environment
so development does not change the existing `.conda-radioroc` lab environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[analysis,dev]'
python tools/check_development.py
radioroc --help
radioroc threshold-scan --help
```

The base install requires pySerial and filelock; plotting requires `[analysis]`. No Qt,
vendor installer, D2XX library or connected board is needed for offline checks.
Install `[gui]` for the optional PySide6/Matplotlib threshold desktop. The
historical conda environment remains available for
existing lab work.

## Commands and compatibility

The installed `radioroc` command and `python -m radioroc` dispatch to the current
script implementations. `python scripts/radioroc_threshold_scan.py ...` and the
other original commands still work from a source checkout.
`python -m radioroc` requires a regular or editable installation; merely adding
`src` to `PYTHONPATH` does not supply the transitional CLI/resource mappings.

Core modules retain the import names `radioroc_client` and `radioroc_analysis`.
Frame helpers now live in `radioroc.protocol`; communication, discovery and
ownership live in `radioroc.transport`. Old names remain re-exported for scripts.
Setuptools temporarily maps `scripts/` to `radioroc.cli` and `configs/` to
`radioroc.resources`, so code and configuration are packaged without duplicate
copies. New package code lives in `src/radioroc/`. These mappings are a migration
step; extract the core gradually instead of rewriting it during packaging.

The default I2C table now resolves independently of the working directory. To
use a custom table, pass `--config PATH`. Packaged presets can be located with:

```python
from importlib.resources import files
preset = files('radioroc.resources').joinpath('presets/threshold_ch4_sipm_dark.json')
```

Successful workflow settings/sequences remain unchanged; transport failures now
propagate explicitly and requests are not automatically resent. Threshold dry-run is now offline; some other dry-run commands still open
the serial port. Offline checks run help, pure functions and recorded/synthetic
data only. Migrate those commands in their own workflow slices.

## Build and verify an installed artifact

```bash
python -m build
python -m venv .venv-wheel
.venv-wheel/bin/python -m pip install dist/*.whl
.venv-wheel/bin/python tools/check_installed_package.py
.venv-wheel/bin/python -m pip install 'radioroc-tools[analysis]'
.venv-wheel/bin/python tools/check_installed_package.py --plot
```

For the optional desktop, install the wheel with `[gui]` and run
`python tools/check_installed_package.py --gui --plot`. Without `--gui`, the
check requires an environment with no Qt installed, proving the core remains
headless. With `--gui`, it exercises configuration, preview, simulation, plotting
and reopening under Qt's offscreen platform.

The smoke check launches isolated Python processes in a temporary directory,
checks packaged configuration bytes, all 15 commands, and optional headless plot
rendering. It catches packaging failures that imports from the checkout conceal.
GitHub Actions repeats the checks on Ubuntu and macOS. Debian installation and
physical USB behavior on each target OS still need separate validation.

## Git and data

Use a short-lived branch for a bounded change. Include acceptance checks and
known limitations in each commit/PR, and keep the existing commands usable.
Update `IMPLEMENTATION_STATUS.md` when completing a delivery. The lead integrates
agent changes; workers should have non-overlapping files or separate worktrees.

Never delete files merely to make Git status clean. `test0/`, `test1/`,
`test1_std/`, `test2/`, `test3/`, `radioroc_runs/`, vendor files, environments and
build artifacts stay local and ignored. Scripts, configuration, automated tests,
logbooks and their selected result figures are tracked. Ignored measurements
need a separate backup; no external data backup was configured in this delivery.

Packaging references: [setuptools configuration](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)
and [GitHub Python workflows](https://docs.github.com/en/actions/tutorials/build-and-test-code/python).

## Communication and board ownership

`radioroc ports --json` lists FTDI candidates and their board identities without
opening them. VID/PID alone does not confirm a RADIOROC board. Select `--port`
explicitly and confirm a status response. The previous Mac default remains for
compatibility; automatic control-interface selection is a later task.

All framed serial entry points, including legacy calibration and serial-probe
scripts, share a board lock under `~/.radioroc/locks`. Two interfaces with the
same VID/PID/serial number share one lock. If serial identity is unavailable,
USB location is used, then a canonical port path as the final fallback. The
fallback cannot group interfaces without identifying metadata. Duplicate USB
serial numbers conservatively contend for the same lock.

Locks coordinate participating programs for the same OS user, including
different checkouts. Use a local home filesystem; other users, vendor D2XX
programs and programs that ignore this lock are outside its guarantee. POSIX
serial exclusive mode supplies an additional port-level advisory check. Leave
lock files in place: the OS lock determines ownership, not whether a file or PID
exists. Normal close and process exit release it; a failed serial close retains
ownership until close succeeds. Prefer `with RadiorocSerial(...)` sessions.

Read requests are sent once because repeating FIFO reads can consume subsequent
data. Fragmented replies are assembled within the timeout. A missing reply raises
`TransportTimeoutError`; incomplete/malformed data raises `TransportProtocolError`;
device I/O failure raises `TransportIOError`. Failed ASIC readback propagates,
instead of pretending a loaded default was measured. Response metadata bytes
1–2 are deliberately opaque until firmware evidence establishes their meaning.
Leading non-header noise is skipped. A bad footer rejects the transaction;
the parser does not search inside a malformed ADC payload for another frame.
Without verified metadata or a transaction identifier, same-shaped stale frames
cannot be distinguished reliably from current replies.
Requests above 256 bytes retain the previous encoding; the 65536-byte maximum is
tested offline only (the vendor wrapper restricts it to 65535).

Transaction serialization prevents interleaving individual calls on one transport.
Threshold jobs now also serialize the complete workflow through the application
layer. Other workflows remain unmigrated; do not run them concurrently.

The historical conda environment needs filelock for this branch; it is now
listed in `environment-radioroc.yml`. Package installations install it automatically.

References: [pySerial timeout/exclusive behavior](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)
and [filelock](https://py-filelock.readthedocs.io/en/latest/).

## Session scope and handoffs

This continuation is **RADIOROC 06 — Desktop hardware threshold workflow**. Number future
handoffs sequentially and include the preceding chat label in `NEXT_SESSION.md`.

Use one bounded delivery per chat: define its outcome, allowed modules, tests
and explicit exclusions before implementation. Put discoveries outside that
scope into `IMPLEMENTATION_STATUS.md` rather than expanding the current change.

Start a new chat after the delivery is tested and committed, particularly when
moving to a different subsystem (transport → jobs, jobs → desktop UI). A second
major change of objective or repeated re-explanation of old decisions is also
a useful signal to checkpoint. Conversation length alone is not a completion
criterion, and a new chat does not replace a clear scope.

Before handoff, record the branch/commit, checks, hardware state, known gaps and
one next task in `IMPLEMENTATION_STATUS.md`; prepare `NEXT_SESSION.md` as the
copyable starting prompt. Ask the new chat to read those files and `AGENTS.md`.
If work is incomplete, label the checkpoint WIP instead of marking it complete.

## Threshold jobs (Delivery 3)

`radioroc threshold-scan` and `scripts/radioroc_threshold_scan.py` now submit the
shared `radioroc.application.threshold.ThresholdJob`. Existing arguments, DAC
encoding, counter reset/enable/stop sequence, rates and CSV columns are retained.
Without `--execute`, the command validates the connection settings and ASIC table
and prints a JSON preview without enumerating/opening serial, waiting for a scan,
or creating output files. Other legacy commands still have their old dry-run
limitations.

The synchronous application API can run on a UI worker thread:

```python
from pathlib import Path
from radioroc_client import ThresholdScanConfig
from radioroc.application import CancellationToken
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig

operation = ThresholdJobConfig(
    ThresholdScanConfig([4], dac_min=0, dac_max=10, dac_step=5,
                        out_dir=Path("radioroc_runs/my_scan")),
    # Omit config_path to use the device's loaded table or packaged defaults.
    initialize_fpga=False,
    apply_defaults=False,
)
preview = ThresholdJob.preview(operation)  # no device or output files
cancel = CancellationToken()
# device is an already-open RadiorocDevice owned by this caller.
result = ThresholdJob().run(device, operation, cancellation=cancel,
                            on_event=lambda event: print(event))
```

The caller opens/closes the transport and selects its thread/event adapter. Call
`cancel.cancel()` from another thread to stop cooperatively. The CLI maps Ctrl-C
to that request and exits 130 after cancellation, or 1 if cleanup/storage failed.
The application runner returns `ThresholdScanResult`, including failures; invalid
input, output initialization failure and a busy session raise before measurement.
The compatibility `device.run_threshold_scan(...)` delegates to the same runner
and raises `ThresholdJobError` for failure, carrying `.result` and the original
exception as its cause. Cancellation returns the partial result.

Events have `kind` (`state` or `point`), `status`, completed/total DAC points,
optional DAC and an immutable tuple of row values. A point means a full DAC row
across the requested channels and averages. States are preparing, running,
cancelling, completed, cancelled, failed and disconnected. The idle state belongs
to the caller; a second job is rejected immediately with `JobBusyError`, including
through another device wrapper of the same transport. The lock covers preparation,
snapshot, scan, cleanup and terminal persistence. Direct device calls and workflows
not yet migrated do not acquire it; do not mix those with a running job. The
existing OS board lease remains responsible for cross-process exclusion.

Callbacks run synchronously on the caller's thread; keep them short. Ordinary
callback exceptions are warnings on the result and do not interrupt acquisition.
GUI adapters must marshal events to the UI and bound/coalesce their display queue.
Cancellation is checked between device operations, in I2C ready polling and at
most every 10 ms during counter windows. An in-flight serial transaction still
uses its transport timeout. Cleanup ignores the cancellation token and may need
multiple bounded transactions; it is not an instantaneous disconnect operation.

The CLI's explicit FPGA initialization and `--apply-defaults` remain intentional
configuration changes. They happen before the temporary scan snapshot and persist
afterward. If preparation fails, metadata reports partially applied/unknown
configuration. Temporary scan restoration covers FPGA words 0, 1 and 6, the
selected threshold DAC registers, all discriminator-selection registers, masks
and Ctest registers when used, and selected trigger gains when changed. ASIC
values come from measured readback, never defaults. If snapshot readback fails,
no ASIC restoration is invented. I2C control word 60 is idled, not replayed as a
saved command. Cleanup attempts remaining captured registers after an individual
failure, records every failure and preserves the original exception. `restored`
means the restoration commands succeeded. The optional
`--verify-restoration` pass runs after job cleanup under the same session lock:
it captures post-job FPGA words 0, 1 and 6, rereads the ASIC snapshot rows,
idles word 60, restores the exact observed post-job FPGA word 0, and rereads
FPGA words 0, 1 and 6. Its separate report uses `passed`, `failed`, or
`incomplete` status and records execution mode, expected/observed values,
mismatches, missing rows, errors, and cleanup attempts. The verification field
is separate from the primary scan status/result while remaining in the result
and manifest; the CLI prints its errors separately. It never repairs or hides
a mismatch. Word 60 readback semantics remain unresolved; only the idle write
is recorded. A requested verification that does not pass makes the CLI exit
with status 1 while preserving the primary job result. This verifier is for
the reviewed bare-board card and does not establish analog validation.

Each run refuses to overwrite any existing run file. A versioned `metadata.json`
exists before preparation. The existing `thresholdscan_attempts.csv` receives
each completed counter window and `thresholdscan.csv` each complete DAC row;
appends are flushed/fsynced. Metadata uses atomic replacement, file fsync and
POSIX directory fsync. It records the effective table, scan/preparation options,
firmware, board identity when available, source fingerprint, application version,
units, counts, snapshots, terminal status and cleanup outcome. Memory transports
are labelled `simulation`; they are test inputs, not an analog simulator. A dry
run produces no synthetic measurement CSV.

Cancellation mid-point retains completed windows in the attempts CSV. A killed
process leaves a nonterminal manifest with cleanup pending; readers must inspect
status and must not interpret it as successful completion. Counts in a nonterminal
manifest can lag flushed CSV data. Persistent filesystem failure may prevent the
terminal update; callers must surface `result.persistence_errors` and treat the
on-disk manifest as potentially stale. A failed write/fsync can leave an unconfirmed
CSV tail; a recovery reader should validate rows before using that tail. No job
is automatically resumed after interruption. Connection-open/output-initialization
failures occur before acquisition and may have no complete manifest. Port-close
errors remain the session owner's responsibility.

## Desktop threshold simulation (Delivery 4, simulation slice)

```bash
.venv-foundation/bin/python -m pip install -e '.[gui,dev]'
.venv-foundation/bin/radioroc-desktop
# Equivalent module entry point; --help works without Qt:
.venv-foundation/bin/python -m radioroc.gui
```

Choose channels, DAC range, T1/T2, counter window/averages, masks, Ctest and optional
trigger gain. Preview validates settings and shows persistent preparation versus
temporary restoration without opening a session or creating files. Run starts a
new simulation directory; the default path is under ignored `radioroc_runs/simulation`.
Hardware mode supports the separate connection workflow below; threshold Run
uses the owned hardware workflow rather than the simulation transport.

The synthetic curve has configurable midpoint, width, plateau rate and channel
spacing. Counts are deterministic and quantized to the selected counter window.
The model exercises real shared register operations and `ThresholdJob.run` through
a simulated ASIC FIFO/counter transport. It does not model analog electronics,
gain/Ctest response, noise or physical timing accuracy. Its parameters/model label
are recorded in `metadata.json`; plots and reopened manifests label simulation.

`ThresholdWorker` owns one non-daemon Python thread and opens, runs and closes the
session there. A Qt timer polls its mailbox every 100 ms; widgets and Matplotlib
stay on the UI thread, following [Qt's threading rules](https://doc.qt.io/qtforpython-6/overviews/qtdoc-threads-qobject.html).
The mailbox coalesces status events and retains at most 1024 completed DAC rows;
the shared writer independently saves every completed window and point. The
terminal display reports coalesced event counts, cleanup and storage errors.
Terminal delivery waits for session close. Cancel and window-close both request
cooperative cancellation; closing waits for cleanup and leaves failures visible.

Open saved result accepts a manifest or threshold CSV. The reader checks columns,
DACs, finite rates and manifest consistency and shows a valid prefix with warnings
when a tail is malformed. Nonterminal manifests are labelled incomplete; no run
is resumed or rewritten. Legacy CSVs have unknown provenance. This is a display
reader, not a crash-recovery or data-repair service.

GUI tests run offscreen when `[gui]` is installed and are skipped on core-only
installs. `python tools/check_development.py` includes them automatically. A real
desktop launch must be recorded separately from the offscreen checks. Application
bundles, Linux desktop launch and hardware snapshot/restore validation remain
separate tasks.

## Desktop hardware connection (Delivery 4, connection slice)

Select hardware mode, refresh the port candidates and explicitly choose a control
port before connecting. Refresh lists candidates without opening them; matching
VID/PID is not proof of the control interface. Connect opens the selected port
under the existing board lease and reads status word 100. Read status repeats
that read on request; disconnect releases the session. Status values are displayed
without inferring a firmware version or board capability from opaque bits.

The application connection worker owns discovery, transport creation, status
reads and close on one background thread. Widgets poll immutable snapshots.
Busy, timeout, protocol, I/O and close failures remain visible. A failed close
retains the session and ownership for an explicit retry; window close waits for
release. No discovery runs automatically at startup. Simulation and hardware
connection cannot run concurrently in one window.

## Desktop hardware threshold workflow (RADIOROC 06)

Hardware Run is implemented through the existing single `ConnectionWorker`
session owner. The worker owns the connected device, submits the shared
`ThresholdJob`, forwards live point/state events to the UI, performs cleanup and
restoration verification, and closes the session. The UI never performs device
I/O and cannot start a second connection or job while one is active. Preview
remains offline and creates no session or run files.

Hardware jobs must use conservative preparation (`initialize_fpga=False` and
`apply_defaults=False`) unless a separately reviewed operation explicitly asks
for those persistent changes. `verify_restoration=True` is mandatory for every
hardware job. The verifier runs in the same owned session after cleanup; a
mismatch, incomplete readback, cleanup/storage failure, or close failure is a
visible fault. A fault blocks another scan until the operator disconnects and
explicitly acknowledges review. The application does not automatically repair or
retry device state. A failed close retains the session and ownership for an
explicit retry; shutdown reports the failure and waits for bounded cleanup.

The worker exposes live completed points, responsive cancellation during a long
window and after a persisted point, truthful partial results, and saved-run
reopening. Cancellation waits for cleanup and verification before terminal
delivery; the connected session remains open until explicit Disconnect or
window shutdown. Use fake transports for automated checks.
Physical GUI validation is pending and is specified separately in
`docs/hardware/desktop_threshold_validation.md`; it does not inherit the
authorization or evidence from the earlier CLI card.
