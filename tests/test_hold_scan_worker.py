"""Offline lifecycle tests for the desktop hold-scan worker.

These tests exercise the real synthetic simulator through the shared
HoldScanJob API. The context-manager seam is used only to observe session
ownership and inject open/close/mid-flight faults; no board or serial device
is involved. This mirrors tests/test_threshold_worker.py; see that module for
the design rationale of each test.
"""

import csv
from pathlib import Path
import tempfile
import threading
import unittest

from radioroc_client import HoldScanConfig
from radioroc.application import JobBusyError
from radioroc.application.hold_scan import HoldScanJobConfig
from radioroc.application.hold_scan_worker import HoldScanWorker
from radioroc.transport.hold_scan_simulator import (
    HoldSimulationConfig,
    create_hold_simulator,
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
        self.inner = create_hold_simulator(operation, simulation)
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


class HoldScanWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def operation(self, *, mode="internal", hold_max=10, hold_step=5, acquisitions=2,
                  channels=(4,)):
        scan = HoldScanConfig(
            mode=mode, channels=list(channels), trigger_channel=channels[0],
            hold_min=0, hold_max=hold_max, hold_step=hold_step, acquisitions=acquisitions,
            out_dir=Path(self.tmp.name) / "run",
        )
        return HoldScanJobConfig(scan)

    def simulation(self):
        return HoldSimulationConfig(baseline_counts=100, peak_counts=500,
                                    rise_width=5, fall_width=5)

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
        worker = HoldScanWorker(self.operation(), self.simulation(), session_factory=factory)
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
        # External mode with delays divisible by 5 produces exactly 1024
        # points across 0..5115ns, exercising the same 1024-row display cap
        # as ThresholdWorker's 0..1023 DAC test.
        operation = self.operation(mode="external", hold_max=5115, hold_step=5, acquisitions=1)
        worker = HoldScanWorker(operation, self.simulation())
        worker.start()
        worker.join(60)

        self.assertFalse(worker.is_alive)
        snapshot = worker.snapshot()
        self.assertIsNotNone(snapshot.outcome)
        result = snapshot.outcome.result
        self.assertEqual((result.status, result.points), ("completed", 1024))
        self.assertEqual(len(snapshot.rows), 1024)
        self.assertGreater(snapshot.coalesced_events, 0)
        saved = self.saved_rows(result.csv_path)
        self.assertEqual(len(saved), 1024)
        self.assertEqual([int(row["hold_delay_ns"]) for row in saved], list(range(0, 5120, 5)))
        self.assertTrue(all(float(dict(row)["ch4_hg_mean"]) >= 0 for row in snapshot.rows))

    def test_cancel_before_any_point_keeps_cleanup(self):
        started = threading.Event()
        released = threading.Event()
        sessions = []

        def factory(operation, simulation):
            session = RecordingSession(operation, simulation)
            original_enter = session.__enter__

            def enter():
                transport = original_enter()
                original_write = transport.write_word

                def write(address, value):
                    if address == 21:
                        started.set()
                        released.wait(2)
                    return original_write(address, value)

                transport.write_word = write
                return transport

            session.__enter__ = enter
            sessions.append(session)
            return session

        worker = HoldScanWorker(self.operation(hold_max=10, hold_step=5), self.simulation(),
                                session_factory=factory)
        worker.start()
        self.assertTrue(started.wait(5))
        worker.cancel()
        released.set()
        worker.join(10)

        snapshot = worker.snapshot()
        result = snapshot.outcome.result
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.points, 0)
        self.assertEqual(len(self.saved_rows(result.csv_path)), 0)
        self.assertEqual(result.cleanup_status, "restored")
        self.assertFalse(worker.is_alive)

    def test_cancel_after_point_keeps_that_point_and_cleanup(self):
        worker = HoldScanWorker(self.operation(hold_max=10, hold_step=5), self.simulation())
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
        worker = HoldScanWorker(self.operation(), self.simulation())
        worker.start()
        with self.assertRaises(JobBusyError):
            worker.start()
        worker.cancel()
        worker.join(10)

    def test_invalid_construction_does_not_open_a_session(self):
        # Unlike ThresholdScanConfig, HoldScanConfig.validate() does not
        # reject duplicate channels (see radioroc_client.py); an
        # out-of-range trigger_channel is used here instead to exercise the
        # same "invalid config never opens a session" guarantee.
        calls = []
        invalid = HoldScanJobConfig(
            HoldScanConfig(mode="internal", channels=[4], trigger_channel=999,
                          out_dir=Path(self.tmp.name) / "invalid")
        )
        with self.assertRaises(ValueError):
            HoldScanWorker(invalid, self.simulation(), session_factory=lambda *_: calls.append(True))
        self.assertEqual(calls, [])
        self.assertFalse((Path(self.tmp.name) / "invalid").exists())

    def test_open_failure_is_reported_without_close_error(self):
        def factory(*_):
            raise OSError("open failed")

        worker = HoldScanWorker(self.operation(), self.simulation(), session_factory=factory)
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

        worker = HoldScanWorker(self.operation(), self.simulation(), session_factory=factory)
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
