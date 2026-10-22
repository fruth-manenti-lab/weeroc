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

    def test_plints_auto_explicit_and_table(self):
        v = self.view
        self.assertFalse(v.plints_are_explicit)
        self.assertEqual(len(v.plints), 2)
        self.assertEqual(v.plint_table.rowCount(), 2)
        self.assertEqual(len(v._plint_items), 2)
        self.assertEqual((v.plints[0].width_mm, v.plints[0].length_mm), (80.0, 40.0))
        v.plint_table.item(0, 3).setText("120")          # editing an auto plint makes it explicit
        self.assertTrue(v.plints_are_explicit)
        self.assertEqual(len(v.layout.plints), 2)
        self.assertEqual(v.layout.plints[0].width_mm, 120.0)
        v.plint_table.item(0, 3).setText("abc")          # bad text is reverted
        self.assertEqual(v.layout.plints[0].width_mm, 120.0)
        self.assertEqual(v.plint_table.item(0, 3).text(), "120")
        v.plint_table.item(0, 4).setText("-5")           # invalid size is rejected
        self.assertEqual(v.layout.plints[0].length_mm, 40.0)
        idx = v.add_plint(1, 5, 5, 60, 30, 10)
        self.assertEqual((idx, len(v.plints), v.plint_table.rowCount()), (2, 3, 3))
        self.assertTrue(v.set_plint(idx, width_mm=70.0, thickness_mm=20.0))
        self.assertEqual((v.plints[idx].width_mm, v.plints[idx].thickness_mm), (70.0, 20.0))
        self.assertTrue(v.remove_plint(idx))
        v.auto_fit_plints()
        self.assertFalse(v.plints_are_explicit)
        self.assertEqual(v.plints[0].width_mm, 80.0)

    def test_big_plints_grow_the_panel_and_save_load(self):
        v = self.view
        before = v._panel_half
        v.set_plint(0, width_mm=400, length_mm=120, thickness_mm=10)   # auto plints become explicit
        v.set_plint(1, width_mm=300, length_mm=150, thickness_mm=20)
        self.assertGreaterEqual(v._panel_half, 200.0)
        self.assertGreater(v._panel_half, before)
        self.assertGreaterEqual(v._panel_half_y, 75.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lay.json"
            self.assertTrue(v.save_layout_to(path))
            v.auto_fit_plints()
            self.assertTrue(v.load_layout_from(path))
        self.assertEqual([(p.layer, p.width_mm) for p in v.layout.plints], [(0, 400.0), (1, 300.0)])

    def test_plint_drag_updates_layout_and_table(self):
        from PySide6.QtCore import QPointF
        v = self.view
        v.edit_mode = True
        item = v._plint_items[1]
        cx = v._panel_centre_x(1)
        item.setPos(QPointF(cx + 3.4, -6.6))
        self.assertTrue(v.plints_are_explicit)
        p = v.plints[1]
        self.assertEqual((p.x_mm, p.y_mm), (3.0, 7.0))
        self.assertEqual(v.plint_table.item(1, 1).text(), "3")
        self.assertEqual(v.plint_table.item(1, 2).text(), "7")

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

    # ---------------------------------------------------- channel lists --
    def _layout_snapshot(self):
        v = self.view
        return sorted((s.channel, s.layer, s.x_mm, s.y_mm) for s in v.layout.sipms)

    def test_channel_fields_prefilled_and_follow_layout(self):
        v = self.view
        self.assertEqual((v.channel_list_text(0), v.channel_list_text(1)), ("0-31", "32-63"))
        self.assertTrue(v.layer1_edit.isEnabled())
        v.rebuild_grid(2, 3, 10.0, 1)
        self.assertEqual((v.channel_list_text(0), v.channel_list_text(1)), ("0-5", ""))
        v.layers_spin.setValue(1)
        self.assertFalse(v.layer1_edit.isEnabled())
        v.layers_spin.setValue(2)
        self.assertTrue(v.layer1_edit.isEnabled())
        v.remove_sipm(2)
        self.assertEqual(v.channel_list_text(0), "0-1, 3-5")
        v.add_sipm(0, channel=40)
        self.assertEqual(v.channel_list_text(0), "0-1, 3-5, 40")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.json"
            v.rebuild_grid(4, 8, 10.0, 2)
            v.save_layout_to(path)
            v.rebuild_grid(1, 2, 10.0, 1)
            v.load_layout_from(path)
        self.assertEqual((v.channel_list_text(0), v.channel_list_text(1)), ("0-31", "32-63"))

    def test_set_channel_lists_success(self):
        v = self.view
        v.cols_spin.setValue(1)
        self.assertTrue(v.set_channel_lists("6", "32"))
        self.assertEqual(self._layout_snapshot(), [(6, 0, 0.0, 0.0), (32, 1, 0.0, 0.0)])
        self.assertEqual(len(v._items), 2)
        self.assertEqual((v.channel_list_text(0), v.channel_list_text(1)), ("6", "32"))
        v.cols_spin.setValue(8)
        v.pitch_spin.setValue(12)
        self.assertTrue(v.set_channel_lists("0-31", "32-63"))
        self.assertEqual(len(v.layout.sipms), 64)
        self.assertEqual(v.layout.placement(0).x_mm, -42.0)
        self.assertEqual(v.layout.placement(0).y_mm, -18.0)
        self.assertEqual(v.layout.placement(40).layer, 1)

    def test_set_channel_lists_errors_change_nothing(self):
        v = self.view
        before = self._layout_snapshot()
        for l0, l1, message in (("70", "", "channel 70 is outside 0..63"), ("6, 6", "", "channel 6 is listed twice"),
                                ("x-y", "", 'cannot read "x-y"'), ("1-3", "3-4", "channel 3"),
                                ("", "", "no channels")):
            with self.subTest(l0=l0, l1=l1):
                self.assertFalse(v.set_channel_lists(l0, l1))
                self.assertIn(message, v.status_label.text())
                self.assertEqual(self._layout_snapshot(), before)
        v.layers_spin.setValue(1)
        self.assertFalse(v.set_channel_lists("1", "2"))
        self.assertIn("Layers", v.status_label.text())
        self.assertEqual(self._layout_snapshot(), before)
        v.layers_spin.setValue(1)
        self.assertTrue(v.set_channel_lists("1-4", ""))
        self.assertEqual(v.layout.layers(), [0])
        v.build_channels_button.click()      # the button uses the fields as they are
        self.assertEqual(v.layout.channels(), [1, 2, 3, 4])

    # ------------------------------------------------------- SiPM table --
    def test_sipm_table_lists_sorted_sipms_and_follows_changes(self):
        v = self.view
        t = v.sipm_table
        self.assertEqual([t.horizontalHeaderItem(c).text() for c in range(4)], ["Channel", "Layer", "X (mm)", "Y (mm)"])
        self.assertEqual(t.rowCount(), 64)
        self.assertEqual([t.item(r, 0).text() for r in range(3)], ["0", "1", "2"])
        self.assertEqual(t.item(40, 1).text(), "1")
        v.edit_mode = True
        v.move_sipm(3, 4.0, 5.0)
        self.assertEqual((t.item(3, 2).text(), t.item(3, 3).text()), ("4", "5"))
        v.remove_sipm(0)
        self.assertEqual((t.rowCount(), t.item(0, 0).text()), (63, "1"))

    def test_sipm_table_edit_channel_layer_and_position(self):
        v = self.view
        t = v.sipm_table
        t.item(5, 0).setText("3")                      # used by another SiPM: reverted
        self.assertEqual(v.layout.placement(5).layer, 0)
        self.assertEqual(sorted(v.layout.channels()), list(range(64)))
        self.assertEqual(t.item(5, 0).text(), "5")
        self.assertIn("already used", v.status_label.text())
        t.item(5, 0).setText("64")
        self.assertIn("outside 0..63", v.status_label.text())
        self.assertEqual(t.item(5, 0).text(), "5")
        t.item(5, 0).setText("x")
        self.assertIn("not a number", v.status_label.text())
        v.remove_sipm(7)
        row = [t.item(r, 0).text() for r in range(t.rowCount())].index("8")
        t.item(row, 0).setText("7")                    # a free channel is accepted
        self.assertNotIn(8, v.layout.channels())
        row7 = [t.item(r, 0).text() for r in range(t.rowCount())].index("7")
        t.item(row7, 1).setText("1")
        self.assertEqual(v.layout.placement(7).layer, 1)
        t.item(row7, 1).setText("2")
        self.assertEqual(v.layout.placement(7).layer, 1)
        self.assertEqual(t.item(row7, 1).text(), "1")
        t.item(row7, 2).setText("123.5")
        t.item(row7, 3).setText("-8")
        p = v.layout.placement(7)
        self.assertEqual((p.x_mm, p.y_mm), (123.5, -8.0))
        self.assertGreaterEqual(v._panel_half, 125.0)  # the panel grew to contain it
        t.item(row7, 2).setText("abc")
        self.assertEqual(v.layout.placement(7).x_mm, 123.5)
        self.assertEqual(t.item(row7, 2).text(), "123.5")

    def test_sipm_table_layer_one_needs_two_layers(self):
        v = self.view
        v.rebuild_grid(1, 2, 10.0, 1)
        v.sipm_table.item(0, 1).setText("1")
        self.assertEqual(v.layout.placement(0).layer, 0)
        self.assertIn("Layers = 2", v.status_label.text())
        v.layers_spin.setValue(2)
        v.sipm_table.item(0, 1).setText("1")
        self.assertEqual(v.layout.placement(0).layer, 1)

    def test_selection_syncs_between_canvas_and_table(self):
        v = self.view
        v.edit_mode = True
        v._items[40].setSelected(True)
        v._items[2].setSelected(True)
        self.assertEqual(sorted(v._table_channels()), [2, 40])
        self.assertEqual(v._selected_channels(), [2, 40])
        v._items[2].setSelected(False)
        self.assertEqual(v._table_channels(), [40])
        v.sipm_table.clearSelection()
        v.sipm_table.selectRow(10)
        self.assertEqual([i.channel for i in v.scene.selectedItems()], [10])
        self.assertTrue(v.remove_button.isEnabled())
        v._remove_clicked()
        self.assertNotIn(10, v.layout.channels())
        self.assertEqual(v.sipm_table.rowCount(), 63)
        self.assertEqual(v.sipm_table.selectedItems(), [])

    def test_selection_survives_table_edit_and_drag(self):
        from PySide6.QtCore import QPointF
        v = self.view
        v.edit_mode = True
        v._items[40].setSelected(True)
        item = v._items[40]
        item.setPos(QPointF(v._panel_centre_x(1) + 2, -3))
        self.assertEqual(v._table_channels(), [40])
        self.assertEqual(v.sipm_table.item(40, 2).text(), "2")
        self.assertEqual(v.sipm_table.item(40, 3).text(), "3")

    # ---------------------------------------------------------- add SiPM --
    def test_add_sipm_defaults_next_free_slot(self):
        v = self.view
        v.remove_sipm(5)
        v.remove_sipm(41)
        v.pitch_spin.setValue(12)
        last = max(v.layout.in_layer(0), key=lambda s: (s.x_mm, s.y_mm))
        self.assertEqual(v.add_sipm(0), 5)
        p = v.layout.placement(5)
        self.assertEqual((p.layer, p.x_mm, p.y_mm), (0, last.x_mm + 12.0, last.y_mm))
        self.assertEqual(v.add_sipm(1, channel=41, x_mm=1.5, y_mm=-2), 41)
        p = v.layout.placement(41)
        self.assertEqual((p.layer, p.x_mm, p.y_mm), (1, 1.5, -2.0))
        v.remove_sipm(60)
        self.assertIsNone(v.add_sipm(0, channel=41))
        self.assertIn("not free", v.status_label.text())

    def test_add_sipm_into_empty_layer_goes_to_origin_and_panel_grows(self):
        v = self.view
        v.set_channel_lists("0", "")
        v.layers_spin.setValue(2)
        self.assertEqual(v.add_sipm(1), 1)
        p = v.layout.placement(1)
        self.assertEqual((p.layer, p.x_mm, p.y_mm), (1, 0.0, 0.0))
        v.add_sipm(1, x_mm=500, y_mm=-300)
        self.assertGreaterEqual(v._panel_half, 500.0)
        self.assertGreaterEqual(v._panel_half_y, 300.0)

    def test_add_sipm_dialog_defaults_and_validation(self):
        v = self.view
        v.remove_sipm(9)
        v.remove_sipm(4)
        dialog = v.add_sipm_dialog(1)
        self.addCleanup(dialog.deleteLater)
        layer, channel, x, y = dialog.values()
        self.assertEqual((layer, channel), (1, 4))
        right = max(v.layout.in_layer(1), key=lambda s: (s.x_mm, s.y_mm))
        self.assertEqual((x, y), (right.x_mm + v.pitch_spin.value(), right.y_mm))
        dialog.set_layer(0)
        self.assertEqual(dialog.values()[0], 0)
        self.assertEqual(dialog.values()[2], max(v.layout.in_layer(0), key=lambda s: (s.x_mm, s.y_mm)).x_mm + 10.0)
        dialog.channel_spin.setValue(10)               # used: stays open with a message
        dialog.accept()
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertIn("already used", dialog.message_label.text())
        dialog.channel_spin.setValue(9)
        dialog.accept()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        v.edit_mode = True
        self.assertEqual(v.add_sipm(*dialog.values()), 9)

    def test_add_dialog_offers_layer_one_only_with_two_layers(self):
        v = self.view
        v.rebuild_grid(1, 2, 10.0, 1)
        dialog = v.add_sipm_dialog(1)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.layer_combo.count(), 1)
        v.layers_spin.setValue(2)
        two = v.add_sipm_dialog(1)
        self.addCleanup(two.deleteLater)
        self.assertEqual((two.layer_combo.count(), two.values()[0], two.values()[2:]), (2, 1, (0.0, 0.0)))

    # ------------------------------------------------- buttons and headers --
    def test_generate_and_open_buttons_sit_in_the_replay_row(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QGroupBox
        v = self.view
        self.assertIs(v.open_run_button, v.open_button)
        events_box = next(g for g in v.findChildren(QGroupBox) if g.title() == "Events")
        for button in (v.generate_button, v.open_button):
            self.assertFalse(events_box.isAncestorOf(button))
        for spin in (v.n_spin, v.seed_spin, v.fraction_spin):
            self.assertTrue(events_box.isAncestorOf(spin))
        v.resize(1100, 700)
        v.show()
        _APP.processEvents()

        def pos(w):
            return w.mapTo(v, QPoint(0, 0))
        self.assertEqual(pos(v.generate_button).y(), pos(v.step_back_button).y())
        self.assertLess(pos(v.generate_button).x(), pos(v.open_button).x())
        self.assertLess(pos(v.open_button).x(), pos(v.step_back_button).x())
        v.hide()

    def test_generate_and_open_buttons_obey_edit_mode(self):
        v = self.view
        self.assertTrue(v.generate_button.isEnabled())
        self.assertTrue(v.open_button.isEnabled())      # usable before any events exist
        v.edit_mode = True
        self.assertFalse(v.generate_button.isEnabled())
        self.assertFalse(v.open_button.isEnabled())
        v.edit_mode = False
        self.assertTrue(v.generate_button.isEnabled())
        with unittest.mock.patch.object(muon_view_module.QFileDialog, "getExistingDirectory", return_value=""):
            v.open_button.click()
        v.generate_button.click()
        self.assertEqual(len(v.events), v.n_spin.value())

    def test_plint_headers_are_centre_labelled(self):
        v = self.view
        h = v.plint_table.horizontalHeaderItem
        self.assertEqual(h(1).text().replace("\n", " "), "Centre X (mm)")
        self.assertEqual(h(2).text().replace("\n", " "), "Centre Y (mm)")
        self.assertEqual(h(1).toolTip(), "Centre of the plint in the layer panel, mm, x to the right")
        self.assertEqual(h(2).toolTip(), "Centre of the plint in the layer panel, mm, y upwards")

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

    def test_pedestal_sources_on_recorded_run(self):
        from radioroc.data.muon_types import SiPMPlacement
        fixture = Path(__file__).parent / "fixtures" / "muon_run_ch6_ch32"
        v = self.view
        v.set_layout(DetectorLayout([SiPMPlacement(6, 0, 0, 0), SiPMPlacement(32, 1, 0, 0)]))
        self.assertTrue(v.load_run(fixture), v.status_label.text())
        self.assertEqual(v.pedestal_mode, "auto")
        auto_hits = v.stats()["coincidences"]
        self.assertLess(auto_hits, 12)
        self.assertIn("muon signal", v.pedestal_warning)
        self.assertTrue(v.pedestal_warning_label.isVisibleTo(v))
        self.assertTrue(v.set_pedestals({6: 92, 32: 100}))
        self.assertEqual(v.pedestal_mode, "manual")
        self.assertEqual(v.pedestals, {6: 92.0, 32: 100.0})
        self.assertEqual(v.pedestal_warning, "")
        self.assertEqual(v.stats()["coincidences"], 11)      # ch6 of event 9 is 37 counts, under the threshold
        self.assertIn("ch6 92", v.pedestal_label.text())
        v.threshold_spin.setValue(35)
        self.assertEqual(v.stats()["coincidences"], 12)
        v.set_pedestal_mode("auto")
        self.assertLess(v.stats()["coincidences"], 12)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ped.json"
            v.set_pedestals({6: 92, 32: 100})
            self.assertTrue(v.save_pedestals_to(path))
            v.set_pedestal_mode("auto")
            self.assertTrue(v.load_pedestal_source(path))
            self.assertEqual((v.pedestal_mode, v.pedestals), ("file", {6: 92.0, 32: 100.0}))
            self.assertFalse(v.load_pedestal_source(Path(tmp) / "missing.json"))
            self.assertIn("Could not load pedestals", v.status_label.text())
            self.assertEqual(v.pedestal_mode, "file")
            self.assertTrue(v.load_pedestal_source(fixture))     # a run folder: median of its events
            self.assertEqual(v.pedestals[6], 174.0)
        v.set_pedestals({6: 92})
        self.assertIn("No pedestal for channel", v.pedestal_warning)

    def test_manual_pedestal_dialog(self):
        from radioroc.gui.muon_view import ManualPedestalDialog
        dialog = ManualPedestalDialog([6, 32], {6: 90.0}, self.view)
        self.assertEqual(dialog.values(), {6: 90.0, 32: dialog.all_spin.value()})
        dialog.set_all(77)
        self.assertEqual(dialog.values(), {6: 77.0, 32: 77.0})
        dialog.table.item(0, 1).setText("x")
        with self.assertRaises(ValueError):
            dialog.values()
        dialog.deleteLater()

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
            window.muon_view.rebuild_grid(4, 8, 10.0, 2)
            window.muon_view.set_plint(0, width_mm=400, length_mm=120, thickness_mm=10)
            window.muon_view.set_plint(1, width_mm=300, length_mm=150, thickness_mm=20)
            window.muon_view.add_plint(0, 120, 0, 60, 40, 10)
            window.muon_view.add_sipm(0)
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
