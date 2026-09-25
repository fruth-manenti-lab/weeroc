"""Offline lifecycle tests for the desktop acquisition worker.

Mirrors test_threshold_worker.py's structure and depth, adapted to
acquisition's different "point" shape: one point is a whole batch's raw
per-channel sample lists (not one scalar per DAC code), so the worker
retains bounded per-batch *summaries* rather than raw rows, and unlike
threshold's fixed 0..1023 DAC axis (where hitting the retention cap is a
defensive assertion), acquisition's batch count has no such fixed bound, so
the retained batch summaries are a rolling window of the *most recent*
batches, not a frozen first-N set. See acquisition_worker.py's
MAX_RETAINED_BATCHES docstring.
"""

import csv
from pathlib import Path
import tempfile
import threading
import unittest

from radioroc_client import AcquisitionConfig
from radioroc.application import JobBusyError
from radioroc.application.acquisition import AcquisitionJobConfig
from radioroc.application.acquisition_worker import AcquisitionWorker, MAX_RETAINED_BATCHES
from radioroc.transport.acquisition_simulator import (
    AcquisitionSimulationConfig,
    create_acquisition_simulator,
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
        self.inner = create_acquisition_simulator(operation, simulation)
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


class AcquisitionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def operation(self, *, batches=2, acquisitions_per_batch=2, channels=(4,), name="run"):
        acquisition = AcquisitionConfig(
            list(channels), trigger_channel=channels[0], batches=batches,
            acquisitions_per_batch=acquisitions_per_batch, timeout_s=1.0,
            out_dir=Path(self.tmp.name) / name,
        )
        return AcquisitionJobConfig(acquisition)

    def simulation(self):
        return AcquisitionSimulationConfig(hg_mean=100, hg_stdev=1, lg_mean=10, lg_stdev=1)

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
        worker = AcquisitionWorker(self.operation(), self.simulation(), session_factory=factory)
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

    def test_batch_summaries_are_bounded_and_reflect_the_most_recent_batches(self):
        total_batches = MAX_RETAINED_BATCHES + 20
        operation = self.operation(batches=total_batches, acquisitions_per_batch=1)
        worker = AcquisitionWorker(operation, self.simulation())
        worker.start()
        worker.join(30)

        self.assertFalse(worker.is_alive)
        snapshot = worker.snapshot()
        self.assertIsNotNone(snapshot.outcome)
        result = snapshot.outcome.result
        self.assertEqual((result.status, result.points), ("completed", total_batches))
        # Bounded: never more than the cap, even though far more batches ran.
        self.assertEqual(len(snapshot.rows), MAX_RETAINED_BATCHES)
        # Rolling window: the retained rows are the *most recent* batches,
        # not the earliest ones -- the last retained row's own "batch" entry
        # is the very last batch that ran.
        last_row = dict(snapshot.rows[-1])
        self.assertEqual(last_row["batch"], total_batches - 1)
        first_row = dict(snapshot.rows[0])
        self.assertEqual(first_row["batch"], total_batches - MAX_RETAINED_BATCHES)
        # Each retained row is a compact summary, not raw samples.
        self.assertEqual(last_row["ch4_hg_count"], 1)
        self.assertIn("ch4_hg_min", last_row)
        self.assertIn("ch4_hg_max", last_row)
        self.assertIn("ch4_hg_mean", last_row)
        saved = self.saved_rows(result.csv_path)
        self.assertEqual(len(saved), total_batches)

    def test_cancel_after_point_preserves_that_batch_and_cleanup(self):
        worker = AcquisitionWorker(self.operation(batches=4, acquisitions_per_batch=2), self.simulation())
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
        self.assertEqual(len(self.saved_rows(result.csv_path)), 2)  # 1 batch * 2 acquisitions
        self.assertEqual(result.cleanup_status, "restored")
        self.assertEqual(len(snapshot.rows), 1)

    def test_double_start_is_rejected(self):
        worker = AcquisitionWorker(self.operation(), self.simulation())
        worker.start()
        with self.assertRaises(JobBusyError):
            worker.start()
        worker.cancel()
        worker.join(10)

    def test_invalid_construction_does_not_open_a_session(self):
        calls = []
        invalid = AcquisitionJobConfig(
            AcquisitionConfig([4, 4], trigger_channel=4, out_dir=Path(self.tmp.name) / "invalid")
        )
        with self.assertRaises(ValueError):
            AcquisitionWorker(invalid, self.simulation(), session_factory=lambda *_: calls.append(True))
        self.assertEqual(calls, [])
        self.assertFalse((Path(self.tmp.name) / "invalid").exists())

    def test_open_failure_is_reported_without_close_error(self):
        def factory(*_):
            raise OSError("open failed")

        worker = AcquisitionWorker(self.operation(), self.simulation(), session_factory=factory)
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

        worker = AcquisitionWorker(self.operation(), self.simulation(), session_factory=factory)
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
