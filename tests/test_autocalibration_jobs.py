"""Offline autocalibration (F08) acceptance tests using the real device operations."""

import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from radioroc_client import RadiorocDevice, parse_bits
from radioroc.application.autocalibration import (
    AutocalibrationJob, AutocalibrationJobConfig, _TopLevelManifestWriter,
)
from radioroc.application.jobs import CancellationToken, JobBusyError, session_lock
from radioroc.transport.errors import TransportIOError
from scripts import radioroc_autocalibrate as cli
from test_scurve_jobs import ScurveTransport


class AutocalibrationJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.config = AutocalibrationJobConfig(
            channels=[4, 5], t1=True,
            out_dir=self.directory,
            probe_dac_min=0, probe_dac_max=20, probe_dac_step=10,
            transition_dac_step=10, transition_margin=5, transition_dac_floor=20,
            transition_dac_cap=20,
            final_window_before=5, final_window_after=5, final_dac_step=5,
        )
        # Consumed in exact scan order: step1_zero (ch4 @ DAC 0,10,20), then
        # step1_full (ch4 @ DAC 0,10,20), then step2 (ch4,ch5 @ DAC 0,10,20).
        # step5/final falls back to ScurveTransport.DEFAULT_READING (250,100),
        # since its exact values aren't asserted on here.
        self.readings = [
            # step1_zero: 100 -> 0 -> 0 => crosses 50% at DAC 5.
            (200, 200), (200, 0), (200, 0),
            # step1_full: 100 -> 100 -> 0 => crosses 50% at DAC 15.
            (200, 200), (200, 200), (200, 0),
            # step2 ch4: 100 -> 50 -> 0 => crosses exactly at DAC 10.
            # step2 ch5: 100 -> 100 -> 0 => crosses at DAC 15.
            (200, 200), (200, 200),
            (200, 100), (200, 200),
            (200, 0), (200, 0),
        ]
        self.transport = ScurveTransport(point_readings=list(self.readings))
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return AutocalibrationJob().run(self.device, self.config, **kwargs)

    def manifest(self):
        return json.loads((self.directory / "autocalibration_metadata.json").read_text())

    def test_success_estimates_corrections_and_manifest(self):
        result = self.run_job()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reference_channel, 4)
        # |15 - 5| / 63 =~ 0.159, floored to the 0.25 minimum.
        self.assertAlmostEqual(result.lsb_ratio, 0.25)
        self.assertAlmostEqual(result.crossings[4], 10.0)
        self.assertAlmostEqual(result.crossings[5], 15.0)
        self.assertAlmostEqual(result.mean_position, 12.5)
        # Packaged default calibration DAC is 32 for every channel.
        self.assertEqual(result.calibration_before, {4: 32, 5: 32})
        # ch4: correction = round((10 - 12.5) / 0.25) = -10 -> 32 - (-10) = 42.
        # ch5: correction = round((15 - 12.5) / 0.25) = 10 -> 32 - 10 = 22.
        self.assertEqual(result.calibration_after, {4: 42, 5: 22})
        self.assertEqual(set(result.sub_runs), {"step1_zero", "step1_full", "step2", "final"})
        for sub_dir in result.sub_runs.values():
            self.assertTrue((sub_dir / "scurve.csv").is_file())

        # The reference channel (4) is itself one of the calibrated channels,
        # so its final on-device value is its own step-3 correction (42), not
        # its restored-after-probing value (32) -- restoration only matters
        # for the window between the probe and step 3's correction, covered
        # by test_reference_channel_calibration_dac_restored_even_if_step2_fails.
        self.assertEqual(parse_bits(self.device.find_i2c_row(4, 4).data) & 0x3F, 42)
        self.assertEqual(parse_bits(self.device.find_i2c_row(5, 4).data) & 0x3F, 22)

        manifest = self.manifest()
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(set(manifest["sub_runs"]), {"step1_zero", "step1_full", "step2", "final"})

    def test_reference_channel_calibration_dac_restored_even_if_step2_fails(self):
        # Only enough readings for step1; step2 runs out of scripted data and
        # falls back to ScurveTransport.DEFAULT_READING, which still lets the
        # scan "succeed" -- so instead, directly simulate a step2 failure by
        # cancelling right after step1 completes.
        token = CancellationToken()
        original_run_sub_scan = AutocalibrationJob._run_sub_scan
        calls = []

        def counting_run_sub_scan(self, *args, **kwargs):
            calls.append(kwargs.get("out_dir"))
            if len(calls) == 3:  # about to start step2
                token.cancel()
            return original_run_sub_scan(self, *args, **kwargs)

        AutocalibrationJob._run_sub_scan = counting_run_sub_scan
        try:
            result = self.run_job(cancellation=token)
        finally:
            AutocalibrationJob._run_sub_scan = original_run_sub_scan
        self.assertEqual(result.status, "cancelled")
        # Restored to its original value (32), not left at the last-probed 63.
        self.assertEqual(parse_bits(self.device.find_i2c_row(4, 4).data) & 0x3F, 32)
        # Corrections were never applied.
        self.assertEqual(result.calibration_after, {})

    def test_verify_restoration_confirms_reference_channel_restored(self):
        result = self.run_job(verify_restoration=True)
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.reference_restored)

    def test_reference_channel_restore_failure_is_flagged_not_silently_succeeded(self):
        # The reference channel's calibration DAC is probed to 0, then 63,
        # then restored to its original value in step 1's own finally block
        # (see test_reference_channel_calibration_dac_restored_even_if_step2_fails
        # for the cancellation path through the same finally). This fails
        # only that third call -- the restore itself -- while leaving every
        # other channel/value combination (including step 3's later,
        # unrelated correction write for this same channel) untouched.
        original_set = self.device.set_calibration_dac_for_channel
        reference_channel = self.config.channels[0]
        calls = {"n": 0}

        def fail_restore(channel, *, t1, value):
            if channel == reference_channel:
                calls["n"] += 1
                if calls["n"] == 3:
                    raise TransportIOError("restore failed")
            return original_set(channel, t1=t1, value=value)

        with patch.object(self.device, "set_calibration_dac_for_channel", side_effect=fail_restore):
            result = self.run_job(verify_restoration=True)
        # A failed restore of the *probed-away* calibration DAC is a
        # cleanup-only fault: it must not be presented as a successful,
        # fully-restored run (reference_restored must go visibly false),
        # but it also must not be conflated with the scan itself failing --
        # step 2/3/final all still ran and produced real results.
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.reference_restored)
        self.assertTrue(any("restore" in warning for warning in result.warnings),
                        result.warnings)
        self.assertEqual(result.calibration_after, {4: 42, 5: 22})

    def test_manifest_write_failure_surfaces_and_releases_session_lock(self):
        # AutocalibrationJob's own top-level manifest writer has no
        # persist()-retry fallback for a second consecutive write failure,
        # unlike every sibling job (Threshold/HoldScan/Scurve/Acquisition),
        # which all catch a failed retry and report it via
        # `result.persistence_errors` instead of raising. Here the failure
        # instead propagates out of `AutocalibrationJob.run()` itself.
        # Both existing callers already treat that as a fault rather than a
        # false success (ConnectionWorker._run_autocalibration's blanket
        # `except Exception`, and radioroc_autocalibrate.py's own top-level
        # `except Exception` -> "ERROR: ..."), so this is not a silent data
        # loss in practice -- but confirm the fault is genuinely visible
        # (never swallowed into a "completed" result) and that the
        # transport's session lock is still released for a later run, not
        # left held forever by the raise.
        original_update = _TopLevelManifestWriter.update
        calls = {"n": 0}

        def fail_update(writer, manifest):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError("disk full")
            return original_update(writer, manifest)

        with patch.object(_TopLevelManifestWriter, "update", new=fail_update):
            with self.assertRaises(OSError):
                self.run_job()

        lock = session_lock(self.transport)
        self.assertTrue(lock.acquire(blocking=False),
                        "session lock was left held after a storage failure")
        lock.release()

    def test_disconnect_mid_transition_scan_reports_partial_sub_runs(self):
        # step1_zero + step1_full each read one point per DAC value (3 DAC
        # values, reference channel only) = 6 scripted reads; the 7th read
        # is step2's first (DAC 0, channel 4), which this fails.
        original = TransportIOError("unplugged")
        self.transport.fail_point_read = original
        self.transport.fail_point_read_at = 6
        result = self.run_job()
        self.assertEqual(result.status, "disconnected")
        self.assertIs(result.error, original)
        # step2's own directory/manifest was created (recorded in sub_runs)
        # even though the sub-scan itself did not complete; "final" never
        # started.
        self.assertEqual(set(result.sub_runs), {"step1_zero", "step1_full", "step2"})
        sub_manifest = json.loads((result.sub_runs["step2"] / "metadata.json").read_text())
        self.assertEqual(sub_manifest["status"], "disconnected")
        self.assertEqual(self.manifest()["status"], "disconnected")

    def test_saved_run_reader_composes_the_four_sub_scans(self):
        from radioroc.data.autocalibration_reader import read_autocalibration_run
        result = self.run_job()
        self.assertEqual(result.status, "completed")

        saved = read_autocalibration_run(self.directory)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.warnings, ())
        self.assertEqual(set(saved.sub_runs), {"step1_zero", "step1_full", "step2", "final"})
        self.assertEqual(list(saved.sub_runs), ["step1_zero", "step1_full", "step2", "final"])
        self.assertEqual(len(saved.sub_runs["step1_zero"].rows), 3)  # DAC 0, 10, 20
        self.assertEqual(len(saved.sub_runs["step2"].rows), 3)
        # Also accepts the manifest file path directly, not just the directory.
        same = read_autocalibration_run(self.directory / "autocalibration_metadata.json")
        self.assertEqual(same.status, saved.status)

    def test_dry_run_never_constructs_output_or_touches_transport(self):
        dry_device = RadiorocDevice(self.transport, dry_run=True)
        result = AutocalibrationJob().run(dry_device, self.config)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.execution_mode, "dry-run")
        self.assertFalse(self.directory.exists())

    def test_reject_second_job_while_first_holds_session_lock(self):
        from radioroc.application.jobs import session_lock
        lock = session_lock(self.transport)
        lock.acquire()
        try:
            with self.assertRaises(JobBusyError):
                self.run_job()
        finally:
            lock.release()

    def test_invalid_configuration_has_no_hardware_or_files(self):
        bad_config = replace(self.config, transition_dac_step=0)
        with self.assertRaises(ValueError):
            AutocalibrationJob().run(self.device, bad_config)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.transport.trace, [])

    def test_cli_dry_run_never_constructs_serial_or_creates_outputs(self):
        with patch("sys.argv", ["autocalibrate", "--port", "/does/not/exist",
                                "--out-dir", str(self.directory)]), \
             patch.object(cli.RadiorocSerial, "from_config",
                         side_effect=AssertionError("serial access")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["execution_mode"], "dry-run")
        self.assertFalse(self.directory.exists())

    def test_cli_and_api_have_identical_command_traces_and_values(self):
        # The CLI defaults to initializing the FPGA unless --skip-fpga-init
        # is passed; self.config leaves initialize_fpga at its own default
        # (False), so match the CLI's actual behavior here.
        expected = AutocalibrationJob().run(self.device, replace(self.config, initialize_fpga=True))
        actual_transport = ScurveTransport(point_readings=list(self.readings))
        cli_dir = self.directory.parent / "cli"
        arguments = [
            "autocalibrate", "--execute", "--channels", "4,5",
            "--probe-dac-min", "0", "--probe-dac-max", "20", "--probe-dac-step", "10",
            "--transition-dac-step", "10", "--transition-margin", "5",
            "--transition-dac-floor", "20", "--transition-dac-cap", "20",
            "--final-window-before", "5", "--final-window-after", "5", "--final-dac-step", "5",
            "--out-dir", str(cli_dir),
        ]
        with patch("sys.argv", arguments), \
             patch.object(cli.RadiorocSerial, "from_config", return_value=actual_transport), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(actual_transport.trace, self.transport.trace)
        self.assertEqual(expected.calibration_after, {4: 42, 5: 22})
        manifest = json.loads((cli_dir / "autocalibration_metadata.json").read_text())
        self.assertEqual(manifest["status"], "completed")

    def test_cli_reports_invalid_configuration_without_hardware_access(self):
        with patch("sys.argv", ["autocalibrate", "--channels", "4,5", "--probe-dac-step", "0"]), \
             patch.object(cli.RadiorocSerial, "from_config",
                         side_effect=AssertionError("serial access")), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()) as error_output:
            self.assertEqual(cli.main(), 1)
        self.assertIn("ERROR", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
