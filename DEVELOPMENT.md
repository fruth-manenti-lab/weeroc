# Development

The lab baseline is tagged `pre-desktop-rebuild` (`603c69b`). The first rebuild
branch is `build/python-foundation`. These commits are local until pushed.

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

The base install requires only pySerial; plotting requires `[analysis]`. No Qt,
vendor installer, D2XX library or connected board is needed for offline checks.
The GUI is not implemented yet. Future dependencies will be introduced with the
features that use them. The historical conda environment remains available for
existing lab work.

## Commands and compatibility

The installed `radioroc` command and `python -m radioroc` dispatch to the current
script implementations. `python scripts/radioroc_threshold_scan.py ...` and the
other original commands still work from a source checkout.

Core modules retain the import names `radioroc_client` and `radioroc_analysis`.
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

Existing workflow behavior remains unchanged: some dry-run commands still open
the serial port. Offline checks run help, pure functions and recorded/synthetic
data only. Fixing dry-run hardware access belongs to the upcoming workflow work.

## Build and verify an installed artifact

```bash
python -m build
python -m venv .venv-wheel
.venv-wheel/bin/python -m pip install dist/*.whl
.venv-wheel/bin/python tools/check_installed_package.py
.venv-wheel/bin/python -m pip install 'radioroc-tools[analysis]'
.venv-wheel/bin/python tools/check_installed_package.py --plot
```

The smoke check launches isolated Python processes in a temporary directory,
checks packaged configuration bytes, all 14 commands, and optional headless plot
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
