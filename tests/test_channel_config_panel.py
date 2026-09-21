"""Offline tests for the shared ChannelConfigPanel widget.

Constructs the panel standalone (no window, no connection at all in most
cases) to prove the extraction is genuinely self-contained; compare with
``tests/test_connection_gui.py``'s channel-config tests, which exercise the
same underlying behavior embedded in ``ThresholdWindow``.
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
class ChannelConfigPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.channel_config_panel import ChannelConfigPanel
        panel = ChannelConfigPanel(worker)
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

    def test_panel_owns_no_worker_until_given_one(self):
        panel = self.make_panel()
        self.assertIsNone(panel.connection_worker)

    def test_build_operation_reflects_the_widgets_and_validates(self):
        panel = self.make_panel()
        panel.channel_config_channels.setText("4")
        panel.channel_config_set_tq_mask.setChecked(True)
        panel.channel_config_set_input_dac_value.setChecked(True)
        panel.channel_config_input_dac_value.setValue(200)
        panel.channel_config_restore.setChecked(True)
        operation = panel.build_operation()
        self.assertEqual(operation.tq_mask_channels, (4,))
        self.assertEqual(operation.input_dac_value_channels, (4,))
        self.assertEqual(operation.input_dac_value, 200)
        self.assertTrue(operation.restore)

    def test_build_operation_rejects_incomplete_input(self):
        panel = self.make_panel()
        panel.channel_config_channels.setText("4")
        # No field is actually requested (tq mask/dac-enable/dac-value all
        # unchecked): nothing to apply.
        with self.assertRaises(ValueError):
            panel.build_operation()

    def test_apply_without_a_worker_is_a_noop(self):
        panel = self.make_panel(None)
        self.assertIsNone(panel.apply())

    def test_apply_submits_operation_and_shows_verified_result(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.channel_config_channels.setText("4")
        panel.channel_config_set_tq_mask.setChecked(True)
        operation = panel.apply()
        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        self.assertIn("verified", panel.channel_config_status.text())

    def test_apply_reports_a_validation_error_on_its_own_status_label(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        result = panel.apply()
        self.assertIsNone(result)
        self.assertIn("Invalid channel configuration", panel.channel_config_status.text())
        self.assertEqual(worker.channel_config_calls, [])

    def test_apply_reports_a_submission_error_on_its_own_status_label(self):
        worker = FakeWorker(raise_on_apply=RuntimeError("bus busy"))
        panel = self.make_panel(worker)
        panel.channel_config_channels.setText("4")
        panel.channel_config_set_tq_mask.setChecked(True)
        result = panel.apply()
        self.assertIsNone(result)
        self.assertIn("Channel config error", panel.channel_config_status.text())
        self.assertIn("bus busy", panel.channel_config_status.text())

    def test_connection_worker_can_be_swapped_in_after_construction(self):
        # This is how an embedding window keeps the panel in sync with a
        # ConnectionPanel's worker, which does not exist until first connect.
        panel = self.make_panel(None)
        self.assertIsNone(panel.apply())
        worker = FakeWorker()
        panel.connection_worker = worker
        panel.channel_config_channels.setText("4")
        panel.channel_config_set_tq_mask.setChecked(True)
        self.assertIsNotNone(panel.apply())


class FakeWorker:
    def __init__(self, raise_on_apply=None):
        from radioroc.application.channel_config import ChannelConfigResult
        self.channel_config_calls = []
        self.raise_on_apply = raise_on_apply
        self._result = ChannelConfigResult(
            applied=("tq_mask channel=4 -> 1",), touched_rows=1,
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
