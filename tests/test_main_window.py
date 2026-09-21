"""Offline tests for the shared shell (MainWindow)."""

import time
import unittest

from PySide6.QtWidgets import QApplication

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.gui.main_window import MainWindow
from radioroc.transport.memory import RadiorocMemoryTransport


def _app():
    return QApplication.instance() or QApplication([])


class _FakeConnectionWorker(ConnectionWorker):
    def __init__(self):
        super().__init__(discovery=lambda: (), session_factory=lambda config: _FakeSession())


class _FakeSession:
    def __enter__(self):
        return RadiorocMemoryTransport()

    def __exit__(self, *exc_info):
        return False


class MainWindowTests(unittest.TestCase):
    def setUp(self):
        _app()

    def _make_window(self):
        window = MainWindow(connection_worker_factory=_FakeConnectionWorker)
        self.addCleanup(self._shut_down, window)
        return window

    @staticmethod
    def _shut_down(window):
        """Worker threads are non-daemon by design; leaving one running after
        a test returns hangs interpreter exit, not just the test itself.
        Processing events around the shutdown avoids a QTimer/QObject
        teardown racing against the worker thread's own exit."""
        _app().processEvents()
        worker = window.connection_panel.connection_worker
        if worker is not None and worker.snapshot().state != "stopped":
            try:
                worker.shutdown()
            except Exception:
                pass
            worker.join(3)
        _app().processEvents()
        window.deleteLater()
        _app().processEvents()

    def test_one_worker_is_shared_by_every_page(self):
        window = self._make_window()
        worker = window.connection_panel.connection_worker
        self.assertIsNotNone(worker)
        self.assertIs(worker, window.threshold_window.connection_worker)
        self.assertIs(worker, window.hold_scan_window.connection_worker)
        self.assertIs(worker, window.scurve_window.connection_worker)
        self.assertIs(worker, window.channel_config_panel.connection_worker)

    def test_scan_windows_have_no_embedded_connection_ui_when_shared(self):
        window = self._make_window()
        for scan_window in (window.threshold_window, window.hold_scan_window,
                           window.scurve_window):
            self.assertIsNone(scan_window._connection_panel)
            self.assertIsNone(scan_window._channel_config_panel)

    def test_sidebar_switches_pages(self):
        window = self._make_window()
        self.assertEqual(window.pages.currentIndex(), 0)
        window.sidebar.setCurrentRow(1)
        self.assertEqual(window.pages.currentIndex(), 1)

    def test_status_strip_reflects_worker_state(self):
        window = self._make_window()
        window._refresh_status_strip()
        self.assertIn("Not connected", window.status_strip.text())

    def test_close_shuts_down_the_shared_worker_once(self):
        window = self._make_window()
        worker = window.connection_panel.connection_worker
        window.close()
        for _ in range(200):
            _app().processEvents()
            if worker.snapshot().state == "stopped":
                break
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "stopped")


if __name__ == "__main__":
    unittest.main()
