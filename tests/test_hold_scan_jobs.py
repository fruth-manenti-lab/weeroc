"""Offline hold-scan acceptance tests using the real device operations."""

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

from radioroc_client import HoldScanConfig, N_CHANNELS, RadiorocDevice, RadiorocMemoryTransport, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig, HoldScanJobError
from radioroc.data.hold_scan import HoldRunWriter
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_hold_scan as cli


def adc_payload(nb_acq, values):
    """Build a word-20 ADC frame payload.

    `values` maps channel -> (high_gain_list, low_gain_list), each of length
    `nb_acq`. Every unlisted channel reports zero for every acquisition.
    """
    zero = ([0.0] * nb_acq, [0.0] * nb_acq)
    payload = bytearray()
    for i in range(nb_acq):
        for channel in range(N_CHANNELS):
            high_list, low_list = values.get(channel, zero)
            low_raw = round(low_list[i] / 0.25)
            high_raw = round(high_list[i] / 0.25)
            payload += low_raw.to_bytes(2, "big") + high_raw.to_bytes(2, "big")
    return bytes(payload)


class HoldTransport(RadiorocMemoryTransport):
    """Scripted ASIC FIFO and ADC batch responses; no analog/timing claims."""

    # Bit 5 (ADC ready) and bit 7 (I2C FIFO ready) both set.
    READY_WORD4 = bits(5)

    def __init__(self, *, nb_acq=2, adc_batches=None):
        super().__init__({
            4: self.READY_WORD4, 21: bits(1), 22: bits(2), 23: bits(3), 24: bits(4),
            25: bits(5), 26: bits(6), 27: bits(7), 28: bits(0), 30: bits(8), 31: bits(9),
            77: bits(10), 78: bits(11), 100: bits(5),
        })
        self.asic = {(a, s): (a * 3 + s) % 256 for a in range(67) for s in range(N_CHANNELS)}
        self.original_asic = dict(self.asic)
        self.original_words = dict(self.words)
        self.nb_acq = nb_acq
        self.adc_batches = iter(adc_batches if adc_batches is not None else [])
        self.trace = []
        self.pending = b""
        self.replies = b""
        self.fail_snapshot = False
        self.fail_adc_read = None
        self.fail_adc_read_at = 0
        self.adc_read_count = 0
        self.poll_token = None
        self.word4_read_started = threading.Event()
        self.release_word4 = threading.Event()
        self.release_word4.set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read_word(self, address):
        self.trace.append(("read", address))
        if address == 4:
            self.word4_read_started.set()
            self.release_word4.wait(5)
            if self.poll_token:
                self.poll_token.cancel()
                return bits(0)
            return self.READY_WORD4
        if address == 29:
            return bits(self.nb_acq)
        return super().read_word(address)

    def write_word(self, address, value):
        self.trace.append(("write", address, value))
        super().write_word(address, value)
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
        if address == 20:
            if self.fail_adc_read is not None and self.adc_read_count >= self.fail_adc_read_at:
                raise self.fail_adc_read
            payload = next(self.adc_batches, None)
            self.adc_read_count += 1
            if payload is None:
                payload = adc_payload(self.nb_acq, {})
            return payload
        return super().read_words(address, length)


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class HoldScanJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.scan = HoldScanConfig(mode="external", channels=[4], trigger_channel=4,
                                   hold_min=0, hold_max=5, hold_step=5, acquisitions=2,
                                   timeout_s=1.0, out_dir=self.directory)
        self.config = HoldScanJobConfig(self.scan)
        self.transport = HoldTransport(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([100.0, 200.0], [10.0, 20.0])}),
            adc_payload(2, {4: ([300.0, 400.0], [30.0, 40.0])}),
        ])
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return HoldScanJob().run(self.device, self.config, **kwargs)

    def manifest(self):
        return json.loads((self.directory / "metadata.json").read_text())

    def test_success_values_progress_and_manifest(self):
        events = []
        result = self.run_job(on_event=events.append)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("completed", "restored", 2))
        written = rows(result.csv_path)
        self.assertEqual(written[0]["hold_delay_ns"], "0")
        self.assertEqual(written[0]["ch4_hg_mean"], "150.0")
        self.assertEqual(written[0]["ch4_lg_mean"], "15.0")
        self.assertEqual(written[0]["ch4_count"], "2")
        self.assertEqual(written[1]["hold_delay_ns"], "5")
        self.assertEqual(written[1]["ch4_hg_mean"], "350.0")
        self.assertEqual(written[1]["ch4_lg_mean"], "35.0")
        self.assertEqual([(e.point, e.completed_points) for e in events if e.kind == "point"], [(0, 1), (5, 2)])
        self.assertEqual([e.status for e in events if e.kind == "state"], ["preparing", "running", "completed"])
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.transport.original_words[address])
        manifest = self.manifest()
        self.assertEqual(manifest["completed_points"], 2)
        self.assertEqual(manifest["execution_mode"], "simulation")
        self.assertEqual(manifest["firmware_status_word"], bits(5))
        self.assertEqual(manifest["cleanup"]["status"], "restored")

    def test_internal_mode_captures_and_restores_hold_code_register(self):
        self.config = HoldScanJobConfig(replace(self.scan, mode="internal", hold_min=0, hold_max=5, hold_step=5))
        result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertEqual(rows(result.csv_path)[0]["hold_code"], "0")
        self.assertEqual(self.transport.asic[65, 8], self.transport.original_asic[65, 8])

    def test_cancel_after_point_preserves_partial_data(self):
        token = CancellationToken()
        events = []

        def progress(event):
            events.append(event)
            if event.kind == "point":
                token.cancel()

        result = self.run_job(cancellation=token, on_event=progress)
        self.assertEqual((result.status, result.points), ("cancelled", 1))
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertIn("cancelling", [event.status for event in events])
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.transport.original_words[address])

    def test_cancel_during_adc_ready_polling(self):
        token = CancellationToken()
        self.transport.poll_token = token
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.points, 0)
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        self.assertEqual(self.manifest()["cleanup"]["status"], "restored")

    def test_precancelled_job_has_manifest_and_no_device_access(self):
        token = CancellationToken()
        token.cancel()
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.transport.trace, [])
        self.assertEqual(self.manifest()["completed_points"], 0)

    def test_reject_second_job_while_first_holds_session_lock(self):
        self.transport.release_word4.clear()
        token = CancellationToken()
        results = []
        thread = threading.Thread(target=lambda: results.append(self.run_job(cancellation=token)))
        thread.start()
        try:
            self.assertTrue(self.transport.word4_read_started.wait(2))
            second = HoldScanJobConfig(replace(self.scan, out_dir=self.directory.parent / "second"))
            with self.assertRaises(JobBusyError):
                HoldScanJob().run(RadiorocDevice(self.transport), second)
            self.assertFalse(Path(second.scan.out_dir).exists())
        finally:
            self.transport.release_word4.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, "completed")
        # Lock is released after terminal cleanup.
        third_transport = HoldTransport(nb_acq=2)
        third = HoldScanJobConfig(replace(self.scan, hold_max=0, out_dir=self.directory.parent / "third"))
        self.assertEqual(HoldScanJob().run(RadiorocDevice(third_transport), third).status, "completed")

    def test_snapshot_failure_does_not_restore_uncaptured_asic_state(self):
        self.transport.fail_snapshot = True
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 0))
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.transport.original_words[address])
        self.assertNotIn("snapshot", self.manifest())
        self.assertIsInstance(result.error, TransportTimeoutError)

    def test_disconnect_preserves_original_error_and_completed_point(self):
        original = TransportIOError("unplugged")
        self.transport.fail_adc_read = original
        self.transport.fail_adc_read_at = 1
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("disconnected", 1))
        self.assertIs(result.error, original)
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "disconnected")
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_cleanup_failure_does_not_mask_original_error(self):
        original = TransportTimeoutError("adc timeout")
        self.transport.fail_adc_read = original
        write = self.device.write_register
        calls = {"count": 0}

        def fail_restore(add, subadd, data):
            if (add, subadd) == (65, 12):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise TransportIOError("restore failed")
            return write(add, subadd, data)

        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertIs(result.error, original)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("failed", "failed", 0))
        self.assertEqual(len(result.cleanup_errors), 1)
        self.assertEqual(self.manifest()["device_state"], "unknown")
        self.assertIn("adc timeout", self.manifest()["error"])

    def test_cleanup_failure_after_success_is_failed(self):
        write = self.device.write_register
        calls = {"count": 0}

        def fail_restore(add, subadd, data):
            if (add, subadd) == (65, 12):
                calls["count"] += 1
                # Two configure_adc_external_hold writes (one per point) plus
                # the final cleanup restore is the third occurrence.
                if calls["count"] == 3:
                    raise TransportIOError("cleanup only")
            return write(add, subadd, data)

        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertEqual((result.status, result.points, result.cleanup_status), ("failed", 2, "failed"))
        self.assertEqual(self.manifest()["status"], "failed")

    def test_data_write_failure_retains_prior_points(self):
        original = HoldRunWriter.append_point

        def append(writer, row):
            if row["hold_delay_ns"] == 5:
                raise OSError("disk full")
            return original(writer, row)

        with patch.object(HoldRunWriter, "append_point", new=append):
            result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 1))
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "failed")
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_manifest_failure_keeps_previous_manifest_and_reports_unsaved_status(self):
        original = HoldRunWriter.update

        def update(writer, manifest):
            if manifest["completed_points"]:
                raise OSError("manifest disk full")
            original(writer, manifest)

        with patch.object(HoldRunWriter, "update", new=update):
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
        for changes in ({"mode": "bogus"}, {"hold_step": 0}, {"acquisitions": 0},
                        {"acquisitions": 256}, {"adc_window_ns": 3}, {"sync_io": "bogus"},
                        {"timeout_s": 0}, {"trigger_channel": 999}, {"channels": [70]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                HoldScanJob().run(self.device, HoldScanJobConfig(replace(self.scan, **changes)))
        self.assertEqual(self.transport.trace, [])
        self.assertFalse(self.directory.exists())

    def test_legacy_api_uses_runner_and_failure_carries_result(self):
        self.transport.fail_adc_read = TransportIOError("unplugged")
        with self.assertRaises(HoldScanJobError) as error:
            self.device.run_hold_scan(self.scan)
        self.assertEqual(error.exception.result.points, 0)
        self.assertEqual(error.exception.result.status, "disconnected")

    def test_legacy_source_execution_without_installed_project_metadata(self):
        with patch("radioroc.application.hold_scan.version", side_effect=PackageNotFoundError):
            result = self.device.run_hold_scan(self.scan)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.manifest()["application_version"], "uninstalled-source")
        self.assertEqual(len(self.manifest()["source_fingerprint"]), 64)

    def test_cli_and_api_have_identical_command_traces_and_values(self):
        expected = HoldScanJob().run(self.device, replace(self.config, initialize_fpga=True))
        actual_transport = HoldTransport(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([100.0, 200.0], [10.0, 20.0])}),
            adc_payload(2, {4: ([300.0, 400.0], [30.0, 40.0])}),
        ])
        cli_dir = self.directory.parent / "cli"
        arguments = ["hold-scan", "--execute", "--mode", "external", "--channels", "4",
                     "--hold-min", "0", "--hold-max", "5", "--hold-step", "5",
                     "--acquisitions", "2", "--timeout-s", "1.0", "--out-dir", str(cli_dir)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=actual_transport), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(actual_transport.trace, self.transport.trace)
        self.assertEqual((cli_dir / "holdscan.csv").read_bytes(), expected.csv_path.read_bytes())

    def test_cli_dry_run_never_constructs_serial_or_creates_outputs(self):
        with patch("sys.argv", ["hold-scan", "--port", "/does/not/exist", "--out-dir", str(self.directory)]), patch.object(cli.RadiorocSerial, "from_config", side_effect=AssertionError("serial access")), contextlib.redirect_stdout(io.StringIO()) as output:
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

    def test_cli_sigint_requests_cancellation_and_returns_130(self):
        original = self.transport.read_words

        def read(address, length):
            if address == 20:
                signal.raise_signal(signal.SIGINT)
            return original(address, length)

        arguments = ["hold-scan", "--execute", "--mode", "external", "--channels", "4",
                     "--hold-min", "0", "--hold-max", "5", "--hold-step", "5",
                     "--acquisitions", "2", "--timeout-s", "1.0", "--out-dir", str(self.directory)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=self.transport), patch.object(self.transport, "read_words", side_effect=read), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 130)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertEqual(self.manifest()["completed_points"], 0)

    def test_threshold_dac_asic_registers_are_captured_and_restored(self):
        """Regression test for a state-leak bug found while testing this job:
        HoldScanJobConfig.registers() omitted ASIC 65/1 (or 65/3) and 65/2 even
        when scan.threshold_dac is set, so device.set_threshold_dac's writes
        were never snapshotted or restored. Fixed in hold_scan.py registers().
        """
        self.config = HoldScanJobConfig(replace(self.scan, threshold_dac=512, t1=True))
        result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertIn((65, 2), set(self.config.registers()))
        self.assertIn((65, 1), set(self.config.registers()))
        self.assertEqual(self.transport.asic[65, 2], self.transport.original_asic[65, 2])
        self.assertEqual(self.transport.asic[65, 1], self.transport.original_asic[65, 1])

    def test_abrupt_process_exit_leaves_durable_nonterminal_run(self):
        code = '''
import os
from pathlib import Path
import sys
from radioroc_client import RadiorocDevice, RadiorocMemoryTransport, HoldScanConfig
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig
words = {4: "00000101", 21: "00000001", 29: "00000010"}
payloads = {20: bytes(64 * 4 * 2)}
device = RadiorocDevice(RadiorocMemoryTransport(words, payloads))
config = HoldScanJobConfig(HoldScanConfig(mode="external", channels=[4], trigger_channel=4,
                                          hold_min=0, hold_max=5, hold_step=5, acquisitions=2,
                                          timeout_s=1.0, out_dir=Path(sys.argv[1])))
def exit_after_point(event):
    if event.kind == "point":
        os._exit(17)
HoldScanJob().run(device, config, on_event=exit_after_point)
'''
        process = subprocess.run([sys.executable, "-c", code, str(self.directory)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 17, process.stderr)
        self.assertEqual(self.manifest()["status"], "running")
        self.assertNotIn("finished_at", self.manifest())
        self.assertEqual(self.manifest()["cleanup"]["status"], "pending")
        self.assertEqual(len(rows(self.directory / "holdscan.csv")), 1)


if __name__ == "__main__":
    unittest.main()
