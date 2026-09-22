"""Focused offline tests for saved acquisition run validation."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.acquisition_reader import read_acquisition_run


class AcquisitionReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "run"
        self.directory.mkdir()

    def write_csv(self, rows, fields=("batch", "event", "channel", "hg", "lg")):
        with (self.directory / "events.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def write_manifest(self, **updates):
        manifest = {
            "schema_version": 1,
            "status": "completed",
            "execution_mode": "simulation",
            "operation": {"acquisition": {"channels": [4], "batches": 2, "start_batch": 0}},
            "total_points": 2,
            "completed_points": 2,
            "cleanup": {"status": "restored", "errors": []},
            "persistence_errors": [],
        }
        manifest.update(updates)
        (self.directory / "metadata.json").write_text(json.dumps(manifest))

    def two_batch_rows(self):
        return [
            {"batch": 0, "event": 0, "channel": 4, "hg": 100.0, "lg": 10.0},
            {"batch": 0, "event": 1, "channel": 4, "hg": 200.0, "lg": 20.0},
            {"batch": 1, "event": 0, "channel": 4, "hg": 300.0, "lg": 30.0},
            {"batch": 1, "event": 1, "channel": 4, "hg": 400.0, "lg": 40.0},
        ]

    def test_reads_completed_run_from_all_supported_paths(self):
        self.write_csv(self.two_batch_rows())
        self.write_manifest()
        for path in (self.directory, self.directory / "metadata.json", self.directory / "events.csv"):
            with self.subTest(path=path):
                saved = read_acquisition_run(path)
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.execution_mode, "simulation")
                self.assertEqual(saved.channels, [4])
                self.assertEqual(len(saved.rows), 4)
                self.assertEqual(saved.rows, saved.current_segment_rows)
                self.assertEqual(saved.rows[2], {"batch": 1, "event": 0, "channel": 4, "hg": 300.0, "lg": 30.0})
                self.assertEqual(saved.warnings, ())

    def test_nonterminal_manifest_is_truthfully_incomplete(self):
        self.write_csv(self.two_batch_rows()[:2])
        self.write_manifest(status="running", completed_points=1,
                            operation={"acquisition": {"channels": [4], "batches": 1, "start_batch": 0}})
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("nonterminal" in warning for warning in saved.warnings))

    def test_cancelled_run_reports_partial_progress(self):
        self.write_csv(self.two_batch_rows()[:2])
        self.write_manifest(status="cancelled", completed_points=1, total_points=2,
                            operation={"acquisition": {"channels": [4], "batches": 2, "start_batch": 0}})
        saved = read_acquisition_run(self.directory)
        # "cancelled" is terminal and self-consistent here (one batch worth of
        # rows present, completed_points says one batch done), so it is not
        # downgraded -- unlike threshold, a cancelled acquisition mid-batch is
        # expected to have fewer distinct batches than `batches` requests.
        self.assertEqual(saved.status, "cancelled")
        self.assertEqual(len(saved.current_segment_rows), 2)

    def test_legacy_csv_has_unknown_provenance(self):
        self.write_csv([{"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0}])
        saved = read_acquisition_run(self.directory / "events.csv")
        self.assertEqual((saved.status, saved.execution_mode, saved.manifest), ("unknown", "unknown", {}))
        self.assertEqual(saved.rows, ({"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0},))
        self.assertEqual(saved.rows, saved.current_segment_rows)
        self.assertEqual(saved.channels, [4])
        self.assertTrue(any("provenance unavailable" in warning for warning in saved.warnings))
        with self.assertRaises(FileNotFoundError):
            read_acquisition_run(self.directory / "metadata.json")

    def test_legacy_csv_channels_are_derived_from_distinct_values(self):
        self.write_csv([
            {"batch": 0, "event": 0, "channel": 5, "hg": 1.0, "lg": 2.0},
            {"batch": 0, "event": 0, "channel": 2, "hg": 3.0, "lg": 4.0},
        ])
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.channels, [2, 5])

    def test_invalid_tail_is_salvaged_and_completed_is_downgraded(self):
        (self.directory / "events.csv").write_text(
            "batch,event,channel,hg,lg\n0,0,4,100.0,10.0\n0,1,4,nan,20.0\n1,0,4,300.0,30.0\n")
        self.write_manifest()
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.rows, ({"batch": 0, "event": 0, "channel": 4, "hg": 100.0, "lg": 10.0},))
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("invalid CSV tail" in warning for warning in saved.warnings))

    def test_channel_outside_manifest_in_current_segment_warns_without_dropping_rows(self):
        # An unexpected channel in the CURRENT segment's own batch range is a
        # real inconsistency worth a warning, but parsing must not treat it
        # as file corruption: both rows are structurally valid CSV data and
        # must still be readable, unlike test_invalid_tail_is_salvaged_and_
        # completed_is_downgraded's genuinely malformed numeric field above.
        (self.directory / "events.csv").write_text(
            "batch,event,channel,hg,lg\n0,0,4,100.0,10.0\n0,0,9,5.0,6.0\n")
        self.write_manifest(operation={"acquisition": {"channels": [4], "batches": 1, "start_batch": 0}},
                            completed_points=1, total_points=1)
        saved = read_acquisition_run(self.directory)
        self.assertEqual(len(saved.rows), 2)
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("channels the manifest doesn't declare" in warning for warning in saved.warnings))

    def test_earlier_append_segment_with_different_channels_does_not_corrupt_current_segment(self):
        # AcquisitionRunWriter's append mode lets events.csv accumulate rows
        # from separate job runs, and nothing prevents a later --append
        # invocation from using a different --channels value than an earlier
        # one. The reader must not let an EARLIER segment's now-irrelevant
        # channel set look like corruption and truncate everything after it
        # -- that would silently destroy the current (later, more relevant)
        # segment's genuinely valid data, which is exactly what regressed
        # before this test was added: the old implementation raised out of
        # row parsing itself on any channel outside the *current* manifest,
        # discarding the whole rest of the file from the first such row
        # onward -- including this run's own real data, whenever the
        # channel mismatch happened to belong to an earlier segment.
        (self.directory / "events.csv").write_text(
            "batch,event,channel,hg,lg\n"
            "0,0,4,10.0,1.0\n"      # earlier segment, channel 4 (not in the CURRENT manifest below)
            "1,0,5,20.0,2.0\n"      # current segment, channel 5 -- must survive intact
        )
        self.write_manifest(operation={"acquisition": {"channels": [5], "batches": 1, "start_batch": 1}},
                            completed_points=1, total_points=1)
        saved = read_acquisition_run(self.directory)
        self.assertEqual(len(saved.rows), 2)
        self.assertEqual(saved.current_segment_rows,
                         ({"batch": 1, "event": 0, "channel": 5, "hg": 20.0, "lg": 2.0},))
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.warnings, ())

    def test_completed_cleanup_or_storage_failure_is_incomplete_and_reported(self):
        self.write_csv(self.two_batch_rows())
        self.write_manifest(cleanup={"status": "failed", "errors": ["restore failed"]},
                            persistence_errors=["disk full"])
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.status, "incomplete")
        self.assertIn("cleanup error: restore failed", saved.warnings)
        self.assertIn("storage error: disk full", saved.warnings)

        self.write_manifest(cleanup={"status": "pending", "errors": []})
        self.assertEqual(read_acquisition_run(self.directory).status, "incomplete")

    def test_verification_fault_remains_visible_when_reopened(self):
        self.write_csv(self.two_batch_rows())
        for terminal in ("completed", "cancelled"):
            for report in ({"status": "failed", "errors": ["ASIC mismatch"]},
                           {"status": "incomplete"}, None):
                with self.subTest(terminal=terminal, report=report):
                    self.write_manifest(status=terminal, verification=report)
                    saved = read_acquisition_run(self.directory)
                    self.assertEqual(saved.status, "incomplete")
                    self.assertEqual(len(saved.rows), 4)
                    self.assertTrue(any("verification did not pass" in w for w in saved.warnings))
        self.write_manifest(verification={"status": "passed", "errors": []})
        self.assertEqual(read_acquisition_run(self.directory).status, "completed")

    def test_failed_run_surfaces_manifest_error(self):
        self.write_csv(self.two_batch_rows()[:2])
        self.write_manifest(status="disconnected", completed_points=1, total_points=2,
                            error="TransportIOError: unplugged",
                            operation={"acquisition": {"channels": [4], "batches": 2, "start_batch": 0}})
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.status, "disconnected")
        self.assertIn("run error: TransportIOError: unplugged", saved.warnings)

    def test_rejects_wrong_columns_and_invalid_manifest_channels(self):
        self.write_csv([{"batch": 0, "event": 0, "hg": 1, "extra": 2}], fields=("batch", "event", "hg", "extra"))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "columns"):
            read_acquisition_run(self.directory)
        self.write_csv(self.two_batch_rows())
        self.write_manifest(operation={"acquisition": {"channels": [], "batches": 2, "start_batch": 0}})
        with self.assertRaisesRegex(ValueError, "unique integers"):
            read_acquisition_run(self.directory)

    def test_reader_caps_huge_csv_at_the_defensive_row_limit(self):
        import radioroc.data.acquisition_reader as module
        original_max = module._MAX_ROWS
        module._MAX_ROWS = 5
        try:
            rows = [{"batch": 0, "event": i, "channel": 4, "hg": 1.0, "lg": 1.0} for i in range(10)]
            self.write_csv(rows)
            self.write_manifest(operation={"acquisition": {"channels": [4], "batches": 1, "start_batch": 0}},
                                completed_points=1)
            saved = read_acquisition_run(self.directory)
            self.assertEqual(len(saved.rows), 5)
            self.assertTrue(any("defensive limit" in warning for warning in saved.warnings))
        finally:
            module._MAX_ROWS = original_max

    def test_append_mode_multi_segment_scopes_current_segment_rows(self):
        # First "run": batches 0-1 (two distinct batches, four rows).
        first_rows = self.two_batch_rows()
        self.write_csv(first_rows)
        # Second "run" (append mode) continues at start_batch=2 for two more
        # batches; metadata.json only ever reflects this latest run's own
        # manifest, per AcquisitionRunWriter's append semantics.
        second_rows = [
            {"batch": 2, "event": 0, "channel": 4, "hg": 500.0, "lg": 50.0},
            {"batch": 3, "event": 0, "channel": 4, "hg": 600.0, "lg": 60.0},
        ]
        with (self.directory / "events.csv").open("a", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["batch", "event", "channel", "hg", "lg"])
            writer.writerows(second_rows)
        self.write_manifest(operation={"acquisition": {"channels": [4], "batches": 2, "start_batch": 2}},
                            completed_points=2, total_points=2)

        saved = read_acquisition_run(self.directory)
        self.assertEqual(len(saved.rows), 6)
        self.assertEqual(saved.current_segment_rows, tuple(second_rows))
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.warnings, ())

    def test_append_mode_segment_missing_a_batch_downgrades_completed_status(self):
        self.write_csv([{"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 1.0}])
        # Manifest claims batches 0-2 (three batches) were written this run,
        # but the CSV segment only has batch 0.
        self.write_manifest(operation={"acquisition": {"channels": [4], "batches": 3, "start_batch": 0}},
                            completed_points=3, total_points=3)
        saved = read_acquisition_run(self.directory)
        self.assertEqual(saved.status, "incomplete")
        self.assertTrue(any("missing batches" in warning for warning in saved.warnings))


if __name__ == "__main__":
    unittest.main()
