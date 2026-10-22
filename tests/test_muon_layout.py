import json
from pathlib import Path
import tempfile
import unittest

from radioroc.data.muon_types import (
    DetectorLayout, LayoutError, PlintSpec, SiPMPlacement, format_channel_list, parse_channel_list,
)


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


class ChannelListTests(unittest.TestCase):
    def test_parse_good(self):
        self.assertEqual(parse_channel_list("6"), [6])
        self.assertEqual(parse_channel_list(" 6, 7 ,9-12 "), [6, 7, 9, 10, 11, 12])
        self.assertEqual(parse_channel_list("0-31"), list(range(32)))
        self.assertEqual(parse_channel_list("5 - 7"), [5, 6, 7])
        self.assertEqual(parse_channel_list(""), [])
        self.assertEqual(parse_channel_list("  "), [])
        self.assertEqual(parse_channel_list("63"), [63])

    def test_parse_bad(self):
        cases = {"70": "channel 70 is outside 0..63", "60-64": "channel 64 is outside 0..63",
                 "6, 6": "channel 6 is listed twice", "0-3, 2": "channel 2 is listed twice",
                 "x-y": 'cannot read "x-y"', "1,a": 'cannot read "a"', "-3": 'cannot read "-3"',
                 "9-5": 'range "9-5" must go upwards', "1.5": 'cannot read "1.5"'}
        for text, message in cases.items():
            with self.subTest(text=text), self.assertRaises(LayoutError) as ctx:
                parse_channel_list(text)
            self.assertIn(message, str(ctx.exception))

    def test_format_round_trip(self):
        self.assertEqual(format_channel_list([0, 1, 2, 3, 6, 8, 9]), "0-3, 6, 8-9")
        self.assertEqual(format_channel_list(range(32)), "0-31")
        self.assertEqual(format_channel_list([]), "")
        for text in ("0-31", "6", "6, 8-9"):
            self.assertEqual(format_channel_list(parse_channel_list(text)), text)

    def test_from_channel_lists_grid_and_centering(self):
        layout = DetectorLayout.from_channel_lists({0: list(range(32)), 1: list(range(32, 64))}, 8, 10.0)
        self.assertEqual(len(layout.sipms), 64)
        self.assertEqual(layout.layers(), [0, 1])
        self.assertEqual(layout.channels(), list(range(64)))
        first, last = layout.placement(0), layout.placement(31)
        self.assertEqual((first.x_mm, first.y_mm), (-35.0, -15.0))
        self.assertEqual((last.x_mm, last.y_mm), (35.0, 15.0))
        self.assertEqual(layout.placement(32).layer, 1)
        ref = DetectorLayout.grid(4, 8, 10.0, layers=2)
        self.assertEqual(sorted((s.channel, s.layer, s.x_mm, s.y_mm) for s in layout.sipms),
                         sorted((s.channel, s.layer, s.x_mm, s.y_mm) for s in ref.sipms))

    def test_from_channel_lists_clips_columns_and_partial_rows(self):
        single = DetectorLayout.from_channel_lists({0: [6], 1: [32]}, 8, 10.0)
        self.assertEqual([(s.channel, s.layer, s.x_mm, s.y_mm) for s in single.sipms],
                         [(6, 0, 0.0, 0.0), (32, 1, 0.0, 0.0)])
        column = DetectorLayout.from_channel_lists({0: [1, 2, 3]}, 1, 10.0)
        self.assertEqual([(s.x_mm, s.y_mm) for s in column.sipms], [(0.0, -10.0), (0.0, 0.0), (0.0, 10.0)])
        partial = DetectorLayout.from_channel_lists({0: [1, 2, 3]}, 2, 10.0)
        self.assertEqual([(s.x_mm, s.y_mm) for s in partial.sipms], [(-5.0, -5.0), (5.0, -5.0), (-5.0, 5.0)])

    def test_from_channel_lists_errors(self):
        with self.assertRaises(LayoutError) as ctx:
            DetectorLayout.from_channel_lists({0: [1, 2], 1: [2, 3]}, 2, 10.0)
        self.assertIn("channel 2", str(ctx.exception))
        with self.assertRaises(LayoutError):
            DetectorLayout.from_channel_lists({0: [1, 1]}, 2, 10.0)
        with self.assertRaises(LayoutError):
            DetectorLayout.from_channel_lists({0: [], 1: []}, 2, 10.0)
        with self.assertRaises(LayoutError):
            DetectorLayout.from_channel_lists({0: [1]}, 0, 10.0)
        with self.assertRaises(LayoutError):
            DetectorLayout.from_channel_lists({2: [1]}, 1, 10.0)


if __name__ == "__main__":
    unittest.main()
