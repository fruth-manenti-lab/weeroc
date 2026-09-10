"""Offline acceptance tests for opt-in threshold restoration verification."""

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from radioroc_client import RadiorocDevice, ThresholdScanConfig, ThresholdScanResult, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_threshold_scan as cli

from test_threshold_jobs import ThresholdTransport


class VerificationTransport(ThresholdTransport):
    """ThresholdTransport with faults that begin during independent verification."""

    def __init__(self, *, short_read=False, fail_read=False, fail_cleanup=False, mismatch=False):
        super().__init__()
        # Keep word 0 active so the verifier must preserve its active bit.
        self.words[0] = bits(67)
        self.original_words[0] = bits(67)
        self.short_read = short_read
        self.fail_read = fail_read
        self.fail_cleanup = fail_cleanup
        self.mismatch = mismatch
        self.read55_count = 0
        self.original_word1_writes = 0
        self.verifier_cleanup_started = False

    def write_word(self, address, value):
        if self.verifier_cleanup_started and self.fail_cleanup and address == 60 and value == bits(0):
            raise TransportIOError("verifier cleanup failed")
        super().write_word(address, value)
        if self.mismatch and address == 1 and value == self.original_words[1]:
            self.original_word1_writes += 1
            # The scan has one internal ``00`` write, one window stop, one
            # cleanup stop, and one final FPGA-1 restore. Change word 6 after
            # scan cleanup has restored all captured words.
            if self.original_word1_writes == 4:
                self.words[6] = bits(99)

    def read_words(self, address, length):
        if address != 55:
            return super().read_words(address, length)
        self.read55_count += 1
        if self.fail_read and self.read55_count >= 2:
            self.verifier_cleanup_started = True
            raise TransportTimeoutError("verifier read failed")
        data = super().read_words(address, length)
        if self.short_read and self.read55_count >= 2:
            return data[:-1]
        return data


def _row_keys(rows):
    keys = []
    for row in rows:
        if "address" in row:
            keys.append((row["address"], row["subadd"]) if "subadd" in row else row["address"])
        else:
            keys.append((row.get("add"), row.get("subadd")))
    return keys


def _row_value(row):
    return row.get("value", row.get("data", row.get("observed")))


class ThresholdVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = ThresholdScanConfig(
            [4], dac_min=0, dac_max=0, dac_step=1, trigger_window_ms=1,
            averages=1, out_dir=Path(self.tmp.name) / "run",
        )

    def run_job(self, transport, config=None, **kwargs):
        operation = ThresholdJobConfig(config or self.base)
        return ThresholdJob().run(RadiorocDevice(transport), operation,
                                  verify_restoration=True, **kwargs)

    def test_complete_t1_and_t2_capture_full_register_sets_and_trace_order(self):
        for t1 in (True, False):
            with self.subTest(t1=t1):
                transport = VerificationTransport()
                config = replace(
                    self.base, t1=t1, channels=[4, 5], use_mask=True,
                    use_ctest=True, trigger_preamp_gain=12,
                    out_dir=Path(self.tmp.name) / ("t1" if t1 else "t2"),
                )
                result = self.run_job(transport, config)
                report = result.verification
                self.assertEqual((result.status, result.cleanup_status, report["status"]),
                    ("completed", "restored", "passed"))
                expected_keys = set(ThresholdJobConfig(config).registers())
                self.assertEqual(set(_row_keys(report["expected"]["asic"])), expected_keys)
                self.assertEqual(set(_row_keys(report["observed"]["asic"])), expected_keys)
                self.assertEqual(set(_row_keys(report["expected"]["fpga"])), {0, 1, 6})
                self.assertEqual(set(_row_keys(report["observed"]["fpga_before_asic"])), {0, 1, 6})
                self.assertEqual(set(_row_keys(report["observed"]["fpga_after_asic"])), {0, 1, 6})
                self.assertEqual(
                    _row_value(next(row for row in report["observed"]["fpga_before_asic"]
                                    if row.get("address") == 0)), bits(67)
                )
                self.assertFalse(report["mismatches"])
                self.assertFalse(report["missing"])
                self.assertEqual(json.loads(result.metadata_path.read_text())["verification"], report)
                if t1:
                    self.assertIn((65, 1), expected_keys)
                    self.assertNotIn((65, 3), expected_keys)
                else:
                    self.assertIn((65, 3), expected_keys)
                    self.assertNotIn((65, 1), expected_keys)

                # The last ASIC read is followed by the verifier's own cleanup:
                # idle word 60, restore the observed word 0 including bit 1,
                # then reread FPGA 0/1/6. The scan's restore of word 6 is earlier.
                asic_reads = [i for i, item in enumerate(transport.trace)
                              if item[:2] == ("read_words", 55)]
                self.assertGreaterEqual(len(asic_reads), 2)
                after_asic = asic_reads[-1]
                fpga_batches = [
                    i for i in range(len(transport.trace) - 2)
                    if transport.trace[i:i + 3] == [("read", 0), ("read", 1), ("read", 6)]
                    and i < after_asic
                ]
                self.assertTrue(fpga_batches)
                self.assertLess(fpga_batches[-1] + 2, after_asic)
                idle = max(i for i in range(after_asic + 1, len(transport.trace))
                           if transport.trace[i] == ("write", 60, bits(0)))
                self.assertEqual(transport.trace[idle + 1], ("write", 0, bits(67)))
                self.assertEqual(
                    [transport.trace[i][1] for i in range(idle + 2, idle + 5)], [0, 1, 6]
                )

    def test_cancelled_run_is_verified_after_scan_cleanup(self):
        transport = VerificationTransport()
        token = CancellationToken()
        config = replace(self.base, dac_max=5)

        def cancel_after_point(event):
            if event.kind == "point":
                token.cancel()

        result = self.run_job(transport, config, cancellation=token, on_event=cancel_after_point)
        self.assertEqual((result.status, result.points, result.verification["status"]),
                         ("cancelled", 1, "passed"))
        self.assertEqual(json.loads(result.metadata_path.read_text())["verification"]["status"], "passed")

    def test_cancelled_during_counter_window_is_verified_after_cleanup(self):
        transport = VerificationTransport()
        token = CancellationToken()
        config = replace(self.base, trigger_window_ms=10_000)
        result_holder = []
        thread = threading.Thread(
            target=lambda: result_holder.append(self.run_job(transport, config, cancellation=token)),
            daemon=True,
        )
        thread.start()
        self.assertTrue(transport.counter_started.wait(2))
        token.cancel()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        result = result_holder[0]
        self.assertEqual((result.status, result.verification["status"]), ("cancelled", "passed"))

    def test_absent_snapshot_is_incomplete_without_any_readback(self):
        from radioroc.application.verification import verify_threshold_restoration

        transport = VerificationTransport()
        report = verify_threshold_restoration(
            RadiorocDevice(transport), None, [(65, 2), (66, 4)], execution_mode="simulation"
        )
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["missing"])
        self.assertEqual(report["observed"], {
            "fpga_before_asic": [], "asic": [], "fpga_after_asic": []
        })
        self.assertEqual(transport.trace, [])

    def test_direct_verifier_has_exact_small_transport_suffix(self):
        from radioroc.application.verification import verify_threshold_restoration

        transport = VerificationTransport()
        device = RadiorocDevice(transport)
        registers = [(65, 2), (66, 4)]
        snapshot = {
            "fpga": {address: transport.original_words[address] for address in (0, 1, 6)},
            "asic": {register: bits(transport.asic[register]) for register in registers},
        }
        report = verify_threshold_restoration(device, snapshot, registers, execution_mode="simulation")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(transport.trace, [
            ("read", 0), ("read", 1), ("read", 6),
            ("read", 0), ("write", 60, bits(0)), ("write", 0, bits(67)),
            ("write_words", 56, bytes([129, 65, 2, 0, 129, 66, 4, 0])),
            ("write", 60, bits(0)), ("write", 60, bits(2)), ("read", 4),
            ("write", 60, bits(4)), ("read_words", 55, 2),
            ("write", 0, bits(3)), ("write", 60, bits(0)), ("write", 0, bits(67)),
            ("read", 0), ("read", 1), ("read", 6),
        ])

    def test_direct_verifier_reports_asic_mismatch_without_repair(self):
        from radioroc.application.verification import verify_threshold_restoration

        transport = VerificationTransport()
        device = RadiorocDevice(transport)
        registers = [(65, 2), (66, 4)]
        snapshot = {
            "fpga": {address: transport.original_words[address] for address in (0, 1, 6)},
            "asic": {register: bits(transport.asic[register]) for register in registers},
        }
        changed = (transport.asic[(65, 2)] + 1) % 256
        transport.asic[(65, 2)] = changed
        report = verify_threshold_restoration(device, snapshot, registers, execution_mode="simulation")
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any(item.get("kind") == "asic" and item.get("add") == 65
                            and item.get("subadd") == 2 for item in report["mismatches"]))
        self.assertEqual(transport.asic[(65, 2)], changed)

    def test_cli_exit_codes_reflect_status_and_verification(self):
        cases = (("completed", "passed", 0), ("cancelled", "passed", 130),
                 ("completed", "failed", 1))
        for status, verification_status, expected_code in cases:
            with self.subTest(status=status, verification=verification_status):
                result = ThresholdScanResult(
                    csv_path=Path(self.tmp.name) / f"{status}-{verification_status}.csv",
                    status=status,
                    verification={"status": verification_status},
                )
                args = ["threshold-scan", "--execute", "--verify-restoration",
                        "--out-dir", str(Path(self.tmp.name) / f"cli-{status}-{verification_status}")]
                with patch("sys.argv", args), \
                     patch.object(cli.RadiorocSerial, "from_config", return_value=ThresholdTransport()), \
                     patch.object(cli.ThresholdJob, "run", return_value=result), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(), expected_code)

    def test_verification_keeps_the_transport_job_lock_until_it_finishes(self):
        transport = VerificationTransport()
        entered = threading.Event()
        release = threading.Event()
        result_holder = []
        second = replace(self.base, out_dir=Path(self.tmp.name) / "second")
        from radioroc.application import verification

        real_verify = verification.verify_threshold_restoration

        def blocked_verify(*args, **kwargs):
            entered.set()
            release.wait(2)
            return real_verify(*args, **kwargs)

        with patch("radioroc.application.threshold.verify_threshold_restoration",
                   side_effect=blocked_verify):
            thread = threading.Thread(
                target=lambda: result_holder.append(self.run_job(transport)), daemon=True
            )
            thread.start()
            self.assertTrue(entered.wait(2))
            with self.assertRaises(JobBusyError):
                ThresholdJob().run(RadiorocDevice(transport), ThresholdJobConfig(second))
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder[0].verification["status"], "passed")

    def test_mismatch_is_reported_without_repairing_scan_state(self):
        transport = VerificationTransport(mismatch=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual((result.status, result.cleanup_status, report["status"]),
                         ("completed", "restored", "failed"))
        self.assertTrue(any(item.get("address") == 6 for item in report["mismatches"]))
        self.assertFalse(any(item[:2] == ("write", 6) for item in transport.trace[-8:]))
        self.assertEqual(json.loads(result.metadata_path.read_text())["status"], "completed")

    def test_short_read_is_incomplete_and_does_not_invent_values(self):
        transport = VerificationTransport(short_read=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["errors"])
        self.assertTrue(report["missing"])
        self.assertTrue(all("add" in item and "subadd" in item for item in report["missing"]))
        self.assertLess(len(report["observed"]["asic"]), len(report["expected"]["asic"]))
        self.assertTrue(all(_row_value(row) is not None for row in report["observed"]["asic"]))

    def test_verifier_read_and_verifier_cleanup_errors_are_separate(self):
        transport = VerificationTransport(fail_read=True, fail_cleanup=True)
        result = self.run_job(transport)
        report = result.verification
        self.assertEqual(result.cleanup_status, "restored")
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["errors"])
        self.assertEqual(report["cleanup"]["status"], "failed")
        self.assertTrue(report["cleanup"]["errors"])
        self.assertTrue(any("verifier read failed" in error for error in report["errors"]))
        self.assertTrue(any("verifier cleanup failed" in error for error in report["cleanup"]["errors"]))

    def test_cli_keeps_primary_scan_verification_and_close_errors_separate(self):
        class CloseFaultTransport(ThresholdTransport):
            def __exit__(self, *args):
                raise TransportIOError("close failed")

        result = ThresholdScanResult(
            csv_path=Path(self.tmp.name) / "thresholdscan.csv",
            metadata_path=Path(self.tmp.name) / "metadata.json",
            status="failed", cleanup_status="failed",
            error=TransportTimeoutError("primary failed"),
            cleanup_errors=["scan cleanup failed"],
            verification={
                "status": "failed", "errors": ["verification failed"],
                "cleanup": {"status": "failed", "errors": ["verification cleanup failed"]},
            },
        )
        args = ["threshold-scan", "--execute", "--verify-restoration",
                "--out-dir", str(Path(self.tmp.name) / "cli")]
        with patch("sys.argv", args), \
             patch.object(cli.RadiorocSerial, "from_config", return_value=CloseFaultTransport()), \
             patch.object(cli.ThresholdJob, "run", return_value=result) as run, \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(), 1)
        self.assertTrue(run.call_args.kwargs["verify_restoration"])
        error_text = output.getvalue() + errors.getvalue()
        for message in ("primary failed", "scan cleanup failed", "verification failed",
                        "verification cleanup failed", "close failed"):
            self.assertIn(message, error_text)

    def test_cli_dry_preview_with_verification_never_constructs_transport_or_output(self):
        output_dir = Path(self.tmp.name) / "preview"
        args = ["threshold-scan", "--verify-restoration", "--port", "/does/not/exist",
                "--out-dir", str(output_dir)]
        with patch("sys.argv", args), \
             patch.object(cli.RadiorocSerial, "from_config",
                           side_effect=AssertionError("transport access")), \
             patch("radioroc.transport.discovery.comports",
                   side_effect=AssertionError("discovery access")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["execution_mode"], "dry-run")
        self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
