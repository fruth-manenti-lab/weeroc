"""Offline tests for the Muon detector view (no board, no real time)."""

import csv
import importlib.util
import math
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SHOT_DIR = os.environ.get("MUON_SHOT_DIR")

if GUI_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from radioroc.data import muon_analysis, muon_simulator
    from radioroc.data.muon_types import ClusterHit, DetectorLayout, EventAnalysis, MuonEvent
    from radioroc.gui import muon_view as muon_view_module
    from radioroc.gui.muon_view import MuonView

    _APP = QApplication.instance() or QApplication([])

    def fake_simulate(layout, n_events, seed=1, muon_fraction=0.8, **_kw):
        """Even events hit channel 0 (layer 0) and 32 (layer 1); odd events only channel 1."""
        events = []
        for i in range(n_events):
            hg = {c: 100.0 for c in layout.channels()}
            if i % 2 == 0:
                hg[0] += 300.0
                hg[32] += 200.0
                truth = {"angle_deg": 12.0, "is_muon": True}
            else:
                hg[1] += 300.0
                truth = None
            events.append(MuonEvent(i, 0, i, hg, dict(hg), truth))
        return events, {c: 100.0 for c in layout.channels()}

    def fake_estimate(events, gain="hg"):
        return {c: 100.0 for c in events[0].hg}

    def fake_analyse(event, layout, pedestals, threshold_counts=40.0, gain="hg", **_kw):
        amps = {c: v - pedestals.get(c, 0.0) for c, v in event.hg.items()}
        hits = {}
        for layer in layout.layers():
            cands = [(amps[s.channel], s) for s in layout.in_layer(layer)
                     if amps.get(s.channel, 0.0) > threshold_counts]
            if cands:
                amp, s = max(cands, key=lambda t: t[0])
                hits[layer] = ClusterHit(layer, (s.channel,), s.x_mm, s.y_mm, amp)
            else:
                hits[layer] = None
        coincidence = all(h is not None for h in hits.values()) and len(hits) > 0
        return EventAnalysis(event.index, amps, hits, coincidence, 5.0 if coincidence else None)


def real_logic_available():
    if not GUI_AVAILABLE:
        return False
    try:
        events, _ = muon_simulator.simulate_events(DetectorLayout.grid(2, 2, 10.0, layers=2), 2, seed=1)
        return bool(events)
    except NotImplementedError:
        return False


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 is not installed")
class MuonViewTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            unittest.mock.patch.object(muon_simulator, "simulate_events", fake_simulate),
            unittest.mock.patch.object(muon_analysis, "estimate_pedestals", fake_estimate),
            unittest.mock.patch.object(muon_analysis, "analyse_event", fake_analyse),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.view = MuonView()
        self.view.timer.stop()
        self.addCleanup(self.view.deleteLater)

    def test_default_layout_and_page_structure(self):
        v = self.view
        self.assertEqual(len(v.layout.sipms), 64)
        self.assertEqual(v.layout.layers(), [0, 1])
        self.assertEqual(len(v._items), 64)
        self.assertFalse(v.edit_mode)
        self.assertFalse(v.add_button.isEnabled())

    def test_rebuild_grid_and_one_layer(self):
        v = self.view
        self.assertTrue(v.rebuild_grid(2, 3, 12.0, 1))
        self.assertEqual(len(v.layout.sipms), 6)
        self.assertEqual(v.layout.layers(), [0])
        self.assertEqual(len(v._panel_layers), 1)
        self.assertFalse(v.rebuild_grid(10, 10, 10.0, 1))  # too many channels
        self.assertIn("Cannot build grid", v.status_label.text())
        self.assertEqual(len(v.layout.sipms), 6)

    def test_move_add_remove(self):
        v = self.view
        v.edit_mode = True
        v.move_sipm(0, 3.4, -7.6)
        p = v.layout.placement(0)
        self.assertEqual((p.x_mm, p.y_mm), (3.0, -8.0))
        item = v._items[0]
        cx = v._panel_centre_x(0)
        self.assertEqual((item.pos().x() - cx, item.pos().y()), (3.0, 8.0))
        v.remove_sipm(5)
        self.assertNotIn(5, v.layout.channels())
        self.assertTrue(v.add_button.isEnabled())
        ch = v.add_sipm(1)
        self.assertEqual(ch, 5)
        self.assertEqual(v.layout.placement(5).layer, 1)
        self.assertFalse(v.add_button.isEnabled())
        self.assertIsNone(v.add_sipm(0))
        v.move_to_other_layer(5)
        self.assertEqual(v.layout.placement(5).layer, 0)

    def test_dragging_the_item_updates_the_layout(self):
        from PySide6.QtCore import QPointF
        v = self.view
        v.edit_mode = True
        item = v._items[40]
        layer = v.layout.placement(40).layer
        cx = v._panel_centre_x(layer)
        item.setPos(QPointF(cx + 4.4, -9.6))
        p = v.layout.placement(40)
        self.assertEqual((p.x_mm, p.y_mm), (4.0, 10.0))

    def test_edit_mode_disables_replay(self):
        v = self.view
        v.generate_events(10, 1, 0.8)
        self.assertTrue(v.replay_box.isEnabled())
        v.play()
        self.assertTrue(v._playing)
        v.edit_mode = True
        self.assertFalse(v._playing)
        self.assertFalse(v.replay_box.isEnabled())
        v.play()
        self.assertFalse(v._playing)
        v.edit_mode = False
        self.assertTrue(v.replay_box.isEnabled())

    def test_generate_and_stats(self):
        v = self.view
        self.assertTrue(v.generate_events(10, 3, 0.5))
        self.assertEqual(len(v.events), 10)
        self.assertEqual(len(v.analyses), 10)
        s = v.stats()
        self.assertEqual(s["events"], 10)
        self.assertEqual(s["coincidences"], 5)
        self.assertAlmostEqual(s["fraction"], 0.5)
        self.assertAlmostEqual(s["mean_angle_deg"], 5.0)
        self.assertEqual(v.current_index, 0)
        self.assertIn("Event 1/10", v.info_label.text())
        self.assertIn("truth angle 12.0", v.info_label.text())

    def test_threshold_change_reanalyses(self):
        v = self.view
        v.generate_events(4, 1, 0.8)
        self.assertEqual(v.stats()["coincidences"], 2)
        v.threshold_spin.setValue(250)  # layer 1 amplitude is only 200
        self.assertEqual(v.stats()["coincidences"], 0)
        self.assertIsNone(v.stats()["mean_angle_deg"])

    def test_glow_follows_amplitude_and_decays(self):
        v = self.view
        v.generate_events(4, 1, 0.8)  # event 0: ch0 amp 300, ch32 amp 200; full scale 400
        self.assertAlmostEqual(v.brightness(0), 0.75)
        self.assertAlmostEqual(v.brightness(32), 0.5)
        self.assertEqual(v.brightness(7), 0.0)
        v.glow_spin.setValue(600)
        previous = v.brightness(0)
        for _ in range(200):  # 200 x 30 ms = 10 time constants
            v.advance(30)
            now = v.brightness(0)
            self.assertLessEqual(now, previous)
            previous = now
        self.assertLess(v.brightness(0), 0.01)
        # a brighter second flash takes the maximum, not the sum
        v.show_event(0)
        v.advance(0)
        v.show_event(0)
        self.assertAlmostEqual(v.brightness(0), 0.75)

    def test_item_colour_tracks_brightness(self):
        v = self.view
        v.generate_events(2, 1, 0.8)
        lit = v._items[0].brush().color()
        idle = v._items[7].brush().color()
        self.assertGreater(lit.red(), idle.red() + 50)
        self.assertTrue(v._items[0].is_seed)

    def test_coincidences_only_stepping(self):
        v = self.view
        v.generate_events(6, 1, 0.8)  # even events coincide
        v.coinc_check.setChecked(True)
        self.assertEqual(v.current_index, 0)
        v.step(1)
        self.assertEqual(v.current_index, 2)
        v.step(1)
        self.assertEqual(v.current_index, 4)
        self.assertFalse(v.step(1))
        self.assertEqual(v.current_index, 4)
        v.step(-1)
        self.assertEqual(v.current_index, 2)
        v.coinc_check.setChecked(False)
        v.step(1)
        self.assertEqual(v.current_index, 3)

    def test_play_advances_by_speed_and_stops_at_end(self):
        v = self.view
        v.generate_events(3, 1, 0.8)
        v.speed_spin.setValue(10.0)  # 100 ms per event
        v.play()
        v.advance(30)
        self.assertEqual(v.current_index, 1)  # first step happens at once
        v.advance(100)
        self.assertEqual(v.current_index, 2)
        v.advance(1000)
        self.assertFalse(v._playing)
        self.assertEqual(v.current_index, 2)

    def test_load_run_error_and_success(self):
        v = self.view
        with unittest.mock.patch.object(muon_analysis, "load_events", side_effect=ValueError("boom")):
            self.assertFalse(v.load_run("/nonexistent"))
        self.assertIn("boom", v.status_label.text())
        events, _ = fake_simulate(v.layout, 3)
        events = [MuonEvent(e.index, e.batch, e.event, {**e.hg, 99: 500.0}, e.lg) for e in events]
        with unittest.mock.patch.object(muon_analysis, "load_events", return_value=events):
            self.assertTrue(v.load_run("/some/run"))
        self.assertEqual(len(v.events), 3)
        self.assertIn("[99]", v.status_label.text())

    def test_missing_data_channels_are_hatched(self):
        v = self.view
        events, _ = fake_simulate(v.layout, 2)
        events = [MuonEvent(e.index, e.batch, e.event, {c: x for c, x in e.hg.items() if c < 60}, e.lg)
                  for e in events]
        with unittest.mock.patch.object(muon_analysis, "load_events", return_value=events):
            v.load_run("/x")
        self.assertFalse(v._items[63].has_data)
        self.assertTrue(v._items[0].has_data)

    def test_layout_save_load_and_bad_file(self):
        v = self.view
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "l.json"
            v.rebuild_grid(2, 2, 10.0, 1)
            self.assertTrue(v.save_layout_to(path))
            v.rebuild_grid(3, 3, 10.0, 2)
            self.assertTrue(v.load_layout_from(path))
            self.assertEqual(len(v.layout.sipms), 4)
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertFalse(v.load_layout_from(bad))
            self.assertIn("Could not load layout", v.status_label.text())
            self.assertEqual(len(v.layout.sipms), 4)
            self.assertFalse(v.load_layout_from(Path(tmp) / "missing.json"))

    def test_never_touches_the_board(self):
        import inspect
        source = inspect.getsource(muon_view_module)
        for word in ("ConnectionWorker", "D2XX", "transport"):
            self.assertNotIn(word, source)

    def test_screenshot(self):
        if not SHOT_DIR:
            self.skipTest("MUON_SHOT_DIR not set")
        v = self.view
        v.generate_events(20, 1, 0.8)
        v.resize(860, 640)
        v.show()
        _APP.processEvents()
        Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
        v.grab().save(str(Path(SHOT_DIR) / "muon_view_fake.png"))


@unittest.skipUnless(real_logic_available(), "real muon logic not available")
class MuonViewRealLogicTests(unittest.TestCase):
    def setUp(self):
        self.view = MuonView()
        self.view.timer.stop()
        self.addCleanup(self.view.deleteLater)

    def test_generate_with_simulator(self):
        v = self.view
        self.assertTrue(v.generate_events(60, 1, 0.8))
        self.assertEqual(len(v.analyses), 60)
        s = v.stats()
        self.assertGreater(s["coincidences"], 0)
        v.step(1)
        self.assertEqual(v.current_index, 1)

    def test_load_tiny_run_folder(self):
        v = self.view
        events, _ = muon_simulator.simulate_events(v.layout, 5, seed=2)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            with open(run / "events.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["batch", "event", "channel", "hg", "lg"])
                for e in events:
                    for ch in sorted(e.hg):
                        w.writerow([e.batch, e.event, ch, int(e.hg[ch]), int(e.lg.get(ch, 0))])
            self.assertTrue(v.load_run(run), v.status_label.text())
        self.assertEqual(len(v.events), 5)

    def test_screenshots(self):
        if not SHOT_DIR:
            self.skipTest("MUON_SHOT_DIR not set")
        from radioroc.gui.main_window import MainWindow
        v = self.view
        v.generate_events(100, 1, 0.8)
        v.coinc_check.setChecked(True)
        v.show_event(0)
        v.step(1)
        window = MainWindow()
        try:
            window.sidebar.setCurrentRow(3)
            window.resize(1024, 700)
            window.show()
            window.muon_view.generate_events(100, 1, 0.8)
            window.muon_view.coinc_check.setChecked(True)
            window.muon_view.step(1)
            _APP.processEvents()
            Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
            window.grab().save(str(Path(SHOT_DIR) / "muon_page_1024x700.png"))
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
