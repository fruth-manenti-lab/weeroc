"""Offline tests for the ASIC config Main tab's Initialize FPGA / Apply defaults."""

import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import radioroc_client  # noqa: F401

from radioroc.application.chip_init import ChipInitOperation, run_chip_init

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeDevice:
    def __init__(self):
        self.calls = []
        self.i2c_rows = []

    def initialize_fpga(self):
        self.calls.append("initialize_fpga")

    def apply_default_config(self):
        self.calls.append(f"apply_default_config:{len(self.i2c_rows)}")


class ChipInitCoreTests(unittest.TestCase):
    def test_requires_a_step(self):
        with self.assertRaises(ValueError):
            ChipInitOperation().validate()

    def test_fpga_only_and_defaults_only(self):
        dev = FakeDevice()
        run_chip_init(dev, ChipInitOperation(initialize_fpga=True))
        self.assertEqual(dev.calls, ["initialize_fpga"])
        dev = FakeDevice()
        result = run_chip_init(dev, ChipInitOperation(apply_defaults=True))
        self.assertGreater(result.rows_written, 0)
        self.assertEqual(dev.calls, [f"apply_default_config:{result.rows_written}"])


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class MainPanelChipInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, worker=None):
        from radioroc.gui.main_panel import MainPanel
        panel = MainPanel(worker)
        self.addCleanup(lambda: (panel.deleteLater(), self.app.processEvents()))
        return panel

    def confirm(self, answer):
        return patch("radioroc.gui.main_panel.QMessageBox.question", return_value=answer)

    def test_buttons_disabled_without_worker_or_when_busy(self):
        self.assertFalse(self.make_panel().apply_defaults_button.isEnabled())
        worker = FakeWorker(state="scanning")
        panel = self.make_panel(worker)
        self.assertFalse(panel.initialize_fpga_button.isEnabled())
        worker.state = "connected"
        panel.update_controls()
        self.assertTrue(panel.initialize_fpga_button.isEnabled())
        self.assertTrue(panel.apply_defaults_button.isEnabled())

    def test_initialize_fpga_runs_without_confirmation(self):
        from PySide6.QtWidgets import QMessageBox
        worker = FakeWorker()
        panel = self.make_panel(worker)
        with self.confirm(QMessageBox.StandardButton.No) as question:
            panel.initialize_fpga()
        question.assert_not_called()
        self.assertEqual(worker.calls, [ChipInitOperation(initialize_fpga=True)])
        panel._poll()
        self.assertIn("Initialize FPGA: done", panel.status_label.text())

    def test_apply_defaults_confirms_and_can_be_declined(self):
        from PySide6.QtWidgets import QMessageBox
        worker = FakeWorker()
        panel = self.make_panel(worker)
        with self.confirm(QMessageBox.StandardButton.No):
            self.assertIsNone(panel.apply_defaults())
        self.assertEqual(worker.calls, [])
        with self.confirm(QMessageBox.StandardButton.Yes) as question:
            panel.apply_defaults()
        text = question.call_args.args[2]
        self.assertIn("resets every setting", text)
        self.assertIn("autocalibration trims", text)
        self.assertEqual(worker.calls, [ChipInitOperation(apply_defaults=True)])
        panel._poll()
        self.assertIn("Apply defaults: done", panel.status_label.text())

    def test_failure_is_reported(self):
        from PySide6.QtWidgets import QMessageBox
        worker = FakeWorker()
        panel = self.make_panel(worker)
        with self.confirm(QMessageBox.StandardButton.Yes):
            panel.apply_defaults()
        worker.state, worker.error = "error", "usb gone"
        panel._poll()
        self.assertIn("FAILED", panel.status_label.text())
        self.assertIn("usb gone", panel.status_label.text())

    def test_submission_error_and_hints(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMainWindow
        from radioroc.gui.hint_bar import HintBar
        worker = FakeWorker(raise_on_submit=RuntimeError("busy"))
        panel = self.make_panel(worker)
        panel.initialize_fpga()
        self.assertIn("busy", panel.status_label.text())
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        hint = HintBar(window.statusBar(), "default")
        panel.attach_hints(hint)
        for button in (panel.initialize_fpga_button, panel.apply_defaults_button):
            hint.eventFilter(button, QEvent(QEvent.Type.Enter))
            self.assertNotEqual(window.statusBar().currentMessage(), "default")


class FakeWorker:
    def __init__(self, state="connected", raise_on_submit=None):
        self.state, self.error, self.calls = state, None, []
        self.raise_on_submit = raise_on_submit

    def chip_init(self, operation):
        if self.raise_on_submit is not None:
            raise self.raise_on_submit
        self.calls.append(operation)

    def snapshot(self):
        return SimpleNamespace(state=self.state, error=self.error, fault=None)


if __name__ == "__main__":
    unittest.main()
