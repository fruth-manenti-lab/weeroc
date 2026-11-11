"""Offline tests for the ProbesMasksPanel widget (Enable T1/T2/TQ grids only).

Compare with ``tests/test_channel_config_panel.py``, whose conventions this
mirrors: standalone construction, no real ``ConnectionWorker``, a fake
recording worker.
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
class ProbesMasksPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.probes_masks_panel import ProbesMasksPanel
        panel = ProbesMasksPanel(worker)
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

    def test_apply_probe_submits_only_the_selected_channel_routing(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.probe_channel_spin.setValue(6)
        panel.probe_source_combo.setCurrentIndex(1)

        operation = panel.apply_probe()

        self.assertEqual(operation.analog_probe_sources, {6: "shaper_hg"})
        self.assertIsNone(operation.tq_mask_states)
        self.assertEqual(worker.channel_config_calls, [operation])

    def test_probe_routing_is_exclusive_and_clear_all_button_submits_clear_all(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.probe_source_combo.setCurrentIndex(1)
        self.assertTrue(panel.build_probe_operation().analog_probe_exclusive)
        panel.apply_probe_clear_all()
        self.assertTrue(worker.channel_config_calls[-1].analog_probe_clear_all)

    def test_attach_hints_wires_the_three_grids_and_the_apply_button(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow
        from radioroc.gui.hint_bar import HintBar
        panel = self.make_panel()
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        hint = HintBar(window.statusBar(), "default")
        panel.attach_hints(hint)
        for checkboxes in (panel.t1_checkboxes, panel.t2_checkboxes, panel.tq_checkboxes):
            hint.eventFilter(checkboxes[0], QEvent(QEvent.Type.Enter))
            self.assertNotEqual(window.statusBar().currentMessage(), "default")
        hint.eventFilter(panel.apply_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), "default")

    def test_board_state_colouring(self):
        from radioroc.application.board_state import rows_by_address
        from radioroc.application.channel_config import ChannelConfigOperation
        panel = self.make_panel()
        rows = rows_by_address(ChannelConfigOperation().load_rows())
        state = lambda w: w.property("boardState")
        # Discover each grid's default from the board table, not a guess.
        defaults = {}
        for prefix in ("t1", "t2", "tq"):
            cells = getattr(panel, f"{prefix}_checkboxes")
            for checked in (True, False):
                op = panel._cell_operation(prefix, 0, checked)
                from radioroc.application.board_state import operation_matches
                if operation_matches(rows, op):
                    defaults[prefix] = checked
            self.assertIn(prefix, defaults)
            for cell in cells:
                cell.setChecked(defaults[prefix])
        self.assertIn(state(panel.t1_checkboxes[5]), (None, "unknown"))
        panel.set_board_rows(rows)
        for prefix in ("t1", "t2", "tq"):
            for cell in getattr(panel, f"{prefix}_checkboxes"):
                self.assertEqual(state(cell), "on_board")
        panel.t2_checkboxes[5].setChecked(not defaults["t2"])
        self.assertEqual(state(panel.t2_checkboxes[5]), "not_on_board")
        self.assertEqual(state(panel.t2_checkboxes[6]), "on_board")
        self.assertEqual(state(panel.t1_checkboxes[5]), "on_board")
        # Enable-none/all buttons recolour whole grid.
        panel.tq_enable_all_button.click()
        panel.tq_enable_none_button.click()
        expected = "on_board" if defaults["tq"] is False else "not_on_board"
        self.assertTrue(all(state(c) == expected for c in panel.tq_checkboxes))
        panel.set_board_rows(None)
        self.assertEqual(state(panel.t1_checkboxes[0]), "unknown")
        self.assertEqual(state(panel.tq_checkboxes[0]), "unknown")
        self.assertIn(state(panel.probe_channel_spin), (None,))


    def test_adopts_board_values_and_tracks_edits(self):
        panel = self.make_panel()
        state = lambda w: w.property("boardState")
        button = panel.t1_checkboxes[9]
        self.assertTrue(button.isChecked())
        rows_off = _rows_after("set_mask_for_channel", 9, t1=True, enabled=False)
        rows_on = _rows_after("set_mask_for_channel", 9, t1=True, enabled=True)
        # Pick the variant that differs from the widget's current state.
        from radioroc.application.board_state import operation_matches
        panel.set_board_rows(rows_off)
        self.assertFalse(button.isChecked())
        self.assertEqual(state(button), "on_board")
        self.assertEqual(panel._edited, set())
        button.setChecked(True)
        self.assertEqual(state(button), "not_on_board")
        panel.set_board_rows(rows_off)
        self.assertTrue(button.isChecked())
        self.assertEqual(state(button), "not_on_board")
        panel.set_board_rows(rows_on)
        self.assertEqual(state(button), "on_board")
        self.assertNotIn(("t1", 9), panel._edited)
        panel.set_board_rows(rows_off)
        self.assertFalse(button.isChecked())
        panel.t1_enable_all_button.click()
        self.assertIn(("t1", 9), panel._edited)
        self.assertEqual(state(button), "not_on_board")
        panel.reset_to_board()
        self.assertFalse(button.isChecked())
        self.assertEqual(state(button), "on_board")

def _rows_after(setter_name, *args, **kwargs):
    import contextlib
    import io
    from radioroc.application.board_state import rows_by_address
    from radioroc.application.channel_config import ChannelConfigOperation
    from radioroc_client import RadiorocDevice
    device = RadiorocDevice(None, dry_run=True)
    device.i2c_rows = ChannelConfigOperation().load_rows()
    with contextlib.redirect_stdout(io.StringIO()):
        getattr(device, setter_name)(*args, **kwargs)
    return rows_by_address(device.i2c_rows)



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

    def snapshot(self):
        # This fake completes synchronously (no separate busy period to
        # model); tests call panel._poll() once to simulate the timer tick
        # that a real, asynchronous ConnectionWorker would eventually fire.
        return SimpleNamespace(state="connected")


if __name__ == "__main__":
    unittest.main()
