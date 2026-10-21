import tempfile
import threading
import time
import unittest
from pathlib import Path

from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.jobs import JobBusyError
from radioroc.transport.config import RadiorocConnectionConfig
from tests.test_acquisition_jobs import AcquisitionTransport
from tests.test_connection_worker import ThresholdSession
from tests import test_connection_worker_acquisition as _acq

_Base = _acq.ConnectionWorkerAcquisitionTests

PORT_CONFIG = RadiorocConnectionConfig(port="fake-control")


class GatedTransport(AcquisitionTransport):
    """Status reads can be made to fail or to block, after a scan fault."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fail_status = False
        self.status_gate = None
        self.status_reads = 0

    def read_word(self, address):
        if address == 100 and (self.fail_status or self.status_gate is not None):
            self.status_reads += 1
            if self.status_gate is not None:
                self.status_gate.wait(3)
            if self.fail_status:
                raise TimeoutError("status read timed out")
        return super().read_word(address)


class FaultAcknowledgeTests(unittest.TestCase):
    wait_for = _Base.wait_for
    started = _Base.started
    operation = _Base.operation

    def faulted_worker(self):
        transport = GatedTransport(nb_acq=1)
        transport.fail_snapshot = True
        session = ThresholdSession(transport)
        worker = self.started(session_factory=lambda config: session)
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        worker.run_acquisition(self.operation("fault"))
        snap = self.wait_for(worker, "faulted", timeout=10)
        self.assertTrue(snap.fault)
        return worker, transport, session

    def test_ack_with_open_session_rechecks_status_and_allows_scans(self):
        worker, transport, session = self.faulted_worker()
        with self.assertRaises(JobBusyError):
            worker.run_acquisition(self.operation("blocked"))
        worker.review_fault()
        snap = self.wait_for(worker, "connected")
        self.assertIsNone(snap.fault)
        self.assertIsNone(snap.error)
        self.assertIsNotNone(snap.status_word)
        self.assertEqual(session.close_calls, 0)
        transport.fail_snapshot = False
        worker.run_acquisition(self.operation("again"))  # accepted: no JobBusyError

    def test_ack_keeps_fault_when_board_does_not_answer(self):
        worker, transport, session = self.faulted_worker()
        transport.fail_status = True
        worker.review_fault()
        snap = self.wait_for(worker, "faulted")
        self.assertIn("not answering", snap.fault)
        self.assertIn("power cycle", snap.fault)
        self.assertEqual(session.close_calls, 0)
        time.sleep(.2)
        self.assertEqual(transport.status_reads, 1)  # no automatic retry loop
        with self.assertRaises(JobBusyError):
            worker.run_acquisition(self.operation("blocked"))
        worker.disconnect()
        self.assertTrue(self.wait_for(worker, "idle").fault)

    def test_ack_refused_while_busy_or_without_fault(self):
        worker, transport, _ = self.faulted_worker()
        transport.status_gate = threading.Event()
        worker.review_fault()
        self.assertEqual(worker.snapshot().state, "reading")
        with self.assertRaises(JobBusyError):
            worker.review_fault()
        with self.assertRaises(JobBusyError):
            worker.run_acquisition(self.operation("blocked"))
        transport.status_gate.set()
        self.wait_for(worker, "connected")
        with self.assertRaises(JobBusyError):
            worker.review_fault()  # connected, no fault

    def test_ack_refused_while_scan_running(self):
        transport = GatedTransport(nb_acq=2)
        worker = self.started(session_factory=lambda config: ThresholdSession(transport))
        worker.connect(PORT_CONFIG)
        self.wait_for(worker, "connected")
        with self.assertRaises(JobBusyError):
            worker.review_fault()
        worker.run_acquisition(self.operation("run"))
        with self.assertRaises(JobBusyError):
            worker.review_fault()
        self.wait_for(worker, "connected", timeout=10)

    def test_released_session_ack_still_clears_fault(self):
        worker, _, _ = self.faulted_worker()
        worker.disconnect()
        self.assertTrue(self.wait_for(worker, "idle").fault)
        worker.review_fault()
        self.assertIsNone(worker.snapshot().fault)


del _Base, _acq


if __name__ == "__main__":
    unittest.main()
