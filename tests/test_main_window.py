"""Offline tests for the shared shell (MainWindow)."""

import importlib.util
import os
import time
import unittest

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.transport.config import RadiorocConnectionConfig
from radioroc.transport.discovery import BoardPort

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _FakeConnectionWorker(ConnectionWorker):
    def __init__(self):
        super().__init__(discovery=lambda: (), session_factory=lambda config: _FakeSession())


_CANDIDATE = BoardPort("fake-control", "Fake board", 0x0403, 0x6010, "fake", "1-1", None)


class _FakeConnectionWorkerWithCandidate(ConnectionWorker):
    def __init__(self):
        super().__init__(discovery=lambda: (_CANDIDATE,), session_factory=lambda config: _FakeSession())


class _FakeSession:
    """Matches the session contract other GUI tests already use (e.g.
    tests/test_connection_gui.py's own FakeSession): __enter__ returns self,
    which then answers read_word/close directly -- not a raw transport.
    A prior version of this fixture returned a bare RadiorocMemoryTransport,
    which nothing here ever actually connected through until RADIOROC 27's
    new connection-propagation test tried to -- and it left the worker
    thread stuck in "close_failed" instead of "stopped" on shutdown, hanging
    the whole test process at interpreter exit.
    """

    def __enter__(self):
        return self

    def read_word(self, address):
        return "00000101"

    def close(self):
        pass


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class MainWindowTests(unittest.TestCase):
    def setUp(self):
        _app()

    def _make_window(self, connection_worker_factory=_FakeConnectionWorker):
        from radioroc.gui.main_window import MainWindow
        window = MainWindow(connection_worker_factory=connection_worker_factory)
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
        # Construction now triggers an automatic refresh (see
        # test_port_candidates_are_discovered_automatically_without_a_manual_refresh),
        # so the worker briefly passes through "discovering" first.
        worker = window.connection_panel.connection_worker
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state == "discovering":
            _app().processEvents()
            time.sleep(0.01)
        # Deterministic instead of waiting on the ConnectionPanel's own
        # 100ms poll timer to happen to tick before the next assertion.
        window.connection_panel.poll()
        window._refresh_status_strip()
        self.assertIn("Not connected", window.status_strip.text())

    def test_scan_windows_reflect_a_shared_connection_reaching_connected(self):
        # Found by physically validating the S-curve GUI path on real
        # hardware (RADIOROC 27): each scan window's own
        # status_changed -> poll_connection_worker wiring only self-connects
        # when it owns its ConnectionPanel; an injected worker means nothing
        # tells the window the shared connection changed state, so its run
        # button gating would otherwise stay stuck at its just-constructed
        # "not connected" reading forever.
        window = self._make_window()
        scan_windows = (window.threshold_window, window.hold_scan_window, window.scurve_window)
        for scan_window in scan_windows:
            scan_window.mode.setCurrentIndex(1)  # Hardware connection
        _app().processEvents()
        for scan_window in scan_windows:
            self.assertFalse(scan_window.run_button.isEnabled())

        worker = window.connection_panel.connection_worker
        worker.connect(RadiorocConnectionConfig("fake-port", 115200, 0.5))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state != "connected":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "connected")
        # Deterministic instead of waiting on the ConnectionPanel's own
        # 100ms poll timer to happen to tick before the next assertion.
        window.connection_panel.poll()

        for scan_window in scan_windows:
            self.assertTrue(scan_window.run_button.isEnabled(),
                            f"{type(scan_window).__name__} run button should reflect the "
                            "now-connected shared worker")

    def test_port_candidates_are_discovered_automatically_without_a_manual_refresh(self):
        # The operator found this the hard way: opening the app left the
        # port dropdown empty until Refresh was clicked once, even though
        # the shared worker is already running by construction time (unlike
        # a standalone scan window, which stays lazy on purpose).
        window = self._make_window(_FakeConnectionWorkerWithCandidate)
        worker = window.connection_panel.connection_worker
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state == "discovering":
            _app().processEvents()
            time.sleep(0.01)
        # Deterministic instead of waiting on the ConnectionPanel's own
        # 100ms poll timer to happen to tick before the next assertion.
        window.connection_panel.poll()
        self.assertGreater(window.connection_panel.port_select.count(), 1)
        candidate = window.connection_panel.port_select.itemData(1)
        self.assertEqual(candidate.port, _CANDIDATE.port)

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
