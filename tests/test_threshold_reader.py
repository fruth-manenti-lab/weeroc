"""Focused offline tests for saved threshold run validation."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.threshold_reader import read_threshold_run


class ThresholdReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "run"
        self.directory.mkdir()

    def write_csv(self, rows, fields=("DAC", "ch4")):
        with (self.directory / "thresholdscan.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def write_manifest(self, **updates):
        manifest = {
            "schema_version": 1,
            "status": "completed",
            "execution_mode": "simulation",
            "operation": {"scan": {"channels": [4], "dac_min": 0, "dac_max": 10, "dac_step": 5}},
            "total_points": 3,
            "completed_points": 3,
            "cleanup": {"status": "restored", "errors": []},
            "persistence_errors": [],
        }
        manifest.update(updates)
        (self.directory / "metadata.json").write_text(json.dumps(manifest))

    def test_reads_completed_run_from_all_supported_paths(self):
        self.write_csv([{"DAC": 0, "ch4": 1.5}, {"DAC": 5, "ch4": 0}, {"DAC": 10, "ch4": 3}])
        self.write_manifest()
        for path in (self.directory, self.directory / "metadata.json", self.directory / "thresholdscan.csv"):
            with self.subTest(path=path):
                saved = read_threshold_run(path)
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.execution_mode, "simulation")
                self.assertEqual(saved.rows[1], {"DAC": 5, "ch4": 0.0})
                self.assertEqual(saved.warnings, ())

    def test_nonterminal_manifest_is_truthfully_incomplete(self):
        self.write_csv([{"DAC": 0, "ch4": 1}])
        self.write_manifest(status="running", completed_points=1)
        saved = read_threshold_run(self.directory)
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("nonterminal" in warning for warning in saved.warnings))

    def test_invalid_tail_is_salvaged_and_completed_is_downgraded(self):
        (self.directory / "thresholdscan.csv").write_text("DAC,ch4\n0,2.5\n5,nan\n10,7\n")
        self.write_manifest()
        saved = read_threshold_run(self.directory)
        self.assertEqual(saved.rows, ({"DAC": 0, "ch4": 2.5},))
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("invalid CSV tail" in warning for warning in saved.warnings))

        self.write_csv([{"DAC": 0, "ch4": 1}, {"DAC": 6, "ch4": 2}, {"DAC": 10, "ch4": 3}])
        saved = read_threshold_run(self.directory)
        self.assertEqual(saved.rows, ({"DAC": 0, "ch4": 1.0},))
        self.assertTrue(any("does not match the configured scan" in warning for warning in saved.warnings))

    def test_completed_cleanup_or_storage_failure_is_incomplete_and_reported(self):
        self.write_csv([{"DAC": 0, "ch4": 1}, {"DAC": 5, "ch4": 2}, {"DAC": 10, "ch4": 3}])
        self.write_manifest(cleanup={"status": "failed", "errors": ["restore failed"]},
                            persistence_errors=["disk full"])
        saved = read_threshold_run(self.directory)
        self.assertEqual(saved.status, "incomplete")
        self.assertIn("cleanup error: restore failed", saved.warnings)
        self.assertIn("storage error: disk full", saved.warnings)

        self.write_manifest(cleanup={"status": "pending", "errors": []})
        self.assertEqual(read_threshold_run(self.directory).status, "incomplete")

        self.write_manifest(cleanup={"status": "restored", "errors": ["late error"]})
        self.assertEqual(read_threshold_run(self.directory).status, "incomplete")

    def test_legacy_csv_has_unknown_provenance(self):
        self.write_csv([{"DAC": 2, "ch4": 4.25}])
        saved = read_threshold_run(self.directory / "thresholdscan.csv")
        self.assertEqual((saved.status, saved.execution_mode, saved.manifest), ("unknown", "unknown", {}))
        self.assertEqual(saved.rows, ({"DAC": 2, "ch4": 4.25},))
        self.assertTrue(any("provenance unavailable" in warning for warning in saved.warnings))
        with self.assertRaises(FileNotFoundError):
            read_threshold_run(self.directory / "metadata.json")

    def test_failed_run_surfaces_manifest_error(self):
        self.write_csv([{"DAC": 0, "ch4": 1}])
        self.write_manifest(status="disconnected", completed_points=1, error="TransportIOError: unplugged")
        saved = read_threshold_run(self.directory)
        self.assertEqual(saved.status, "disconnected")
        self.assertIn("run error: TransportIOError: unplugged", saved.warnings)

    def test_rejects_wrong_columns_and_invalid_manifest_bounds(self):
        self.write_csv([{"DAC": 0, "ch5": 1}], fields=("DAC", "ch5"))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "columns"):
            read_threshold_run(self.directory)
        self.write_csv([{"DAC": 0, "ch4": 1}])
        self.write_manifest(operation={"scan": {"channels": [4], "dac_min": 0, "dac_max": 1024, "dac_step": 1}})
        with self.assertRaisesRegex(ValueError, "range 0..1023"):
            read_threshold_run(self.directory)

    def test_reader_caps_legacy_prefix_at_1024_points(self):
        self.write_csv(({"DAC": dac, "ch4": 1} for dac in range(1024)))
        with (self.directory / "thresholdscan.csv").open("a") as stream:
            stream.write("1023,2\n")
        saved = read_threshold_run(self.directory)
        self.assertEqual(len(saved.rows), 1024)
        self.assertTrue(any("1024-point" in warning for warning in saved.warnings))


if __name__ == "__main__":
    unittest.main()
