import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if GUI_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from radioroc.gui.calibration_file_bar import CalibrationFileBar
    from radioroc.gui.calibration_selection import CalibrationSelection

    _APP = QApplication.instance() or QApplication([])


class FakeWorker:
    def __init__(self, state="connected"):
        self.state = state
        self.ops = []

    def snapshot(self):
        return SimpleNamespace(state=self.state)

    def apply_channel_config(self, op):
        self.ops.append(op)


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 is not installed")
class CalibrationFileBarTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _autocal_dir(self):
        run = self.tmp / "runs" / "hardware" / "r1"
        run.mkdir(parents=True)
        (run / "autocalibration_metadata.json").write_text(json.dumps({
            "status": "completed", "calibration_status": "verified", "operation": {"t1": True},
            "calibration_after": {"4": 31, "5": 28}}))
        return run

    def _bar(self, worker=None, window=None, channels=(4, 5)):
        bar = CalibrationFileBar(CalibrationSelection(channels), worker or FakeWorker(), window,
                                 runs_root=self.tmp / "runs")
        return bar

    def test_round_trip_and_no_chip_write_on_load(self):
        worker = FakeWorker()
        bar = self._bar(worker, SimpleNamespace(_active_directory=self._autocal_dir()),
                        channels=(7, 9, 12))
        bar.selection.set_trigger_channels(9, 12)
        bar.operating_threshold.setValue(600)
        bar.bias_text.setText("54.5")
        bar.note_edit.setText("cold run")
        path = self.tmp / "c.json"
        self.assertTrue(bar.save_to(path))
        self.assertIn("2 channel trims", bar.status_label.text())

        other = self._bar(worker)
        other._confirm_reapply = lambda text: False
        self.assertTrue(other.load_from(path))
        self.assertEqual(other.selection.channels(), [7, 9, 12])
        self.assertEqual((other.selection.trigger_channel, other.selection.trigger_channel_2), (9, 12))
        self.assertFalse(other.selection.auto_triggers)
        self.assertEqual(other.operating_threshold.value(), 600)
        self.assertEqual((other.bias_text.text(), other.note_edit.text()), ("54.5", "cold run"))
        self.assertEqual(worker.ops, [])
        self.assertIn("not re-applied", other.status_label.text())

    def test_pedestals_saved_and_restored(self):
        from radioroc.data.pedestals import compute_pedestals
        ps = compute_pedestals([{"channel": 6, "hg": 90 + i, "lg": 80} for i in range(6)])
        bar = self._bar()
        bar.selection.pedestals = ps
        path = self.tmp / "c.json"
        self.assertTrue(bar.save_to(path))
        self.assertEqual(json.loads(path.read_text())["pedestals"], ps.to_dict())
        other = self._bar()
        seen = []
        other.selection.pedestals_changed.connect(seen.append)
        self.assertTrue(other.load_from(path))
        self.assertEqual(other.selection.pedestals, ps)
        self.assertEqual(seen, [ps])
        # an old file without the key still loads and leaves pedestals alone
        data = json.loads(path.read_text())
        del data["pedestals"]
        path.write_text(json.dumps(data))
        third = self._bar()
        self.assertTrue(third.load_from(path))
        self.assertIsNone(third.selection.pedestals)

    def test_reapply_after_confirmation(self):
        worker = FakeWorker()
        bar = self._bar(worker, SimpleNamespace(_active_directory=self._autocal_dir()))
        path = self.tmp / "c.json"
        bar.save_to(path)
        bar._confirm_reapply = lambda text: True
        bar.load_from(path)
        self.assertEqual(len(worker.ops), 1)
        self.assertEqual(worker.ops[0].t1_calibration_dac_values, {4: 31, 5: 28})

    def test_no_reapply_when_disconnected(self):
        worker = FakeWorker(state="disconnected")
        bar = self._bar(worker, SimpleNamespace(_active_directory=self._autocal_dir()))
        path = self.tmp / "c.json"
        bar.save_to(path)
        bar._confirm_reapply = lambda text: self.fail("asked")
        bar.load_from(path)
        self.assertEqual(worker.ops, [])
        self.assertIn("Connect the board", bar.status_label.text())

    def test_save_without_trims(self):
        bar = self._bar()
        path = self.tmp / "c.json"
        self.assertTrue(bar.save_to(path))
        self.assertIn("WITHOUT trims", bar.status_label.text())
        self.assertIsNone(json.loads(path.read_text())["autocalibration"])
        bar.load_from(path)
        self.assertIn("no trims", bar.status_label.text())

    def test_bad_file_does_not_crash_or_change(self):
        bar = self._bar()
        bad = self.tmp / "bad.json"
        bad.write_text("garbage")
        self.assertFalse(bar.load_from(bad))
        self.assertIn("Nothing was changed", bar.status_label.text())
        self.assertEqual(bar.selection.channels(), [4, 5])
        bad.write_text(json.dumps({"schema_version": 9}))
        self.assertFalse(bar.load_from(bad))
        self.assertIn("version", bar.status_label.text())

    def test_defaults(self):
        bar = self._bar()
        self.assertEqual(bar.operating_threshold.value(), 540)
        self.assertEqual(bar.save_button.text(), "Save calibration…")


    def test_hold_delay_is_saved_loaded_and_shared(self):
        bar = self._bar()
        bar.hold_delay.setValue(525)
        self.assertEqual(bar.selection.hold_delay_ns, 525)
        path = self.tmp / "hold.json"
        self.assertTrue(bar.save_to(path))
        self.assertEqual(json.loads(path.read_text())["hold_scan"], {"hold_delay_ns": 525})
        bar.selection.set_hold_delay_ns(100)
        self.assertEqual(bar.hold_delay.value(), 100)
        self.assertTrue(bar.load_from(path))
        self.assertEqual(bar.selection.hold_delay_ns, 525)
        self.assertEqual(bar.hold_delay.value(), 525)

    def test_trigger_gain_and_threshold_are_shared_saved_and_loaded(self):
        bar = self._bar()
        self.assertEqual(bar.trigger_gain.value(), 1)
        self.assertEqual(bar.trigger_gain.accessibleName(), "Trigger gain (paT)")
        bar.trigger_gain.setValue(8)
        bar.operating_threshold.setValue(612)
        self.assertEqual(bar.selection.trigger_gain, 8)
        self.assertEqual(bar.selection.operating_threshold, 612)
        path = self.tmp / "gain.json"
        self.assertTrue(bar.save_to(path))
        self.assertEqual(json.loads(path.read_text())["trigger_gain_code"], 8)
        bar.selection.set_trigger_gain(2)
        bar.selection.set_operating_threshold(100)
        self.assertEqual((bar.trigger_gain.value(), bar.operating_threshold.value()), (2, 100))
        self.assertTrue(bar.load_from(path))
        self.assertEqual((bar.trigger_gain.value(), bar.operating_threshold.value()), (8, 612))

    def test_old_file_without_gain_leaves_gain_unchanged(self):
        bar = self._bar()
        path = self.tmp / "old.json"
        bar.save_to(path)
        data = json.loads(path.read_text())
        del data["trigger_gain_code"]
        path.write_text(json.dumps(data))
        bar.selection.set_trigger_gain(5)
        self.assertTrue(bar.load_from(path))
        self.assertEqual(bar.selection.trigger_gain, 5)

    def test_bias_and_note_are_asked_by_save_button_only(self):
        from unittest import mock
        bar = self._bar()
        bar.bias_text.setText("54")
        with mock.patch("radioroc.gui.calibration_file_bar.QFileDialog.getSaveFileName",
                        return_value=(str(self.tmp / "d.json"), "")):
            bar._ask_bias_and_note = lambda: False
            bar._choose_save()
            self.assertFalse((self.tmp / "d.json").exists())
            bar._ask_bias_and_note = lambda: True
            bar._choose_save()
            self.assertTrue((self.tmp / "d.json").exists())
        self.assertTrue(bar.bias_text.isHidden() and bar.note_edit.isHidden())

    def test_bad_hold_delay_in_file_is_refused(self):
        bar = self._bar()
        path = self.tmp / "bad_hold.json"
        self.assertTrue(bar.save_to(path))
        data = json.loads(path.read_text())
        data["hold_scan"] = {"hold_delay_ns": -5}
        path.write_text(json.dumps(data))
        bar.selection.set_hold_delay_ns(300)
        self.assertFalse(bar.load_from(path))
        self.assertEqual(bar.selection.hold_delay_ns, 300)


if __name__ == "__main__":
    unittest.main()
