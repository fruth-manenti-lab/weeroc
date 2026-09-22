"""Offline acceptance tests for AcquisitionRunWriter's fresh/append CSV+manifest modes."""

from pathlib import Path
import tempfile
import unittest

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)
from radioroc.data.acquisition import AcquisitionRunWriter


def read_csv(path: Path) -> list[str]:
    return path.read_text().splitlines()


class AcquisitionRunWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"

    def test_fresh_write_creates_header_and_refuses_overwrite(self):
        writer = AcquisitionRunWriter(self.directory, {"status": "preparing"})
        self.assertEqual(read_csv(writer.csv_path), ["batch,event,channel,hg,lg"])
        self.assertEqual(writer.metadata_path.read_text().strip(), '{\n  "status": "preparing"\n}')
        writer.append_events([{"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0}])
        self.assertEqual(read_csv(writer.csv_path), ["batch,event,channel,hg,lg", "0,0,4,1.0,2.0"])
        with self.assertRaises(FileExistsError):
            AcquisitionRunWriter(self.directory, {"status": "preparing"})

    def test_append_mode_keeps_existing_rows_and_replaces_manifest(self):
        first = AcquisitionRunWriter(self.directory, {"status": "preparing", "run": 1})
        first.append_events([{"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0},
                             {"batch": 0, "event": 1, "channel": 4, "hg": 3.0, "lg": 4.0}])
        saved_csv = first.csv_path.read_bytes()

        second = AcquisitionRunWriter(self.directory, {"status": "preparing", "run": 2}, append=True)
        # The manifest write on construction replaces the prior run's manifest...
        self.assertEqual(second.metadata_path.read_text().strip(),
                         '{\n  "status": "preparing",\n  "run": 2\n}')
        # ...but the CSV from the first run is untouched, not truncated.
        self.assertEqual(second.csv_path.read_bytes(), saved_csv)

        second.append_events([{"batch": 1, "event": 0, "channel": 4, "hg": 5.0, "lg": 6.0}])
        rows = read_csv(second.csv_path)
        self.assertEqual(rows, [
            "batch,event,channel,hg,lg",
            "0,0,4,1.0,2.0",
            "0,1,4,3.0,4.0",
            "1,0,4,5.0,6.0",
        ])

    def test_append_true_without_existing_files_behaves_like_a_fresh_run(self):
        writer = AcquisitionRunWriter(self.directory, {"status": "preparing"}, append=True)
        self.assertEqual(read_csv(writer.csv_path), ["batch,event,channel,hg,lg"])

    def test_append_mode_recovers_a_csv_missing_from_an_interrupted_prior_run(self):
        # A process killed between HoldRunWriter/AcquisitionRunWriter's own
        # two exclusive-creates (metadata.json succeeds, events.csv doesn't)
        # can leave only the manifest behind. Appending afterward must still
        # produce a properly headered CSV, not a headerless one.
        self.directory.mkdir(parents=True)
        (self.directory / "metadata.json").write_text('{"status": "failed"}')
        writer = AcquisitionRunWriter(self.directory, {"status": "preparing"}, append=True)
        self.assertEqual(read_csv(writer.csv_path), ["batch,event,channel,hg,lg"])
        writer.append_events([{"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0}])
        self.assertEqual(read_csv(writer.csv_path),
                         ["batch,event,channel,hg,lg", "0,0,4,1.0,2.0"])

    def test_append_events_writes_multiple_rows_in_one_call(self):
        writer = AcquisitionRunWriter(self.directory, {"status": "preparing"})
        writer.append_events([
            {"batch": 0, "event": 0, "channel": 4, "hg": 1.0, "lg": 2.0},
            {"batch": 0, "event": 1, "channel": 5, "hg": 3.0, "lg": 4.0},
        ])
        self.assertEqual(read_csv(writer.csv_path), [
            "batch,event,channel,hg,lg", "0,0,4,1.0,2.0", "0,1,5,3.0,4.0",
        ])

    def test_update_atomically_replaces_manifest(self):
        writer = AcquisitionRunWriter(self.directory, {"status": "preparing"})
        writer.update({"status": "completed", "completed_points": 3})
        self.assertEqual(writer.metadata_path.read_text().strip(),
                         '{\n  "status": "completed",\n  "completed_points": 3\n}')
        # No stray temp files should remain beside the run files.
        leftovers = [p.name for p in self.directory.iterdir() if p.name.startswith(".metadata-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
