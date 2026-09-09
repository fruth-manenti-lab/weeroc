"""Offline Qt checks for the desktop hardware connection boundary."""

import importlib.util
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

# Bootstrap the checkout package when discovery sees an older installed wheel.
import radioroc_client  # noqa: F401

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ConnectionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.transport.discovery import BoardPort
        self.candidate = BoardPort("fake-control", "USB candidate", 0x0403, 0x6010,
                                   "fake", "1-1", None)
        self.sessions = []
        self.serial = patch("serial.Serial", side_effect=AssertionError("GUI opened real hardware"))
        self.serial.start()
        self.addCleanup(self.serial.stop)
        self.window = None
        self.addCleanup(self.cleanup_window)

    def make_window(self, *, discovery=None, session_factory=None):
        from radioroc.application.connection_worker import ConnectionWorker
        from radioroc.gui.threshold_window import ThresholdWindow
        discovery = discovery or (lambda: [self.candidate])
        session_factory = session_factory or self.session_factory
        self.window = ThresholdWindow(connection_worker_factory=lambda: ConnectionWorker(
            discovery=discovery, session_factory=session_factory))
        return self.window

    def session_factory(self, config):
        session = FakeSession()
        self.sessions.append((config, session))
        return session

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail("GUI condition was not reached before timeout")

    def wait_state(self, state):
        self.wait_until(lambda: self.window.connection_worker is not None and
                        self.window.connection_worker.snapshot().state == state)
        self.window.poll_connection_worker()

    def cleanup_window(self):
        if self.window is None:
            return
        worker = self.window.connection_worker
        if worker is not None and worker.is_alive:
            if worker.snapshot().state == "close_failed":
                worker.disconnect()
                self.wait_until(lambda: worker.snapshot().state == "idle")
            worker.shutdown()
            worker.join(3)
        self.window.connection_worker = None
        self.window.close()
        self.app.processEvents()

    def select_hardware_candidate(self):
        self.window.mode.setCurrentIndex(1)
        self.window.refresh_connections()
        self.wait_until(lambda: self.window.connection_worker.snapshot().ports ==
                        (self.candidate,))
        self.window.poll_connection_worker()
        self.assertEqual(self.window.port_select.currentIndex(), 0)
        self.assertFalse(self.window.connect_button.isEnabled())
        self.window.port_select.setCurrentIndex(1)

    def test_explicit_selection_connect_status_disconnect_and_truthful_preview(self):
        window = self.make_window()
        self.assertIsNone(window.connection_worker)
        self.select_hardware_candidate()
        self.assertIn("unverified", window.banner.text())
        self.assertTrue(window.connect_button.isEnabled())

        window.connect_hardware()
        self.wait_state("connected")
        config, session = self.sessions[0]
        self.assertEqual(config.port, "fake-control")
        self.assertEqual(window.firmware_status.text(), "0x05 (5)")
        self.assertFalse(window.run_button.isEnabled())

        session.status = "00001010"
        window.read_hardware_status()
        self.wait_state("connected")
        self.wait_until(lambda: window.connection_worker.snapshot().status_word == 10)
        window.poll_connection_worker()
        self.assertEqual(window.firmware_status.text(), "0x0A (10)")

        window.preview()
        preview = json.loads(window.details.toPlainText())
        self.assertEqual(preview["selected_mode"], "hardware")
        self.assertNotIn("simulation", preview)
        self.assertEqual(preview["hardware"]["port"], "fake-control")

        window.mode.setCurrentIndex(0)
        self.assertEqual(window.mode.currentIndex(), 1)
        window.disconnect_hardware()
        self.wait_state("idle")
        self.assertEqual(session.calls[-1], "close")
        window.mode.setCurrentIndex(0)
        self.assertTrue(window.run_button.isEnabled())

    def test_primary_and_close_errors_are_visible_and_retryable(self):
        session = FakeSession(read_error=OSError("status lost"),
                              close_errors=[OSError("release failed")])
        window = self.make_window(session_factory=lambda config: session)
        self.select_hardware_candidate()
        window.connect_hardware()
        self.wait_state("close_failed")
        self.assertIn("OSError: status lost", window.connection_status.text())
        self.assertIn("OSError: release failed", window.connection_status.text())
        self.assertEqual(window.disconnect_button.text(), "Retry close")
        self.assertFalse(window.mode.isEnabled())

        window.disconnect_hardware()
        self.wait_state("idle")
        self.assertIn("previous errors", window.connection_status.text())
        self.assertEqual(session.calls.count("close"), 2)

    def test_window_close_waits_without_blocking_events_and_failed_close_needs_new_request(self):
        from PySide6.QtCore import QTimer
        entered, release = threading.Event(), threading.Event()
        session = FakeSession(entered=entered, release=release,
                              close_errors=[OSError("first close failed")])
        window = self.make_window(session_factory=lambda config: session)
        self.select_hardware_candidate()
        window.show()
        window.connect_hardware()
        self.assertTrue(entered.wait(3))

        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start()
        QTimer.singleShot(20, release.set)
        window.close()
        self.assertTrue(window.isVisible())
        self.wait_state("close_failed")
        heartbeat.stop()
        self.assertGreater(len(ticks), 0)
        self.assertTrue(window.isVisible())
        self.assertIn("first close failed", window.connection_status.text())
        self.assertFalse(window._closing)

        window.close()
        self.wait_until(lambda: not window.isVisible())
        self.assertIsNone(window.connection_worker)
        self.assertEqual(session.calls.count("close"), 2)


class FakeSession:
    def __init__(self, *, status="00000101", read_error=None, entered=None,
                 release=None, close_errors=None):
        self.status = status
        self.read_error = read_error
        self.entered = entered
        self.release = release
        self.close_errors = list(close_errors or ())
        self.calls = []

    def __enter__(self):
        self.calls.append("enter")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(3)
        return self

    def read_word(self, address):
        self.calls.append(("read", address))
        if self.read_error is not None:
            raise self.read_error
        return self.status

    def close(self):
        self.calls.append("close")
        if self.close_errors:
            raise self.close_errors.pop(0)


if __name__ == "__main__":
    unittest.main()
