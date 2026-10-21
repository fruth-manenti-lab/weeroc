#!/usr/bin/env python3
"""Run the same steps as .github/workflows/python.yml in clean virtual environments.

Why: the everyday environment (.venv-foundation) has PySide6 and an editable install, so
`tools/check_development.py` can pass there while GitHub's check fails. CI installs
`.[analysis,dev]` WITHOUT PySide6 (GUI tests must skip, not error), uses a normal
(non-editable) install, builds the wheel and then checks it from a separate environment.

Usage (needs network for pip and build; takes a few minutes per Python):
    python tools/check_ci_parity.py                      # current interpreter
    python tools/check_ci_parity.py --python python3.11  # another interpreter
    python tools/check_ci_parity.py --keep               # keep the temporary directory
Run it with each CI Python (3.11 and 3.13) before pushing a branch that will become a PR.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, env=None, cwd=ROOT):
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, env=env, check=True)


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", default=sys.executable, help="interpreter to build the clean environments with")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--no-gui", action="store_true", help="skip the optional offscreen GUI steps")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="radioroc-ci-"))
    env = dict(os.environ, MPLBACKEND="Agg", PIP_RETRIES="5", PIP_DEFAULT_TIMEOUT="120")
    env.pop("PYTHONPATH", None)  # CI has none; a stray src/ path would hide packaging errors
    try:
        dev = work / "dev"
        run([args.python, "-m", "venv", dev])
        dev_python = venv_python(dev)
        run([dev_python, "-m", "pip", "install", "-q", ".[analysis,dev]"], env=env)
        # Step: python tools/check_development.py  (no PySide6 here: GUI tests must skip, not error)
        run([dev_python, "tools/check_development.py"], env=env)
        run([dev_python, "-m", "build", "--outdir", work / "dist"], env=env)
        wheel = next((work / "dist").glob("*.whl"))

        wheel_env = work / "wheel"
        run([args.python, "-m", "venv", wheel_env])
        wheel_python = venv_python(wheel_env)
        run([wheel_python, "-m", "pip", "install", "-q", wheel], env=env)
        run([wheel_python, "tools/check_installed_package.py"], env=env)
        run([wheel_python, "-m", "pip", "install", "-q", f"{wheel}[analysis]"], env=env)
        run([wheel_python, "tools/check_installed_package.py", "--plot"], env=env)
        if not args.no_gui:
            gui_env = dict(env, QT_QPA_PLATFORM="offscreen")
            run([wheel_python, "-m", "pip", "install", "-q", f"{wheel}[gui]"], env=gui_env)
            run([wheel_python, "tools/check_installed_package.py", "--gui", "--plot"], env=gui_env)
            run([wheel_python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_threshold_gui.py", "-v"],
                env=gui_env)
        print(f"\nCI parity checks passed with {args.python}.")
        return 0
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
