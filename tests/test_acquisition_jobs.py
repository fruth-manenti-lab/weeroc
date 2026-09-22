"""Offline acquisition-job acceptance tests using the real device operations."""

import contextlib
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from radioroc_client import AcquisitionConfig, N_CHANNELS, RadiorocDevice, RadiorocMemoryTransport, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig
from radioroc.data.acquisition import AcquisitionRunWriter
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_acquire as cli


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


class AcquisitionTransport(RadiorocMemoryTransport):
    """Scripted ASIC FIFO and ADC batch responses; no analog/timing claims."""

    # Bit 5 (ADC ready) and bit 7 (I2C FIFO ready) both set.
    READY_WORD4 = bits(5)

    def __init__(self, *, nb_acq=2, adc_batches=None):
        super().__init__({
            4: self.READY_WORD4, 21: bits(1), 22: bits(2), 23: bits(3), 24: bits(4),
            25: bits(5), 26: bits(6), 27: bits(7), 28: bits(0), 30: bits(8), 31: bits(9),
            100: bits(5),
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


class AcquisitionJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        # threshold_dac=530/trigger_preamp_gain=1 match radioroc_acquire.py's own
        # CLI defaults (applied unconditionally in main() when unset), so the
        # CLI-vs-direct-job trace parity test below compares like with like.
        self.acquisition = AcquisitionConfig(channels=[4], trigger_channel=4, batches=2,
                                             acquisitions_per_batch=2, timeout_s=1.0,
                                             threshold_dac=530, trigger_preamp_gain=1,
                                             out_dir=self.directory)
        self.config = AcquisitionJobConfig(self.acquisition)
        self.transport = AcquisitionTransport(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([100.0, 200.0], [10.0, 20.0])}),
            adc_payload(2, {4: ([300.0, 400.0], [30.0, 40.0])}),
        ])
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return AcquisitionJob().run(self.device, self.config, **kwargs)

    def manifest(self):
        return json.loads((self.directory / "metadata.json").read_text())

    def test_success_values_progress_and_manifest(self):
        events = []
        result = self.run_job(on_event=events.append)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("completed", "restored", 2))
        written = rows(result.csv_path)
        self.assertEqual(len(written), 4)
        self.assertEqual(written[0], {"batch": "0", "event": "0", "channel": "4", "hg": "100.0", "lg": "10.0"})
        self.assertEqual(written[1], {"batch": "0", "event": "1", "channel": "4", "hg": "200.0", "lg": "20.0"})
        self.assertEqual(written[2], {"batch": "1", "event": "0", "channel": "4", "hg": "300.0", "lg": "30.0"})
        self.assertEqual(written[3], {"batch": "1", "event": "1", "channel": "4", "hg": "400.0", "lg": "40.0"})
        point_events = [e for e in events if e.kind == "point"]
        self.assertEqual([e.point for e in point_events], [0, 1])
        self.assertEqual([e.completed_points for e in point_events], [1, 2])
        self.assertEqual(dict(point_events[0].values)["ch4_hg"], [100.0, 200.0])
        self.assertEqual(dict(point_events[0].values)["ch4_lg"], [10.0, 20.0])
        self.assertEqual([e.status for e in events if e.kind == "state"], ["preparing", "running", "completed"])
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.transport.original_words[address])
        manifest = self.manifest()
        self.assertEqual(manifest["completed_points"], 2)
        self.assertEqual(manifest["total_points"], 2)
        self.assertEqual(manifest["execution_mode"], "simulation")
        self.assertEqual(manifest["firmware_status_word"], bits(5))
        self.assertEqual(manifest["cleanup"]["status"], "restored")

    def test_cancel_after_point_preserves_partial_data(self):
        token = CancellationToken()
        events = []

        def progress(event):
            events.append(event)
            if event.kind == "point":
                token.cancel()

        result = self.run_job(cancellation=token, on_event=progress)
        self.assertEqual((result.status, result.points), ("cancelled", 1))
        self.assertEqual(len(rows(result.csv_path)), 2)
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
            second = AcquisitionJobConfig(replace(self.acquisition, out_dir=self.directory.parent / "second"))
            with self.assertRaises(JobBusyError):
                AcquisitionJob().run(RadiorocDevice(self.transport), second)
            self.assertFalse(Path(second.acquisition.out_dir).exists())
        finally:
            self.transport.release_word4.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, "completed")
        third_transport = AcquisitionTransport(nb_acq=2)
        third = AcquisitionJobConfig(replace(self.acquisition, batches=1, out_dir=self.directory.parent / "third"))
        self.assertEqual(AcquisitionJob().run(RadiorocDevice(third_transport), third).status, "completed")

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
        self.assertEqual(len(rows(result.csv_path)), 2)
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
                # The first write is configure_adc_external_hold's own setup
                # write (before the loop); the second is the cleanup restore.
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

    def test_data_write_failure_retains_prior_points(self):
        original = AcquisitionRunWriter.append_events

        def append(writer, event_rows):
            if event_rows and event_rows[0]["batch"] == 1:
                raise OSError("disk full")
            return original(writer, event_rows)

        with patch.object(AcquisitionRunWriter, "append_events", new=append):
            result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 1))
        self.assertEqual(len(rows(result.csv_path)), 2)
        self.assertEqual(self.manifest()["status"], "failed")
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
        for changes in ({"batches": 0}, {"acquisitions_per_batch": 0}, {"acquisitions_per_batch": 256},
                        {"adc_window_ns": 3}, {"timeout_s": 0}, {"trigger_channel": 999},
                        {"channels": [70]}, {"hold_delay_ns": 3}, {"start_batch": -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AcquisitionJob().run(self.device, AcquisitionJobConfig(replace(self.acquisition, **changes)))
        self.assertEqual(self.transport.trace, [])
        self.assertFalse(self.directory.exists())

    def test_callback_error_is_warning_and_does_not_interrupt_data(self):
        def fail(event):
            raise ValueError("display gone")

        result = self.run_job(on_event=fail)
        self.assertEqual((result.status, result.points), ("completed", 2))
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(self.manifest()["warnings"], result.warnings)

    def test_append_mode_continues_batch_numbering_without_truncating(self):
        first = self.run_job()
        self.assertEqual(first.status, "completed")
        first_rows = rows(first.csv_path)
        self.assertEqual(len(first_rows), 4)

        continuation_transport = AcquisitionTransport(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([500.0, 600.0], [50.0, 60.0])}),
        ])
        continuation_config = AcquisitionJobConfig(replace(self.acquisition, batches=1, start_batch=2))
        second = AcquisitionJob().run(RadiorocDevice(continuation_transport), continuation_config,
                                      append=True)
        self.assertEqual(second.status, "completed")
        combined = rows(self.directory / "events.csv")
        self.assertEqual(len(combined), 6)
        self.assertEqual([row["batch"] for row in combined], ["0", "0", "1", "1", "2", "2"])
        self.assertEqual(combined[4], {"batch": "2", "event": "0", "channel": "4", "hg": "500.0", "lg": "50.0"})
        # The second run's manifest replaces the first, per append semantics.
        self.assertEqual(self.manifest()["completed_points"], 1)

    def test_legacy_source_execution_without_installed_project_metadata(self):
        from importlib.metadata import PackageNotFoundError
        with patch("radioroc.application.acquisition.version", side_effect=PackageNotFoundError):
            result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.manifest()["application_version"], "uninstalled-source")
        self.assertEqual(len(self.manifest()["source_fingerprint"]), 64)

    def test_cli_and_api_have_identical_command_traces_and_values(self):
        expected = AcquisitionJob().run(self.device, replace(self.config, initialize_fpga=True))
        actual_transport = AcquisitionTransport(nb_acq=2, adc_batches=[
            adc_payload(2, {4: ([100.0, 200.0], [10.0, 20.0])}),
            adc_payload(2, {4: ([300.0, 400.0], [30.0, 40.0])}),
        ])
        cli_dir = self.directory.parent / "cli"
        arguments = ["acquire", "--execute", "--channels", "4", "--batches", "2",
                     "--acquisitions-per-batch", "2", "--timeout-s", "1.0", "--out-dir", str(cli_dir)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=actual_transport), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(actual_transport.trace, self.transport.trace)
        self.assertEqual((cli_dir / "events.csv").read_bytes(), expected.csv_path.read_bytes())

    def test_cli_dry_run_never_constructs_serial_or_creates_outputs(self):
        with patch("sys.argv", ["acquire", "--port", "/does/not/exist", "--out-dir", str(self.directory)]), patch.object(cli.RadiorocSerial, "from_config", side_effect=AssertionError("serial access")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["execution_mode"], "dry-run")
        self.assertFalse(self.directory.exists())

    def test_cli_sigint_requests_cancellation_and_returns_130(self):
        original = self.transport.read_words

        def read(address, length):
            if address == 20:
                signal.raise_signal(signal.SIGINT)
            return original(address, length)

        arguments = ["acquire", "--execute", "--channels", "4", "--batches", "2",
                     "--acquisitions-per-batch", "2", "--timeout-s", "1.0", "--out-dir", str(self.directory)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=self.transport), patch.object(self.transport, "read_words", side_effect=read), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 130)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertEqual(self.manifest()["completed_points"], 0)

    def test_threshold_dac_asic_registers_are_captured_and_restored(self):
        """Regression-style guard: AcquisitionJobConfig.registers() must include
        ASIC 65/1 (or 65/3) and 65/2 whenever acquisition.threshold_dac is set,
        so device.set_threshold_dac's writes are snapshotted and restored."""
        self.config = AcquisitionJobConfig(replace(self.acquisition, threshold_dac=512, t1=True))
        result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertIn((65, 2), set(self.config.registers()))
        self.assertIn((65, 1), set(self.config.registers()))
        self.assertEqual(self.transport.asic[65, 2], self.transport.original_asic[65, 2])
        self.assertEqual(self.transport.asic[65, 1], self.transport.original_asic[65, 1])


if __name__ == "__main__":
    unittest.main()
