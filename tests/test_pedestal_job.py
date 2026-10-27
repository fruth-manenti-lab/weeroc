import json
import tempfile
import unittest
from pathlib import Path

from radioroc_client import RadiorocDevice
from radioroc.application import CancellationToken
from radioroc.application.pedestal import PedestalJob, PedestalJobConfig
from radioroc.data.pedestals import PEDESTALS_FILENAME, find_pedestals_for_run
from test_acquisition_jobs import AcquisitionTransport, adc_payload


def pedestal_batches(n_batches, nb=20):
    return [adc_payload(nb, {6: ([95.0 + (i % 3) for i in range(nb)], [89.0] * nb),
                             32: ([107.5] * nb, [120.0] * nb)}) for _ in range(n_batches)]


class PedestalJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "run"
        self.config = PedestalJobConfig([32, 6], self.dir, hold_delay_ns=30, events=40)

    def device(self, **kwargs):
        self.transport = AcquisitionTransport(nb_acq=20, adc_batches=pedestal_batches(2), **kwargs)
        return RadiorocDevice(self.transport)

    def test_config_is_forced_trigger(self):
        job = self.config.acquisition_job_config()
        a = job.acquisition
        self.assertEqual((a.channels, a.trigger_channel, a.batches, a.acquisitions_per_batch), ([6, 32], 6, 2, 20))
        self.assertTrue(a.synchro_trigger)
        self.assertFalse(a.external_trigger)
        self.assertEqual((a.trigger_type, a.trigger_source, a.threshold_dac, a.hold_delay_ns), (0, 3, 550, 30))
        self.assertEqual(PedestalJob.preview(self.config)["pedestal_settings"]["batches"], 2)
        with self.assertRaises(ValueError):
            PedestalJobConfig([6], self.dir, events=2).acquisition_job_config()

    def test_run_writes_pedestals_and_restores(self):
        device = self.device()
        out = PedestalJob().run(device, self.config, verify_restoration=True)
        self.assertEqual(out.acquisition.status, "completed")
        self.assertIsNone(out.error)
        self.assertEqual(out.acquisition.verification["status"], "passed")
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        ps = find_pedestals_for_run(self.dir)
        self.assertEqual(ps, out.pedestals)
        self.assertEqual(ps.channels[6].n, 40)
        self.assertAlmostEqual(ps.hg()[6], 96.0)
        self.assertEqual(ps.hg()[32], 107.5)
        self.assertEqual(ps.lg(), {6: 89.0, 32: 120.0})
        self.assertEqual(ps.settings["pat_gain"], 1)
        self.assertEqual(json.loads((self.dir / PEDESTALS_FILENAME).read_text())["kind"], "pedestals")

    def test_cancelled_run_writes_nothing(self):
        token = CancellationToken()
        token.cancel()
        out = PedestalJob().run(self.device(), self.config, cancellation=token)
        self.assertEqual(out.acquisition.status, "cancelled")
        self.assertIsNone(out.pedestals)
        self.assertIsNotNone(out.error)
        self.assertFalse((self.dir / PEDESTALS_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
