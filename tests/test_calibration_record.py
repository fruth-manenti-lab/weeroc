"""Focused offline tests for the plint calibration record (Step 6)."""

import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.calibration_record import load_calibration_record, save_calibration_record


class CalibrationRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_sub_scan(self, name, *, status="completed", board_identity="usb:0403:6010:serial:RD3_32"):
        directory = self.root / name
        directory.mkdir()
        manifest = {"schema_version": 1, "status": status, "board_identity": board_identity}
        (directory / "metadata.json").write_text(json.dumps(manifest))
        return directory

    def test_happy_path_round_trips_every_field(self):
        sub_scan_dirs = {
            "step1_pedestal": self.make_sub_scan("step1"),
            "step2_threshold_alignment": self.make_sub_scan("step2"),
            "step4_gain": self.make_sub_scan("step4"),
            "step5_hold_scan": self.make_sub_scan("step5"),
        }
        out_path = self.root / "calibration" / "calibration_record.json"
        written = save_calibration_record(
            out_path,
            operator="tengiz",
            threshold_dac=512,
            threshold_margin_reasoning="peak center plus 20 codes of noise margin",
            per_channel_relative_response={"ch4": 10800.0, "ch6": 10500.0, "ch32": 11200.0},
            sub_scan_dirs=sub_scan_dirs,
            excluded_channels=[{"channel": "ch12", "reason": "dead preamp"}, ("ch13", "outlier response")],
            hold_delay_ns=450,
            conversion_delay_ns=300,
            trigger_preamp_gain_code=32,
            shaper_gain_codes={"HG": 10, "LG": 20},
        )
        self.assertEqual(written, out_path)
        self.assertTrue(out_path.is_file())

        record = load_calibration_record(out_path)
        self.assertEqual(record["schema_version"], 1)
        self.assertIn("created_at", record)
        self.assertEqual(record["operator"], "tengiz")
        self.assertEqual(record["board_identity"], "usb:0403:6010:serial:RD3_32")
        self.assertEqual(record["threshold_dac"], 512)
        self.assertEqual(record["threshold_margin_reasoning"], "peak center plus 20 codes of noise margin")
        self.assertEqual(record["per_channel_relative_response"],
                          {"ch4": 10800.0, "ch6": 10500.0, "ch32": 11200.0})
        self.assertEqual(record["excluded_channels"],
                          [{"channel": "ch12", "reason": "dead preamp"},
                           {"channel": "ch13", "reason": "outlier response"}])
        self.assertEqual(record["hold_delay_ns"], 450)
        self.assertEqual(record["conversion_delay_ns"], 300)
        self.assertEqual(record["trigger_preamp_gain_code"], 32)
        self.assertEqual(record["shaper_gain_codes"], {"HG": 10, "LG": 20})
        self.assertEqual(set(record["sub_scans"]), set(sub_scan_dirs))
        for label, directory in sub_scan_dirs.items():
            self.assertEqual(record["sub_scans"][label],
                              {"path": str(directory), "status": "completed"})

    def test_missing_metadata_raises_naming_the_step(self):
        sub_scan_dirs = {
            "step1_pedestal": self.make_sub_scan("step1"),
            "step2_threshold_alignment": self.root / "does_not_exist",
        }
        (self.root / "does_not_exist").mkdir()
        with self.assertRaises(ValueError) as ctx:
            save_calibration_record(
                self.root / "calibration_record.json",
                operator="tengiz", threshold_dac=512, threshold_margin_reasoning="x",
                per_channel_relative_response={"ch4": 1.0}, sub_scan_dirs=sub_scan_dirs,
            )
        self.assertIn("step2_threshold_alignment", str(ctx.exception))

    def test_wrong_status_raises_naming_step_and_status(self):
        sub_scan_dirs = {
            "step1_pedestal": self.make_sub_scan("step1"),
            "step5_hold_scan": self.make_sub_scan("step5", status="cancelled"),
        }
        with self.assertRaises(ValueError) as ctx:
            save_calibration_record(
                self.root / "calibration_record.json",
                operator="tengiz", threshold_dac=512, threshold_margin_reasoning="x",
                per_channel_relative_response={"ch4": 1.0}, sub_scan_dirs=sub_scan_dirs,
            )
        message = str(ctx.exception)
        self.assertIn("step5_hold_scan", message)
        self.assertIn("cancelled", message)

    def test_conflicting_board_identity_raises_naming_both_values(self):
        sub_scan_dirs = {
            "step1_pedestal": self.make_sub_scan("step1", board_identity="usb:0403:6010:serial:RD3_32"),
            "step4_gain": self.make_sub_scan("step4", board_identity="usb:0403:6010:serial:RD3_99"),
        }
        with self.assertRaises(ValueError) as ctx:
            save_calibration_record(
                self.root / "calibration_record.json",
                operator="tengiz", threshold_dac=512, threshold_margin_reasoning="x",
                per_channel_relative_response={"ch4": 1.0}, sub_scan_dirs=sub_scan_dirs,
            )
        message = str(ctx.exception)
        self.assertIn("RD3_32", message)
        self.assertIn("RD3_99", message)

    def test_load_rejects_wrong_or_missing_schema_version(self):
        for payload in ({"schema_version": 2}, {}):
            path = self.root / "bad.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_calibration_record(path)


if __name__ == "__main__":
    unittest.main()
