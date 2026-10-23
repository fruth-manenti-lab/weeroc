"""Spin box helper: typing replaces the value instead of appending to it."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer


class _SelectAllOnFocus(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusIn:
            # Deferred so the mouse press that gave focus does not reset the selection.
            QTimer.singleShot(0, obj.selectAll)
        return False


def select_all_on_focus(spin):
    """Select the whole text when the spin box gains focus; returns the spin box."""
    line_edit = spin.lineEdit()
    filt = _SelectAllOnFocus(line_edit)  # parented: lives as long as the line edit
    line_edit.installEventFilter(filt)
    return spin
