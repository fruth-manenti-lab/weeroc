"""Offline tests for the MainPanel widget.

Mirrors tests/test_threshold_calibration_panel.py's conventions: skip guard,
offscreen platform, and a fake/recording connection worker. Unlike that
panel's 64-cell grids, MainPanel shows one channel's front end at a time, so
these tests also cover channel-switch save/load and the trigger-selection
combo's mapping to RadiorocDevice.TRIGGER_SELECTION_CODES.
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
class MainPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.main_panel import MainPanel
        panel = MainPanel(worker)
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

    def test_default_widget_values_match_the_packaged_defaults(self):
        panel = self.make_panel()
        self.assertEqual(panel.channel_spin.value(), 0)
        self.assertEqual(panel.channel_spin.minimum(), 0)
        self.assertEqual(panel.channel_spin.maximum(), 63)
        self.assertEqual(panel.compensation_spin.value(), 0)
        self.assertEqual(panel.preamp_gain_spin.value(), 8)
        self.assertEqual(panel.high_gain_spin.value(), 8)
        self.assertEqual(panel.high_gain_shaping_spin.value(), 4)
        self.assertFalse(panel.high_gain_shaping_slow_check.isChecked())
        self.assertEqual(panel.low_gain_spin.value(), 8)
        self.assertEqual(panel.low_gain_shaping_spin.value(), 4)
        self.assertFalse(panel.low_gain_shaping_slow_check.isChecked())
        self.assertEqual(panel.t1_threshold_spin.value(), 0)
        self.assertEqual(panel.t2_threshold_spin.value(), 2)
        self.assertEqual(panel.tq_threshold_spin.value(), 520)
        self.assertEqual(panel.trigger_selection_combo.currentText(), "Global T1")
        self.assertEqual(panel.delay_spin.value(), 255)
        self.assertEqual(panel.slope_spin.value(), 4)

    def test_trigger_selection_combo_lists_expected_items_in_order(self):
        panel = self.make_panel()
        expected = ["External", "Local T1", "Local T2", "Local TQ",
                    "Global T1", "Global T2", "Global TQ"]
        actual = [panel.trigger_selection_combo.itemText(i)
                 for i in range(panel.trigger_selection_combo.count())]
        self.assertEqual(actual, expected)

    def test_switching_channel_preserves_the_previous_channels_edits(self):
        panel = self.make_panel()
        panel.preamp_gain_spin.setValue(40)
        panel.compensation_spin.setValue(3)
        panel.high_gain_shaping_slow_check.setChecked(True)
        panel.channel_spin.setValue(5)
        # Channel 5 was never visited before, so it loads the packaged default.
        self.assertEqual(panel.preamp_gain_spin.value(), 8)
        self.assertEqual(panel.compensation_spin.value(), 0)
        self.assertFalse(panel.high_gain_shaping_slow_check.isChecked())
        panel.channel_spin.setValue(0)
        # Switching back to channel 0 restores its edited values.
        self.assertEqual(panel.preamp_gain_spin.value(), 40)
        self.assertEqual(panel.compensation_spin.value(), 3)
        self.assertTrue(panel.high_gain_shaping_slow_check.isChecked())

    def test_build_operation_includes_every_visited_channel_including_switched_away(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.preamp_gain_spin.setValue(40)
        panel.channel_spin.setValue(5)
        panel.preamp_gain_spin.setValue(20)
        # Switch away from channel 5 without an explicit save call; Apply
        # must still see channel 5's edited value via build_operation's own
        # save step, not just the currently-displayed channel (0).
        panel.channel_spin.setValue(0)
        operation = panel.build_operation()
        self.assertEqual(operation.trigger_preamp_gain_values[0], 40)
        self.assertEqual(operation.trigger_preamp_gain_values[5], 20)
        self.assertEqual(len(operation.trigger_preamp_gain_values), 2)

    def test_trigger_selection_maps_to_expected_codes(self):
        from radioroc_client import RadiorocDevice
        panel = self.make_panel()
        for index, mode in enumerate(
            ["external", "local_t1", "local_t2", "local_tq",
             "global_t1", "global_t2", "global_tq"]
        ):
            panel.trigger_selection_combo.setCurrentIndex(index)
            operation = panel.build_operation()
            self.assertEqual(operation.trigger_selection, mode)
            self.assertIn(mode, RadiorocDevice.TRIGGER_SELECTION_CODES)

    def test_build_operation_is_valid_and_includes_common_fields(self):
        panel = self.make_panel()
        panel.t1_threshold_spin.setValue(100)
        panel.delay_spin.setValue(50)
        panel.slope_spin.setValue(3)
        operation = panel.build_operation()
        self.assertEqual(operation.t1_threshold_dac, 100)
        self.assertEqual(operation.delay_code, 50)
        self.assertEqual(operation.delay_slope, 3)
        self.assertTrue(operation.verify)

    def test_apply_submits_the_built_operation(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.preamp_gain_spin.setValue(15)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        self.assertEqual(operation.trigger_preamp_gain_values[0], 15)

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

    def test_apply_then_poll_shows_the_snapshot(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.apply()
        panel._poll()
        self.assertIn("write(s)", panel.status_label.text())
        self.assertIn("Main:", panel.status_label.text())


class FakeWorker:
    def __init__(self, raise_on_apply=None):
        from radioroc.application.channel_config import ChannelConfigResult
        self.channel_config_calls = []
        self.raise_on_apply = raise_on_apply
        self._result = ChannelConfigResult(
            applied=("trigger_preamp_gain channel=0 -> 15",), touched_rows=1,
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
