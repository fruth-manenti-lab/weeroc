import json
import tempfile
import unittest
from pathlib import Path

from radioroc.data.muon_analysis import load_pedestals
from radioroc.data.pedestals import (
    PEDESTALS_FILENAME, PedestalSet, compute_pedestals, find_pedestals_for_run,
    load_pedestals_json, save_pedestals_json, to_muon_pedestals)


def make_rows():
    rows = []
    for i, v in enumerate([90, 92, 94, 96, 98]):
        rows.append({"channel": 6, "hg": v, "lg": 80 + i})
    for v in [100, 100, 100, 100, 104, 100]:
        rows.append({"channel": 32, "hg": v, "lg": 120})
    for v in [1, 2, 3]:
        rows.append({"channel": 9, "hg": v, "lg": v})
    return rows


class PedestalTests(unittest.TestCase):
    def test_compute_median_sd_and_rejects_short_channels(self):
        ps = compute_pedestals(make_rows(), settings={"hold": 30}, source_run="r")
        self.assertEqual(sorted(ps.channels), [6, 32])
        c6 = ps.channels[6]
        self.assertEqual((c6.hg_median, c6.lg_median, c6.n), (94.0, 82.0, 5))
        self.assertAlmostEqual(c6.hg_sd, 1.4826 * 2.0, places=5)   # robust sd (MAD)
        self.assertEqual(ps.hg(), {6: 94.0, 32: 100.0})
        self.assertEqual(ps.lg()[32], 120.0)
        self.assertEqual((ps.source_run, ps.settings), ("r", {"hold": 30}))

    def test_robust_sd_ignores_a_stray_pulse(self):
        rows = [{"channel": 6, "hg": 95.0 + 0.5 * (i % 5), "lg": 90.0} for i in range(100)]
        rows.append({"channel": 6, "hg": 258.5, "lg": 90.0})   # one muon during a forced trigger
        c6 = compute_pedestals(rows).channels[6]
        self.assertLess(c6.hg_sd, 2.0)
        self.assertAlmostEqual(c6.hg_median, 96.0, places=1)

    def test_channel_filter(self):
        self.assertEqual(sorted(compute_pedestals(make_rows(), channels=[6]).channels), [6])

    def test_roundtrip_and_find(self):
        ps = compute_pedestals(make_rows())
        with tempfile.TemporaryDirectory() as tmp:
            path = save_pedestals_json(Path(tmp) / PEDESTALS_FILENAME, ps)
            data = json.loads(path.read_text())
            self.assertEqual((data["schema_version"], data["kind"]), (1, "pedestals"))
            self.assertEqual(set(data["channels"]), {"6", "32"})
            self.assertEqual(load_pedestals_json(path), ps)
            self.assertEqual(PedestalSet.from_dict(ps.to_dict()), ps)
            self.assertEqual(find_pedestals_for_run(tmp), ps)
            # muon_analysis reads the same file
            self.assertEqual(load_pedestals(path), to_muon_pedestals(ps))

    def test_find_absent_or_bad(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_pedestals_for_run(tmp))
            (Path(tmp) / PEDESTALS_FILENAME).write_text("{nope")
            self.assertIsNone(find_pedestals_for_run(tmp))

    def test_from_dict_rejects_garbage(self):
        for bad in (None, {}, {"schema_version": 1, "channels": {"99": {}}},
                    {"schema_version": 1, "channels": {"6": {"hg_median": 1}}}):
            with self.assertRaises(ValueError):
                PedestalSet.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
