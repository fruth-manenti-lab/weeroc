"""Offline tests for the ProbesMasksPanel widget (Enable T1/T2/TQ grids only).

Compare with ``tests/test_channel_config_panel.py``, whose conventions this
mirrors: standalone construction, no real ``ConnectionWorker``, a fake
recording worker.
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
class ProbesMasksPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.probes_masks_panel import ProbesMasksPanel
        return ProbesMasksPanel(worker)

    def test_each_grid_has_64_checkboxes_all_checked_by_default(self):
        panel = self.make_panel()
        for checkboxes in (panel.t1_checkboxes, panel.t2_checkboxes, panel.tq_checkboxes):
            self.assertEqual(len(checkboxes), 64)
            self.assertTrue(all(cb.isChecked() for cb in checkboxes))

    def test_apply_submits_operation_reflecting_unchecked_boxes_per_grid(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.t1_checkboxes[4].setChecked(False)
        panel.t2_checkboxes[10].setChecked(False)
        panel.tq_checkboxes[63].setChecked(False)

        operation = panel.apply()

        self.assertIsNotNone(operation)
        self.assertEqual(len(worker.channel_config_calls), 1)
        self.assertEqual(len(operation.t1_mask_states), 64)
        self.assertEqual(len(operation.t2_mask_states), 64)
        self.assertEqual(len(operation.tq_mask_states), 64)
        self.assertFalse(operation.t1_mask_states[4])
        self.assertTrue(operation.t1_mask_states[5])
        self.assertFalse(operation.t2_mask_states[10])
        self.assertTrue(operation.t2_mask_states[11])
        self.assertFalse(operation.tq_mask_states[63])
        self.assertTrue(operation.tq_mask_states[62])

    def test_enable_none_and_enable_all_only_affect_their_own_grid(self):
        panel = self.make_panel()
        panel.t1_enable_none_button.click()
        self.assertTrue(all(not cb.isChecked() for cb in panel.t1_checkboxes))
        self.assertTrue(all(cb.isChecked() for cb in panel.t2_checkboxes))
        self.assertTrue(all(cb.isChecked() for cb in panel.tq_checkboxes))

        panel.t1_enable_all_button.click()
        self.assertTrue(all(cb.isChecked() for cb in panel.t1_checkboxes))

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
            applied=("tq_mask channel=63 -> 0",), touched_rows=64,
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
