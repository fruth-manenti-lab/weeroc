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
from radioroc.application.connection_worker import ConnectionWorker

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
assert 'PySide6' not in sys.modules and 'PyQt6' not in sys.modules
# The installed connection service remains usable without Qt or hardware.
worker = ConnectionWorker(discovery=lambda: ())
worker.start()
worker.shutdown()
worker.join(5)
assert not worker.is_alive and worker.snapshot().state == 'stopped'
if sys.argv[3] != 'gui':
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

GUI_PROBE = r'''
from pathlib import Path
import time
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.gui.threshold_window import ThresholdWindow
from radioroc.data.threshold_reader import read_threshold_run
from radioroc.transport.discovery import BoardPort
app = QApplication([])
class OfflineSession:
    def __enter__(self):
        return self
    def read_word(self, address):
        assert address == 100
        return '00000101'
    def close(self):
        pass
candidate = BoardPort('offline-control', 'Offline wheel fixture', 0x0403, 0x6010,
                      'offline', None, None)
window = ThresholdWindow(connection_worker_factory=lambda: ConnectionWorker(
    discovery=lambda: [candidate], session_factory=lambda config: OfflineSession()))
def wait_connection(state):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        app.processEvents()
        if window.connection_worker.snapshot().state == state:
            window.poll_connection_worker()
            return
        time.sleep(0.01)
    raise AssertionError(f'connection did not reach {state}')
window.output.setText(str(Path('desktop-simulation').resolve()))
window.dac_max.setValue(50)
window.window_ms.setValue(1)
with patch('serial.Serial', side_effect=AssertionError('hardware opened')):
    window.show()
    assert window.preview() is not None
    assert not Path('desktop-simulation').exists()
    window.start_run()
    deadline = time.monotonic() + 30
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None
    saved = read_threshold_run(Path('desktop-simulation'))
    assert saved.status == 'completed' and saved.execution_mode == 'simulation'
    assert len(saved.rows) == 3
    window.open_saved(saved.directory)
    assert 'SIMULATION' in window.status.text()
    assert len(window.axes.lines) == 2
    window.mode.setCurrentIndex(1)
    assert not window.run_button.isEnabled()
    window.refresh_connections()
    wait_connection('idle')
    assert window.port_select.currentData() is None
    window.port_select.setCurrentIndex(1)
    window.connect_hardware()
    wait_connection('connected')
    assert window.connection_worker.snapshot().status_word == 5
    assert not window.run_button.isEnabled()
    window.disconnect_hardware()
    wait_connection('idle')
    window.close()
    deadline = time.monotonic() + 10
    while window.connection_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.connection_worker is None
print('Installed GUI simulation/reopen and fake hardware connection passed offline.')
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--gui", action="store_true", help="check optional GUI using Qt offscreen")
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
        commands = json.loads(run(["-c", PROBE, str(root), digest, "gui" if args.gui else "headless"]))
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
        run(["-m", "radioroc.gui", "--help"])
        if args.gui:
            env["QT_QPA_PLATFORM"] = "offscreen"
            print(run(["-c", GUI_PROBE]).strip())
        print(f"Installed package resources and {len(commands)} CLI commands passed outside checkout"
              + ("; headless plot rendered." if args.plot else "."))


if __name__ == "__main__":
    main()
