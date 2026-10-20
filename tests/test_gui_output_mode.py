"""Offscreen checks: run directory follows Simulation/Hardware mode, saved autocalibration
results populate the controls, and hold-scan labels follow the hold mode."""

import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_WINDOWS = (("radioroc.gui.threshold_window", "ThresholdWindow"),
            ("radioroc.gui.hold_scan_window", "HoldScanWindow"),
            ("radioroc.gui.scurve_window", "ScurveWindow"),
            ("radioroc.gui.acquisition_window", "AcquisitionWindow"))


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class OutputModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        serial = patch("serial.Serial", side_effect=AssertionError("GUI opened hardware"))
        serial.start()
        self.addCleanup(serial.stop)

    def make(self, module, name):
        window = getattr(importlib.import_module(module), name)()
        self.addCleanup(self._close, window)
        return window

    def _close(self, window):
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_output_follows_mode_for_every_window(self):
        for module, name in _WINDOWS:
            with self.subTest(window=name):
                window = self.make(module, name)
                self.assertEqual(window.mode.currentIndex(), 1)
                self.assertIn("hardware", Path(window.output.text()).parts)
                window.mode.setCurrentIndex(0)
                simulation_path = Path(window.output.text())
                self.assertEqual(simulation_path.parent.name, "simulation")
                self.assertEqual(simulation_path.parent.parent.name, "radioroc_runs")
                window.mode.setCurrentIndex(1)
                self.assertEqual(Path(window.output.text()).parent.name, "hardware")
                # A user-chosen path survives mode changes in both directions.
                custom = str(Path(self.tmp.name) / "my_run")
                window.output.setText(custom)
                window.mode.setCurrentIndex(0)
                self.assertEqual(window.output.text(), custom)
                window.mode.setCurrentIndex(1)
                self.assertEqual(window.output.text(), custom)

    def test_run_start_guard_regenerates_auto_and_refuses_user_chosen(self):
        for module, name in _WINDOWS:
            with self.subTest(window=name):
                window = self.make(module, name)
                window.mode.setCurrentIndex(0)
                # Stale auto default pasted back in: regenerated.
                stale = str(Path.cwd() / "radioroc_runs" / "hardware" / "20260101-000000-abcdef12")
                window.output.setText(stale)
                window.operation()
                self.assertEqual(Path(window.output.text()).parent.name, "simulation")
                # Hand-chosen path inside the hardware tree: refused, left untouched.
                chosen = str(Path.cwd() / "radioroc_runs" / "hardware" / "my_custom_run")
                window.output.setText(chosen)
                with self.assertRaises(ValueError):
                    window.operation()
                self.assertEqual(window.output.text(), chosen)

    def test_hold_simulation_run_writes_to_simulation_tree(self):
        from radioroc.gui.hold_scan_window import HoldScanWindow
        window = HoldScanWindow()
        self.addCleanup(self._close, window)
        window.mode.setCurrentIndex(0)
        window.hold_mode.setCurrentIndex(0)
        window.hold_max.setValue(10)
        window.hold_step.setValue(5)
        window.acquisitions.setValue(2)
        directory = Path(window.output.text())
        self.assertEqual(directory.parent.name, "simulation")
        window.start_run()
        deadline = time.monotonic() + 15
        while window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertTrue((directory / "metadata.json").is_file())
        self.assertFalse((Path("radioroc_runs") / "hardware").exists())

    def test_hold_labels_and_axis_follow_hold_mode(self):
        from radioroc.gui.hold_scan_window import HoldScanWindow
        window = HoldScanWindow()
        self.addCleanup(self._close, window)
        form = window.controls.layout()
        window.hold_mode.setCurrentIndex(1)
        self.assertIn("(ns)", form.labelForField(window.hold_min).text())
        window.hold_mode.setCurrentIndex(0)
        for field in (window.hold_min, window.hold_max):
            text = form.labelForField(field).text()
            self.assertIn("code", text)
            self.assertNotIn("ns", text)
        self.assertNotIn("ns", form.labelForField(window.hold_step).text())
        window._plot((), "hold_code", "t")
        self.assertIn("code", window.axes.get_xlabel().lower())
        window.hold_mode.setCurrentIndex(1)
        self.assertIn("(ns)", form.labelForField(window.hold_max).text())
        self.assertEqual(window.hold_max.suffix(), " ns")

    def test_autocalibration_reopen_populates_controls_from_manifest(self):
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        directory = Path(self.tmp.name) / "saved"
        directory.mkdir()
        operation = {
            "channels": [4, 6, 32], "t1": False, "use_mask": False, "use_ctest": True,
            "clock_index": 2, "trigger_level": True, "trigger_preamp_gain": 7,
            "out_dir": str(directory), "config_path": None, "initialize_fpga": False,
            "apply_defaults": False, "probe_dac_min": 10, "probe_dac_max": 900,
            "probe_dac_step": 25, "transition_dac_step": 8, "transition_margin": 120,
            "transition_dac_floor": 200, "transition_dac_cap": 1000, "final_window_before": 40,
            "final_window_after": 90, "final_dac_step": 3, "target_percent": 50.0}
        (directory / "autocalibration_metadata.json").write_text(json.dumps(
            {"operation": operation, "status": "completed", "sub_runs": {}, "error": None,
             "warnings": []}))
        window = AutocalibrationWindow()
        self.addCleanup(self._close, window)
        self.assertFalse(window.use_ctest.isChecked())
        window.open_saved(directory)
        self.assertEqual(window.channel_select.selected_channels(), [4, 6, 32])
        self.assertTrue(window.use_ctest.isChecked())
        self.assertTrue(window.trigger_level.isChecked())
        self.assertEqual(window.discriminator.currentIndex(), 1)
        self.assertEqual(window.clock_index.value(), 2)
        self.assertEqual(window.trigger_preamp_gain.value(), 7)
        self.assertEqual(window.probe_dac_max.value(), 900)
        self.assertEqual(window.final_dac_step.value(), 3)
        self.assertIn("saved run's settings", window.banner.text())

    def test_other_windows_mark_controls_as_not_describing_saved_run(self):
        import inspect
        for module, name in _WINDOWS:
            source = inspect.getsource(getattr(importlib.import_module(module), name).open_saved)
            self.assertIn("Controls show current settings", source)


if __name__ == "__main__":
    unittest.main()
