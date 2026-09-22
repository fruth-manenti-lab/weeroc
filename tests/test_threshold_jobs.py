"""Offline threshold acceptance tests using the real device operations."""

import contextlib
import csv
from dataclasses import replace
import io
from importlib.metadata import PackageNotFoundError
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from radioroc_client import RadiorocDevice, RadiorocMemoryTransport, ThresholdScanConfig, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig, ThresholdJobError
from radioroc.data.threshold import ThresholdRunWriter
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_threshold_scan as cli


class ThresholdTransport(RadiorocMemoryTransport):
    """Scripted ASIC FIFO and counter responses; no analog/timing claims."""
    def __init__(self, counts=(10, 30, 20, 40)):
        super().__init__({0: bits(7), 1: bits(3), 6: bits(12), 100: bits(5)})
        self.asic = {(a, s): (a * 3 + s) % 256 for a in range(67) for s in range(64)}
        self.original_asic = dict(self.asic)
        self.original_words = dict(self.words)
        self.counts = iter(counts)
        self.trace = []
        self.pending = b""
        self.replies = b""
        self.read_count = 0
        self.counter_started = threading.Event()
        self.fail_counter = None
        self.fail_snapshot = False
        self.poll_token = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read_word(self, address):
        self.trace.append(("read", address))
        if address == 4:
            if self.poll_token:
                self.poll_token.cancel()
                return bits(0)
            return bits(1)
        return super().read_word(address)

    def write_word(self, address, value):
        self.trace.append(("write", address, value))
        super().write_word(address, value)
        if address == 1 and value.startswith("10"):
            self.counter_started.set()
        if address == 60 and value == bits(2):
            for offset in range(0, len(self.pending), 4):
                chip, add, subadd, data = self.pending[offset:offset + 4]
                if chip & 128:
                    self.replies += bytes([self.asic[add, subadd]])
                else:
                    self.asic[add, subadd] = data
            self.pending = b""

    def write_words(self, address, payload):
        self.trace.append(("write_words", address, payload))
        if address == 56:
            self.pending += payload
        else:
            super().write_words(address, payload)

    def read_words(self, address, length):
        self.trace.append(("read_words", address, length))
        if address == 55:
            if self.fail_snapshot:
                raise TransportTimeoutError("snapshot timeout")
            data, self.replies = self.replies, b""
            return data
        if address == 96:
            if self.fail_counter and self.read_count == 2:
                raise self.fail_counter
            self.read_count += 1
            return next(self.counts).to_bytes(4, "little")
        return super().read_words(address, length)


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class ThresholdJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.scan = ThresholdScanConfig([4], dac_min=0, dac_max=5, dac_step=5,
                                        trigger_window_ms=1, averages=2, out_dir=self.directory)
        self.config = ThresholdJobConfig(self.scan)
        self.transport = ThresholdTransport()
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return ThresholdJob().run(self.device, self.config, **kwargs)

    def manifest(self):
        return json.loads((self.directory / "metadata.json").read_text())

    def test_success_values_progress_and_restoration(self):
        events = []
        result = self.run_job(on_event=events.append)
        self.assertEqual((result.status, result.cleanup_status, result.points, result.attempts),
                         ("completed", "restored", 2, 4))
        self.assertEqual(rows(result.csv_path), [{"DAC": "0", "ch4": "20000.0"}, {"DAC": "5", "ch4": "30000.0"}])
        self.assertEqual([r["trigger_count"] for r in rows(result.attempts_csv_path)], ["10", "30", "20", "40"])
        self.assertEqual([(e.point, e.completed_points) for e in events if e.kind == "point"], [(0, 1), (5, 2)])
        self.assertEqual([e.status for e in events if e.kind == "state"], ["preparing", "running", "completed"])
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in (0, 1, 6):
            self.assertEqual(self.transport.words[address], self.transport.original_words[address])
        manifest = self.manifest()
        self.assertEqual(manifest["completed_attempts"], 4)
        self.assertEqual(manifest["execution_mode"], "simulation")
        self.assertEqual(manifest["firmware_status_word"], bits(5))
        # Existing counter reset/enable/stop sequence and little-endian counts.
        writes = [t[2] for t in self.transport.trace if t[:2] == ("write", 1)]
        self.assertEqual(writes[:4], ["01000011", "00000011", "10000011", "00000011"])

    def test_t2_ctest_gain_and_multichannel_values_restore_all_state(self):
        self.config = ThresholdJobConfig(replace(self.scan, channels=[4, 5], averages=1,
                                                  t1=False, use_ctest=True, trigger_preamp_gain=12))
        result = self.run_job()
        self.assertEqual(rows(result.csv_path), [
            {"DAC": "0", "ch4": "10000.0", "ch5": "30000.0"},
            {"DAC": "5", "ch4": "20000.0", "ch5": "40000.0"}])
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_cancel_after_point_preserves_partial_data(self):
        token = CancellationToken()
        events = []
        def progress(event):
            events.append(event)
            if event.kind == "point":
                token.cancel()
        result = self.run_job(cancellation=token, on_event=progress)
        self.assertEqual((result.status, result.points, result.attempts), ("cancelled", 1, 2))
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertIn("cancelling", [event.status for event in events])
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_cancel_mid_point_retains_completed_counter_windows(self):
        token = CancellationToken()
        original = self.transport.read_words
        def read(address, length):
            data = original(address, length)
            if address == 96:
                token.cancel()
            return data
        with patch.object(self.transport, "read_words", side_effect=read):
            result = self.run_job(cancellation=token)
        self.assertEqual((result.status, result.points, result.attempts), ("cancelled", 0, 1))
        self.assertEqual(len(rows(result.attempts_csv_path)), 1)
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_cancel_during_window_and_reject_second_wrapper_on_session(self):
        self.config = ThresholdJobConfig(replace(self.scan, trigger_window_ms=10000))
        token = CancellationToken()
        results = []
        thread = threading.Thread(target=lambda: results.append(self.run_job(cancellation=token)))
        thread.start()
        try:
            self.assertTrue(self.transport.counter_started.wait(2))
            second = ThresholdJobConfig(replace(self.scan, out_dir=self.directory.parent / "second"))
            with self.assertRaises(JobBusyError):
                ThresholdJob().run(RadiorocDevice(self.transport), second)
            self.assertFalse(Path(second.scan.out_dir).exists())
        finally:
            token.cancel()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, "cancelled")
        # Lock is released after terminal cleanup.
        third = ThresholdJobConfig(replace(self.scan, out_dir=self.directory.parent / "third"))
        self.assertEqual(ThresholdJob().run(self.device, third).status, "completed")

    def test_cancel_during_i2c_ready_polling(self):
        token = CancellationToken()
        self.transport.poll_token = token
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.points, 0)
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        self.assertEqual(self.transport.words[0], self.transport.original_words[0])
        self.assertEqual(self.manifest()["cleanup"]["status"], "restored")

    def test_precancelled_job_has_manifest_and_no_device_access(self):
        token = CancellationToken()
        token.cancel()
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.transport.trace, [])
        self.assertEqual(self.manifest()["completed_points"], 0)

    def test_snapshot_failure_does_not_restore_uncaptured_asic_state(self):
        self.transport.fail_snapshot = True
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 0))
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        self.assertEqual(self.transport.words[0], self.transport.original_words[0])
        self.assertNotIn("snapshot", self.manifest())
        self.assertIsInstance(result.error, TransportTimeoutError)

    def test_disconnect_preserves_original_error_and_completed_point(self):
        original = TransportIOError("unplugged")
        self.transport.fail_counter = original
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("disconnected", 1))
        self.assertIs(result.error, original)
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "disconnected")

    def test_cleanup_failure_does_not_mask_original_error(self):
        original = TransportTimeoutError("counter timeout")
        self.transport.fail_counter = original
        write = self.device.write_register
        def fail_restore(add, subadd, data):
            if self.transport.read_count >= 2 and (add, subadd) == (65, 2) and data == bits(self.transport.original_asic[65, 2]):
                raise TransportIOError("restore failed")
            return write(add, subadd, data)
        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertIs(result.error, original)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("failed", "failed", 1))
        self.assertEqual(len(result.cleanup_errors), 1)
        self.assertEqual(self.manifest()["device_state"], "unknown")
        self.assertIn("counter timeout", self.manifest()["error"])

    def test_cleanup_failure_after_success_is_failed(self):
        write = self.device.write_register
        def fail_restore(add, subadd, data):
            if self.transport.read_count == 4 and (add, subadd) == (65, 2):
                raise TransportIOError("cleanup only")
            return write(add, subadd, data)
        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertEqual((result.status, result.points, result.cleanup_status), ("failed", 2, "failed"))
        self.assertEqual(self.manifest()["status"], "failed")

    def test_data_write_failure_retains_prior_points_and_attempts(self):
        original = ThresholdRunWriter.append_point
        def append(writer, row):
            if row["DAC"] == 5:
                raise OSError("disk full")
            return original(writer, row)
        with patch.object(ThresholdRunWriter, "append_point", new=append):
            result = self.run_job()
        self.assertEqual((result.status, result.points, result.attempts), ("failed", 1, 4))
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "failed")
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_manifest_failure_keeps_previous_manifest_and_reports_unsaved_status(self):
        original = ThresholdRunWriter.update
        def update(writer, manifest):
            if manifest["completed_points"]:
                raise OSError("manifest disk full")
            original(writer, manifest)
        with patch.object(ThresholdRunWriter, "update", new=update):
            result = self.run_job()
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.persistence_errors)
        self.assertEqual(self.manifest()["status"], "running")
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_existing_run_is_never_truncated(self):
        result = self.run_job()
        saved = result.csv_path.read_bytes()
        self.transport.trace.clear()
        with self.assertRaises(FileExistsError):
            self.run_job()
        self.assertEqual(result.csv_path.read_bytes(), saved)
        self.assertEqual(self.transport.trace, [])

    def test_invalid_configuration_has_no_hardware_or_files(self):
        for changes in ({"dac_min": -1}, {"dac_max": 1024}, {"trigger_window_ms": float("nan")},
                        {"averages": 1.5}, {"channels": [4, 4]}, {"channels": [True]}, {"t1": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ThresholdJob().run(self.device, ThresholdJobConfig(replace(self.scan, **changes)))
        self.assertEqual(self.transport.trace, [])
        self.assertFalse(self.directory.exists())

    def test_legacy_api_uses_runner_and_failure_carries_result(self):
        self.transport.fail_counter = TransportIOError("unplugged")
        with self.assertRaises(ThresholdJobError) as error:
            self.device.run_threshold_scan(self.scan)
        self.assertEqual(error.exception.result.points, 1)
        self.assertEqual(error.exception.result.status, "disconnected")

    def test_legacy_source_execution_without_installed_project_metadata(self):
        with patch("radioroc.application.threshold.version", side_effect=PackageNotFoundError):
            result = self.device.run_threshold_scan(self.scan)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.manifest()["application_version"], "uninstalled-source")
        self.assertEqual(len(self.manifest()["source_fingerprint"]), 64)

    def test_cli_and_api_have_identical_command_traces_and_values(self):
        expected = ThresholdJob().run(self.device, replace(self.config, initialize_fpga=True))
        actual_transport = ThresholdTransport()
        cli_dir = self.directory.parent / "cli"
        arguments = ["threshold-scan", "--execute", "--dac-min", "0", "--dac-max", "5", "--dac-step", "5",
                     "--window-ms", "1", "--averages", "2", "--out-dir", str(cli_dir)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=actual_transport), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(actual_transport.trace, self.transport.trace)
        self.assertEqual((cli_dir / "thresholdscan.csv").read_bytes(), expected.csv_path.read_bytes())

    def test_cli_dry_run_never_constructs_serial_or_creates_outputs(self):
        with patch("sys.argv", ["threshold-scan", "--port", "/does/not/exist", "--out-dir", str(self.directory)]), patch.object(cli.RadiorocSerial, "from_config", side_effect=AssertionError("serial access")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["execution_mode"], "dry-run")
        self.assertFalse(self.directory.exists())

    def test_callback_error_is_warning_and_does_not_interrupt_data(self):
        def fail(event):
            raise ValueError("display gone")
        result = self.run_job(on_event=fail)
        self.assertEqual((result.status, result.points), ("completed", 2))
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(self.manifest()["warnings"], result.warnings)

    def test_explicit_preparation_persists_after_temporary_scan_restoration(self):
        self.config = replace(self.config, initialize_fpga=True, apply_defaults=True)
        expected = self.config.load_rows()
        result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.transport.words[0], "00111111")
        self.assertEqual(self.transport.words[1], "01000000")
        for row in expected:
            self.assertEqual(self.transport.asic[row.add, row.subadd], int(row.data, 2))
        self.assertEqual(self.manifest()["preparation"]["status"], "completed")

    def test_preparation_failure_reports_unknown_configuration(self):
        self.config = replace(self.config, apply_defaults=True)
        with patch.object(self.transport, "write_words", side_effect=TransportIOError("apply interrupted")):
            result = self.run_job()
        self.assertEqual((result.status, result.cleanup_status), ("disconnected", "failed"))
        self.assertEqual(result.points, 0)
        self.assertEqual(self.manifest()["device_state"], "unknown")
        self.assertEqual(self.manifest()["preparation"]["status"], "failed_or_cancelled")

    def test_i2c_cleanup_error_preserves_original_poll_error(self):
        primary = TransportTimeoutError("original poll failure")
        write = self.transport.write_word
        read = self.transport.read_word
        def fail_poll(address):
            if address == 4:
                raise primary
            return read(address)
        def fail_cleanup(address, data):
            if address == 0 and data == bits(7):
                raise TransportIOError("bus cleanup failed")
            write(address, data)
        with patch.object(self.transport, "read_word", side_effect=fail_poll), patch.object(self.transport, "write_word", side_effect=fail_cleanup):
            result = self.run_job()
        self.assertIs(result.error, primary)
        self.assertTrue(self.manifest()["error_notes"])
        self.assertEqual(result.cleanup_status, "failed")

    def test_cli_sigint_requests_cancellation_and_returns_130(self):
        original = self.transport.read_words
        def read(address, length):
            data = original(address, length)
            if address == 96:
                signal.raise_signal(signal.SIGINT)
            return data
        arguments = ["threshold-scan", "--execute", "--window-ms", "1", "--averages", "2",
                     "--out-dir", str(self.directory)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=self.transport), patch.object(self.transport, "read_words", side_effect=read), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 130)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertEqual(self.manifest()["completed_attempts"], 1)

    def test_abrupt_process_exit_leaves_durable_nonterminal_run(self):
        code = '''
import os
from pathlib import Path
import sys
from radioroc_client import RadiorocDevice, RadiorocMemoryTransport, ThresholdScanConfig
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig
device = RadiorocDevice(RadiorocMemoryTransport({4: '00000001'}, {96: (3).to_bytes(4, 'little')}))
config = ThresholdJobConfig(ThresholdScanConfig([4], dac_min=0, dac_max=5, dac_step=5,
                                               trigger_window_ms=1, out_dir=Path(sys.argv[1])))
def exit_after_point(event):
    if event.kind == 'point':
        os._exit(17)
ThresholdJob().run(device, config, on_event=exit_after_point)
'''
        process = subprocess.run([sys.executable, "-c", code, str(self.directory)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 17, process.stderr)
        self.assertEqual(self.manifest()["status"], "running")
        self.assertNotIn("finished_at", self.manifest())
        self.assertEqual(self.manifest()["cleanup"]["status"], "pending")
        self.assertEqual(rows(self.directory / "thresholdscan.csv"), [{"DAC": "0", "ch4": "3000.0"}])


if __name__ == "__main__":
    unittest.main()
