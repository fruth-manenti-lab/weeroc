"""The bundled desktop icon must ship as package data and load as an image."""

import unittest
from importlib.resources import files
from pathlib import Path


class DesktopIconTests(unittest.TestCase):
    def test_icon_resource_is_a_png(self):
        try:
            icon = files("radioroc.resources") / "radioroc_icon.png"
        except ModuleNotFoundError:
            # Running from a source checkout: the package-data mapping
            # radioroc.resources -> configs/ exists only in an installed package.
            icon = Path(__file__).resolve().parents[1] / "configs" / "radioroc_icon.png"
        data = icon.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    def test_gui_sets_the_window_icon_without_error(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ModuleNotFoundError:
            self.skipTest("PySide6 not installed")
        from radioroc.gui.__main__ import _set_icon
        app = QApplication.instance() or QApplication([])
        _set_icon(app)
        self.assertFalse(app.windowIcon().isNull())


if __name__ == "__main__":
    unittest.main()
