"""Offline tests for the InputDacGridPanel widget.

Mirrors tests/test_channel_config_panel.py's conventions: skip guard,
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

    def test_attach_hints_wires_the_grid_and_buttons(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow
        from radioroc.gui.hint_bar import HintBar
        panel = self.make_panel()
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        hint = HintBar(window.statusBar(), "default")
        panel.attach_hints(hint)
        hint.eventFilter(panel.channel_value_spinboxes[0], QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), "default")
        hint.eventFilter(panel.apply_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), "default")

    def test_board_state_colouring(self):
        from radioroc.application.board_state import operation_matches, rows_by_address
        from radioroc.application.channel_config import ChannelConfigOperation
        panel = self.make_panel()
        rows = rows_by_address(ChannelConfigOperation().load_rows())
        state = lambda w: w.property("boardState")
        # Find the board default for channel 0's value and for impedance.
        default = next(v for v in range(256)
                       if operation_matches(rows, panel._value_operation(0, v)))
        for spin in panel.channel_value_spinboxes:
            spin.setValue(default)
        default_hiz = not operation_matches(rows, ChannelConfigOperation(input_dac_impedance=True))
        panel.hiz_checkbox.setChecked(default_hiz)
        self.assertIn(state(panel.channel_value_spinboxes[2]), (None, "unknown"))
        panel.set_board_rows(rows)
        self.assertTrue(all(state(s) == "on_board" for s in panel.channel_value_spinboxes))
        self.assertEqual(state(panel.hiz_checkbox), "on_board")
        panel.channel_value_spinboxes[2].setValue((default + 1) % 256)
        self.assertEqual(state(panel.channel_value_spinboxes[2]), "not_on_board")
        self.assertEqual(state(panel.channel_value_spinboxes[3]), "on_board")
        panel.hiz_checkbox.setChecked(not default_hiz)
        self.assertEqual(state(panel.hiz_checkbox), "not_on_board")
        panel.set_board_rows(None)
        self.assertEqual(state(panel.channel_value_spinboxes[0]), "unknown")
        self.assertEqual(state(panel.hiz_checkbox), "unknown")


    def test_adopts_board_values_and_tracks_edits(self):
        panel = self.make_panel()
        state = lambda w: w.property("boardState")
        spin = panel.channel_value_spinboxes[4]
        rows = _rows_after("set_input_dac_value", 4, 77)
        panel.set_board_rows(rows)
        self.assertEqual(spin.value(), 77)
        self.assertEqual(state(spin), "on_board")
        self.assertEqual(panel._edited, set())
        spin.setValue(100)
        self.assertEqual(state(spin), "not_on_board")
        panel.set_board_rows(rows)
        self.assertEqual(spin.value(), 100)
        self.assertEqual(state(spin), "not_on_board")
        panel.set_board_rows(_rows_after("set_input_dac_value", 4, 100))
        self.assertEqual(state(spin), "on_board")
        self.assertNotIn(("value", 4), panel._edited)
        panel.set_board_rows(rows)
        self.assertEqual(spin.value(), 77)
        spin.setValue(5)
        panel.reset_to_board()
        self.assertEqual(spin.value(), 77)
        self.assertEqual(state(spin), "on_board")
        # HiZ follows the board's impedance setting (checked -> impedance False).
        hiz_rows = _rows_after("set_input_dac_impedance", False)
        panel.set_board_rows(hiz_rows)
        self.assertTrue(panel.hiz_checkbox.isChecked())
        self.assertEqual(state(panel.hiz_checkbox), "on_board")
        panel.hiz_checkbox.setChecked(False)
        self.assertEqual(state(panel.hiz_checkbox), "not_on_board")
        panel.reset_to_board()
        self.assertTrue(panel.hiz_checkbox.isChecked())

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
            applied=("input_dac_value channel=4 -> 200",), touched_rows=1,
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
