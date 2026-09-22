"""Offline acceptance tests for opt-in acquisition restoration verification."""

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from radioroc_client import AcquisitionConfig, AcquisitionResult, RadiorocDevice, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig, _FPGA_ACQUISITION_ADDRESSES
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_acquire as cli

from test_acquisition_jobs import AcquisitionTransport, adc_payload


class AcquisitionVerificationTransport(AcquisitionTransport):
    """AcquisitionTransport with faults that begin during independent verification."""

    def __init__(self, *, short_read=False, fail_read=False, fail_cleanup=False, mismatch=False,
                 nb_acq=2, adc_batches=None):
        super().__init__(nb_acq=nb_acq, adc_batches=adc_batches)
        # Keep word 0 active so the verifier must preserve its active bit.
        self.words[0] = bits(67)
        self.original_words[0] = bits(67)
        self.short_read = short_read
        self.fail_read = fail_read
        self.fail_cleanup = fail_cleanup
        self.mismatch = mismatch
        self.read55_count = 0
        self.verifier_cleanup_started = False

    def write_word(self, address, value):
        if self.verifier_cleanup_started and self.fail_cleanup and address == 60 and value == bits(0):
            raise TransportIOError("verifier cleanup failed")
        super().write_word(address, value)
        # Word 26 is part of the job's own FPGA footprint and is fully restored
        # by cleanup before verification starts; drift it afterward so only
        # the verifier's independent re-read can notice.
        if self.mismatch and address == 31 and value == self.original_words[31]:
            self.words[26] = bits(200)

    def read_words(self, address, length):
        if address != 55:
            return super().read_words(address, length)
        # configure_adc_external_hold reads back ASIC 65/12 once (a one-byte
        # read_words(55, 1) call) before the job's own snapshot/verifier reads
        # happen. Only count full snapshot-sized reads so the fault below
        # targets the verifier's own readback, not that unrelated read.
        if length > 1:
            self.read55_count += 1
        if self.fail_read and length > 1 and self.read55_count >= 2:
            self.verifier_cleanup_started = True
            raise TransportTimeoutError("verifier read failed")
        data = super().read_words(address, length)
        if self.short_read and length > 1 and self.read55_count >= 2:
            return data[:-1]
        return data


def _row_keys(rows):
    keys = []
    for row in rows:
        if "address" in row:
            keys.append(row["address"])
        else:
            keys.append((row.get("add"), row.get("subadd")))
    return keys


class AcquisitionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = AcquisitionConfig(
            channels=[4], trigger_channel=4, batches=1, acquisitions_per_batch=2, timeout_s=1.0,
            out_dir=Path(self.tmp.name) / "run",
        )

    def run_job(self, transport, config=None, **kwargs):
        operation = AcquisitionJobConfig(config or self.base)
        return AcquisitionJob().run(RadiorocDevice(transport), operation,
                                    verify_restoration=True, **kwargs)

    def test_clean_run_captures_full_fpga_footprint_and_passes(self):
        transport = AcquisitionVerificationTransport()
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual((result.status, result.cleanup_status, report["status"]),
                         ("completed", "restored", "passed"))
        self.assertEqual(set(_row_keys(report["expected"]["fpga"])), set(_FPGA_ACQUISITION_ADDRESSES))
        self.assertEqual(set(_row_keys(report["observed"]["fpga_before_asic"])), set(_FPGA_ACQUISITION_ADDRESSES))
        self.assertEqual(set(_row_keys(report["observed"]["fpga_after_asic"])), set(_FPGA_ACQUISITION_ADDRESSES))
        self.assertFalse(report["mismatches"])
        self.assertFalse(report["missing"])
        self.assertEqual(json.loads(result.metadata_path.read_text())["verification"], report)

    def test_cancelled_run_is_verified_after_cleanup(self):
        transport = AcquisitionVerificationTransport()
        token = CancellationToken()
        config = replace(self.base, batches=2)

        def cancel_after_point(event):
            if event.kind == "point":
                token.cancel()

        result = self.run_job(transport, config, cancellation=token, on_event=cancel_after_point)
        self.assertEqual((result.status, result.points, result.verification["status"]),
                         ("cancelled", 1, "passed"))

    def test_verification_keeps_the_transport_job_lock_until_it_finishes(self):
        transport = AcquisitionVerificationTransport()
        entered = threading.Event()
        release = threading.Event()
        result_holder = []
        second = replace(self.base, out_dir=Path(self.tmp.name) / "second")
        from radioroc.application import verification

        real_verify = verification.verify_restoration

        def blocked_verify(*args, **kwargs):
            entered.set()
            release.wait(2)
            return real_verify(*args, **kwargs)

        with patch("radioroc.application.acquisition.run_restoration_check", side_effect=blocked_verify):
            thread = threading.Thread(target=lambda: result_holder.append(self.run_job(transport)), daemon=True)
            thread.start()
            self.assertTrue(entered.wait(2))
            with self.assertRaises(JobBusyError):
                AcquisitionJob().run(RadiorocDevice(transport), AcquisitionJobConfig(second))
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder[0].verification["status"], "passed")

    def test_mismatch_is_reported_without_repairing_scan_state(self):
        transport = AcquisitionVerificationTransport(mismatch=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual((result.status, result.cleanup_status, report["status"]),
                         ("completed", "restored", "failed"))
        self.assertTrue(any(item.get("address") == 26 for item in report["mismatches"]))
        self.assertFalse(any(item[:2] == ("write", 26) for item in transport.trace[-8:]))
        self.assertEqual(json.loads(result.metadata_path.read_text())["status"], "completed")

    def test_short_read_is_incomplete_and_does_not_invent_values(self):
        transport = AcquisitionVerificationTransport(short_read=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["errors"])
        self.assertTrue(report["missing"])
        self.assertTrue(all("add" in item and "subadd" in item for item in report["missing"]))
        self.assertLess(len(report["observed"]["asic"]), len(report["expected"]["asic"]))

    def test_verifier_read_and_verifier_cleanup_errors_are_separate(self):
        transport = AcquisitionVerificationTransport(fail_read=True, fail_cleanup=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual(result.cleanup_status, "restored")
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["errors"])
        self.assertEqual(report["cleanup"]["status"], "failed")
        self.assertTrue(report["cleanup"]["errors"])
        self.assertTrue(any("verifier read failed" in error for error in report["errors"]))
        self.assertTrue(any("verifier cleanup failed" in error for error in report["cleanup"]["errors"]))

    def test_cli_exit_codes_reflect_status_and_verification(self):
        cases = (("completed", "passed", 0), ("cancelled", "passed", 130), ("completed", "failed", 1))
        for status, verification_status, expected_code in cases:
            with self.subTest(status=status, verification=verification_status):
                result = AcquisitionResult(
                    csv_path=Path(self.tmp.name) / f"{status}-{verification_status}.csv",
                    status=status,
                    verification={"status": verification_status},
                )
                args = ["acquire", "--execute", "--verify-restoration",
                        "--out-dir", str(Path(self.tmp.name) / f"cli-{status}-{verification_status}")]
                with patch("sys.argv", args), \
                     patch.object(cli.RadiorocSerial, "from_config", return_value=AcquisitionTransport()), \
                     patch.object(cli.AcquisitionJob, "run", return_value=result), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(), expected_code)

    def test_cli_dry_preview_with_verification_never_constructs_transport_or_output(self):
        output_dir = Path(self.tmp.name) / "preview"
        args = ["acquire", "--verify-restoration", "--port", "/does/not/exist", "--out-dir", str(output_dir)]
        with patch("sys.argv", args), \
             patch.object(cli.RadiorocSerial, "from_config", side_effect=AssertionError("transport access")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["execution_mode"], "dry-run")
        self.assertFalse(output_dir.exists())

    def test_threshold_dac_registers_are_verified(self):
        """A run that sets threshold_dac captures and verifies ASIC 65/1 and
        65/2 as part of the same restoration check used for every other
        temporary register."""
        transport = AcquisitionVerificationTransport()
        config = replace(self.base, threshold_dac=512, t1=True)
        result = self.run_job(transport, config)
        self.assertEqual(result.verification["status"], "passed")
        expected_keys = {(row["add"], row["subadd"]) for row in result.verification["expected"]["asic"]}
        self.assertIn((65, 2), expected_keys)
        self.assertIn((65, 1), expected_keys)


if __name__ == "__main__":
    unittest.main()
