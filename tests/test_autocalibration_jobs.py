"""Offline autocalibration (F08) acceptance tests using the real device operations."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from radioroc_client import RadiorocDevice, parse_bits
from radioroc.application.autocalibration import (
    AutocalibrationJob, AutocalibrationJobConfig,
)
from radioroc.application.jobs import CancellationToken, JobBusyError
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


if __name__ == "__main__":
    unittest.main()
