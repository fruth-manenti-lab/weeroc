import threading
import time
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

# Bootstrap the checkout package when test discovery uses an older installed wheel.
import radioroc_client  # noqa: F401
from radioroc_client import I2CRow, ThresholdScanConfig, ThresholdScanResult, bits

from radioroc.application.channel_config import ChannelConfigOperation
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.jobs import JobBusyError
from radioroc.application.raw_registers import RawRegisterWrite
from radioroc.application.threshold import ThresholdJobConfig
from radioroc.transport.config import RadiorocConnectionConfig
from radioroc.transport.discovery import BoardPort
from radioroc.transport.errors import DeviceBusyError, TransportIOError
from radioroc.transport.ownership import BoardLease
from radioroc.transport.serial import RadiorocSerial
from tests.test_threshold_jobs import ThresholdTransport


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


class ThresholdSession:
    """Persistent fake session around the real job's scripted transport."""

    def __init__(self, transport):
        self.transport = transport
        self.thread_ids = []
        self.close_calls = 0

    def __enter__(self):
        self.thread_ids.append(threading.get_ident())
        return self.transport

    def close(self):
        self.thread_ids.append(threading.get_ident())
        self.close_calls += 1


class OwnedThresholdTransport(ThresholdTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.thread_ids = []

    def read_word(self, address):
        self.thread_ids.append(threading.get_ident())
        return super().read_word(address)

    def write_word(self, address, value):
        self.thread_ids.append(threading.get_ident())
        return super().write_word(address, value)

    def read_words(self, address, length):
        self.thread_ids.append(threading.get_ident())
        return super().read_words(address, length)

    def write_words(self, address, payload):
        self.thread_ids.append(threading.get_ident())
        return super().write_words(address, payload)


class BlockingCounterFaultTransport(OwnedThresholdTransport):
    def __init__(self):
        super().__init__()
        self.counter_read = threading.Event()
        self.release_counter = threading.Event()

    def read_words(self, address, length):
        if address == 96:
            self.counter_read.set()
            self.release_counter.wait(3)
            raise TransportIOError("counter disconnected")
        return super().read_words(address, length)


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
        def cleanup():
            for _ in range(2):
                if not worker.is_alive:
                    return
                try:
                    worker.shutdown()
                except JobBusyError:
                    pass
                worker.join(3)
        self.addCleanup(cleanup)
        return worker

    def operation(self, name="run", *, dac_max=0, window_ms=.001):
        if not hasattr(self, "_threshold_tmp"):
            self._threshold_tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._threshold_tmp.cleanup)
        return ThresholdJobConfig(ThresholdScanConfig(
            [4], dac_min=0, dac_max=dac_max, dac_step=1,
            trigger_window_ms=window_ms, averages=1,
            out_dir=Path(self._threshold_tmp.name) / name,
        ))

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
        self.assertIn("OSError: close failed", snap.fault)
        worker.disconnect()
        snap = self.wait_for(worker, "idle")
        self.assertIn("OSError: read failed", snap.error)
        self.assertIn("OSError: close failed", snap.close_error)
        self.assertIn("OSError: close failed", snap.fault)
        worker.review_fault()
        reviewed = worker.snapshot()
        self.assertIsNone(reviewed.fault)
        self.assertIn("OSError: read failed", reviewed.error)
        self.assertIn("OSError: close failed", reviewed.close_error)

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

    def test_threshold_job_uses_persistent_owner_and_publishes_verified_rows(self):
        transport = OwnedThresholdTransport(counts=(10,))
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")

        worker.run_threshold(self.operation())
        self.assertEqual(worker.snapshot().state, "scanning")
        with self.assertRaises(JobBusyError):
            worker.read_status()
        with self.assertRaises(JobBusyError):
            worker.disconnect()
        snap = self.wait_for(worker, "connected", timeout=10)
        threshold = worker.threshold_snapshot()

        self.assertIsNone(snap.fault)
        self.assertEqual(threshold.outcome.result.status, "completed")
        self.assertEqual(threshold.outcome.result.verification["status"], "passed")
        self.assertEqual(len(threshold.rows), 1)
        self.assertEqual(set(transport.thread_ids + session.thread_ids),
                         {worker._thread.ident})
        self.assertEqual(session.close_calls, 0)

    def test_channel_config_applies_verifies_restores_and_stays_on_worker_thread(self):
        transport = OwnedThresholdTransport()
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")

        worker.apply_channel_config(ChannelConfigOperation(
            tq_mask_channels=(4,), tq_mask_value=True,
            input_dac_value_channels=(4,), input_dac_value=200,
            input_dac_impedance=True, verify=True, restore=True,
        ))
        self.assertEqual(worker.snapshot().state, "configuring")
        with self.assertRaises(JobBusyError):
            worker.read_status()
        snap = self.wait_for(worker, "connected", timeout=5)
        result = worker.channel_config_snapshot()

        self.assertIsNone(snap.fault)
        self.assertEqual(result.verify_mismatches, ())
        self.assertTrue(result.restored)
        self.assertEqual(result.restore_mismatches, ())
        self.assertIn("tq_mask channel=4 -> 1", result.applied)
        self.assertEqual(set(transport.thread_ids + session.thread_ids),
                         {worker._thread.ident})
        self.assertEqual(session.close_calls, 0)

    def test_channel_config_mismatch_faults_until_disconnected_and_reviewed(self):
        transport = OwnedThresholdTransport()
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        config = RadiorocConnectionConfig(port="fake-control")
        worker.connect(config)
        self.wait_for(worker, "connected")

        # Force a readback mismatch, the same way test_channel_config.py
        # exercises the same fault path against the shared core directly.
        device = worker._device
        original_read_register_bits = device.read_register_bits

        def flaky_read_register_bits(add, subadd):
            if (add, subadd) == (4, 6):
                return "00000000"
            return original_read_register_bits(add, subadd)

        device.read_register_bits = flaky_read_register_bits

        worker.apply_channel_config(ChannelConfigOperation(tq_mask_channels=(4,), verify=True))
        snap = self.wait_for(worker, "faulted", timeout=5)
        self.assertIn("channel config mismatch", snap.fault)
        self.assertIsNotNone(worker.channel_config_snapshot())
        with self.assertRaises(JobBusyError):
            worker.apply_channel_config(ChannelConfigOperation(tq_mask_channels=(5,)))

        worker.disconnect()
        idle = self.wait_for(worker, "idle")
        self.assertIsNotNone(idle.fault)
        worker.review_fault()

    def test_read_all_registers_reflects_hardware_and_stays_on_worker_thread(self):
        transport = OwnedThresholdTransport()
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")

        # A small, deliberately narrow row set: OwnedThresholdTransport's
        # synthetic ASIC map only covers add 0..66 / subadd 0..63, unlike the
        # real packaged default config CSV, which also carries reserved
        # (add, subadd>=64) probe-block rows -- see test_raw_registers.py for
        # the same reasoning against the shared core directly.
        device = worker._device
        device.i2c_rows = [I2CRow(4, 0, bits(0, 8)), I2CRow(4, 6, bits(0, 8))]

        worker.read_all_registers()
        self.assertEqual(worker.snapshot().state, "reading")
        self.wait_for(worker, "connected")
        rows = worker.raw_registers_snapshot()

        self.assertEqual(len(rows), 2)
        self.assertEqual(set(transport.thread_ids + session.thread_ids),
                         {worker._thread.ident})

    def test_write_raw_register_writes_verifies_and_faults_on_mismatch(self):
        transport = OwnedThresholdTransport()
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")
        device = worker._device
        device.i2c_rows = [I2CRow(4, 0, bits(0, 8))]

        worker.write_raw_register(RawRegisterWrite(4, 0, bits(200, 8)))
        self.wait_for(worker, "connected")
        result = worker.raw_register_write_snapshot()
        self.assertEqual(result.written, bits(200, 8))
        self.assertEqual(result.observed, bits(200, 8))
        self.assertFalse(result.mismatch)

        original_read_register_bits = device.read_register_bits

        def flaky_read_register_bits(add, subadd):
            if (add, subadd) == (4, 0):
                return bits(0, 8)
            return original_read_register_bits(add, subadd)

        device.read_register_bits = flaky_read_register_bits
        worker.write_raw_register(RawRegisterWrite(4, 0, bits(200, 8)))
        snap = self.wait_for(worker, "faulted", timeout=5)
        self.assertIn("raw register write mismatch", snap.fault)
        self.assertTrue(worker.raw_register_write_snapshot().mismatch)

    def test_verified_cancellation_returns_to_connected_after_cleanup(self):
        transport = OwnedThresholdTransport(counts=(10,))
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")
        worker.run_threshold(self.operation(window_ms=1000))
        self.assertTrue(transport.counter_started.wait(5))
        worker.cancel_threshold()

        snap = self.wait_for(worker, "connected", timeout=10)
        result = worker.threshold_snapshot().outcome.result
        self.assertEqual((result.status, result.cleanup_status,
                          result.verification["status"]),
                         ("cancelled", "restored", "passed"))
        self.assertIsNone(snap.fault)

    def test_threshold_fault_latches_until_disconnected_and_reviewed(self):
        transport = OwnedThresholdTransport()
        transport.fail_snapshot = True
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        config = RadiorocConnectionConfig(port="fake-control")
        worker.connect(config)
        self.wait_for(worker, "connected")
        worker.run_threshold(self.operation("fault"))

        snap = self.wait_for(worker, "faulted", timeout=10)
        self.assertIn("threshold status: failed", snap.fault)
        self.assertIsNotNone(worker.threshold_snapshot().outcome)
        for command in (worker.refresh, lambda: worker.connect(config),
                        lambda: worker.run_threshold(self.operation("blocked"))):
            with self.assertRaises(JobBusyError):
                command()
        with self.assertRaises(JobBusyError):
            worker.review_fault()

        worker.disconnect()
        idle = self.wait_for(worker, "idle")
        self.assertIsNotNone(idle.fault)
        saved = worker.threshold_snapshot()
        saved.outcome.result.status = "changed by caller"
        self.assertEqual(worker.threshold_snapshot().outcome.result.status, "failed")
        with self.assertRaises(JobBusyError):
            worker.connect(config)
        worker.review_fault()
        self.assertIsNone(worker.snapshot().fault)
        self.assertEqual(worker.threshold_snapshot().outcome.result.status, "failed")

    def test_shutdown_during_job_waits_for_verified_cleanup_then_closes(self):
        transport = OwnedThresholdTransport(counts=(10,))
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")
        worker.run_threshold(self.operation("shutdown", window_ms=1000))
        self.assertTrue(transport.counter_started.wait(5))
        worker.shutdown()
        worker.join(10)

        self.assertFalse(worker.is_alive)
        self.assertEqual(worker.snapshot().state, "stopped")
        self.assertEqual(worker.threshold_snapshot().outcome.result.status, "cancelled")
        self.assertEqual(session.close_calls, 1)

    def test_new_job_fault_during_shutdown_stays_alive_for_explicit_retry(self):
        transport = BlockingCounterFaultTransport()
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(RadiorocConnectionConfig(port="fake-control"))
        self.wait_for(worker, "connected")
        worker.run_threshold(self.operation("shutdown-fault"))
        self.assertTrue(transport.counter_read.wait(5))
        worker.shutdown()
        transport.release_counter.set()

        snap = self.wait_for(worker, "faulted", timeout=10)
        self.assertTrue(worker.is_alive)
        self.assertIn("counter disconnected", snap.fault)
        self.assertEqual(session.close_calls, 0)
        worker.shutdown()
        worker.join(10)
        self.assertFalse(worker.is_alive)
        self.assertEqual(worker.snapshot().state, "stopped")
        self.assertEqual(session.close_calls, 1)

    def test_fault_classifier_covers_each_terminal_safety_boundary(self):
        cases = (
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored", error=ValueError("primary"),
                                 verification={"status": "passed"}), "ValueError: primary"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="failed",
                                 verification={"status": "passed"}), "cleanup status: failed"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored", cleanup_errors=["restore failed"],
                                 verification={"status": "passed"}), "cleanup: restore failed"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored", persistence_errors=["disk full"],
                                 verification={"status": "passed"}), "persistence: disk full"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored", verification=None),
             "restoration verification is absent"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored",
                                 verification={"status": "incomplete"}),
             "restoration verification incomplete"),
            (ThresholdScanResult(Path("run.csv"), status="completed",
                                 cleanup_status="restored",
                                 verification={"status": "failed"}),
             "restoration verification failed"),
        )
        for result, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, ConnectionWorker._threshold_fault(result, None))


if __name__ == "__main__":
    unittest.main()
