import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.muon_types import DetectorLayout, LayoutError, PlintSpec, SiPMPlacement


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

    def test_auto_plints(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=2)
        self.assertEqual(layout.plints, [])
        auto = layout.effective_plints()
        self.assertEqual([p.layer for p in auto], [0, 1])
        self.assertEqual((auto[0].x_mm, auto[0].y_mm, auto[0].width_mm, auto[0].length_mm, auto[0].thickness_mm),
                         (0.0, 0.0, 80.0, 40.0, 10.0))
        self.assertNotIn("plints", layout.to_dict())

    def test_explicit_plints_and_grid_arguments(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=2, plint_width_mm=400, plint_length_mm=120,
                                     plint_thickness_mm=10)
        self.assertEqual(len(layout.plints), 2)
        self.assertEqual(layout.effective_plints(), layout.plints)
        self.assertEqual(layout.plints[1], PlintSpec(1, 0.0, 0.0, 400.0, 120.0, 10.0))
        partial = DetectorLayout.grid(4, 8, 10, layers=1, plint_thickness_mm=20)
        self.assertEqual((partial.plints[0].width_mm, partial.plints[0].thickness_mm), (80.0, 20.0))

    def test_plint_json_round_trip_and_old_files(self):
        layout = DetectorLayout.grid(2, 3, 12.5, layers=2)
        layout.plints = [PlintSpec(0, 1.0, 2.0, 300.0, 100.0, 10.0), PlintSpec(1, 0.0, 0.0, 200.0, 90.0, 20.0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = layout.save_json(Path(tmp) / "layout.json")
            loaded = DetectorLayout.load_json(path)
            self.assertEqual(loaded.plints, layout.plints)
            data = json.loads(path.read_text())
            self.assertEqual(data["schema_version"], 1)
            del data["plints"]
            path.write_text(json.dumps(data))
            self.assertEqual(DetectorLayout.load_json(path).plints, [])

    def test_plint_validation(self):
        base = [SiPMPlacement(0, 0, 0, 0)]
        for bad in (PlintSpec(2, 0, 0, 10, 10, 10), PlintSpec(0, 0, 0, 0, 10, 10), PlintSpec(0, 0, 0, 10, 1e5, 10),
                    PlintSpec(0, 0, 0, 10, 10, -1), PlintSpec(0, float("nan"), 0, 10, 10, 10)):
            with self.assertRaises(LayoutError):
                DetectorLayout(base, plints=[bad]).validate()


if __name__ == "__main__":
    unittest.main()
