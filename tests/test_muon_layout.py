import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.muon_types import DetectorLayout, LayoutError, SiPMPlacement


class MuonLayoutTests(unittest.TestCase):
    def test_grid_sizes(self):
        one = DetectorLayout.grid(4, 8, 10, layers=1)
        two = DetectorLayout.grid(4, 8, 10, layers=2)
        self.assertEqual(len(one.sipms), 32)
        self.assertEqual(one.layers(), [0])
        self.assertEqual(len(two.sipms), 64)
        self.assertEqual(two.layers(), [0, 1])
        self.assertEqual(two.channels(), list(range(64)))
        self.assertEqual(len(two.in_layer(1)), 32)
        xs = [s.x_mm for s in two.in_layer(0)]
        self.assertAlmostEqual(min(xs), -35.0)
        self.assertAlmostEqual(max(xs), 35.0)

    def test_bad_layer_count(self):
        with self.assertRaises(LayoutError):
            DetectorLayout.grid(4, 8, layers=3)

    def test_channel_overflow(self):
        with self.assertRaises(LayoutError):
            DetectorLayout.grid(4, 8, 10, layers=2, first_channel=1)

    def test_duplicate_and_bad_values(self):
        layout = DetectorLayout([SiPMPlacement(1, 0, 0, 0), SiPMPlacement(1, 0, 5, 0)])
        with self.assertRaisesRegex(LayoutError, "more than one"):
            layout.validate()
        with self.assertRaises(LayoutError):
            DetectorLayout([SiPMPlacement(0, 2, 0, 0)]).validate()
        with self.assertRaises(LayoutError):
            DetectorLayout([SiPMPlacement(0, 0, float("nan"), 0)]).validate()
        with self.assertRaises(LayoutError):
            DetectorLayout([SiPMPlacement(0, 0, 0, 0)], layer_spacing_mm=0).validate()

    def test_json_round_trip(self):
        layout = DetectorLayout.grid(2, 3, 12.5, layers=2, layer_spacing_mm=80, name="demo")
        with tempfile.TemporaryDirectory() as tmp:
            path = layout.save_json(Path(tmp) / "sub" / "layout.json")
            loaded = DetectorLayout.load_json(path)
        self.assertEqual(loaded.to_dict(), layout.to_dict())
        self.assertEqual(loaded.name, "demo")
        self.assertEqual(loaded.layer_spacing_mm, 80)

    def test_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaises(LayoutError):
                DetectorLayout.load_json(tmp / "missing.json")
            (tmp / "bad.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(LayoutError):
                DetectorLayout.load_json(tmp / "bad.json")
            (tmp / "schema.json").write_text(json.dumps({"schema_version": 9}), encoding="utf-8")
            with self.assertRaises(LayoutError):
                DetectorLayout.load_json(tmp / "schema.json")
            (tmp / "partial.json").write_text(json.dumps({"schema_version": 1, "sipms": [{"channel": 0}]}),
                                              encoding="utf-8")
            with self.assertRaises(LayoutError):
                DetectorLayout.load_json(tmp / "partial.json")


if __name__ == "__main__":
    unittest.main()
