"""ConnectionWorker acquisition tests, mirroring the threshold-related cases
in test_connection_worker.py: busy-state rejection, teardown on disconnect/
shutdown, and fault latching. Kept in a separate file (rather than appended
to test_connection_worker.py) so the acquisition-specific addition to
ConnectionWorker is reviewable independently of the existing threshold
suite it mirrors.
"""

import tempfile
import time
import unittest
from pathlib import Path

import radioroc_client  # noqa: F401
from radioroc_client import AcquisitionConfig

from radioroc.application.acquisition import AcquisitionJobConfig
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.jobs import JobBusyError
from radioroc.transport.config import RadiorocConnectionConfig
from tests.test_acquisition_jobs import AcquisitionTransport, adc_payload
from tests.test_connection_worker import ThresholdSession

PORT_CONFIG = RadiorocConnectionConfig(port="fake-control")


class ConnectionWorkerAcquisitionTests(unittest.TestCase):
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

    def operation(self, name="run", *, batches=2, acquisitions_per_batch=2, channels=(4,)):
        if not hasattr(self, "_tmp"):
            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        acquisition = AcquisitionConfig(
            list(channels), trigger_channel=channels[0], batches=batches,
            acquisitions_per_batch=acquisitions_per_batch, timeout_s=1.0,
            threshold_dac=530, trigger_preamp_gain=1,
            out_dir=Path(self._tmp.name) / name,
        )
        return AcquisitionJobConfig(acquisition)

    def transport_and_session(self, **kwargs):
        transport = AcquisitionTransport(**kwargs)
        return transport, ThresholdSession(transport)

    def test_acquisition_job_uses_persistent_owner_and_publishes_verified_batch_summaries(self):
        transport, session = self.transport_and_session(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([100.0, 200.0], [10.0, 20.0])}),
            adc_payload(2, {4: ([300.0, 400.0], [30.0, 40.0])}),
        ])
        worker = self.started(session_factory=lambda config: session)
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")

        worker.run_acquisition(self.operation())
        self.assertEqual(worker.snapshot().state, "scanning")
        with self.assertRaises(JobBusyError):
            worker.read_status()
        with self.assertRaises(JobBusyError):
            worker.disconnect()
        snap = self.wait_for(worker, "connected", timeout=10)
        acquisition = worker.acquisition_snapshot()

        self.assertIsNone(snap.fault)
        self.assertEqual(acquisition.outcome.result.status, "completed")
        self.assertEqual(acquisition.outcome.result.verification["status"], "passed")
        self.assertEqual(acquisition.outcome.result.points, 2)
        self.assertEqual(len(acquisition.rows), 2)
        row0 = dict(acquisition.rows[0])
        self.assertEqual(row0["batch"], 0)
        self.assertEqual(row0["ch4_hg_count"], 2)
        self.assertEqual(row0["ch4_hg_min"], 100.0)
        self.assertEqual(row0["ch4_hg_max"], 200.0)
        self.assertEqual(session.close_calls, 0)

    def test_run_acquisition_rejected_while_busy_or_disconnected(self):
        transport, session = self.transport_and_session(nb_acq=1)
        worker = self.started(session_factory=lambda config: session)
        with self.assertRaises(JobBusyError):
            worker.run_acquisition(self.operation("idle"))

        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        worker.run_acquisition(self.operation("first"))
        self.assertEqual(worker.snapshot().state, "scanning")
        with self.assertRaises(JobBusyError):
            worker.run_acquisition(self.operation("second"))
        self.wait_for(worker, "connected", timeout=10)

    def test_cancel_acquisition_rejected_when_not_scanning(self):
        transport, session = self.transport_and_session(nb_acq=1)
        worker = self.started(session_factory=lambda config: session)
        with self.assertRaises(JobBusyError):
            worker.cancel_acquisition()
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        with self.assertRaises(JobBusyError):
            worker.cancel_acquisition()

    def test_verified_cancellation_returns_to_connected_after_cleanup(self):
        # Cancel via the same "stop after the first completed batch" hook
        # test_acquisition_worker.py's own cancel test uses, rather than
        # racing AcquisitionTransport's word-4 read (which is polled both
        # for the I2C-FIFO-ready and ADC-ready bits, including during
        # preparation -- timing cancellation off it non-deterministically
        # lands before enough state was ever snapshotted, which is a
        # genuinely different (and correctly non-"passed") verification
        # outcome, not a bug in the cancel path being tested here.
        transport, session = self.transport_and_session(nb_acq=2)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        original_publish = worker._publish_acquisition

        def publish_and_cancel(event):
            original_publish(event)
            if event.kind == "point":
                worker.cancel_acquisition()

        worker._publish_acquisition = publish_and_cancel
        worker.run_acquisition(self.operation("cancel", batches=50, acquisitions_per_batch=2))

        snap = self.wait_for(worker, "connected", timeout=10)
        result = worker.acquisition_snapshot().outcome.result
        self.assertEqual((result.status, result.cleanup_status,
                          result.verification["status"]),
                         ("cancelled", "restored", "passed"))
        self.assertIsNone(snap.fault)

    def test_acquisition_fault_latches_until_disconnected_and_reviewed(self):
        transport, session = self.transport_and_session(nb_acq=1)
        transport.fail_snapshot = True
        worker = self.started(session_factory=lambda config: session)
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        worker.run_acquisition(self.operation("fault"))

        snap = self.wait_for(worker, "faulted", timeout=10)
        self.assertIn("acquisition status: failed", snap.fault)
        self.assertIsNotNone(worker.acquisition_snapshot().outcome)
        for command in (worker.refresh, lambda: worker.connect(PORT_CONFIG),
                        lambda: worker.run_acquisition(self.operation("blocked"))):
            with self.assertRaises(JobBusyError):
                command()
        with self.assertRaises(JobBusyError):
            worker.review_fault()

        worker.disconnect()
        idle = self.wait_for(worker, "idle")
        self.assertIsNotNone(idle.fault)
        self.assertEqual(worker.acquisition_snapshot().outcome.result.status, "failed")
        with self.assertRaises(JobBusyError):
            worker.connect(PORT_CONFIG)
        worker.review_fault()
        self.assertIsNone(worker.snapshot().fault)
        self.assertEqual(worker.acquisition_snapshot().outcome.result.status, "failed")

    def test_shutdown_during_job_waits_for_verified_cleanup_then_closes(self):
        transport, session = self.transport_and_session(nb_acq=2)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        original_publish = worker._publish_acquisition

        def publish_and_shutdown(event):
            original_publish(event)
            if event.kind == "point":
                worker.shutdown()

        worker._publish_acquisition = publish_and_shutdown
        worker.run_acquisition(self.operation("shutdown", batches=50, acquisitions_per_batch=2))
        worker.join(10)

        self.assertFalse(worker.is_alive)
        self.assertEqual(worker.snapshot().state, "stopped")
        self.assertEqual(worker.acquisition_snapshot().outcome.result.status, "cancelled")
        self.assertEqual(session.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
