"""The bundled desktop icon must ship as package data and load as an image."""

import unittest
from importlib.resources import files


class DesktopIconTests(unittest.TestCase):
    def test_icon_resource_is_a_png(self):
        data = (files("radioroc.resources") / "radioroc_icon.png").read_bytes()
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
