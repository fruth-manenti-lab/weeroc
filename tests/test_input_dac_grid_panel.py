"""Offline tests for the InputDacGridPanel widget.

Mirrors tests/test_channel_config_panel.py's conventions: skip guard,
offscreen platform, and a fake/recording connection worker.
"""

import importlib.util
import os
import unittest

# Bootstrap the checkout package when test discovery sees an older installed wheel.
import radioroc_client  # noqa: F401

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class InputDacGridPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.input_dac_grid_panel import InputDacGridPanel
        panel = InputDacGridPanel(worker)
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

    def test_panel_has_64_spinboxes_defaulting_to_128_in_range(self):
        panel = self.make_panel()
        self.assertEqual(len(panel.channel_value_spinboxes), 64)
        for spin in panel.channel_value_spinboxes:
            self.assertEqual(spin.value(), 128)
            self.assertEqual(spin.minimum(), 0)
            self.assertEqual(spin.maximum(), 255)

    def test_apply_submits_all_64_values_reflecting_changes(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.channel_value_spinboxes[4].setValue(200)
        panel.channel_value_spinboxes[10].setValue(0)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        values = operation.input_dac_values
        self.assertEqual(len(values), 64)
        self.assertEqual(values[4], 200)
        self.assertEqual(values[10], 0)
        self.assertEqual(values[0], 128)

    def test_hiz_checked_maps_to_impedance_false(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.hiz_checkbox.setChecked(True)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertIs(operation.input_dac_impedance, False)

    def test_hiz_unchecked_maps_to_impedance_true(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertIs(operation.input_dac_impedance, True)

    def test_all_on_submits_enable_operation_for_all_channels(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        operation = panel.all_on()
        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        self.assertEqual(operation.input_dac_enable_channels, tuple(range(64)))
        self.assertTrue(operation.input_dac_enable_value)
        self.assertIsNone(operation.input_dac_values)

    def test_all_off_submits_enable_operation_for_all_channels(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        operation = panel.all_off()
        self.assertIsNotNone(operation)
        self.assertEqual(operation.input_dac_enable_channels, tuple(range(64)))
        self.assertFalse(operation.input_dac_enable_value)

    def test_apply_without_a_worker_is_a_noop(self):
        panel = self.make_panel(None)
        self.assertIsNone(panel.apply())

    def test_all_on_without_a_worker_is_a_noop(self):
        panel = self.make_panel(None)
        self.assertIsNone(panel.all_on())

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
            applied=("input_dac_value channel=4 -> 200",), touched_rows=1,
            verify_mismatches=(), restored=False, restore_mismatches=(),
        )

    def apply_channel_config(self, operation):
        if self.raise_on_apply is not None:
            raise self.raise_on_apply
        self.channel_config_calls.append(operation)

    def channel_config_snapshot(self):
        return self._result if self.channel_config_calls else None


if __name__ == "__main__":
    unittest.main()
