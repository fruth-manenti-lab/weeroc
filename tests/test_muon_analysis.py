import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from radioroc.data.muon_analysis import (
    analyse_event, estimate_pedestals, events_from_rows, load_events, load_pedestals, pedestals_look_biased,
    save_pedestals,
)
from radioroc.data.muon_simulator import simulate_events
from radioroc.data.muon_types import DetectorLayout, MuonEvent, SiPMPlacement


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
                if abs(hx) > 35.0 or abs(hy) > 15.0:
                    continue  # plint margin outside the SiPM bounding box: a centroid cannot leave the SiPMs
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


FIXTURE = Path(__file__).parent / "fixtures" / "muon_run_ch6_ch32"


class PedestalSourceTests(unittest.TestCase):
    def test_json_round_trip_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = save_pedestals(tmp / "sub" / "ped.json", {6: 92.0, 32: 100.5})
            self.assertEqual(load_pedestals(path), {6: 92.0, 32: 100.5})
            self.assertEqual(json.loads(path.read_text())["gain"], "hg")
            with self.assertRaisesRegex(ValueError, "cannot read"):
                load_pedestals(tmp / "missing.json")
            (tmp / "bad.json").write_text("{nope")
            with self.assertRaisesRegex(ValueError, "cannot read"):
                load_pedestals(tmp / "bad.json")
            (tmp / "schema.json").write_text(json.dumps({"schema_version": 2, "pedestals": {}}))
            with self.assertRaisesRegex(ValueError, "not a pedestal file"):
                load_pedestals(tmp / "schema.json")
            (tmp / "lg.json").write_text(json.dumps({"schema_version": 1, "gain": "lg", "pedestals": {"1": 90}}))
            with self.assertRaisesRegex(ValueError, "gain"):
                load_pedestals(tmp / "lg.json")
            (tmp / "val.json").write_text(json.dumps({"schema_version": 1, "pedestals": {"x": 1}}))
            with self.assertRaisesRegex(ValueError, "invalid"):
                load_pedestals(tmp / "val.json")
            (tmp / "range.json").write_text(json.dumps({"schema_version": 1, "pedestals": {"99": 1}}))
            with self.assertRaisesRegex(ValueError, "invalid"):
                load_pedestals(tmp / "range.json")
            (tmp / "none.json").write_text(json.dumps({"schema_version": 1, "pedestals": {}}))
            with self.assertRaisesRegex(ValueError, "no pedestals"):
                load_pedestals(tmp / "none.json")

    def test_pedestal_run_directory(self):
        rows = [{"batch": 0, "event": e, "channel": c, "hg": 90 + c + e, "lg": 80} for e in range(5) for c in (1, 2)]
        with tempfile.TemporaryDirectory() as tmp:
            _write_run(Path(tmp) / "ped", rows, [1, 2], 1)
            self.assertEqual(load_pedestals(Path(tmp) / "ped"), {1: 93.0, 2: 94.0})
            _write_run(Path(tmp) / "empty", [], [1], 1)
            with self.assertRaisesRegex(ValueError, "pedestal run"):
                load_pedestals(Path(tmp) / "empty")
            with self.assertRaisesRegex(ValueError, "pedestal run"):
                load_pedestals(Path(tmp))

    def test_biased_heuristic(self):
        quiet = [MuonEvent(i, 0, i, {0: 100.0 + i % 3}, {0: 90.0}) for i in range(20)]
        self.assertEqual(pedestals_look_biased(quiet, estimate_pedestals(quiet), 40.0), [])
        hot = [MuonEvent(i, 0, i, {0: 250.0 + 10 * (i % 5), 1: 100.0}, {0: 90.0, 1: 90.0}) for i in range(20)]
        hot += [MuonEvent(20, 0, 20, {0: 100.0, 1: 100.0}, {0: 90.0, 1: 90.0})] * 6
        self.assertEqual(pedestals_look_biased(hot, estimate_pedestals(hot), 40.0), [0])
        self.assertEqual(pedestals_look_biased(hot, {1: 100.0}, 40.0), [])

    def test_recorded_coincidence_run(self):
        # tests/fixtures/muon_run_ch6_ch32 approximates the 2026-10-21 coincidence-trigger run: every event holds a
        # muon pulse on both channels, so the median of the events sits on the pulse height. No real run
        # folders are committed.
        layout = DetectorLayout([SiPMPlacement(6, 0, 0, 0), SiPMPlacement(32, 1, 0, 0)])
        events = load_events(FIXTURE)
        self.assertEqual(len(events), 12)
        true_peds = {6: 92.0, 32: 100.0}
        good = [analyse_event(e, layout, true_peds, threshold_counts=40.0) for e in events]
        # ch6 of event 9 is only 129 - 92 = 37 counts, just under the threshold of 40: 11 of 12 at 40, all 12 at 35.
        self.assertEqual(sum(a.coincidence for a in good), 11)
        self.assertTrue(all(analyse_event(e, layout, true_peds, threshold_counts=35.0).coincidence for e in events))
        estimate = estimate_pedestals(events)
        # ch32 is flagged; ch6 (median 169.5 vs 10th percentile 138) is below the 40-count warning margin.
        self.assertIn(32, pedestals_look_biased(events, estimate, 40.0))
        self.assertEqual(pedestals_look_biased(events, true_peds, 40.0), [])
        biased = [analyse_event(e, layout, estimate, threshold_counts=40.0) for e in events]
        self.assertLess(sum(a.coincidence for a in biased), 12)


if __name__ == "__main__":
    unittest.main()
