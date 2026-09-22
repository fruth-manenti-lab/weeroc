"""Unit tests for the shared channel multi-select grid widget.

``format_channels`` itself (the pure range-collapsing logic) lives in
``radioroc_client`` and is tested in ``tests/test_radioroc_core.py``
alongside that module's other dependency-free functions, precisely so it
can be tested without the ``[gui]`` extra installed -- this file only
covers the actual Qt widget, which does require it.
"""

import importlib.util
import os
import unittest

import radioroc_client  # noqa: F401  (side effect: puts src/ on sys.path for radioroc.*)

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ChannelSelectGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_grid(self, initial_channels=(4,)):
        from radioroc.gui.channel_select import ChannelSelectGrid
        grid = ChannelSelectGrid(initial_channels)
        self.addCleanup(grid.deleteLater)
        return grid

    def test_starts_collapsed_with_initial_selection(self):
        grid = self.make_grid((4, 5))
        self.assertFalse(grid.grid_group.isVisible())
        self.assertEqual(grid.selected_channels(), [4, 5])
        self.assertIn("4-5", grid.toggle_button.text())

    def test_toggle_button_expands_and_collapses_the_grid(self):
        grid = self.make_grid()
        # isVisible() reflects actual on-screen visibility (which depends on
        # the whole ancestor chain being shown), not just this widget's own
        # setVisible() flag -- show() it first, same as any other Qt test
        # that asserts on-screen visibility rather than the visibility flag.
        grid.show()
        grid.toggle_button.setChecked(True)
        self.assertTrue(grid.grid_group.isVisible())
        grid.toggle_button.setChecked(False)
        self.assertFalse(grid.grid_group.isVisible())

    def test_clicking_a_channel_button_updates_selection_and_summary(self):
        grid = self.make_grid((4,))
        grid.channel_buttons[10].setChecked(True)
        self.assertEqual(grid.selected_channels(), [4, 10])
        self.assertIn("4,10", grid.toggle_button.text())
        grid.channel_buttons[4].setChecked(False)
        self.assertEqual(grid.selected_channels(), [10])

    def test_select_all_and_select_none(self):
        grid = self.make_grid((4,))
        grid.select_all_button.click()
        self.assertEqual(len(grid.selected_channels()), 64)
        grid.select_none_button.click()
        self.assertEqual(grid.selected_channels(), [])

    def test_set_channels_replaces_the_current_selection(self):
        grid = self.make_grid((4,))
        grid.set_channels([0, 1, 63])
        self.assertEqual(grid.selected_channels(), [0, 1, 63])
        self.assertFalse(grid.channel_buttons[4].isChecked())

    def test_checked_button_uses_the_theme_blue(self):
        from radioroc.gui.channel_select import CHECKED_FILL
        grid = self.make_grid((4,))
        self.assertIn(CHECKED_FILL, grid.channel_buttons[4].styleSheet())
        self.assertEqual(CHECKED_FILL, "#007990")


if __name__ == "__main__":
    unittest.main()
