import math
import unittest

from radioroc.data.muon_simulator import simulate_events
from radioroc.data.muon_types import DetectorLayout, PlintSpec


class MuonSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.layout = DetectorLayout.grid(4, 8, 10, layers=2)

    def test_deterministic(self):
        a, pa = simulate_events(self.layout, 30, seed=5)
        b, pb = simulate_events(self.layout, 30, seed=5)
        c, _ = simulate_events(self.layout, 30, seed=6)
        self.assertEqual(a, b)
        self.assertEqual(pa, pb)
        self.assertNotEqual(a, c)

    def test_all_channels_and_indices(self):
        events, peds = simulate_events(self.layout, 25, seed=2)
        self.assertEqual(sorted(peds), list(range(64)))
        for i, ev in enumerate(events):
            self.assertEqual(sorted(ev.hg), list(range(64)))
            self.assertEqual(sorted(ev.lg), list(range(64)))
            self.assertEqual((ev.index, ev.batch, ev.event), (i, i // 10, i % 10))

    def test_muon_has_bright_sipm_near_truth(self):
        events, peds = simulate_events(self.layout, 100, seed=3, muon_fraction=1.0)
        for ev in events:
            self.assertTrue(ev.truth["is_muon"])
            for layer, (hx, hy) in ev.truth["hit_xy"].items():
                best = max(self.layout.in_layer(layer), key=lambda s: ev.hg[s.channel])
                self.assertLess(math.hypot(best.x_mm - hx, best.y_mm - hy), 8.0)
                self.assertGreater(ev.hg[best.channel] - peds[best.channel], 100.0)

    def test_fraction_extremes(self):
        none, _ = simulate_events(self.layout, 40, seed=1, muon_fraction=0.0)
        self.assertTrue(all(ev.truth == {"is_muon": False} for ev in none))
        for ev in none:  # at least one bump, and small
            self.assertGreaterEqual(max(ev.hg.values()) - 95.0, 20.0)
            self.assertLess(max(ev.hg.values()), 95.0 + 80.0 + 20.0)
        allm, _ = simulate_events(self.layout, 40, seed=1, muon_fraction=1.0)
        self.assertTrue(all(ev.truth["is_muon"] for ev in allm))
        self.assertTrue(all(0.0 <= ev.truth["angle_deg"] <= 60.0 for ev in allm))

    def test_saturation_cap(self):
        events, _ = simulate_events(self.layout, 20, seed=4, muon_fraction=1.0, peak_counts=20000.0)
        top = max(v for ev in events for v in ev.hg.values())
        self.assertEqual(top, 4095.0)
        self.assertTrue(all(v <= 4095.0 for ev in events for v in list(ev.hg.values()) + list(ev.lg.values())))
        # lg keeps the large values below saturation
        ev = events[0]
        ch = max(ev.hg, key=ev.hg.get)
        self.assertLess(ev.lg[ch], ev.hg[ch])

    def test_single_layer(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=1)
        events, peds = simulate_events(layout, 20, seed=1, muon_fraction=1.0)
        self.assertEqual(len(peds), 32)
        for ev in events:
            self.assertEqual(list(ev.truth["hit_xy"]), [0])
            self.assertEqual(len(ev.hg), 32)

    def test_entry_points_follow_plints(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=2, plint_width_mm=200, plint_length_mm=40)
        events, _ = simulate_events(layout, 300, seed=7, muon_fraction=1.0)
        xs = [ev.truth["hit_xy"][0][0] for ev in events]
        self.assertGreater(max(xs), 60.0)          # beyond the SiPM bounding box (35 mm)
        self.assertLessEqual(max(abs(x) for x in xs), 100.0)
        for ev in events:                           # every track crosses a plint of each layer
            for layer, (x, y) in ev.truth["hit_xy"].items():
                self.assertLessEqual(abs(x), 100.0 + 1e-9)
                self.assertLessEqual(abs(y), 20.0 + 1e-9)

    def test_two_plints_in_first_layer(self):
        layout = DetectorLayout.grid(4, 8, 10, layers=2)
        layout.plints = [PlintSpec(0, -50, 0, 20, 20, 10), PlintSpec(0, 50, 0, 20, 20, 10),
                         PlintSpec(1, 0, 0, 200, 40, 10)]
        events, _ = simulate_events(layout, 200, seed=3, muon_fraction=1.0)
        starts = [ev.truth["hit_xy"][0][0] for ev in events]
        self.assertTrue(any(x < -30 for x in starts) and any(x > 30 for x in starts))
        self.assertTrue(all(abs(abs(x) - 50) <= 10 + 1e-9 for x in starts))

    def test_zero_events(self):
        self.assertEqual(simulate_events(self.layout, 0)[0], [])


if __name__ == "__main__":
    unittest.main()
