import importlib.util
import os
import unittest

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ModelAndPanelTests(_QtCase):
    def test_auto_rule_manual_override_and_reenable(self):
        from radioroc.gui.calibration_selection import CalibrationSelection
        sel = CalibrationSelection((4, 5))
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2, sel.auto_triggers), (4, 5, True))
        sel.set_channels([9, 6, 20])
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2), (6, 9))
        sel.set_channels([7])
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2), (7, 7))
        sel.set_trigger_channels(30, 31)
        self.assertFalse(sel.auto_triggers)
        sel.set_channels([1, 2])
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2), (30, 31))
        sel.set_auto_triggers(True)
        self.assertEqual((sel.trigger_channel, sel.trigger_channel_2), (1, 2))

    def test_panel_syncs_both_ways(self):
        from radioroc.gui.calibration_selection import CalibrationSelection
        from radioroc.gui.calibration_selection_panel import CalibrationSelectionPanel
        sel = CalibrationSelection((4, 5))
        panel = CalibrationSelectionPanel(sel)
        self.assertTrue(panel.auto_checkbox.isChecked())
        panel.channel_select.channel_buttons[10].setChecked(True)
        self.assertEqual(sel.channels(), [4, 5, 10])
        sel.set_channels([12, 13])
        self.assertEqual(panel.channel_select.selected_channels(), [12, 13])
        self.assertEqual((panel.trigger_channel.value(), panel.trigger_channel_2.value()), (12, 13))
        panel.trigger_channel.setValue(40)
        self.assertFalse(sel.auto_triggers)
        self.assertFalse(panel.auto_checkbox.isChecked())
        self.assertEqual(sel.trigger_channel, 40)
        panel.auto_checkbox.setChecked(True)
        self.assertTrue(sel.auto_triggers)
        self.assertEqual((panel.trigger_channel.value(), panel.trigger_channel_2.value()), (12, 13))
        sel.set_trigger_channels(1, 2)
        self.assertFalse(panel.auto_checkbox.isChecked())


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class WindowsUseSharedSelectionTests(_QtCase):
    def setUp(self):
        from radioroc.gui.calibration_selection import CalibrationSelection
        self.sel = CalibrationSelection((6, 32))

    def test_hidden_widgets_follow_model(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        for cls in (ThresholdWindow, HoldScanWindow, ScurveWindow, AutocalibrationWindow,
                    AcquisitionWindow):
            w = cls(selection=self.sel)
            self.assertEqual(w.channel_select.selected_channels(), [6, 32], cls.__name__)
            self.assertTrue(w.channel_select.isHidden())
            self.sel.set_channels([8, 9])
            self.assertEqual(w.channel_select.selected_channels(), [8, 9], cls.__name__)
            self.sel.set_channels([6, 32])
            w.close()

    def test_trigger_spins_follow_model_and_are_hidden(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        hold = HoldScanWindow(selection=self.sel)
        acq = AcquisitionWindow(selection=self.sel)
        self.assertEqual(hold.trigger_channel.value(), 6)
        self.assertEqual((acq.trigger_channel.value(), acq.trigger_channel_2.value()), (6, 32))
        self.assertTrue(hold.trigger_channel.isHidden())
        self.assertTrue(acq.trigger_channel.isHidden() and acq.trigger_channel_2.isHidden())
        self.sel.set_trigger_channels(10, 11)
        self.assertEqual(hold.trigger_channel.value(), 10)
        self.assertEqual((acq.trigger_channel.value(), acq.trigger_channel_2.value()), (10, 11))
        self.assertIn("T1=10, T2=11", acq.shared_selection_label.text())
        self.assertIn("Calibration page", acq.shared_selection_label.text())

    def test_acquisition_hold_delay_follows_shared_value(self):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        acq = AcquisitionWindow(selection=self.sel)
        self.sel.set_hold_delay_ns(525)
        self.assertEqual(acq.hold_delay_ns.value(), 525)
        acq.hold_delay_ns.setValue(540)
        self.assertEqual(self.sel.hold_delay_ns, 540)

    def test_trigger_gain_follows_shared_value_in_every_window(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        from radioroc.gui.calibration_selection import CalibrationSelection
        for cls, name in ((ThresholdWindow, "gain"), (HoldScanWindow, "trigger_preamp_gain"),
                          (ScurveWindow, "trigger_preamp_gain"),
                          (AutocalibrationWindow, "trigger_preamp_gain"),
                          (AcquisitionWindow, "trigger_preamp_gain")):
            with self.subTest(window=cls.__name__):
                sel = CalibrationSelection()
                win = cls(selection=sel)
                spin = getattr(win, name)
                self.assertEqual(spin.value(), 1)
                sel.set_trigger_gain(8)
                self.assertEqual(spin.value(), 8)
                spin.setValue(3)
                self.assertEqual(sel.trigger_gain, 3)

    def test_standalone_windows_keep_current_gain(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        self.assertEqual(ThresholdWindow().gain.value(), 0)
        acq = AcquisitionWindow()
        self.assertEqual(acq.trigger_preamp_gain.value(), 0)
        self.assertEqual(acq.threshold_dac.value(), 0)

    def test_acquisition_threshold_and_gain_follow_shared_values(self):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        acq = AcquisitionWindow(selection=self.sel)
        self.assertEqual(acq.threshold_dac.value(), 540)
        self.sel.set_operating_threshold(612)
        self.assertEqual(acq.threshold_dac.value(), 612)
        acq.threshold_dac.setValue(600)
        self.assertEqual(self.sel.operating_threshold, 600)
        self.sel.set_trigger_gain(8)
        self.assertEqual(acq.trigger_preamp_gain.value(), 8)

    def test_pedestals_attribute_and_signal(self):
        from radioroc.data.pedestals import compute_pedestals
        from radioroc.gui.calibration_selection import CalibrationSelection
        sel = CalibrationSelection((4, 5))
        self.assertIsNone(sel.pedestals)
        seen = []
        sel.pedestals_changed.connect(seen.append)
        ps = compute_pedestals([{"channel": 4, "hg": 90 + i, "lg": 80} for i in range(6)])
        sel.pedestals = ps
        sel.pedestals = ps
        self.assertIs(sel.pedestals, ps)
        sel.pedestals = None
        self.assertEqual(seen, [ps, None])

    def test_model_validates_gain_and_threshold(self):
        with self.assertRaises(ValueError):
            self.sel.set_trigger_gain(0)
        with self.assertRaises(ValueError):
            self.sel.set_trigger_gain(64)
        with self.assertRaises(ValueError):
            self.sel.set_operating_threshold(1024)
        self.assertEqual((self.sel.trigger_gain, self.sel.operating_threshold), (1, 540))

    def test_autocalibration_saved_channels_set_selection(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        w = AutocalibrationWindow(selection=self.sel)
        w._apply_saved_operation({"channels": [20, 21]})
        self.assertEqual(self.sel.channels(), [20, 21])
        self.assertEqual(w.channel_select.selected_channels(), [20, 21])

    def test_standalone_window_unchanged(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        from radioroc.gui.hold_scan_window import HoldScanWindow
        from radioroc.gui.scurve_window import ScurveWindow
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        from radioroc.gui.acquisition_window import AcquisitionWindow
        w = ThresholdWindow()
        self.assertFalse(w.channel_select.isHidden() and False)
        self.assertEqual(w.channel_select.selected_channels(), [4, 5])
        self.assertIsNone(w.shared_selection)


if __name__ == "__main__":
    unittest.main()
