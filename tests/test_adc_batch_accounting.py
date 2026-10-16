"""Offline requested-vs-received ADC event accounting tests (fake transports)."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

from radioroc_client import AcquisitionConfig, HoldScanConfig, RadiorocDevice, bits
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig
from radioroc.data.hold_reader import read_hold_run
from radioroc.transport.errors import TransportProtocolError
from tests.test_acquisition_jobs import AcquisitionTransport, adc_payload as acq_payload
from tests.test_hold_scan_jobs import HoldTransport, adc_payload as hold_payload


class DeviceAccountingTests(unittest.TestCase):
    def device(self, nb_acq, payload):
        transport = HoldTransport(nb_acq=nb_acq, adc_batches=[payload])
        return RadiorocDevice(transport), transport

    def test_matching_count_has_no_warning(self):
        device, _ = self.device(2, hold_payload(2, {}))
        device.acquire_adc_batch(nb_acq=2, timeout_s=1.0)
        info = device.last_adc_batch
        self.assertEqual((info["requested"], info["received"], info["count_word"]), (2, 2, 512))
        self.assertEqual((info["payload_bytes"], info["warnings"]), (2 * 64 * 4, []))

    def test_count_word_not_multiple_of_256_is_flagged(self):
        device, transport = self.device(2, hold_payload(2, {}))
        transport.words[28] = bits(7)
        device.acquire_adc_batch(nb_acq=2, timeout_s=1.0)
        self.assertEqual(device.last_adc_batch["count_word"], 519)
        self.assertEqual(device.last_adc_batch["received"], 2)
        self.assertIn("not a multiple of 256", device.last_adc_batch["warnings"][0])

    def test_short_payload_raises(self):
        device, _ = self.device(2, hold_payload(2, {})[:-4])
        with self.assertRaises(TransportProtocolError):
            device.acquire_adc_batch(nb_acq=2, timeout_s=1.0)
        self.assertEqual(device.last_adc_batch["requested"], 2)


class HoldAccountingTests(unittest.TestCase):
    def run_scan(self, received):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name) / "run"
        scan = HoldScanConfig(mode="external", channels=[4], trigger_channel=4, hold_min=0, hold_max=0,
                              hold_step=5, acquisitions=2, timeout_s=1.0, out_dir=directory)
        transport = HoldTransport(nb_acq=received, adc_batches=[hold_payload(received, {})])
        result = HoldScanJob().run(RadiorocDevice(transport), HoldScanJobConfig(scan))
        with result.csv_path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        return result, rows, directory

    def test_match(self):
        result, rows, _ = self.run_scan(2)
        self.assertEqual(result.status, "completed")
        self.assertEqual((rows[0]["requested"], rows[0]["received"]), ("2", "2"))
        self.assertEqual(result.warnings, [])

    def test_more_received(self):
        result, rows, directory = self.run_scan(5)
        self.assertEqual((rows[0]["requested"], rows[0]["received"], rows[0]["ch4_count"]), ("2", "5", "5"))
        self.assertTrue(any("requested 2 events but received 5" in w for w in result.warnings))
        self.assertEqual(json.loads((directory / "metadata.json").read_text())["warnings"], result.warnings)
        saved = read_hold_run(directory)
        self.assertEqual(saved.rows[0]["received"], 5)

    def test_fewer_received(self):
        result, rows, _ = self.run_scan(1)
        self.assertEqual((rows[0]["requested"], rows[0]["received"]), ("2", "1"))
        self.assertTrue(any("received 1" in w for w in result.warnings))


class AcquisitionAccountingTests(unittest.TestCase):
    def run_acq(self, received_per_batch, configure=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name) / "run"
        acquisition = AcquisitionConfig(channels=[4], trigger_channel=4, batches=len(received_per_batch),
                                        acquisitions_per_batch=2, timeout_s=1.0, threshold_dac=530,
                                        trigger_preamp_gain=1, out_dir=directory)
        transport = AcquisitionTransport(nb_acq=received_per_batch[0],
                                         adc_batches=[acq_payload(n, {}) for n in received_per_batch])
        result = AcquisitionJob().run(RadiorocDevice(transport), AcquisitionJobConfig(acquisition))
        return result, json.loads((directory / "metadata.json").read_text())

    def test_match(self):
        result, manifest = self.run_acq([2, 2])
        self.assertEqual(result.warnings, [])
        self.assertEqual([(b["requested"], b["received"], b["mismatch"]) for b in manifest["batch_counts"]],
                         [(2, 2, False), (2, 2, False)])

    def test_more_received(self):
        result, manifest = self.run_acq([5])
        self.assertTrue(any("requested 2 events but received 5" in w for w in result.warnings))
        self.assertEqual(manifest["batch_counts"][0]["received"], 5)
        self.assertTrue(manifest["batch_counts"][0]["mismatch"])
        self.assertEqual(manifest["warnings"], result.warnings)

    def test_fewer_received(self):
        result, manifest = self.run_acq([1])
        self.assertEqual((manifest["batch_counts"][0]["received"], manifest["batch_counts"][0]["mismatch"]), (1, True))
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
