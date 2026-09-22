"""Unit tests for the hover-hint status-bar helper used by the scan windows."""

import importlib.util
import os
import unittest

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class HintBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _bar_and_widget(self, default_text="default"):
        from PySide6.QtWidgets import QMainWindow, QPushButton
        from radioroc.gui.hint_bar import HintBar
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        button = QPushButton(window)
        hint = HintBar(window.statusBar(), default_text)
        return window, hint, button

    def test_shows_default_text_immediately(self):
        window, hint, _ = self._bar_and_widget("hover a control")
        self.assertEqual(window.statusBar().currentMessage(), "hover a control")

    def test_hovering_an_attached_widget_shows_its_hint(self):
        from PySide6.QtCore import QEvent
        window, hint, button = self._bar_and_widget("default")
        hint.attach(button, "does a thing")
        hint.eventFilter(button, QEvent(QEvent.Type.Enter))
        self.assertEqual(window.statusBar().currentMessage(), "does a thing")

    def test_leaving_reverts_to_default(self):
        from PySide6.QtCore import QEvent
        window, hint, button = self._bar_and_widget("default")
        hint.attach(button, "does a thing")
        hint.eventFilter(button, QEvent(QEvent.Type.Enter))
        hint.eventFilter(button, QEvent(QEvent.Type.Leave))
        self.assertEqual(window.statusBar().currentMessage(), "default")

    def test_set_default_changes_the_fallback_text(self):
        window, hint, _ = self._bar_and_widget("default")
        hint.set_default("new default")
        self.assertEqual(window.statusBar().currentMessage(), "new default")

    def test_unattached_widget_is_ignored(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QPushButton
        window, hint, button = self._bar_and_widget("default")
        other = QPushButton(window)
        self.addCleanup(other.deleteLater)
        hint.eventFilter(other, QEvent(QEvent.Type.Enter))
        self.assertEqual(window.statusBar().currentMessage(), "default")


if __name__ == "__main__":
    unittest.main()
