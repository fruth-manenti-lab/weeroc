"""Offline lifecycle tests for the desktop threshold worker.

These tests exercise the real deterministic simulator through the shared
ThresholdJob API. The context-manager seam is used only to observe session
ownership and inject open/close faults; no board or serial device is involved.
"""

import csv
from pathlib import Path
import tempfile
import threading
import unittest

from radioroc_client import ThresholdScanConfig
from radioroc.application import JobBusyError
from radioroc.application.threshold import ThresholdJobConfig
from radioroc.application.threshold_worker import ThresholdWorker
from radioroc.transport.threshold_simulator import (
    ThresholdSimulationConfig,
    create_threshold_simulator,
)


class RecordingSession:
    """Wrap a simulator session while recording thread and close ordering."""

    def __init__(self, operation, simulation, *, entered=None, exited=None,
                 exit_started=None, release_exit=None, close_error=None):
        self.operation = operation
        self.simulation = simulation
        self.entered = entered
        self.exited = exited
        self.exit_started = exit_started
        self.release_exit = release_exit
        self.close_error = close_error
        self.inner = create_threshold_simulator(operation, simulation)
        self.thread_ids = []

    def __enter__(self):
        self.thread_ids.append(threading.get_ident())
        if self.entered:
            self.entered.set()
        return self.inner.__enter__()

    def __exit__(self, *args):
        self.thread_ids.append(threading.get_ident())
        if self.exit_started:
            self.exit_started.set()
        if self.release_exit:
            self.release_exit.wait(2)
        try:
            return self.inner.__exit__(*args)
        finally:
            if self.exited:
                self.exited.set()
            if self.close_error:
                raise self.close_error


class ThresholdWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def operation(self, *, dac_max=2, dac_step=2, window_ms=0.001, averages=1):
        scan = ThresholdScanConfig(
            [4], dac_min=0, dac_max=dac_max, dac_step=dac_step,
            trigger_window_ms=window_ms, averages=averages,
            out_dir=Path(self.tmp.name) / "run",
        )
        return ThresholdJobConfig(scan)

    def simulation(self):
        return ThresholdSimulationConfig(
            midpoint=1, width=1, plateau_hz=1000, channel_spacing=0,
        )

    @staticmethod
    def saved_rows(path):
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def test_session_job_and_close_run_on_one_worker_thread(self):
        entered = threading.Event()
        exited = threading.Event()
        sessions = []
        factory_threads = []

        def factory(operation, simulation):
            factory_threads.append(threading.get_ident())
            session = RecordingSession(operation, simulation, entered=entered, exited=exited)
            sessions.append(session)
            return session

        main_thread = threading.get_ident()
        worker = ThresholdWorker(self.operation(), self.simulation(), session_factory=factory)
        worker.start()
        worker.join(10)

        self.assertFalse(worker.is_alive)
        self.assertTrue(entered.is_set())
        self.assertTrue(exited.is_set())
        self.assertEqual(len(sessions), 1)
        self.assertEqual(factory_threads + sessions[0].thread_ids,
                         [factory_threads[0]] * 3)
        self.assertNotEqual(factory_threads[0], main_thread)
        snapshot = worker.snapshot()
        self.assertIsNotNone(snapshot.outcome)
        self.assertEqual(snapshot.outcome.result.status, "completed")

    def test_simulator_rows_survive_coalescing_and_are_bounded_at_1024(self):
        # Skip the real-time wait in this data-volume test while leaving the
        # simulator's deterministic counter generation and durable writer in place.
        from unittest.mock import patch
        operation = self.operation(dac_max=1023, dac_step=1)
        worker = ThresholdWorker(operation, self.simulation())
        with patch("radioroc_client.RadiorocDevice.accurate_delay_ms", return_value=None):
            worker.start()
            worker.join(30)

        self.assertFalse(worker.is_alive)
        snapshot = worker.snapshot()
        self.assertIsNotNone(snapshot.outcome)
        result = snapshot.outcome.result
        self.assertEqual((result.status, result.points), ("completed", 1024))
        self.assertEqual(len(snapshot.rows), 1024)
        self.assertGreater(snapshot.coalesced_events, 1024)
        saved = self.saved_rows(result.csv_path)
        self.assertEqual(len(saved), 1024)
        self.assertEqual([int(row["DAC"]) for row in saved], list(range(1024)))
        self.assertTrue(all(float(dict(row)["ch4"]) >= 0 for row in snapshot.rows))

    def test_cancel_during_counter_window_keeps_partial_attempts_and_cleanup(self):
        counter_started = threading.Event()
        sessions = []

        def factory(operation, simulation):
            session = RecordingSession(operation, simulation)
            original_enter = session.__enter__

            def enter():
                transport = original_enter()
                original_write = transport.write_word

                def write(address, value):
                    if address == 1 and value.startswith("10"):
                        counter_started.set()
                    return original_write(address, value)

                transport.write_word = write
                return transport

            session.__enter__ = enter
            sessions.append(session)
            return session

        worker = ThresholdWorker(self.operation(dac_max=4, dac_step=2, window_ms=100),
                                 self.simulation(), session_factory=factory)
        worker.start()
        self.assertTrue(counter_started.wait(5))
        worker.cancel()
        worker.join(10)

        snapshot = worker.snapshot()
        result = snapshot.outcome.result
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.points, 0)
        self.assertGreaterEqual(result.attempts, 0)
        self.assertEqual(len(self.saved_rows(result.csv_path)), result.points)
        self.assertEqual(result.cleanup_status, "restored")
        self.assertFalse(worker.is_alive)

    def test_cancel_after_point_keeps_that_point_and_cleanup(self):
        worker = ThresholdWorker(self.operation(dac_max=4, dac_step=2), self.simulation())
        publish = worker._publish

        def publish_and_cancel(event):
            publish(event)
            if event.kind == "point":
                worker.cancel()

        worker._publish = publish_and_cancel
        worker.start()
        worker.join(10)

        snapshot = worker.snapshot()
        result = snapshot.outcome.result
        self.assertEqual((result.status, result.points), ("cancelled", 1))
        self.assertEqual(len(self.saved_rows(result.csv_path)), 1)
        self.assertEqual(result.cleanup_status, "restored")

    def test_double_start_is_rejected(self):
        worker = ThresholdWorker(self.operation(), self.simulation())
        worker.start()
        with self.assertRaises(JobBusyError):
            worker.start()
        worker.cancel()
        worker.join(10)

    def test_invalid_construction_does_not_open_a_session(self):
        calls = []
        invalid = ThresholdJobConfig(
            ThresholdScanConfig([4, 4], out_dir=Path(self.tmp.name) / "invalid")
        )
        with self.assertRaises(ValueError):
            ThresholdWorker(invalid, self.simulation(), session_factory=lambda *_: calls.append(True))
        self.assertEqual(calls, [])
        self.assertFalse((Path(self.tmp.name) / "invalid").exists())

    def test_open_failure_is_reported_without_close_error(self):
        def factory(*_):
            raise OSError("open failed")

        worker = ThresholdWorker(self.operation(), self.simulation(), session_factory=factory)
        worker.start()
        worker.join(10)
        outcome = worker.snapshot().outcome
        self.assertIsNone(outcome.result)
        self.assertIn("OSError: open failed", outcome.error)
        self.assertIsNone(outcome.close_error)

    def test_terminal_outcome_waits_for_session_exit_and_close_failure_is_separate(self):
        exit_started = threading.Event()
        release_exit = threading.Event()
        sessions = []

        def factory(operation, simulation):
            session = RecordingSession(
                operation, simulation, exit_started=exit_started,
                release_exit=release_exit, close_error=OSError("close failed"),
            )
            sessions.append(session)
            return session

        worker = ThresholdWorker(self.operation(), self.simulation(), session_factory=factory)
        worker.start()
        self.assertTrue(exit_started.wait(10))
        self.assertIsNone(worker.snapshot().outcome)
        release_exit.set()
        worker.join(10)
        outcome = worker.snapshot().outcome
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.result.status, "completed")
        self.assertIn("OSError: close failed", outcome.close_error)


if __name__ == "__main__":
    unittest.main()
