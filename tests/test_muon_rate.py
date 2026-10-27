"""Offline tests for the muon rate (pure module, CLI and Muon page Rate box). Synthetic runs only."""

import contextlib
import csv
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radioroc.data import muon_rate
from radioroc.data.muon_types import DetectorLayout, PlintSpec

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def write_run(directory, *, batches=5, start_batch=0, per_batch=10, accepted=3, batch_step=10.0,
              elapsed=60.0, timestamps=True, append_old_rows=0):
    """Hand-built run: channels 0 (layer 0) and 32 (layer 1); the first `accepted` events of each batch hit both."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for b in range(append_old_rows):
        rows += [{"batch": b, "event": 0, "channel": ch, "hg": 100.0, "lg": 10.0} for ch in (0, 32)]
    for b in range(start_batch, start_batch + batches):
        for e in range(per_batch):
            hg = 400.0 if e < accepted else 100.0
            rows += [{"batch": b, "event": e, "channel": ch, "hg": hg, "lg": 10.0} for ch in (0, 32)]
    with (directory / "events.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["batch", "event", "channel", "hg", "lg"])
        writer.writeheader()
        writer.writerows(rows)
    received = [{"batch": start_batch + i, "received_at": (T0 + timedelta(seconds=batch_step * i)).isoformat()}
                for i in range(batches)] if timestamps else []
    manifest = {
        "schema_version": 1, "status": "completed", "execution_mode": "simulation",
        "operation": {"acquisition": {"channels": [0, 32], "batches": batches, "start_batch": start_batch}},
        "total_points": batches, "completed_points": batches,
        "cleanup": {"status": "restored", "errors": []}, "persistence_errors": [],
        "created_at": (T0 - timedelta(seconds=5)).isoformat(),
        "finished_at": (T0 - timedelta(seconds=5) + timedelta(seconds=elapsed)).isoformat(),
        "elapsed_seconds": elapsed, "batch_received_at": received,
        "batch_counts": [{"batch": start_batch + i, "requested": per_batch, "received": per_batch,
                          "mismatch": False} for i in range(batches)],
    }
    (directory / "metadata.json").write_text(json.dumps(manifest))
    return directory


class MuonRateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.layout = DetectorLayout.grid(4, 8, 10.0, layers=2)

    def analyse(self, path):
        return muon_rate.analyse_run(path, self.layout, 40.0)

    def test_both_time_bases(self):
        run = write_run(self.root / "run")
        timing = muon_rate.read_run_timing(run)
        self.assertEqual(timing.elapsed_seconds, 60.0)
        self.assertEqual(sorted(timing.batch_times), [0, 1, 2, 3, 4])
        self.assertEqual(timing.events_per_batch, {b: 10 for b in range(5)})
        result = self.analyse(run).result
        self.assertEqual((result.accepted, result.trigger_events), (15, 50))
        self.assertAlmostEqual(result.accepted_fraction, 0.3)
        self.assertAlmostEqual(result.wall_rate_per_min, 15.0)          # 15 / 60 s
        self.assertAlmostEqual(result.wall_sigma_per_min, 60 * math.sqrt(15) / 60.0)
        self.assertEqual(result.batch_seconds, 40.0)
        self.assertAlmostEqual(result.batch_rate_per_min, 18.0)         # 12 after the first batch / 40 s
        self.assertAlmostEqual(result.batch_sigma_per_min, 60 * math.sqrt(12) / 40.0)
        self.assertEqual(result.basis, "batch")
        self.assertEqual(result.rate_per_min, result.batch_rate_per_min)

    def test_fallback_with_fewer_than_two_batches(self):
        run = write_run(self.root / "one", batches=1)
        result = self.analyse(run).result
        self.assertEqual(result.basis, "wall")
        self.assertIsNone(result.batch_rate_per_min)
        self.assertAlmostEqual(result.rate_per_min, 3.0)
        self.assertTrue(any("wall-clock" in w for w in result.warnings))

    def test_fallback_without_timestamps(self):
        result = self.analyse(write_run(self.root / "nots", timestamps=False)).result
        self.assertEqual(result.basis, "wall")
        self.assertTrue(result.warnings)

    def test_multi_segment_uses_current_segment_and_warns(self):
        run = write_run(self.root / "seg", batches=3, start_batch=2, append_old_rows=2)
        timing = muon_rate.read_run_timing(run)
        self.assertEqual(sorted(timing.events_per_batch), [2, 3, 4])
        self.assertTrue(any("earlier append segments" in w for w in timing.warnings))
        result = self.analyse(run).result
        self.assertEqual(result.trigger_events, 30)          # old batches 0, 1 excluded
        self.assertTrue(any("earlier append segments" in w for w in result.warnings))

    def test_background_subtraction(self):
        signal = muon_rate.compute_rate(120, 400, 60.0, batch_seconds=50.0, accepted_after_first=100,
                                        trigger_after_first=350)
        background = muon_rate.compute_rate(9, 300, 60.0, batch_seconds=45.0, accepted_after_first=9,
                                            trigger_after_first=250)
        net = muon_rate.subtract_background(signal, background)
        self.assertAlmostEqual(net.rate_per_min, 120.0 - 12.0)
        self.assertAlmostEqual(net.sigma_per_min, math.hypot(signal.sigma_per_min, background.sigma_per_min))

    def test_area_overlap(self):
        layout = DetectorLayout.grid(1, 2, 10.0, layers=2)
        layout.plints = [PlintSpec(0, 0, 0, 100, 50), PlintSpec(1, 20, 0, 100, 50)]
        self.assertAlmostEqual(muon_rate.coincidence_area_cm2(layout), 80 * 50 / 100.0)
        layout.plints = [PlintSpec(0, 0, 0, 100, 50), PlintSpec(1, 500, 0, 100, 50)]
        self.assertIsNone(muon_rate.coincidence_area_cm2(layout))
        one = DetectorLayout.grid(1, 2, 10.0, layers=1)
        one.plints = [PlintSpec(0, 0, 0, 100, 50)]
        self.assertAlmostEqual(muon_rate.coincidence_area_cm2(one), 50.0)
        self.assertIsNotNone(muon_rate.coincidence_area_cm2(self.layout))
        flux, sigma = muon_rate.flux_per_cm2(10.0, 1.0, 50.0)
        self.assertAlmostEqual((flux, sigma), (0.2, 0.02))
        self.assertIsNone(muon_rate.flux_per_cm2(10.0, 1.0, 0))

    def test_block_drift_flag(self):
        times = {b: T0 + timedelta(seconds=10 * b) for b in range(9)}
        events = {b: 20 for b in range(9)}
        steady = muon_rate.block_rates(times, events, {b: 5 for b in range(9)}, k=4)
        self.assertEqual(len(steady.blocks), 4)
        self.assertFalse(steady.drift)
        self.assertEqual(steady.dof, 3)
        drifting = muon_rate.block_rates(times, events, {b: (1 if b < 5 else 12) for b in range(9)}, k=4)
        self.assertTrue(drifting.drift)
        self.assertGreater(drifting.chi2_per_dof, 2.0)
        self.assertEqual(muon_rate.block_rates({0: T0}, {0: 5}, {0: 1}).blocks, ())

    def test_summary_text(self):
        run_dir = write_run(self.root / "run")
        bg_dir = write_run(self.root / "bg", accepted=1)
        run, bg = self.analyse(run_dir), self.analyse(bg_dir)
        net = muon_rate.subtract_background(run.result, bg.result)
        text = muon_rate.format_summary(run.timing, run.result, blocks=run.blocks, background=bg.result,
                                        background_timing=bg.timing, net=net, area_cm2=40.0,
                                        settings=["Detection threshold: 40 counts"])
        for needle in (str(run_dir), "Trigger events: 50", "Accepted", "Wall-clock time", "Batch-completion time",
                       "18.00 ±", "Background", "Net rate", "Coincidence area: 40.00 cm2", "Flux (net)",
                       "Blocks", "Detection threshold: 40 counts"):
            self.assertIn(needle, text)

    def test_is_inside(self):
        self.assertTrue(muon_rate.is_inside(self.root / "run" / "s.txt", self.root / "run"))
        self.assertFalse(muon_rate.is_inside(self.root / "other.txt", self.root / "run"))

    def test_cli_prints_summary_and_settings(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        self.addCleanup(sys.path.pop, 0)
        import radioroc_muon_rate
        out, err = io.StringIO(), io.StringIO()
        run, bg = write_run(self.root / "run"), write_run(self.root / "bg", accepted=1)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = radioroc_muon_rate.main([str(run), "--background", str(bg), "--threshold", "40",
                                            "--area-cm2", "20"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("Effective settings", err.getvalue())
        self.assertIn("Net rate", out.getvalue())
        self.assertIn("Flux (net)", out.getvalue())


if GUI_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from radioroc.gui.muon_view import MuonView

    _APP = QApplication.instance() or QApplication([])


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 is not installed")
class MuonViewRateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.view = MuonView()
        self.view.timer.stop()
        self.addCleanup(self.view.deleteLater)

    def test_simulated_events_have_no_rate(self):
        self.view.generate_events(20, 1, 0.8)
        self.assertIn("saved run", self.view.rate_label.text())
        self.assertEqual(self.view.rate_summary_text(), "")

    def test_loading_a_run_fills_rate_box_and_background_gives_net(self):
        v = self.view
        run = write_run(self.root / "run")
        bg = write_run(self.root / "bg", accepted=1)
        self.assertTrue(v.load_run(run))
        self.assertIn("Rate: 18.00", v.rate_label.text())
        self.assertIn("Wall clock: 15.00", v.rate_label.text())
        self.assertGreater(v.area_spin.value(), 0)
        self.assertTrue(v.load_background(bg))
        self.assertIn("Net rate", v.background_label.text())
        self.assertIn("Flux (net)", v.flux_label.text())
        v.threshold_spin.setValue(1000)       # nothing above threshold: rate follows the analysis
        self.assertIn("Rate: 0.00", v.rate_label.text())
        v.threshold_spin.setValue(40)
        self.assertIn("Rate: 18.00", v.rate_label.text())
        text = v.rate_summary_text()
        self.assertIn("Net rate", text)
        self.assertTrue(v.copy_summary())
        self.assertEqual(QApplication.clipboard().text(), text)
        self.assertFalse(v.save_summary_to(run / "summary.txt"))
        self.assertTrue(v.save_summary_to(self.root / "out" / "summary.txt"))


if __name__ == "__main__":
    unittest.main()
