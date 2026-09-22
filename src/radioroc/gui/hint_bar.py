"""Hover-hint helper for the desktop GUI.

Wires mouse Enter/Leave events on arbitrary widgets to a status bar (or
anything exposing ``showMessage()``/``clearMessage()``), so a small line at
the bottom of the window always describes whatever control the cursor is
over -- mirroring the vendor GUI's status-line help text -- falling back to
a window-level default description when nothing is hovered.
"""
from PySide6.QtCore import QEvent, QObject


class HintBar(QObject):
    def __init__(self, bar, default_text=""):
        super().__init__(bar)
        self._bar = bar
        self._default_text = default_text
        self.show_default()

    def set_default(self, text):
        self._default_text = text
        self.show_default()

    def show_default(self):
        self._bar.showMessage(self._default_text)

    def attach(self, widget, text):
        """Show `text` in the bar whenever the mouse hovers `widget`."""
        widget.setProperty("_hint_text", text)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Enter:
            text = obj.property("_hint_text")
            if text:
                self._bar.showMessage(text)
        elif event.type() == QEvent.Type.Leave:
            self.show_default()
        return False
