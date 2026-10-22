import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from radioroc.data.muon_analysis import analyse_event, estimate_pedestals, events_from_rows, load_events
from radioroc.data.muon_simulator import simulate_events
from radioroc.data.muon_types import DetectorLayout, MuonEvent


def _write_run(directory: Path, rows, channels, batches):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "events.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["batch", "event", "channel", "hg", "lg"])
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"schema_version": 1, "status": "completed", "execution_mode": "simulation",
                "operation": {"acquisition": {"channels": channels, "batches": batches, "start_batch": 0}},
                "completed_points": batches}
    (directory / "metadata.json").write_text(json.dumps(manifest), encoding="utf-8")


class RowsTests(unittest.TestCase):
    def test_grouping_and_bad_values(self):
        rows = [
            {"batch": "0", "event": "0", "channel": "1", "hg": "100", "lg": "90"},
            {"batch": "0", "event": "0", "channel": "2", "hg": "nan", "lg": "90"},
            {"batch": "0", "event": "0", "channel": "3", "hg": "abc", "lg": "90"},
            {"batch": "0", "event": "1", "channel": "1", "hg": 110.0, "lg": 91.0},
            {"batch": "0", "event": "0", "channel": "4", "hg": 120.0, "lg": 95.0},
            {"batch": "1", "event": "0", "channel": "1", "hg": 130.0, "lg": 96.0},
            {"batch": "1", "event": "0"},
        ]
        events = events_from_rows(rows)
        self.assertEqual([(e.index, e.batch, e.event) for e in events], [(0, 0, 0), (1, 0, 1), (2, 1, 0)])
        self.assertEqual(events[0].hg, {1: 100.0, 4: 120.0})
        self.assertEqual(events[0].lg, {1: 90.0, 4: 95.0})
        filtered = events_from_rows(rows, channels=[4])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].hg, {4: 120.0})

    def test_load_events(self):
        rows = [{"batch": b, "event": e, "channel": c, "hg": 100 + c + e, "lg": 90 + c}
                for b in range(2) for e in range(3) for c in (0, 5)]
        with tempfile.TemporaryDirectory() as tmp:
            _write_run(Path(tmp) / "run", rows, [0, 5], 2)
            events = load_events(Path(tmp) / "run")
            self.assertEqual(len(events), 6)
            self.assertEqual(events[4].hg, {0: 101.0, 5: 106.0})
            _write_run(Path(tmp) / "empty", [], [0], 1)
            with self.assertRaisesRegex(ValueError, "no events"):
                load_events(Path(tmp) / "empty")

    def test_pedestals(self):
        events = [MuonEvent(i, 0, i, {0: v, 1: 50.0}, {0: v - 10, 1: 40.0}) for i, v in enumerate([100, 101, 102, 900, 100])]
        self.assertEqual(estimate_pedestals(events), {0: 101.0, 1: 50.0})
        self.assertEqual(estimate_pedestals(events, gain="lg")[0], 91.0)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = DetectorLayout.grid(4, 8, 10, layers=2)
        cls.events, cls.true_peds = simulate_events(cls.layout, 2000, seed=11)
        cls.peds = estimate_pedestals(cls.events)
        cls.results = [analyse_event(e, cls.layout, cls.peds) for e in cls.events]

    def test_pedestal_estimate(self):
        # With mostly-muon data the median of central SiPMs is biased upward by shared light, so the
        # accuracy check uses a muon-poor sample; the recognition tests above use the biased estimate.
        events, _ = simulate_events(self.layout, 1000, seed=12, muon_fraction=0.2)
        peds = estimate_pedestals(events)
        self.assertTrue(all(abs(v - 95.0) < 2.0 for v in peds.values()))
        self.assertEqual(sorted(self.peds), list(range(64)))

    def test_coincidence_rates(self):
        pairs = list(zip(self.events, self.results))
        muons = [r for e, r in pairs if e.truth["is_muon"]]
        others = [r for e, r in pairs if not e.truth["is_muon"]]
        self.assertGreaterEqual(sum(r.coincidence for r in muons) / len(muons), 0.95)
        self.assertLess(sum(r.coincidence for r in others) / len(others), 0.05)

    def test_centroid_and_angle(self):
        good = total = 0
        angle_err = []
        for e, r in zip(self.events, self.results):
            if not e.truth["is_muon"] or not r.coincidence:
                continue
            for layer, (hx, hy) in e.truth["hit_xy"].items():
                total += 1
                hit = r.hits[layer]
                good += math.hypot(hit.x_mm - hx, hit.y_mm - hy) <= 6.0
            if e.truth["angle_deg"] > 10:
                angle_err.append(abs(r.angle_deg - e.truth["angle_deg"]))
        self.assertGreaterEqual(good / total, 0.90)
        self.assertGreater(len(angle_err), 20)
        self.assertLess(sum(angle_err) / len(angle_err), 12.0)

    def test_cluster_structure(self):
        for e, r in zip(self.events, self.results):
            if e.truth["is_muon"] and r.coincidence:
                hit = r.hits[0]
                amps = [r.amplitudes[c] for c in hit.channels]
                self.assertEqual(amps, sorted(amps, reverse=True))
                self.assertAlmostEqual(hit.charge, sum(amps))
                self.assertIsNotNone(r.angle_deg)
                break
        else:
            self.fail("no coincidence found")

    def test_single_layer_and_missing_channels(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=1)
        events, peds = simulate_events(layout, 20, seed=2, muon_fraction=1.0)
        r = analyse_event(events[0], layout, peds)
        self.assertTrue(r.coincidence)
        self.assertIsNone(r.angle_deg)
        partial = MuonEvent(0, 0, 0, {0: 95.0}, {0: 90.0})
        r = analyse_event(partial, layout, peds)
        self.assertFalse(r.coincidence)
        self.assertEqual(r.amplitudes[0], 0.0)
        self.assertEqual(len(r.amplitudes), 1)

    def test_saturated_seed_uses_lg(self):
        events, peds = simulate_events(self.layout, 10, seed=4, muon_fraction=1.0, peak_counts=8000.0)
        saturated = [e for e in events if max(e.hg.values()) >= 4000]
        self.assertTrue(saturated)
        e = saturated[0]
        r = analyse_event(e, self.layout, peds)
        seed = max(e.hg, key=e.hg.get)
        self.assertGreater(r.amplitudes[seed], 4095 - 95)
        self.assertTrue(r.coincidence)

    def test_lg_gain(self):
        lg_peds = estimate_pedestals(self.events, gain="lg")
        muon = next(e for e in self.events if e.truth["is_muon"])
        r = analyse_event(muon, self.layout, lg_peds, threshold_counts=10.0, gain="lg")
        self.assertTrue(r.coincidence)


if __name__ == "__main__":
    unittest.main()
