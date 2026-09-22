"""Offline tests for the RawRegisterPanel widget (F06).

Mirrors tests/test_input_dac_grid_panel.py's conventions: skip guard,
offscreen platform, and a fake/recording connection worker -- plus a fake
that can stay "busy" for a controlled number of poll ticks, since this
panel (unlike its channel-config-family siblings) polls for completion
instead of assuming the result is ready the instant a command is submitted.
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
class RawRegisterPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.raw_register_panel import RawRegisterPanel
        panel = RawRegisterPanel(worker)
        self.addCleanup(self._cleanup_widget, panel)
        return panel

    def _cleanup_widget(self, widget):
        widget.deleteLater()
        self.app.processEvents()

    def test_panel_starts_with_an_empty_table_and_dash_status(self):
        panel = self.make_panel()
        self.assertEqual(panel.table.rowCount(), 0)
        self.assertEqual(panel.status_label.text(), "—")

    def test_read_all_populates_the_table_only_once_polling_detects_completion(self):
        from radioroc_client import I2CRow, bits
        worker = FakeWorker(busy_polls=2)
        worker.rows_result = (I2CRow(4, 0, bits(200, 8)), I2CRow(5, 6, bits(1, 8)))
        panel = self.make_panel(worker)

        panel.read_all()
        self.assertEqual(worker.read_all_calls, 1)
        self.assertIn("Reading", panel.status_label.text())
        self.assertEqual(panel.table.rowCount(), 0)  # not yet -- still "in flight"

        panel._poll()  # still busy (1st of 2)
        self.assertEqual(panel.table.rowCount(), 0)
        panel._poll()  # still busy (2nd of 2)
        self.assertEqual(panel.table.rowCount(), 0)
        panel._poll()  # now resolves
        self.assertEqual(panel.table.rowCount(), 2)
        self.assertEqual(panel.table.item(0, 0).text(), "4")
        self.assertEqual(panel.table.item(0, 1).text(), "0")
        self.assertEqual(panel.table.item(0, 2).text(), bits(200, 8))
        self.assertEqual(panel.table.item(0, 3).text(), "C8")
        self.assertIn("Read 2 register(s)", panel.status_label.text())

    def test_write_register_reports_verified_result_after_polling(self):
        from radioroc.application.raw_registers import RawRegisterResult
        worker = FakeWorker(busy_polls=1)
        panel = self.make_panel(worker)
        panel.write_address.setText("4")
        panel.write_subaddress.setText("0")
        panel.write_data.setText("11001000")

        panel.write_register()
        self.assertEqual(len(worker.write_calls), 1)
        submitted = worker.write_calls[0]
        self.assertEqual((submitted.add, submitted.subadd, submitted.data), (4, 0, "11001000"))

        worker.write_result = RawRegisterResult(4, 0, "11001000", "11001000", False)
        panel._poll()  # still busy
        self.assertIn("Writing", panel.status_label.text())
        panel._poll()  # resolves
        self.assertIn("verified", panel.status_label.text())
        self.assertNotIn("MISMATCH", panel.status_label.text())

    def test_write_register_reports_a_mismatch(self):
        from radioroc.application.raw_registers import RawRegisterResult
        worker = FakeWorker(busy_polls=0)
        worker.write_result = RawRegisterResult(4, 0, "11001000", "00000000", True)
        panel = self.make_panel(worker)
        panel.write_address.setText("4")
        panel.write_subaddress.setText("0")
        panel.write_data.setText("11001000")

        panel.write_register()
        panel._poll()
        self.assertIn("MISMATCH", panel.status_label.text())

    def test_write_register_rejects_invalid_input_before_submitting(self):
        worker = FakeWorker()
        panel = self.make_panel(worker)
        panel.write_address.setText("not-a-number")
        panel.write_subaddress.setText("0")
        panel.write_data.setText("11001000")

        panel.write_register()
        self.assertEqual(worker.write_calls, [])
        self.assertIn("Invalid register write", panel.status_label.text())

    def test_read_all_without_a_worker_is_a_noop(self):
        panel = self.make_panel(None)
        panel.read_all()
        self.assertEqual(panel.table.rowCount(), 0)

    def test_read_all_reports_a_submission_error_on_its_own_status_label(self):
        worker = FakeWorker(raise_on_read_all=RuntimeError("bus busy"))
        panel = self.make_panel(worker)
        panel.read_all()
        self.assertIn("bus busy", panel.status_label.text())
        self.assertIsNone(panel._pending)

    def test_selecting_a_row_populates_the_write_fields(self):
        from radioroc_client import I2CRow, bits
        worker = FakeWorker(busy_polls=0)
        worker.rows_result = (I2CRow(4, 0, bits(200, 8)),)
        panel = self.make_panel(worker)
        panel.read_all()
        panel._poll()

        panel.table.selectRow(0)
        self.assertEqual(panel.write_address.text(), "4")
        self.assertEqual(panel.write_subaddress.text(), "0")
        self.assertEqual(panel.write_data.text(), bits(200, 8))

    def test_attach_hints_wires_the_read_and_write_controls(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow
        from radioroc.gui.hint_bar import HintBar
        panel = self.make_panel()
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        hint = HintBar(window.statusBar(), "default")
        panel.attach_hints(hint)
        hint.eventFilter(panel.read_all_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), "default")
        hint.eventFilter(panel.write_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), "default")


class FakeWorker:
    def __init__(self, *, busy_polls=0, raise_on_read_all=None, raise_on_write=None):
        self.busy_polls = busy_polls
        self._remaining = 0
        self._busy_state = None
        self.read_all_calls = 0
        self.write_calls = []
        self.raise_on_read_all = raise_on_read_all
        self.raise_on_write = raise_on_write
        self.rows_result = ()
        self.write_result = None

    def read_all_registers(self):
        if self.raise_on_read_all is not None:
            raise self.raise_on_read_all
        self.read_all_calls += 1
        self._busy_state = "reading"
        self._remaining = self.busy_polls

    def write_raw_register(self, write):
        if self.raise_on_write is not None:
            raise self.raise_on_write
        self.write_calls.append(write)
        self._busy_state = "configuring"
        self._remaining = self.busy_polls

    def snapshot(self):
        if self._busy_state is not None:
            if self._remaining > 0:
                self._remaining -= 1
                return SimpleNamespace(state=self._busy_state)
            self._busy_state = None
        return SimpleNamespace(state="connected")

    def raw_registers_snapshot(self):
        return self.rows_result

    def raw_register_write_snapshot(self):
        return self.write_result


if __name__ == "__main__":
    unittest.main()
