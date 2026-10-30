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


class CustomAsicConfigTests(unittest.TestCase):
    def test_save_load_roundtrip_and_custom_write(self):
        import tempfile
        from pathlib import Path
        from radioroc_client import I2CRow
        from radioroc.application.asic_config_file import load_asic_config, save_asic_config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.csv"
            saved = [I2CRow(0, 1, "00001000"), I2CRow(3, 7, "11110000")]
            self.assertEqual(save_asic_config(saved, path), 2)
            self.assertEqual(load_asic_config(path), saved)
            dev = FakeDevice()
            result = run_chip_init(dev, ChipInitOperation(apply_defaults=True, config_path=path))
            # A partial file overlays the packaged table: its rows win, the rest stay default.
            self.assertGreater(result.rows_written, 2)
            by_key = {(r.add, r.subadd): r.data for r in dev.i2c_rows}
            self.assertEqual((by_key[(0, 1)], by_key[(3, 7)]), ("00001000", "11110000"))

    def test_partial_vendor_style_file_overlays_defaults(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.csv"
            path.write_text("add,subadd,data\r\n0,1,xx1xxxx1\r\n")
            base = FakeDevice()
            run_chip_init(base, ChipInitOperation(apply_defaults=True))
            dev = FakeDevice()
            result = run_chip_init(dev, ChipInitOperation(apply_defaults=True, config_path=path))
            self.assertEqual(result.rows_written, len(base.i2c_rows))
            old = next(r.data for r in base.i2c_rows if (r.add, r.subadd) == (0, 1))
            new = next(r.data for r in dev.i2c_rows if (r.add, r.subadd) == (0, 1))
            self.assertEqual(new, "".join(n if n != "x" else o for n, o in zip("xx1xxxx1", old)))

    def test_malformed_files_rejected(self):
        import tempfile
        from pathlib import Path
        from radioroc.application.asic_config_file import load_asic_config
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.csv"
            for text in ("a,b\n1,2\n", "add,subadd,data\n0,1,101\n", "add,subadd,data\n"):
                bad.write_text(text)
                with self.assertRaises(ValueError):
                    load_asic_config(bad)
            with self.assertRaises(ValueError):
                ChipInitOperation(initialize_fpga=True, config_path=bad).validate()


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class WheelGuardTests(unittest.TestCase):
    def test_unfocused_spin_ignores_wheel_but_focused_accepts(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication, QSpinBox
        from radioroc.gui.spin_util import install_wheel_guard
        app = QApplication.instance() or QApplication([])
        owner = QSpinBox()
        install_wheel_guard(owner)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(10)
        spin.show()

        def wheel():
            event = QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, 120),
                                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            app.sendEvent(spin, event)
        wheel()
        self.assertEqual(spin.value(), 10)
        spin.setFocus()
        app.processEvents()
        if spin.hasFocus():  # offscreen platforms may refuse focus
            wheel()
            self.assertEqual(spin.value(), 11)


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
