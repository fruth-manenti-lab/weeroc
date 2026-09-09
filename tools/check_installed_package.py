"""Verify an installed wheel in isolated Python processes outside the checkout.

Run with the wheel environment's Python. Pass --plot after installing [analysis]
to exercise rendering. No command opens a device or modifies board settings.
"""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROBE = r'''
import hashlib
import importlib.util
from importlib.resources import files
import json
from pathlib import Path
import sys
import radioroc_client
import radioroc_analysis
from radioroc.__main__ import COMMANDS
from radioroc.transport import RadiorocSerial
from radioroc.cli.radioroc_standard_scurves import RadiorocSerial as LegacySerial
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig

repo = Path(sys.argv[1]).resolve()
assert not Path(radioroc_client.__file__).resolve().is_relative_to(repo / 'src')
assert Path(radioroc_client.__file__).resolve() != repo / 'radioroc_client.py'
assert radioroc_client.encode_read_request(100) == bytes.fromhex('aa 00 e4 00 55')
assert radioroc_client.RadiorocSerial is RadiorocSerial is LegacySerial
assert hashlib.sha256(radioroc_client.DEFAULT_CONFIG.read_bytes()).hexdigest() == sys.argv[2]
device = radioroc_client.RadiorocDevice(radioroc_client.RadiorocMemoryTransport(), dry_run=True)
device.load_default_config()
assert len(device.i2c_rows) == 677
resources = files('radioroc.resources')
assert json.loads(resources.joinpath('presets/threshold_ch4_sipm_dark.json').read_text())['channels'] == '4'
assert 'matplotlib.pyplot' not in sys.modules
assert importlib.util.find_spec('PySide6') is None
assert importlib.util.find_spec('PyQt6') is None
# Exercise the packaged workflow/data modules with explicitly synthetic input.
memory = radioroc_client.RadiorocMemoryTransport({4: '00000001'}, {96: (3).to_bytes(4, 'little')})
scan = radioroc_client.ThresholdScanConfig([4], dac_min=0, dac_max=0,
                                         trigger_window_ms=1, out_dir=Path('synthetic-job'))
result = ThresholdJob().run(radioroc_client.RadiorocDevice(memory), ThresholdJobConfig(scan))
assert result.status == 'completed' and result.points == 1
assert result.csv_path.read_text() == 'DAC,ch4\n0,3000.0\n'
manifest = json.loads(result.metadata_path.read_text())
assert manifest['status'] == 'completed' and manifest['execution_mode'] == 'simulation'
print(json.dumps(list(COMMANDS)))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256((root / "configs/radio_default_i2c.csv").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="radioroc-wheel-") as directory:
        work = Path(directory)
        env = {**os.environ, "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(work / "mpl")}

        def run(arguments: list[str]) -> str:
            result = subprocess.run([sys.executable, "-I", *arguments], cwd=work,
                                    env=env, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError(f"{arguments}: {result.stdout}\n{result.stderr}")
            return result.stdout

        import json
        commands = json.loads(run(["-c", PROBE, str(root), digest]))
        run(["-m", "radioroc", "--version"])
        run(["-m", "radioroc", "--help"])
        # Exercise the generated console entry point as well as python -m.
        executable = Path(sys.executable).parent / ("radioroc.exe" if os.name == "nt" else "radioroc")
        subprocess.run([str(executable), "--help"], cwd=work, env=env,
                       check=True, stdout=subprocess.DEVNULL, timeout=30)
        for command in commands:
            run(["-m", "radioroc", command, "--help"])
        preview = json.loads(run(["-m", "radioroc", "threshold-scan", "--port", "/no/hardware",
                                  "--out-dir", str(work / "preview")]))
        assert preview["execution_mode"] == "dry-run"
        assert not (work / "preview").exists()
        if args.plot:
            scan = work / "thresholdscan.csv"
            scan.write_text("DAC,ch4\n0,100\n5,1000\n10,500\n")
            run(["-m", "radioroc", "plot-threshold", str(scan), "--out", str(work / "plot.png")])
            assert (work / "plot.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        print(f"Installed package resources and {len(commands)} CLI commands passed outside checkout"
              + ("; headless plot rendered." if args.plot else "."))


if __name__ == "__main__":
    main()
