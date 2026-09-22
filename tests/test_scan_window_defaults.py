"""Locks the scan windows' default Device/mode selection.

Every other GUI test sets ``window.mode`` explicitly before use (see e.g.
``test_threshold_gui.py``'s "this suite only exercises simulation"), so
nothing in the routine local suite ever exercised the *default* value on
construction. RADIOROC 33 found a real CI failure where the installed-wheel
GUI probe (``tools/check_installed_package.py``'s ``GUI_PROBE``, which only
runs in CI's separate wheel-verification stage) still assumed Simulation was
the default after an earlier commit switched it to Hardware connection --
invisible locally for as long as it took to notice. This file re-creates
that one assertion per scan window as a fast, no-wheel-build, routine check
so a future default change can't hide the same way again.
"""

import importlib.util
import os
import unittest

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ScanWindowDefaultModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _assert_defaults_to_hardware(self, window):
        self.addCleanup(window.close)
        self.assertEqual(window.mode.currentText(), "Hardware connection")
        self.assertEqual(window.mode.currentIndex(), 1)

    def test_threshold_window_defaults_to_hardware(self):
        from radioroc.gui.threshold_window import ThresholdWindow
        self._assert_defaults_to_hardware(ThresholdWindow())

    def test_hold_scan_window_defaults_to_hardware(self):
        from radioroc.gui.hold_scan_window import HoldScanWindow
        self._assert_defaults_to_hardware(HoldScanWindow())

    def test_scurve_window_defaults_to_hardware(self):
        from radioroc.gui.scurve_window import ScurveWindow
        self._assert_defaults_to_hardware(ScurveWindow())


if __name__ == "__main__":
    unittest.main()
