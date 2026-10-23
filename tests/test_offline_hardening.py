import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from radioroc.application.acquisition import AcquisitionJobConfig
from radioroc.application.hold_scan import HoldScanJobConfig
from radioroc_client import AcquisitionConfig, HoldScanConfig

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
MESSAGE = "2-channel coincidence needs two different channels, but both trigger channels are 4."


def _acq(**kw):
    base = dict(channels=[4], trigger_channel=4, batches=1, acquisitions_per_batch=1,
                trigger_type=1, trigger_source=3, trigger_source_2=3, trigger_channel_2=4,
                out_dir=Path("x"))
    base.update(kw)
    return AcquisitionConfig(**base)


class CoincidenceValidationTests(unittest.TestCase):
    def test_acquisition_rejects_same_channel_coincidence(self):
        with self.assertRaisesRegex(ValueError, MESSAGE) as ctx:
            AcquisitionJobConfig(_acq()).validate()
        self.assertIn('choose Trigger type "Simple trigger"', str(ctx.exception))

    def test_acquisition_accepts_distinct_channels_and_simple_trigger(self):
        AcquisitionJobConfig(_acq(channels=[4, 5], trigger_channel_2=5)).validate()
        AcquisitionJobConfig(_acq(trigger_type=0)).validate()

    def test_hold_scan_rejects_same_channel_coincidence(self):
        scan = HoldScanConfig(mode="external", channels=[4], trigger_channel=4, hold_min=0,
                              hold_max=0, hold_step=5, trigger_type=1, trigger_source=3,
                              trigger_source_2=3, trigger_channel_2=4, out_dir=Path("x"))
        with self.assertRaisesRegex(ValueError, MESSAGE):
            HoldScanJobConfig(scan).validate()


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.gui.calibration_selection import CalibrationSelection
        self.sel = CalibrationSelection((6, 32))

    def _acquisition(self, **kw):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        w = AcquisitionWindow(**kw)
        self.addCleanup(w.close)
        return w

    def test_hold_delay_default_is_30(self):
        from radioroc.gui.calibration_selection import DEFAULT_HOLD_DELAY_NS
        self.assertEqual(DEFAULT_HOLD_DELAY_NS, 30)
        self.assertEqual(self.sel.hold_delay_ns, 30)
        self.assertEqual(self._acquisition().hold_delay_ns.value(), 30)
        self.assertEqual(self._acquisition(selection=self.sel).hold_delay_ns.value(), 30)

    def test_long_hold_delay_note_only_when_self_triggered(self):
        w = self._acquisition()
        w.hold_delay_ns.setValue(525)
        w.external_trigger.setChecked(False)
        self.assertIsNotNone(w.preview())
        self.assertIn("Hold delay 525 ns is long for a self-triggered run", w.status.text())
        w.hold_delay_ns.setValue(30)
        w.preview()
        self.assertNotIn("is long", w.status.text())
        w.hold_delay_ns.setValue(525)
        w.external_trigger.setChecked(True)
        w.preview()
        self.assertNotIn("is long", w.status.text())

    def test_preview_shows_same_channel_coincidence_message(self):
        sel = type(self.sel)((9,))
        w = self._acquisition(selection=sel)
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2), (9, 9))
        w.trigger_type.setCurrentIndex(1)
        w.trigger_source_2.setCurrentIndex(3)  # GUI default is NORT1 (not a per-channel coincidence)
        self.assertIsNone(w.preview())
        self.assertIn("Preview failed: 2-channel coincidence needs two different channels, "
                      "but both trigger channels are 9.", w.status.text())
        sel.set_channels([9, 10])
        self.assertIsNotNone(w.preview())

    def test_reopening_saved_results_carries_channels(self):
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.threshold_window import ThresholdWindow
        cases = [(ThresholdWindow, "radioroc.gui.threshold_window.read_threshold_run"),
                 (HoldScanWindow, "radioroc.gui.hold_scan_window.read_hold_run"),
                 (ScurveWindow, "radioroc.gui.scurve_window.read_scurve_run")]
        for cls, target in cases:
            for manifest, expected in (({"operation": {"scan": {"channels": [20, 21]}}}, [20, 21]),
                                       ({"operation": {}}, [6, 32]), ({}, [6, 32])):
                sel = type(self.sel)((6, 32))
                w = cls(selection=sel)
                saved = SimpleNamespace(execution_mode="simulation", status="completed",
                                        directory=Path("d"), rows=[], x_name="x", warnings=[],
                                        manifest=manifest)
                with mock.patch(target, return_value=saved), \
                        mock.patch.object(cls, "_plot", create=True):
                    w.open_saved(Path("d"))
                self.assertEqual(sel.channels(), expected, (cls.__name__, manifest))
                w.close()

    def test_reopening_saved_run_uses_current_segment_channels(self):
        w = self._acquisition(selection=self.sel)
        saved = SimpleNamespace(execution_mode="simulation", status="completed",
                                directory=Path("d"), rows=[], current_segment_rows=[],
                                channels=[12, 13], manifest={}, warnings=[])
        with mock.patch("radioroc.gui.acquisition_window.read_acquisition_run", return_value=saved):
            w.open_saved(Path("d"))
        self.assertEqual(self.sel.channels(), [12, 13])
        saved.channels = []
        with mock.patch("radioroc.gui.acquisition_window.read_acquisition_run", return_value=saved):
            w.open_saved(Path("d"))
        self.assertEqual(self.sel.channels(), [12, 13])

    def test_typing_replaces_spin_value(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w = self._acquisition()
        w.show()
        spin = w.acquisitions_per_batch  # 50; appending "7" would give 507 > 255 and be rejected
        w.activateWindow()
        QTest.qWait(100)
        spin.setFocus(Qt.TabFocusReason)
        QTest.qWait(30)
        self.assertEqual(spin.lineEdit().selectedText(), "50")
        QTest.keyClicks(spin.lineEdit(), "7")
        self.assertEqual(spin.value(), 7)


if __name__ == "__main__":
    unittest.main()
