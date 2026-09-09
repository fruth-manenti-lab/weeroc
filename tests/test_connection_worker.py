import threading
import time
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

# Bootstrap the checkout package when test discovery uses an older installed wheel.
import radioroc_client  # noqa: F401

from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.jobs import JobBusyError
from radioroc.transport.config import RadiorocConnectionConfig
from radioroc.transport.discovery import BoardPort
from radioroc.transport.errors import DeviceBusyError
from radioroc.transport.ownership import BoardLease
from radioroc.transport.serial import RadiorocSerial


PORT = BoardPort("fake-control", "Fake board", 0x0403, 0x6010, "fake", "1-1", None)


class FakeSession:
    def __init__(self, *, status="00000101", enter_error=None, read_error=None,
                 close_error=None, entered=None, release=None):
        self.status = status
        self.enter_error = enter_error
        self.read_error = read_error
        self.close_error = close_error
        self.entered = entered
        self.release = release
        self.calls = []
        self.thread_ids = []

    def __enter__(self):
        self.calls.append("enter")
        self.thread_ids.append(threading.get_ident())
        if self.entered:
            self.entered.set()
        if self.release:
            self.release.wait(5)
        if self.enter_error:
            raise self.enter_error
        return self

    def read_word(self, address):
        self.calls.append(("read", address))
        self.thread_ids.append(threading.get_ident())
        if self.read_error:
            raise self.read_error
        return self.status

    def close(self):
        self.calls.append("close")
        self.thread_ids.append(threading.get_ident())
        if self.close_error:
            error, self.close_error = self.close_error, None
            raise error


class ScriptedSerial:
    def __init__(self):
        self.chunks = deque([bytes.fromhex("aa 00 e4 05 55")])
        self.timeout = .01
        self.out_waiting = 0
        self.writes = []
        self.closed = False
        self.close_calls = 0
        self.close_error = None

    def write(self, frame):
        self.writes.append(frame)
        return len(frame)

    def read(self, size):
        return self.chunks.popleft() if self.chunks else b""

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.close_calls += 1
        if self.close_error:
            error, self.close_error = self.close_error, None
            raise error
        self.closed = True


class ConnectionWorkerTests(unittest.TestCase):
    def wait_for(self, worker, state, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snap = worker.snapshot()
            if snap.state == state:
                return snap
            time.sleep(.01)
        self.fail(f"worker did not reach {state}: {worker.snapshot()}")

    def started(self, **kwargs):
        worker = ConnectionWorker(**kwargs)
        self.assertEqual(worker.snapshot().state, "idle")
        worker.start()
        self.addCleanup(lambda: (worker.shutdown(), worker.join(3)) if worker.is_alive else None)
        return worker

    def test_refresh_is_worker_thread_only_and_does_not_open_session(self):
        discovery_threads = []
        worker = self.started(discovery=lambda: discovery_threads.append(threading.get_ident()) or [PORT])
        worker.refresh()
        deadline = time.monotonic() + 3
        while not discovery_threads and time.monotonic() < deadline:
            time.sleep(.01)
        snap = worker.snapshot()
        self.assertEqual(snap.ports, (PORT,))
        self.assertNotEqual(discovery_threads, [threading.get_ident()])

    def test_connect_read_and_disconnect_stay_on_worker_thread(self):
        sessions = []
        factory_threads = []

        def factory(config):
            factory_threads.append(threading.get_ident())
            session = FakeSession()
            sessions.append(session)
            return session

        worker = self.started(session_factory=factory)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.assertEqual(self.wait_for(worker, "connected").status_word, 5)
        worker.read_status()
        self.wait_for(worker, "connected")
        worker.disconnect()
        self.wait_for(worker, "idle")
        self.assertEqual(set(factory_threads + sessions[0].thread_ids),
                         {worker._thread.ident})

    def test_read_failure_preserves_primary_and_close_errors(self):
        session = FakeSession(read_error=OSError("read failed"), close_error=OSError("close failed"))
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        snap = self.wait_for(worker, "close_failed")
        self.assertIn("OSError: read failed", snap.error)
        self.assertIn("OSError: close failed", snap.close_error)
        worker.disconnect()
        snap = self.wait_for(worker, "idle")
        self.assertIn("OSError: read failed", snap.error)
        self.assertIn("OSError: close failed", snap.close_error)

    def test_failed_enter_keeps_session_for_close_retry(self):
        session = FakeSession(enter_error=OSError("open failed"), close_error=OSError("close failed"))
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.assertEqual(self.wait_for(worker, "close_failed").error, "OSError: open failed")
        worker.disconnect()
        self.wait_for(worker, "idle")
        self.assertEqual(session.calls.count("close"), 2)

    def test_shutdown_queues_behind_connect_and_closes_then_stops(self):
        entered, release = threading.Event(), threading.Event()
        session = FakeSession(entered=entered, release=release)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.assertTrue(entered.wait(3))
        worker.shutdown()
        release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive)
        self.assertEqual(worker.snapshot().state, "stopped")
        self.assertIn("close", session.calls)

    def test_overlapping_commands_are_rejected_after_busy_state_is_published(self):
        entered, release = threading.Event(), threading.Event()
        worker = self.started(session_factory=lambda config: FakeSession(entered=entered, release=release))
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.assertEqual(worker.snapshot().state, "connecting")
        with self.assertRaises(JobBusyError):
            worker.refresh()
        self.assertTrue(entered.wait(3))
        release.set()
        self.wait_for(worker, "connected")

    def test_connect_is_rejected_while_the_existing_session_is_connected(self):
        worker = self.started(session_factory=lambda config: FakeSession())
        config = RadiorocConnectionConfig(port="fake-control")
        worker.connect(config)
        self.wait_for(worker, "connected")
        with self.assertRaises(JobBusyError):
            worker.connect(config)

    def test_failed_read_clears_stale_status_after_a_clean_close(self):
        session = FakeSession(read_error=OSError("unplugged"))
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.assertEqual(self.wait_for(worker, "error").status_word, None)
        snap = worker.snapshot()
        self.assertIsNone(snap.port)
        self.assertIn("OSError: unplugged", snap.error)

    def test_real_serial_session_reads_only_status_and_releases_lease(self):
        fake = ScriptedSerial()
        with tempfile.TemporaryDirectory() as directory, \
             patch("radioroc.transport.serial.board_identity", return_value="usb:fake"), \
             patch("radioroc.transport.serial.serial.Serial", return_value=fake):
            lock_dir = Path(directory)
            worker = self.started(session_factory=lambda config: RadiorocSerial(
                config.port, config.baud, .01, lock_dir=lock_dir))
            worker.connect(RadiorocConnectionConfig(port="fake-control"))
            self.assertEqual(self.wait_for(worker, "connected").status_word, 5)
            self.assertEqual(fake.writes, [bytes.fromhex("aa 00 e4 00 55")])
            with self.assertRaises(DeviceBusyError):
                BoardLease("usb:fake", "other", directory=lock_dir).acquire()
            worker.disconnect()
            self.wait_for(worker, "idle")
            self.assertTrue(fake.closed)
            with BoardLease("usb:fake", "other", directory=lock_dir):
                pass

    def test_real_serial_failed_enter_does_not_receive_a_second_close(self):
        fake = ScriptedSerial()
        with tempfile.TemporaryDirectory() as directory, \
             patch("radioroc.transport.serial.board_identity", return_value="usb:fake"), \
             patch("radioroc.transport.serial.serial.Serial", return_value=fake), \
             patch.object(fake, "reset_input_buffer", side_effect=OSError("init failed")):
            worker = self.started(session_factory=lambda config: RadiorocSerial(
                config.port, config.baud, .01, lock_dir=Path(directory)))
            worker.connect(RadiorocConnectionConfig(port="fake-control"))
            self.assertEqual(self.wait_for(worker, "error").error.split(":", 1)[0],
                             "TransportIOError")
            self.assertTrue(fake.closed)
            self.assertEqual(fake.close_calls, 1)

    def test_failed_serial_enter_with_retained_lease_waits_for_explicit_retry(self):
        fake = ScriptedSerial()
        fake.close_error = OSError("close failed")
        with tempfile.TemporaryDirectory() as directory, \
             patch("radioroc.transport.serial.board_identity", return_value="usb:fake"), \
             patch("radioroc.transport.serial.serial.Serial", return_value=fake), \
             patch.object(fake, "reset_input_buffer", side_effect=OSError("init failed")):
            worker = self.started(session_factory=lambda config: RadiorocSerial(
                config.port, config.baud, .01, lock_dir=Path(directory)))
            worker.connect(RadiorocConnectionConfig(port="fake-control"))
            snap = self.wait_for(worker, "close_failed")
            self.assertIn("TransportIOError", snap.error)
            self.assertEqual(snap.error, snap.close_error)
            self.assertEqual(fake.close_calls, 1)
            worker.disconnect()
            self.wait_for(worker, "idle")
            self.assertEqual(fake.close_calls, 2)


if __name__ == "__main__":
    unittest.main()
