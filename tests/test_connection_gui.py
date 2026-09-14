"""Offline Qt checks for the desktop hardware connection boundary."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

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
        self.assertTrue(window.run_button.isEnabled())

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
        self.assertTrue(preview["hardware"]["threshold_run_available"])
        self.assertEqual(preview["hardware"]["restoration_verification"], "mandatory")

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

    def test_hardware_run_uses_connection_worker_and_fault_requires_disconnected_review(self):
        worker = FakeHardwareWorker()
        window = self.make_window(discovery=lambda: [], session_factory=self.session_factory)
        window.connection_worker = worker
        window.mode.setCurrentIndex(1)
        worker.state = "connected"
        window._update_connection_controls()
        self.assertTrue(window.run_button.isEnabled())
        self.assertIn("hardware", window.output.text())

        window.start_run()
        self.assertEqual(worker.run_calls, 1)
        self.assertEqual(worker.snapshot().state, "scanning")
        self.assertFalse(window.reopen_button.isEnabled())
        window.cancel_run()
        self.assertEqual(worker.cancel_calls, 1)

        worker.finish_fault()
        window.poll_worker()
        self.assertIn("failed", window.status.text())
        self.assertFalse(window.run_button.isEnabled())
        window.disconnect_hardware()
        self.assertEqual(worker.snapshot().state, "idle")
        self.assertTrue(window.review_fault_button.isEnabled())
        window.review_hardware_fault()
        self.assertIsNone(worker.snapshot().fault)

        worker.state = "scanning"
        window._hardware_running = True
        window.close()
        self.assertGreaterEqual(worker.shutdown_calls, 1)

    def test_channel_config_submits_operation_and_shows_verified_result(self):
        from radioroc.application.channel_config import ChannelConfigResult

        worker = FakeHardwareWorker()
        window = self.make_window(discovery=lambda: [], session_factory=self.session_factory)
        window.connection_worker = worker
        window.mode.setCurrentIndex(1)
        worker.state = "connected"
        window._update_connection_controls()
        self.assertTrue(window.channel_config_apply_button.isEnabled())

        window.channel_config_channels.setText("4")
        window.channel_config_set_tq_mask.setChecked(True)
        window.channel_config_set_input_dac_value.setChecked(True)
        window.channel_config_input_dac_value.setValue(200)
        window.channel_config_restore.setChecked(True)
        window.apply_channel_config()

        self.assertEqual(len(worker.channel_config_calls), 1)
        operation = worker.channel_config_calls[0]
        self.assertEqual(operation.tq_mask_channels, (4,))
        self.assertEqual(operation.input_dac_value_channels, (4,))
        self.assertEqual(operation.input_dac_value, 200)
        self.assertTrue(operation.restore)
        self.assertEqual(worker.state, "configuring")
        window._update_connection_controls()
        self.assertFalse(window.channel_config_apply_button.isEnabled())

        worker.channel_config_result = ChannelConfigResult(
            applied=("tq_mask channel=4 -> 1", "input_dac_value channel=4 -> 200"),
            touched_rows=2, verify_mismatches=(), restored=True, restore_mismatches=(),
        )
        worker.state = "connected"
        window.poll_connection_worker()
        self.assertIn("verified", window.channel_config_status.text())
        self.assertIn("restored", window.channel_config_status.text())
        self.assertTrue(window.channel_config_apply_button.isEnabled())

    def test_channel_config_rejects_incomplete_input_before_submitting(self):
        worker = FakeHardwareWorker()
        window = self.make_window(discovery=lambda: [], session_factory=self.session_factory)
        window.connection_worker = worker
        window.mode.setCurrentIndex(1)
        worker.state = "connected"
        window._update_connection_controls()

        window.channel_config_set_input_dac_value.setChecked(True)
        window.channel_config_channels.setText("4")
        # input_dac_value spinbox left at 0 is valid, so instead leave no
        # channels selected for any operation to trigger "at least one field".
        window.channel_config_set_input_dac_value.setChecked(False)
        window.apply_channel_config()

        self.assertEqual(worker.channel_config_calls, [])
        self.assertIn("Invalid channel configuration", window.channel_config_status.text())

    def test_hardware_run_replaces_saved_result_banner_before_plot_is_cleared(self):
        worker = FakeHardwareWorker()
        window = self.make_window()
        window.connection_worker = worker
        window.mode.setCurrentIndex(1)
        worker.state = "connected"
        window._update_connection_controls()
        with tempfile.TemporaryDirectory() as temp:
            saved = Path(temp) / "saved"
            saved.mkdir()
            (saved / "thresholdscan.csv").write_text("DAC,ch4\n0,1\n")
            (saved / "metadata.json").write_text(json.dumps({
                "schema_version": 1,
                "status": "completed",
                "execution_mode": "simulation",
                "operation": {"scan": {"channels": [4], "dac_min": 0,
                                       "dac_max": 0, "dac_step": 1}},
                "total_points": 1,
                "completed_points": 1,
                "cleanup": {"status": "restored", "errors": []},
                "persistence_errors": [],
            }))
            window.open_saved(saved)
            self.assertIn("SAVED RESULT · SIMULATION", window.banner.text())

            window.output.setText(str(Path(temp) / "current-hardware"))
            window.start_run()
            self.assertEqual(worker.run_calls, 1)
            self.assertIn("HARDWARE · RUN", window.banner.text())
            self.assertNotIn("SAVED RESULT", window.banner.text())
            self.assertIn("current-hardware", window.banner.text())

            worker.finish_fault()
            window.poll_worker()

            window.open_saved(saved)
            worker.state = "connected"
            worker.fault = None
            worker.run_error = RuntimeError("submission rejected")
            window.start_run()
            self.assertEqual(worker.run_calls, 2)
            self.assertIn("HARDWARE · RUN", window.banner.text())
            self.assertNotIn("SAVED RESULT", window.banner.text())
            self.assertIn("Could not start hardware scan", window.status.text())

    def test_shutdown_consumes_hardware_terminal_before_releasing_stopped_worker(self):
        worker = FakeHardwareWorker()
        window = self.make_window()
        window.connection_worker = worker
        window.mode.setCurrentIndex(1)
        worker.state = "connected"
        window._update_connection_controls()
        window.start_run()
        worker.finish_fault()
        worker.state = "stopped"
        window._closing = True
        window.poll_connection_worker()
        self.assertIsNone(window.connection_worker)
        self.assertIn('"verification"', window.details.toPlainText())
        self.assertFalse(window._closing)


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


class FakeHardwareWorker:
    """UI seam: no transport or threshold job is created in this test."""

    def __init__(self):
        self.state = "idle"
        self.fault = None
        self.run_calls = self.cancel_calls = self.shutdown_calls = 0
        self.outcome = None
        self.run_error = None
        self.channel_config_calls = []
        self.channel_config_result = None

    @property
    def is_alive(self):
        return self.state != "stopped"

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def snapshot(self):
        return SimpleNamespace(state=self.state, ports=(), port="fake-control",
                               status_word=5, error=None, close_error=None, fault=self.fault)

    def run_threshold(self, operation):
        self.run_calls += 1
        if self.run_error is not None:
            raise self.run_error
        self.state = "scanning"

    def cancel_threshold(self):
        self.cancel_calls += 1

    def apply_channel_config(self, operation):
        self.channel_config_calls.append(operation)
        self.state = "configuring"

    def threshold_snapshot(self):
        return SimpleNamespace(event=None, rows=(), coalesced_events=0, outcome=self.outcome)

    def channel_config_snapshot(self):
        return self.channel_config_result

    def finish_fault(self):
        result = SimpleNamespace(status="completed", points=0, attempts=0,
                                 cleanup_status="restored", cleanup_errors=(),
                                 persistence_errors=(), error=None, warnings=(),
                                 execution_mode="hardware", verification={"status": "failed"})
        self.outcome = SimpleNamespace(result=result, error=None, close_error=None)
        self.state = "faulted"
        self.fault = "restoration verification did not pass"

    def disconnect(self):
        self.state = "idle"

    def review_fault(self):
        self.fault = None

    def shutdown(self):
        self.shutdown_calls += 1
        if self.state == "scanning":
            self.cancel_threshold()
        self.state = "stopped"


if __name__ == "__main__":
    unittest.main()
