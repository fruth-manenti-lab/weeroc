"""Spin box helper: typing replaces the value instead of appending to it."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox


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


class _WheelGuard(QObject):
    """Ignore mouse-wheel events on spin boxes and dropdowns that are not focused.

    Scrolling a page with the wheel otherwise changes whatever value the
    pointer happens to pass over. The event is ignored (not consumed), so it
    propagates to the parent and still scrolls the surrounding scroll area.
    Click the control first to change it with the wheel.
    """

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Wheel
                and isinstance(obj, (QAbstractSpinBox, QComboBox))
                and not obj.hasFocus()):
            event.ignore()
            return True
        return False


def install_wheel_guard(owner):
    """Install the guard application-wide (covers widgets created later); parented to ``owner``."""
    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(_WheelGuard(owner))
