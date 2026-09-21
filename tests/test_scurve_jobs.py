"""Offline S-curve acceptance tests using the real device operations."""

import contextlib
import csv
from dataclasses import replace
import io
from importlib.metadata import PackageNotFoundError
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from radioroc_client import N_CHANNELS, RadiorocDevice, RadiorocMemoryTransport, ScurveConfig, bits
from radioroc.application import CancellationToken, JobBusyError
from radioroc.application.scurve import ScurveJob, ScurveJobConfig, ScurveJobError
from radioroc.data.scurve import ScurveRunWriter
from radioroc.transport.errors import TransportIOError, TransportTimeoutError
from scripts import radioroc_scurve as cli


class ScurveTransport(RadiorocMemoryTransport):
    """Scripted ASIC FIFO and per-point trigger-count responses.

    `point_readings` scripts one `(pulse_data, fifo9)` byte pair per
    channel-per-DAC measurement, consumed in scan order; unscripted calls
    fall back to a default pair.
    """

    # Bit index 7 (I2C FIFO ready) set; matches HoldTransport's convention.
    READY_WORD4 = bits(5)
    DEFAULT_READING = (250, 100)

    def __init__(self, *, point_readings=None):
        super().__init__({
            0: "00000000", 1: "01000000", 3: "00000000", 4: self.READY_WORD4,
            6: "00000000", 100: bits(5),
        })
        self.asic = {(a, s): (a * 3 + s) % 256 for a in range(67) for s in range(N_CHANNELS)}
        self.original_asic = dict(self.asic)
        self.original_words = dict(self.words)
        self.point_readings = iter(point_readings if point_readings is not None else [])
        self.trace = []
        self.pending = b""
        self.replies = b""
        self.fail_snapshot = False
        self.fail_point_read = None
        self.fail_point_read_at = 0
        self.point_read_count = 0
        self.cancel_after_reads = None
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
        if address == 8:
            if self.fail_point_read is not None and self.point_read_count >= self.fail_point_read_at:
                raise self.fail_point_read
            pulse_data, fifo9 = next(self.point_readings, self.DEFAULT_READING)
            self.point_read_count += 1
            if self.cancel_after_reads is not None:
                token, count = self.cancel_after_reads
                if self.point_read_count == count:
                    token.cancel()
            return bytes([pulse_data, fifo9])
        return super().read_words(address, length)


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class ScurveJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.scan = ScurveConfig(channels=[4, 5], dac_min=0, dac_max=1, dac_step=1,
                                 clock_index=3, out_dir=self.directory)
        self.config = ScurveJobConfig(self.scan)
        # 2 DAC points x 2 channels = 4 scripted point-level reads.
        self.readings = [(250, 125), (100, 50), (200, 200), (255, 0)]
        self.transport = ScurveTransport(point_readings=list(self.readings))
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return ScurveJob().run(self.device, self.config, **kwargs)

    def manifest(self):
        return json.loads((self.directory / "metadata.json").read_text())

    def expected_word(self, address, *, clock_index=None):
        """Word 1's clock-index bits are set during preparation and, unlike
        the per-point gate bits, are never reverted to the pre-run default;
        every other word in `_FPGA_SCURVE_ADDRESSES` is fully temporary."""
        if address != 1:
            return self.transport.original_words[address]
        clock_index = self.scan.clock_index if clock_index is None else clock_index
        original = self.transport.original_words[1]
        return original[:4] + bits(clock_index, 2) + original[6:]

    def test_success_values_progress_and_manifest(self):
        events = []
        result = self.run_job(on_event=events.append)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("completed", "restored", 2))
        written = rows(result.csv_path)
        self.assertEqual(written[0]["DAC"], "0")
        self.assertEqual(written[0]["ch4"], "50.0")
        self.assertTrue(math.isnan(float(written[0]["ch5"])))
        self.assertEqual(written[1]["DAC"], "1")
        self.assertEqual(written[1]["ch4"], "100.0")
        self.assertEqual(written[1]["ch5"], "0.0")
        self.assertEqual([(e.point, e.completed_points) for e in events if e.kind == "point"], [(0, 1), (1, 2)])
        self.assertEqual([e.status for e in events if e.kind == "state"], ["preparing", "running", "completed"])
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.expected_word(address))
        manifest = self.manifest()
        self.assertEqual(manifest["completed_points"], 2)
        self.assertEqual(manifest["execution_mode"], "simulation")
        self.assertEqual(manifest["firmware_status_word"], bits(5))
        self.assertEqual(manifest["cleanup"]["status"], "restored")
        self.assertEqual(manifest["units"], {"DAC": "code", "value": "percent"})

    def test_cancel_after_point_preserves_partial_data(self):
        self.scan = replace(self.scan, channels=[4])
        self.config = ScurveJobConfig(self.scan)
        self.transport = ScurveTransport(point_readings=[(250, 125), (200, 200)])
        self.device = RadiorocDevice(self.transport)
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
            self.assertEqual(self.transport.words[address], self.expected_word(address))

    def test_cancel_mid_point_discards_incomplete_row(self):
        """Cancellation partway through a DAC point's channel sweep must not
        write a partial row: only the third of four checkpoints (the one
        following the second channel's own measurement) observes the
        cancellation, so the second DAC point's row is discarded whole."""
        token = CancellationToken()
        # Cancel once the 3rd point-level read (DAC=1, ch4) has returned; the
        # next checkpoint (before ch5's read) then raises.
        self.transport.cancel_after_reads = (token, 3)
        result = self.run_job(cancellation=token)
        self.assertEqual((result.status, result.points), ("cancelled", 1))
        written = rows(result.csv_path)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["DAC"], "0")
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.expected_word(address))

    def test_cancel_during_i2c_ready_polling(self):
        token = CancellationToken()
        self.transport.poll_token = token
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.points, 0)
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in (0, 1, 3, 6):
            self.assertEqual(self.transport.words[address], self.expected_word(address))
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
            second = ScurveJobConfig(replace(self.scan, out_dir=self.directory.parent / "second"))
            with self.assertRaises(JobBusyError):
                ScurveJob().run(RadiorocDevice(self.transport), second)
            self.assertFalse(Path(second.scan.out_dir).exists())
        finally:
            self.transport.release_word4.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, "completed")
        # Lock is released after terminal cleanup.
        third_transport = ScurveTransport(point_readings=[(250, 125)])
        third = ScurveJobConfig(replace(self.scan, channels=[4], dac_max=0,
                                        out_dir=self.directory.parent / "third"))
        self.assertEqual(ScurveJob().run(RadiorocDevice(third_transport), third).status, "completed")

    def test_snapshot_failure_does_not_restore_uncaptured_asic_state(self):
        self.transport.fail_snapshot = True
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 0))
        self.assertEqual(self.transport.asic, self.transport.original_asic)
        for address in self.transport.original_words:
            self.assertEqual(self.transport.words[address], self.expected_word(address))
        self.assertNotIn("snapshot", self.manifest())
        self.assertIsInstance(result.error, TransportTimeoutError)

    def test_disconnect_preserves_original_error_and_completed_point(self):
        original = TransportIOError("unplugged")
        self.transport.fail_point_read = original
        # First 2 reads (DAC=0, ch4 and ch5) succeed, completing one point;
        # the 3rd (DAC=1, ch4) fails.
        self.transport.fail_point_read_at = 2
        result = self.run_job()
        self.assertEqual((result.status, result.points), ("disconnected", 1))
        self.assertIs(result.error, original)
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "disconnected")
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_cleanup_failure_does_not_mask_original_error(self):
        original = TransportTimeoutError("point read timeout")
        self.transport.fail_point_read = original
        self.transport.fail_point_read_at = 0
        write = self.device.write_register
        calls = {"count": 0}

        def fail_restore(add, subadd, data):
            if (add, subadd) == (65, 2):
                calls["count"] += 1
                # The 1st occurrence is set_threshold_dac's own preparation
                # write for DAC=0 (before the scripted read fails); the 2nd
                # is the cleanup restore.
                if calls["count"] == 2:
                    raise TransportIOError("restore failed")
            return write(add, subadd, data)

        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertIs(result.error, original)
        self.assertEqual((result.status, result.cleanup_status, result.points), ("failed", "failed", 0))
        self.assertEqual(len(result.cleanup_errors), 1)
        self.assertEqual(self.manifest()["device_state"], "unknown")
        self.assertIn("point read timeout", self.manifest()["error"])

    def test_cleanup_failure_after_success_is_failed(self):
        write = self.device.write_register
        calls = {"count": 0}

        def fail_restore(add, subadd, data):
            if (add, subadd) == (65, 2):
                calls["count"] += 1
                # set_threshold_dac writes (65, 2) once per DAC point (2 here);
                # the final cleanup restore is the third occurrence.
                if calls["count"] == 3:
                    raise TransportIOError("cleanup only")
            return write(add, subadd, data)

        with patch.object(self.device, "write_register", side_effect=fail_restore):
            result = self.run_job()
        self.assertEqual((result.status, result.points, result.cleanup_status), ("failed", 2, "failed"))
        self.assertEqual(self.manifest()["status"], "failed")

    def test_data_write_failure_retains_prior_points(self):
        original = ScurveRunWriter.append_point

        def append(writer, row):
            if row["DAC"] == 1:
                raise OSError("disk full")
            return original(writer, row)

        with patch.object(ScurveRunWriter, "append_point", new=append):
            result = self.run_job()
        self.assertEqual((result.status, result.points), ("failed", 1))
        self.assertEqual(len(rows(result.csv_path)), 1)
        self.assertEqual(self.manifest()["status"], "failed")
        self.assertEqual(self.transport.asic, self.transport.original_asic)

    def test_manifest_failure_keeps_previous_manifest_and_reports_unsaved_status(self):
        original = ScurveRunWriter.update

        def update(writer, manifest):
            if manifest["completed_points"]:
                raise OSError("manifest disk full")
            original(writer, manifest)

        with patch.object(ScurveRunWriter, "update", new=update):
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
        for changes in ({"dac_step": 0}, {"clock_index": 4}, {"clock_index": -1},
                        {"channels": [70]}, {"channels": [4, 4]}, {"trigger_preamp_gain": 0},
                        {"trigger_preamp_gain": 64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ScurveJob().run(self.device, ScurveJobConfig(replace(self.scan, **changes)))
        self.assertEqual(self.transport.trace, [])
        self.assertFalse(self.directory.exists())

    def test_legacy_api_uses_runner_and_failure_carries_result(self):
        self.transport.fail_point_read = TransportIOError("unplugged")
        self.transport.fail_point_read_at = 0
        with self.assertRaises(ScurveJobError) as error:
            self.device.run_scurve(self.scan)
        self.assertEqual(error.exception.result.points, 0)
        self.assertEqual(error.exception.result.status, "disconnected")

    def test_legacy_source_execution_without_installed_project_metadata(self):
        with patch("radioroc.application.scurve.version", side_effect=PackageNotFoundError):
            result = self.device.run_scurve(self.scan)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.manifest()["application_version"], "uninstalled-source")
        self.assertEqual(len(self.manifest()["source_fingerprint"]), 64)

    def test_cli_and_api_have_identical_command_traces_and_values(self):
        expected = ScurveJob().run(self.device, replace(self.config, initialize_fpga=True))
        actual_transport = ScurveTransport(point_readings=list(self.readings))
        cli_dir = self.directory.parent / "cli"
        arguments = ["scurve", "--execute", "--channels", "4,5", "--dac-min", "0", "--dac-max", "1",
                     "--dac-step", "1", "--clock-index", "3", "--out-dir", str(cli_dir)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=actual_transport), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(actual_transport.trace, self.transport.trace)
        self.assertEqual((cli_dir / "scurve.csv").read_bytes(), expected.csv_path.read_bytes())

    def test_cli_dry_run_never_constructs_serial_or_creates_outputs(self):
        with patch("sys.argv", ["scurve", "--port", "/does/not/exist", "--out-dir", str(self.directory)]), patch.object(cli.RadiorocSerial, "from_config", side_effect=AssertionError("serial access")), contextlib.redirect_stdout(io.StringIO()) as output:
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
        # initialize_fpga sets word1="01000000"; configure_scurve_firmware then
        # sets bits 4:6 to clock_index=3 ("11"), keeping the rest unchanged.
        self.assertEqual(self.transport.words[1], "01001100")
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
            if address == 8:
                signal.raise_signal(signal.SIGINT)
            return original(address, length)

        arguments = ["scurve", "--execute", "--channels", "4,5", "--dac-min", "0", "--dac-max", "1",
                     "--dac-step", "1", "--clock-index", "3", "--out-dir", str(self.directory)]
        with patch("sys.argv", arguments), patch.object(cli.RadiorocSerial, "from_config", return_value=self.transport), patch.object(self.transport, "read_words", side_effect=read), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 130)
        self.assertEqual(self.manifest()["status"], "cancelled")
        self.assertEqual(self.manifest()["completed_points"], 0)

    def test_abrupt_process_exit_leaves_durable_nonterminal_run(self):
        code = '''
import os
from pathlib import Path
import sys
from radioroc_client import RadiorocDevice, RadiorocMemoryTransport, ScurveConfig
from radioroc.application.scurve import ScurveJob, ScurveJobConfig
words = {4: "00000101", 100: "00000101"}
payloads = {8: bytes([250, 125])}
device = RadiorocDevice(RadiorocMemoryTransport(words, payloads))
config = ScurveJobConfig(ScurveConfig(channels=[4], dac_min=0, dac_max=1, dac_step=1,
                                      clock_index=3, out_dir=Path(sys.argv[1])))
def exit_after_point(event):
    if event.kind == "point":
        os._exit(17)
ScurveJob().run(device, config, on_event=exit_after_point)
'''
        process = subprocess.run([sys.executable, "-c", code, str(self.directory)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 17, process.stderr)
        self.assertEqual(self.manifest()["status"], "running")
        self.assertNotIn("finished_at", self.manifest())
        self.assertEqual(self.manifest()["cleanup"]["status"], "pending")
        self.assertEqual(len(rows(self.directory / "scurve.csv")), 1)


if __name__ == "__main__":
    unittest.main()
