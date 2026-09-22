"""Optional Qt acceptance checks; all sessions are simulated and offscreen."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ThresholdGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.window = ThresholdWindow()
        self.window.mode.setCurrentIndex(0)  # this suite only exercises simulation
        self.window.output.setText(str(self.directory))
        self.window.dac_max.setValue(50)
        self.window.window_ms.setValue(1)
        self.serial = patch("serial.Serial", side_effect=AssertionError("GUI opened hardware"))
        self.serial.start()
        self.addCleanup(self.serial.stop)
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        if self.window.worker:
            self.window.cancel_run()
            self.wait_idle()
        self.window.close()
        # deleteLater routes destruction through Qt's own thread-safe
        # mechanism instead of leaving it to Python's cyclic GC, which can
        # run on any thread and crashes destroying a main-thread QTimer.
        self.window.deleteLater()
        self.app.processEvents()

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.window.worker, "worker failed to finish and release session")

    def test_preview_and_invalid_input_are_offline(self):
        self.assertIsNotNone(self.window.preview())
        self.assertIn("temporary_asic_registers", self.window.details.toPlainText())
        self.assertIn("persist", self.window.details.toPlainText())
        self.assertFalse(self.directory.exists())
        self.window.channels.setText("4,4")
        self.window.start_run()
        self.assertIsNone(self.window.worker)
        self.assertIn("unique", self.window.status.text())
        self.assertFalse(self.directory.exists())

    def test_configure_finish_plot_reopen(self):
        self.window.discriminator.setCurrentIndex(1)
        self.window.ctest.setChecked(True)
        self.window.gain.setValue(12)
        self.window.start_run()
        self.assertFalse(self.window.controls.isEnabled())
        self.wait_idle()
        self.assertIn("completed", self.window.status.text())
        self.assertIn("restored", self.window.status.text())
        self.assertEqual(len(self.window.axes.lines), 2)
        self.assertEqual(len(self.window.axes.lines[0].get_xdata()), 3)
        manifest = json.loads((self.directory / "metadata.json").read_text())
        self.assertFalse(manifest["operation"]["scan"]["t1"])
        self.assertEqual(manifest["simulation"]["midpoint"], 500)
        self.window.open_saved(self.directory)
        self.assertIn("SIMULATION", self.window.banner.text())
        self.assertIn("completed", self.window.status.text())
        self.assertEqual(len(self.window.axes.lines[0].get_xdata()), 3)

    def test_cancel_close_keeps_event_loop_responsive_and_waits_for_cleanup(self):
        from PySide6.QtCore import QTimer
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start()
        self.window.show()
        self.window.window_ms.setValue(1000)
        self.window.start_run()
        # Wait for actual running state before closing.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            snap = self.window.worker.snapshot()
            if snap.event and snap.event.status == "running":
                break
            time.sleep(0.005)
        self.assertIsNotNone(snap.event)
        self.assertEqual(snap.event.status, "running")
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.wait_idle()
        heartbeat.stop()
        self.assertGreater(len(ticks), 0)
        self.assertFalse(self.window.isVisible())
        manifest = json.loads((self.directory / "metadata.json").read_text())
        self.assertEqual(manifest["status"], "cancelled")
        self.assertEqual(manifest["cleanup"]["status"], "restored")

    def test_reopen_nonterminal_manifest_is_incomplete(self):
        self.window.start_run()
        self.wait_idle()
        path = self.directory / "metadata.json"
        manifest = json.loads(path.read_text())
        manifest["status"] = "running"
        manifest["cleanup"]["status"] = "pending"
        path.write_text(json.dumps(manifest))
        self.window.open_saved(self.directory)
        self.assertIn("incomplete", self.window.status.text())
        self.assertIn("SIMULATION", self.window.status.text())

    def test_hardware_mode_cannot_start(self):
        self.window.mode.setCurrentIndex(1)
        self.assertFalse(self.window.run_button.isEnabled())
        self.window.start_run()
        self.assertIsNone(self.window.worker)
        self.assertFalse(self.directory.exists())

    def test_close_failure_remains_visible(self):
        from radioroc.application.threshold_worker import ThresholdWorker
        from radioroc.transport.threshold_simulator import create_threshold_simulator
        class BrokenClose:
            def __init__(self, operation, simulation):
                self.inner = create_threshold_simulator(operation, simulation)
            def __enter__(self):
                return self.inner.__enter__()
            def __exit__(self, *args):
                self.inner.__exit__(*args)
                raise OSError("injected session close failure")
        self.window.worker_factory = lambda op, sim: ThresholdWorker(op, sim, session_factory=BrokenClose)
        self.window.show()
        self.window.start_run()
        self.window.close()
        self.wait_idle()
        self.assertTrue(self.window.isVisible())
        self.assertIn("Review errors", self.window.status.text())
        self.assertIn("injected session close failure", self.window.details.toPlainText())


if __name__ == "__main__":
    unittest.main()
