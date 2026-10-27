"""Offline tests: saved pedestals flow from the Calibration page into muon runs (synthetic data only)."""

import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from test_muon_rate import write_run

from radioroc.data import pedestal_flow

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _install_stub():
    """Local stand-in for radioroc.data.pedestals (test-only) when the real module is not installed yet."""
    mod = types.ModuleType("radioroc.data.pedestals")
    mod.PEDESTALS_FILENAME = "pedestals.json"

    @dataclasses.dataclass
    class ChannelPedestal:
        channel: int
        hg_median: float
        hg_sd: float = 1.0
        lg_median: float = 10.0
        lg_sd: float = 1.0
        n: int = 100

    @dataclasses.dataclass
    class PedestalSet:
        channels: dict
        created_at: str = ""
        source_run: object = None
        settings: dict = dataclasses.field(default_factory=dict)

        def hg(self):
            return {c: p.hg_median for c, p in self.channels.items()}

        def lg(self):
            return {c: p.lg_median for c, p in self.channels.items()}

        def to_dict(self):
            return {"created_at": self.created_at, "channels": {str(c): dataclasses.asdict(p)
                                                                 for c, p in self.channels.items()}}

        @classmethod
        def from_dict(cls, d):
            return cls({int(c): ChannelPedestal(**p) for c, p in d["channels"].items()}, d.get("created_at", ""))

    def save_pedestals_json(path, ps):
        Path(path).write_text(json.dumps(ps.to_dict()))
        return Path(path)

    def load_pedestals_json(path):
        return PedestalSet.from_dict(json.loads(Path(path).read_text()))

    def find_pedestals_for_run(run_dir):
        p = Path(run_dir) / "pedestals.json"
        return load_pedestals_json(p) if p.is_file() else None

    for fn in (ChannelPedestal, PedestalSet, save_pedestals_json, load_pedestals_json, find_pedestals_for_run):
        setattr(mod, fn.__name__, fn)
    sys.modules["radioroc.data.pedestals"] = mod
    return mod


try:
    from radioroc.data import pedestals as ped_mod
except ImportError:
    ped_mod = _install_stub()


def make_set(values, created_at="2026-01-01T10:00:00"):
    return ped_mod.PedestalSet(
        channels={c: ped_mod.ChannelPedestal(channel=c, hg_median=v, hg_sd=1.0, lg_median=10.0, lg_sd=1.0, n=100)
                  for c, v in values.items()},
        created_at=created_at, source_run=None, settings={})


class PedestalFlowHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_status_text(self):
        text, warn = pedestal_flow.pedestal_status_text(None)
        self.assertTrue(warn)
        self.assertIn("run the Pedestals step on the Calibration page", text)
        text, warn = pedestal_flow.pedestal_status_text(make_set({6: 95.0, 32: 107.5}), [6, 32])
        self.assertFalse(warn)
        self.assertIn("ch6 95.0, ch32 107.5 (HG, from pedestal run 2026-01-01T10:00:00)", text)
        text, warn = pedestal_flow.pedestal_status_text(make_set({6: 95.0}), [6, 7])
        self.assertTrue(warn)
        self.assertIn("7", text)

    def test_write_into_new_run_only(self):
        run = write_run(self.root / "run")
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        ok, _ = pedestal_flow.write_run_pedestals(run, make_set({0: 95.0, 32: 100.0}), [0, 32])
        self.assertTrue(ok)
        self.assertEqual(ped_mod.find_pedestals_for_run(run).hg(), {0: 95.0, 32: 100.0})
        for name, data in before.items():
            self.assertEqual((run / name).read_bytes(), data)
        # never overwrite
        ok, msg = pedestal_flow.write_run_pedestals(run, make_set({0: 1.0, 32: 2.0}), [0, 32])
        self.assertFalse(ok)
        self.assertIn("already exists", msg)
        self.assertEqual(ped_mod.find_pedestals_for_run(run).hg()[0], 95.0)

    def test_not_written_when_channels_not_covered_or_absent(self):
        run = write_run(self.root / "run")
        ok, msg = pedestal_flow.write_run_pedestals(run, make_set({0: 95.0}), [0, 32])
        self.assertFalse(ok)
        self.assertIn("32", msg)
        self.assertFalse((run / "pedestals.json").exists())
        self.assertFalse(pedestal_flow.write_run_pedestals(run, None, [0])[0])


class CliDefaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scripts = str(Path(__file__).resolve().parents[1] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    def run_cli(self, *argv):
        import radioroc_muon_rate
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = radioroc_muon_rate.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_uses_saved_pedestals(self):
        run = write_run(self.root / "run")
        pedestal_flow.write_run_pedestals(run, make_set({0: 95.0, 32: 100.0}), [0, 32])
        code, out, err = self.run_cli(str(run))
        self.assertEqual(code, 0, err)
        self.assertIn("saved with the run", out)
        self.assertNotIn("WARNING", err)

    def test_auto_warns_without_saved_pedestals(self):
        run = write_run(self.root / "run")
        code, out, err = self.run_cli(str(run))
        self.assertEqual(code, 0, err)
        self.assertIn("run the Pedestals step", err)
        self.assertIn("median of this run", out)

    def test_explicit_auto_ignores_saved(self):
        run = write_run(self.root / "run")
        pedestal_flow.write_run_pedestals(run, make_set({0: 95.0, 32: 100.0}), [0, 32])
        code, out, err = self.run_cli(str(run), "--pedestals", "auto")
        self.assertEqual(code, 0, err)
        self.assertNotIn("saved with the run", out)


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_muon_load_run_picks_saved_pedestals(self):
        from radioroc.gui.muon_view import MuonView
        view = MuonView()
        self.addCleanup(view.deleteLater)
        run = write_run(self.root / "run")
        pedestal_flow.write_run_pedestals(run, make_set({0: 95.0, 32: 100.0}), [0, 32])
        self.assertTrue(view.load_run(run))
        self.assertEqual(view.pedestal_mode, "file")
        self.assertEqual(view.pedestals[0], 95.0)
        self.assertIn("from pedestal run (2026-01-01T10:00:00)", view.pedestal_label.text())
        self.assertIn("Pedestals: from pedestal run 2026-01-01T10:00:00", view.rate_label.text())
        self.assertIn("Pedestals: from pedestal run", view.rate_summary_text())
        # a following run without pedestals falls back to auto
        plain = write_run(self.root / "plain")
        self.assertTrue(view.load_run(plain))
        self.assertEqual(view.pedestal_mode, "auto")
        self.assertIn("median of this run", view.rate_label.text())

    def test_muon_ignores_saved_pedestals_not_covering_data(self):
        from radioroc.gui.muon_view import MuonView
        view = MuonView()
        self.addCleanup(view.deleteLater)
        run = write_run(self.root / "run")
        pedestal_flow.write_run_pedestals(run, make_set({0: 95.0, 32: 100.0}), [0, 32])
        (run / "pedestals.json").write_text(json.dumps(make_set({0: 95.0}).to_dict()))
        view.load_run(run)
        self.assertEqual(view.pedestal_mode, "auto")

    def test_acquisition_status_line(self):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        from radioroc.gui.calibration_selection import CalibrationSelection
        selection = CalibrationSelection()
        window = AcquisitionWindow(selection=selection)
        self.addCleanup(window.deleteLater)
        label = window.pedestal_status_label
        self.assertIn("none yet, run the Pedestals step on the Calibration page", label.text())
        if not hasattr(selection, "pedestals_changed"):
            self.skipTest("CalibrationSelection.pedestals not implemented yet")
        selection.set_pedestals(make_set({6: 95.0, 32: 107.5}))
        self.assertIn("ch6 95.0, ch32 107.5", label.text())

    def test_acquisition_writes_pedestals_helper(self):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        from radioroc.gui.calibration_selection import CalibrationSelection
        selection = CalibrationSelection()
        selection.pedestals = make_set({0: 95.0, 32: 100.0})
        window = AcquisitionWindow(selection=selection)
        self.addCleanup(window.deleteLater)
        run = write_run(self.root / "run")
        self.assertTrue(window._save_run_pedestals(run, (0, 32))[0])
        self.assertTrue((run / "pedestals.json").is_file())
        run2 = write_run(self.root / "run2")
        self.assertFalse(window._save_run_pedestals(run2, (0, 5))[0])
        self.assertFalse((run2 / "pedestals.json").exists())


if __name__ == "__main__":
    unittest.main()
