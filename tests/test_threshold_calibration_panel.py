"""Offline tests for the ThresholdCalibrationPanel widget.

Mirrors tests/test_input_dac_grid_panel.py's conventions: skip guard,
offscreen platform, and a fake/recording connection worker.
"""

import importlib.util
import os
import unittest
from types import SimpleNamespace

# Bootstrap the checkout package when test discovery sees an older installed wheel.
import radioroc_client  # noqa: F401

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ThresholdCalibrationPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.threshold_calibration_panel import ThresholdCalibrationPanel
        panel = ThresholdCalibrationPanel(worker)
        self.addCleanup(self._cleanup_widget, panel)
        return panel

    def _cleanup_widget(self, widget):
        # deleteLater routes destruction through Qt's own thread-safe
        # mechanism instead of leaving it to Python's cyclic GC, which can
        # run on any thread and crashes destroying a main-thread QTimer --
        # even for a plain QWidget with no timer of its own, since its Qt
        # signal/slot connections can keep it alive in a reference cycle
        # only cyclic GC (not refcounting) ever breaks, at an unpredictable
        # later moment on an unpredictable thread.
        widget.deleteLater()
        self.app.processEvents()

    def test_panel_has_64_spinboxes_per_grid_defaulting_to_32_in_range(self):
        panel = self.make_panel()
        self.assertEqual(len(panel.t1_spinboxes), 64)
        self.assertEqual(len(panel.t2_spinboxes), 64)
        for spin in list(panel.t1_spinboxes) + list(panel.t2_spinboxes):
            self.assertEqual(spin.value(), 32)
            self.assertEqual(spin.minimum(), 0)
            self.assertEqual(spin.maximum(), 63)

    def test_apply_submits_all_64_values_per_grid_reflecting_changes(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.t1_spinboxes[4].setValue(10)
        panel.t1_spinboxes[10].setValue(0)
        panel.t2_spinboxes[7].setValue(63)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        t1_values = operation.t1_calibration_dac_values
        t2_values = operation.t2_calibration_dac_values
        self.assertEqual(len(t1_values), 64)
        self.assertEqual(len(t2_values), 64)
        self.assertEqual(t1_values[4], 10)
        self.assertEqual(t1_values[10], 0)
        self.assertEqual(t1_values[0], 32)
        self.assertEqual(t2_values[7], 63)
        self.assertEqual(t2_values[0], 32)

    def test_set_all_on_t1_does_not_affect_t2(self):
        panel = self.make_panel()
        panel.t1_set_all_spinbox.setValue(15)
        panel.t1_set_all_button.click()
        for spin in panel.t1_spinboxes:
            self.assertEqual(spin.value(), 15)
        for spin in panel.t2_spinboxes:
            self.assertEqual(spin.value(), 32)

    def test_set_all_on_t2_does_not_affect_t1(self):
        panel = self.make_panel()
        panel.t2_set_all_spinbox.setValue(50)
        panel.t2_set_all_button.click()
        for spin in panel.t2_spinboxes:
            self.assertEqual(spin.value(), 50)
        for spin in panel.t1_spinboxes:
            self.assertEqual(spin.value(), 32)

    def test_apply_without_a_worker_is_a_noop(self):
        panel = self.make_panel(None)
        self.assertIsNone(panel.apply())

    def test_apply_reports_a_submission_error_on_its_own_status_label(self):
        worker = FakeWorker(raise_on_apply=RuntimeError("bus busy"))
        panel = self.make_panel(worker)
        before = panel.status_label.text()
        result = panel.apply()
        self.assertIsNone(result)
        self.assertNotEqual(panel.status_label.text(), before)
        self.assertTrue(panel.status_label.text())
        self.assertIn("bus busy", panel.status_label.text())


class FakeWorker:
    def __init__(self, raise_on_apply=None):
        from radioroc.application.channel_config import ChannelConfigResult
        self.channel_config_calls = []
        self.raise_on_apply = raise_on_apply
        self._result = ChannelConfigResult(
            applied=("t1_calibration_dac channel=4 -> 10",), touched_rows=1,
            verify_mismatches=(), restored=False, restore_mismatches=(),
        )

    def apply_channel_config(self, operation):
        if self.raise_on_apply is not None:
            raise self.raise_on_apply
        self.channel_config_calls.append(operation)

    def channel_config_snapshot(self):
        return self._result if self.channel_config_calls else None

    def snapshot(self):
        # This fake completes synchronously (no separate busy period to
        # model); tests call panel._poll() once to simulate the timer tick
        # that a real, asynchronous ConnectionWorker would eventually fire.
        return SimpleNamespace(state="connected")


if __name__ == "__main__":
    unittest.main()
