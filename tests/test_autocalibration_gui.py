"""Optional Qt acceptance checks for the hardware-only Autocalibration window.

Mirrors tests/test_scurve_gui.py's structure and conventions; see that module
for the design rationale of each scenario. Unlike ScurveWindow, this window
has no standalone simulation mode, so every scenario here drives a real
``ConnectionWorker`` wired to the same scripted ``ScurveTransport``/
``ThresholdSession`` fakes ``test_autocalibration_jobs.py``'s and
``test_connection_worker.py``'s own autocalibration tests already use,
instead of a simulation worker.
"""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class AutocalibrationGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.application.connection_worker import ConnectionWorker
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.transport.config import RadiorocConnectionConfig
        from tests.test_connection_worker import ThresholdSession
        from tests.test_scurve_jobs import ScurveTransport

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"

        # Same scripted readings/config shape as
        # test_autocalibration_jobs.AutocalibrationJobTests and
        # test_connection_worker's own autocalibration test: a worked
        # 2-channel, tiny-range sequence with hand-verifiable corrections
        # (calibration_after == {4: 42, 5: 22}).
        self.readings = [
            (200, 200), (200, 0), (200, 0),      # step1_zero: 100 -> 0 -> 0, crosses at DAC 5.
            (200, 200), (200, 200), (200, 0),    # step1_full: 100 -> 100 -> 0, crosses at DAC 15.
            (200, 200), (200, 200),              # step2 DAC0: ch4=100, ch5=100
            (200, 100), (200, 200),              # step2 DAC10: ch4=50, ch5=100
            (200, 0), (200, 0),                  # step2 DAC20: ch4=0, ch5=0
        ]
        self.transport = ScurveTransport(point_readings=list(self.readings))
        self.session = ThresholdSession(self.transport)
        self.worker = ConnectionWorker(
            discovery=lambda: (), session_factory=lambda config: self.session)
        self.worker.start()
        self.worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self._wait_for(self.worker, "connected")
        self.addCleanup(self._shut_down_worker)

        self.window = AutocalibrationWindow(connection_worker=self.worker)
        self.addCleanup(self.cleanup_window)
        self.window.output.setText(str(self.directory))
        self.window.probe_dac_min.setValue(0)
        self.window.probe_dac_max.setValue(20)
        self.window.probe_dac_step.setValue(10)
        self.window.transition_dac_step.setValue(10)
        self.window.transition_margin.setValue(5)
        self.window.transition_dac_floor.setValue(20)
        self.window.transition_dac_cap.setValue(20)
        self.window.final_window_before.setValue(5)
        self.window.final_window_after.setValue(5)
        self.window.final_dac_step.setValue(5)

    def _wait_for(self, worker, state, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if worker.snapshot().state == state:
                return
            time.sleep(0.01)
        self.fail(f"worker did not reach {state}: {worker.snapshot()}")

    def _shut_down_worker(self):
        self.app.processEvents()
        if self.worker.is_alive:
            try:
                self.worker.shutdown()
            except Exception:
                pass
            self.worker.join(3)
        self.app.processEvents()

    def cleanup_window(self):
        if self.window._hardware_running:
            self.window.cancel_run()
            self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_idle(self, timeout=15):
        deadline = time.monotonic() + timeout
        while self.window._hardware_running and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(self.window._hardware_running, "job failed to reach a terminal snapshot")

    def test_default_field_values(self):
        window = self.window
        self.assertEqual(window.channels.text(), "4,5")
        self.assertEqual(window.discriminator.currentIndex(), 0)  # T1
        self.assertTrue(window.use_mask.isChecked())
        self.assertFalse(window.use_ctest.isChecked())
        self.assertFalse(window.trigger_level.isChecked())
        self.assertEqual(window.trigger_preamp_gain.value(), 0)
        self.assertEqual(window.trigger_preamp_gain.specialValueText(), "Keep current")
        self.assertFalse(window.initialize_fpga.isChecked())
        self.assertFalse(window.apply_defaults.isChecked())
        self.assertIsNone(window.worker)

    def test_build_operation_produces_a_valid_config(self):
        from radioroc.application.autocalibration import AutocalibrationJobConfig
        operation = self.window.operation()
        self.assertIsInstance(operation, AutocalibrationJobConfig)
        self.assertEqual(operation.channels, [4, 5])
        self.assertTrue(operation.t1)
        self.assertEqual(operation.probe_dac_min, 0)
        self.assertEqual(operation.probe_dac_max, 20)
        self.assertEqual(operation.probe_dac_step, 10)
        self.assertEqual(operation.transition_dac_cap, 20)
        self.assertEqual(operation.final_dac_step, 5)
        operation.validate()  # raises on invalid input; must not raise here.

    def test_operation_rejects_invalid_channels(self):
        self.window.channels.setText("4,")
        with self.assertRaises(ValueError):
            self.window.operation()

    def test_preview_is_offline_and_shows_a_dry_run(self):
        trace_before = list(self.transport.trace)  # connect() already read the status word.
        operation = self.window.preview()
        self.assertIsNotNone(operation)
        text = self.window.details.toPlainText()
        self.assertIn("dry-run", text)
        self.assertIn("temporary_asic_registers", text)
        self.assertIn("preparation_policy", text)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.transport.trace, trace_before)

    def test_run_end_to_end_updates_plot_progress_and_result(self):
        self.window.start_run()
        self.assertFalse(self.window.controls.isEnabled())
        self.wait_idle()
        self.assertIn("completed", self.window.status.text())
        self.assertGreater(len(self.window.axes.lines), 0)
        self.assertGreater(self.window.progress.value(), 0)

        manifest = json.loads((self.directory / "autocalibration_metadata.json").read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(set(manifest["sub_runs"]), {"step1_zero", "step1_full", "step2", "final"})

        details = json.loads(self.window.details.toPlainText())
        self.assertEqual(details["status"], "completed")
        self.assertEqual(details["reference_channel"], 4)
        self.assertEqual(details["calibration_before"], {"4": 32, "5": 32})
        self.assertEqual(details["calibration_after"], {"4": 42, "5": 22})
        self.assertIsNone(self.window.worker)

    def test_cancel_calls_worker_and_updates_status(self):
        calls = []
        self.window.connection_worker.cancel_autocalibration = lambda: calls.append(1)
        self.window._hardware_running = True
        self.window.cancel_button.setEnabled(True)
        self.window.cancel_run()
        self.assertEqual(calls, [1])
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.assertIn("Cancelling", self.window.status.text())
        self.window._hardware_running = False  # avoid cleanup_window waiting on nothing

    def test_cancel_without_a_worker_is_a_no_op(self):
        self.window.connection_worker = None
        self.window.cancel_run()  # must not raise
        self.assertFalse(self.window.cancel_button.isEnabled())

    def test_open_saved_shows_the_final_sub_scan_by_default(self):
        self.window.start_run()
        self.wait_idle()
        self.window.axes.clear()  # prove open_saved re-plots rather than reusing state

        self.window.open_saved(self.directory)
        self.assertIn("SAVED RESULT", self.window.banner.text())
        self.assertIn("final", self.window.status.text())
        self.assertGreater(len(self.window.axes.lines), 0)
        details = json.loads(self.window.details.toPlainText())
        self.assertEqual(details["status"], "completed")
        self.assertEqual(set(details["sub_run_points"]),
                         {"step1_zero", "step1_full", "step2", "final"})

    def test_open_saved_with_no_sub_runs_shows_an_empty_plot(self):
        from radioroc.data.autocalibration_reader import SavedAutocalibrationRun

        empty = SavedAutocalibrationRun(self.directory, {"status": "completed"}, {},
                                        "completed", ())
        with patch("radioroc.gui.autocalibration_window.read_autocalibration_run",
                   return_value=empty):
            self.window.open_saved(self.directory)
        self.assertEqual(len(self.window.axes.lines), 0)
        self.assertIn("no sub-scan data", self.window.status.text())

    def test_choose_saved_opens_the_selected_path(self):
        self.window.start_run()
        self.wait_idle()
        with patch("radioroc.gui.autocalibration_window.QFileDialog.getOpenFileName",
                   return_value=(str(self.directory), "")):
            self.window.choose_saved()
        self.assertIn("SAVED RESULT", self.window.banner.text())

    def test_run_button_disabled_without_a_connected_worker(self):
        from radioroc.application.connection_worker import ConnectionWorker
        from radioroc.gui.autocalibration_window import AutocalibrationWindow

        idle_worker = ConnectionWorker(discovery=lambda: (), session_factory=lambda config: None)
        idle_worker.start()
        self.addCleanup(lambda: (idle_worker.shutdown(), idle_worker.join(3)))
        window = AutocalibrationWindow(connection_worker=idle_worker)
        self.addCleanup(window.close)
        self.assertFalse(window.run_button.isEnabled())
        window.start_run()
        self.assertIsNone(window._active_directory)


if __name__ == "__main__":
    unittest.main()
