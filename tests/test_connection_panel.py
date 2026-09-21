"""Offline Qt checks for the shared ConnectionPanel widget.

Mirrors the fake-worker/fake-session pattern already used by
``tests/test_connection_gui.py`` (which exercises the same behavior through
``ThresholdWindow``), but constructs ``ConnectionPanel`` standalone -- no
window at all -- to prove the extraction is genuinely self-contained.
"""

import importlib.util
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Bootstrap the checkout package when test discovery sees an older installed wheel.
import radioroc_client  # noqa: F401

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ConnectionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.transport.discovery import BoardPort
        self.candidate = BoardPort("fake-control", "USB candidate", 0x0403, 0x6010,
                                   "fake", "1-1", None)
        self.sessions = []
        self.serial = patch("serial.Serial", side_effect=AssertionError("test opened real hardware"))
        self.serial.start()
        self.addCleanup(self.serial.stop)
        self.panel = None
        self.addCleanup(self.cleanup_panel)

    def cleanup_panel(self):
        if self.panel is None:
            return
        worker = self.panel.connection_worker
        if worker is not None and getattr(worker, "is_alive", False):
            worker.shutdown()
            worker.join(3)
        # deleteLater (not just letting Python's GC eventually collect it)
        # routes the QTimer's destruction through Qt's own thread-safe
        # mechanism; a leftover reference cycle collected by the cyclic GC
        # on the wrong thread is what causes "Timers cannot be stopped from
        # another thread" crashes in this test suite.
        self.panel.deleteLater()
        self.app.processEvents()

    def session_factory(self, config):
        session = FakeSession()
        self.sessions.append((config, session))
        return session

    def make_panel(self, *, discovery=None, session_factory=None):
        from radioroc.application.connection_worker import ConnectionWorker
        from radioroc.gui.connection_panel import ConnectionPanel
        discovery = discovery or (lambda: [self.candidate])
        session_factory = session_factory or self.session_factory
        self.panel = ConnectionPanel(connection_worker_factory=lambda: ConnectionWorker(
            discovery=discovery, session_factory=session_factory))
        return self.panel

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail("condition was not reached before timeout")

    def test_worker_is_created_lazily_on_first_use(self):
        panel = self.make_panel()
        self.assertIsNone(panel.connection_worker)
        self.assertFalse(panel.timer.isActive())
        self.assertTrue(panel.refresh())
        self.assertIsNotNone(panel.connection_worker)
        self.assertTrue(panel.timer.isActive())

    def test_refresh_connect_status_and_disconnect_round_trip(self):
        panel = self.make_panel()
        self.assertTrue(panel.refresh())
        self.wait_until(lambda: panel.connection_worker.snapshot().ports == (self.candidate,))
        panel.poll()
        self.assertEqual(panel.port_select.count(), 2)  # placeholder + one candidate
        panel.port_select.setCurrentIndex(1)
        panel.update_controls()
        self.assertTrue(panel.connect_button.isEnabled())

        self.assertTrue(panel.connect_selected())
        self.wait_until(lambda: panel.connection_worker.snapshot().state == "connected")
        panel.poll()
        config, session = self.sessions[0]
        self.assertEqual(config.port, "fake-control")
        self.assertEqual(panel.firmware_status.text(), "0x05 (5)")
        self.assertTrue(panel.disconnect_button.isEnabled())

        self.assertTrue(panel.disconnect())
        self.wait_until(lambda: panel.connection_worker.snapshot().state == "idle")
        self.assertEqual(session.calls[-1], "close")

    def test_a_raised_command_leaves_its_error_on_connection_status(self):
        panel = self.make_panel()

        def boom(worker):
            raise RuntimeError("injected")

        self.assertFalse(panel._run(boom))
        self.assertIn("Connection error", panel.connection_status.text())
        self.assertIn("injected", panel.connection_status.text())

    def test_mode_locked_reflects_connection_state(self):
        panel = self.make_panel()
        self.assertFalse(panel.mode_locked())
        panel.connection_worker = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="connected"))
        self.assertTrue(panel.mode_locked())
        panel.connection_worker = SimpleNamespace(snapshot=lambda: SimpleNamespace(state="idle"))
        self.assertFalse(panel.mode_locked())

    def test_update_controls_respects_commands_available_and_fault_gating(self):
        panel = self.make_panel()
        panel.connection_worker = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(state="faulted", fault="restore mismatch"))
        panel.update_controls(commands_available=True)
        self.assertFalse(panel.refresh_button.isEnabled())
        # "faulted" is a session state, not {idle, error}: review isn't offered yet.
        self.assertFalse(panel.review_fault_button.isEnabled())

        panel.connection_worker = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(state="idle", fault="restore mismatch"))
        panel.update_controls(commands_available=True)
        self.assertTrue(panel.review_fault_button.isEnabled())
        panel.update_controls(commands_available=False)
        self.assertFalse(panel.review_fault_button.isEnabled())

    def test_status_changed_is_emitted_on_every_poll(self):
        panel = self.make_panel()
        ticks = []
        panel.status_changed.connect(lambda: ticks.append(1))
        self.assertTrue(panel.refresh())  # issues the command and polls once internally
        self.assertGreaterEqual(len(ticks), 1)
        panel.poll()
        self.assertGreaterEqual(len(ticks), 2)


class ConnectionWorkerSharedAcrossWindowsTests(unittest.TestCase):
    """A single injected ConnectionWorker must read the same way from every
    window it's handed to -- none of them may create their own."""

    @classmethod
    def setUpClass(cls):
        if not GUI_AVAILABLE:
            raise unittest.SkipTest("install [gui] for desktop acceptance checks")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_one_worker_injected_into_threshold_and_hold_scan_windows(self):
        from radioroc.application.connection_worker import ConnectionWorker
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.threshold_window import ThresholdWindow

        worker = ConnectionWorker(discovery=lambda: [], session_factory=lambda cfg: None)
        worker.start()

        threshold = ThresholdWindow(connection_worker=worker)
        hold_scan = HoldScanWindow(connection_worker=worker)

        def _cleanup():
            threshold.close()
            hold_scan.close()
            worker.shutdown()
            worker.join(3)
            # deleteLater routes destruction through Qt's own thread-safe
            # mechanism instead of leaving it to Python's cyclic GC, which
            # can run on any thread (including the worker thread) and is
            # what causes "Timers cannot be stopped from another thread".
            threshold.deleteLater()
            hold_scan.deleteLater()
            self.app.processEvents()

        self.addCleanup(_cleanup)

        self.assertIs(threshold.connection_worker, worker)
        self.assertIs(hold_scan.connection_worker, worker)
        self.assertFalse(hasattr(threshold, "_connection_panel") and threshold._connection_panel)
        self.assertIsNone(threshold._connection_panel)
        self.assertIsNone(hold_scan._connection_panel)
        # Neither window created its own worker: both read the one snapshot.
        self.assertEqual(threshold.connection_worker.snapshot(), hold_scan.connection_worker.snapshot())


class FakeSession:
    def __init__(self, *, status="00000101"):
        self.status = status
        self.calls = []

    def __enter__(self):
        self.calls.append("enter")
        return self

    def read_word(self, address):
        self.calls.append(("read", address))
        return self.status

    def close(self):
        self.calls.append("close")


if __name__ == "__main__":
    unittest.main()
