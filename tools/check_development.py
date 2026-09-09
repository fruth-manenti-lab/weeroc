"""Run the offline development checks without opening a hardware connection."""

from pathlib import Path
import os
import subprocess
import sys


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "MPLBACKEND": "Agg"}
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "radioroc_client.py",
         "radioroc_analysis.py", "scripts", "src", "tests", "tools"],
        cwd=root, env=env, check=True,
    )
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=root, env=env, check=True)
    excluded = {"__init__.py", "radioroc_cli_common.py", "radioroc_env_check.py"}
    commands = sorted(p for p in (root / "scripts").glob("*.py") if p.name not in excluded)
    for script in commands:
        result = subprocess.run([sys.executable, str(script), "--help"], cwd=root,
                                env=env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{script.name}: {result.stdout}\n{result.stderr}")
    print(f"Offline tests and {len(commands)} legacy CLI help checks passed.")


if __name__ == "__main__":
    main()
