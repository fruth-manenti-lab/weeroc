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
        self.assertIs(worker, window.autocalibration_window.connection_worker)
        self.assertIs(worker, window.acquisition_window.connection_worker)
        self.assertIs(worker, window.channel_config_panel.connection_worker)
        self.assertIs(worker, window.main_panel.connection_worker)

    def test_autocalibration_window_is_the_fourth_calibration_tab(self):
        window = self._make_window()
        self.assertIs(window.calibration_tabs.widget(3), window.autocalibration_window)
        self.assertEqual(window.calibration_tabs.tabText(3), "Autocalibration")

    def test_acquisition_is_its_own_sidebar_page_left_of_calibration(self):
        # Acquisition used to be the Calibration tab widget's fifth sub-tab;
        # it is now a separate top-level sidebar page, ahead of Calibration,
        # since collecting data is a distinct phase from calibrating (see
        # PLINT_STUDENT_MVP_DIRECTIVE.md's target workflow).
        window = self._make_window()
        self.assertEqual(window.sidebar.count(), 3)
        self.assertEqual(window.sidebar.item(0).text(), "ASIC config.")
        self.assertEqual(window.sidebar.item(1).text(), "Acquisition")
        self.assertEqual(window.sidebar.item(2).text(), "Calibration")
        self.assertIs(window.pages.widget(1).layout().itemAt(0).widget(), window.acquisition_window)
        for index in range(window.calibration_tabs.count()):
            self.assertIsNot(window.calibration_tabs.widget(index), window.acquisition_window)

    def test_main_panel_is_the_first_asic_config_tab(self):
        window = self._make_window()
        # Each ASIC-config tab wraps its panel in a QScrollArea (see
        # IMPLEMENTATION_STATUS.md RADIOROC 31) so tall panels can scroll
        # instead of pushing their own controls off-screen; the panel itself
        # is that scroll area's contained widget.
        self.assertIs(window.asic_config_tabs.widget(0).widget(), window.main_panel)
        self.assertEqual(window.asic_config_tabs.tabText(0), "Main")

    def test_scan_windows_have_no_embedded_connection_ui_when_shared(self):
        window = self._make_window()
        for scan_window in (window.threshold_window, window.hold_scan_window,
                           window.scurve_window, window.acquisition_window):
            self.assertIsNone(scan_window._connection_panel)
            self.assertIsNone(scan_window._channel_config_panel)

    def test_scan_windows_default_to_hardware_mode(self):
        window = self._make_window()
        for scan_window in (window.threshold_window, window.hold_scan_window,
                            window.scurve_window, window.acquisition_window):
            self.assertEqual(scan_window.mode.currentIndex(), 1)
            self.assertEqual(scan_window.mode.currentText(), "Hardware connection")

    def test_sidebar_switches_pages(self):
        window = self._make_window()
        self.assertEqual(window.pages.currentIndex(), 0)
        window.sidebar.setCurrentRow(1)
        self.assertEqual(window.pages.currentIndex(), 1)
        window.sidebar.setCurrentRow(2)
        self.assertEqual(window.pages.currentIndex(), 2)

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
        # threshold/hold-scan/S-curve/acquisition each have their own
        # Simulation/Hardware mode combo box; Autocalibration is
        # hardware-only and has none, so it is exercised alongside the
        # others but not mode-toggled.
        scan_windows = (window.threshold_window, window.hold_scan_window, window.scurve_window,
                        window.acquisition_window)
        all_scan_windows = scan_windows + (window.autocalibration_window,)
        for scan_window in scan_windows:
            scan_window.mode.setCurrentIndex(1)  # Hardware connection
        _app().processEvents()
        for scan_window in all_scan_windows:
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

        for scan_window in all_scan_windows:
            self.assertTrue(scan_window.run_button.isEnabled(),
                            f"{type(scan_window).__name__} run button should reflect the "
                            "now-connected shared worker")

    def test_scan_window_mode_switches_to_hardware_after_connecting_first(self):
        # The operator hit this directly: connect via the shared ASIC-config
        # page first (the normal order -- Threshold/Hold-scan/S-curve don't
        # own a connection of their own to connect from), then try to
        # switch a scan tab to "Hardware connection". _mode_switch_locked
        # and _update_connection_controls both used to read the *shared*
        # worker's own "connected" state as a reason to lock/grey out this
        # window's mode selector -- correct for a window that owns its
        # connection (switching away from Hardware mid-session would orphan
        # it), wrong here, since this window never owns that connection's
        # lifecycle at all. The sibling test above never caught it because
        # it switches mode before connecting, the opposite of how this
        # actually gets used.
        window = self._make_window()
        worker = window.connection_panel.connection_worker
        worker.connect(RadiorocConnectionConfig("fake-port", 115200, 0.5))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state != "connected":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "connected")
        window.connection_panel.poll()

        scan_windows = (window.threshold_window, window.hold_scan_window, window.scurve_window,
                       window.acquisition_window)
        for scan_window in scan_windows:
            scan_window.poll_connection_worker()
            self.assertTrue(scan_window.mode.isEnabled(),
                            f"{type(scan_window).__name__} mode selector should not be greyed "
                            "out just because the shared connection is already connected")
            scan_window.mode.setCurrentIndex(1)  # Hardware connection
            self.assertEqual(scan_window.mode.currentIndex(), 1,
                            f"{type(scan_window).__name__} should accept switching to Hardware "
                            "mode once already connected via the shared ASIC-config page")

    def test_threshold_scan_actually_runs_after_connecting_and_switching_to_hardware(self):
        # The operator asked, fairly, whether tests exercise "basic things
        # like this" -- connect, then actually run a scan, not just check
        # that a button's enabled state looks right. This drives the real
        # MainWindow/ThresholdWindow classes through the exact sequence a
        # user follows (connect on the shared ASIC-config page, switch a
        # Calibration tab to Hardware, run it) against a session backed by a
        # faithful fake ASIC/FPGA transport (not just a bare read_word
        # stub), and checks the run actually completes.
        from tests.test_connection_worker import OwnedThresholdTransport, ThresholdSession

        class _RealSessionWorker(ConnectionWorker):
            def __init__(self):
                super().__init__(discovery=lambda: (),
                                 session_factory=lambda config: ThresholdSession(OwnedThresholdTransport()))

        window = self._make_window(_RealSessionWorker)
        worker = window.connection_panel.connection_worker
        worker.connect(RadiorocConnectionConfig("fake-port", 115200, 0.5))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state != "connected":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "connected")
        window.connection_panel.poll()

        tw = window.threshold_window
        tw.poll_connection_worker()
        tw.mode.setCurrentIndex(1)  # Hardware connection
        self.assertEqual(tw.mode.currentIndex(), 1)
        tw.channel_select.set_channels([4])
        tw.dac_min.setValue(0)
        tw.dac_max.setValue(0)
        tw.dac_step.setValue(1)
        tw.window_ms.setValue(1)
        _app().processEvents()
        self.assertTrue(tw.run_button.isEnabled())

        tw.start_run()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and tw._hardware_running:
            _app().processEvents()
            time.sleep(0.01)
        self.assertFalse(tw._hardware_running, "hardware run never finished")
        self.assertIn("completed", tw.status.text().lower())

    def test_scurve_actually_runs_after_connecting_and_switching_to_hardware(self):
        # Same shape as the threshold-scan version above, for S-curve.
        from tests.test_connection_worker import OwnedThresholdTransport, ThresholdSession

        class _RealSessionWorker(ConnectionWorker):
            def __init__(self):
                super().__init__(discovery=lambda: (),
                                 session_factory=lambda config: ThresholdSession(OwnedThresholdTransport()))

        window = self._make_window(_RealSessionWorker)
        worker = window.connection_panel.connection_worker
        worker.connect(RadiorocConnectionConfig("fake-port", 115200, 0.5))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state != "connected":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "connected")
        window.connection_panel.poll()

        sw = window.scurve_window
        sw.poll_connection_worker()
        sw.mode.setCurrentIndex(1)  # Hardware connection
        self.assertEqual(sw.mode.currentIndex(), 1)
        sw.channel_select.set_channels([4])
        sw.dac_min.setValue(0)
        sw.dac_max.setValue(0)
        sw.dac_step.setValue(1)
        _app().processEvents()
        self.assertTrue(sw.run_button.isEnabled())

        sw.start_run()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and sw._hardware_running:
            _app().processEvents()
            time.sleep(0.01)
        self.assertFalse(sw._hardware_running, "hardware run never finished")
        self.assertIn("completed", sw.status.text().lower())

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

    def test_close_recovers_when_a_hardware_job_faults_racing_the_shutdown(self):
        # A live-reproduced defect (RADIOROC 40/41's offline defect-hunt):
        # ConnectionWorker deliberately holds its shutdown when a running
        # job faults right as a shutdown is already queued behind it (see
        # test_new_job_fault_during_shutdown_stays_alive_for_explicit_retry
        # in tests/test_connection_worker.py) -- the documented contract is
        # that the *caller* must retry shutdown() once more after seeing
        # "faulted". Before this fix, MainWindow never did: an operator who
        # closed the app at exactly the moment a hardware fault landed (e.g.
        # a USB hiccup during a run's mandatory restoration-verification
        # read) got a window that never closes via any UI action.
        from tests.test_connection_worker import BlockingCounterFaultTransport, ThresholdSession

        transport = BlockingCounterFaultTransport()

        class _FaultingSessionWorker(ConnectionWorker):
            def __init__(self):
                super().__init__(discovery=lambda: (),
                                 session_factory=lambda config: ThresholdSession(transport))

        window = self._make_window(_FaultingSessionWorker)
        worker = window.connection_panel.connection_worker
        worker.connect(RadiorocConnectionConfig("fake-port", 115200, 0.5))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worker.snapshot().state != "connected":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "connected")
        window.connection_panel.poll()

        tw = window.threshold_window
        tw.poll_connection_worker()
        tw.mode.setCurrentIndex(1)  # Hardware connection
        tw.channel_select.set_channels([4])
        tw.dac_min.setValue(0)
        tw.dac_max.setValue(0)
        tw.dac_step.setValue(1)
        tw.window_ms.setValue(1)
        _app().processEvents()
        self.assertTrue(tw.run_button.isEnabled())
        tw.start_run()

        # Let the scan actually reach (and block on) the counter read that
        # BlockingCounterFaultTransport will fault once released -- not a
        # sleep-and-hope, an explicit signal the fake transport sets.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not transport.counter_read.is_set():
            _app().processEvents()
            time.sleep(0.01)
        self.assertTrue(transport.counter_read.is_set(), "scan never reached the counter read")

        # Close mid-run: this queues ConnectionWorker's shutdown behind the
        # still-running job, exactly the race the held-shutdown contract
        # exists for.
        window.close()
        _app().processEvents()
        self.assertNotEqual(worker.snapshot().state, "stopped",
                            "closed before the race could even happen")

        # Now let the fault land while that shutdown is queued.
        transport.release_counter.set()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and worker.snapshot().state != "stopped":
            _app().processEvents()
            time.sleep(0.01)
        self.assertEqual(worker.snapshot().state, "stopped",
                         "window never recovered from a job fault racing its own shutdown "
                         "(the required explicit shutdown() retry never happened)")

    def test_hint_bar_reports_into_the_window_status_bar(self):
        from PySide6.QtCore import QEvent
        window = self._make_window()
        self.assertIsNotNone(window.hint)
        default_message = window.statusBar().currentMessage()
        self.assertTrue(default_message)
        window.hint.eventFilter(window.connection_panel.connect_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), default_message)
        window.hint.eventFilter(window.connection_panel.connect_button, QEvent(QEvent.Type.Leave))
        self.assertEqual(window.statusBar().currentMessage(), default_message)
        window.hint.eventFilter(window.main_panel.apply_button, QEvent(QEvent.Type.Enter))
        self.assertNotEqual(window.statusBar().currentMessage(), default_message)


if __name__ == "__main__":
    unittest.main()
