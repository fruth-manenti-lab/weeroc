"""Colour ASIC-config controls by whether their value is on the board.

Three states, shared by every ASIC-config tab:

- ``ON_BOARD`` (green border): the board holds this value.
- ``NOT_ON_BOARD`` (amber border, pale amber fill on value fields): the
  control shows a value the board does not hold -- edited but not applied,
  or changed on the board by something else (defaults, a loaded config,
  autocalibration).
- ``UNKNOWN`` (the control's normal look): the app does not know what the
  board holds (not connected, or not read back since connecting).

The vendor app had a narrower version of this: its typed number fields went
grey while edited and back to dark blue once Enter wrote them, judged
against its own record of writes rather than the board.

``mark_widget`` stores the state in the widget's ``boardState`` property
(for tests and tooling) and appends one style rule to the widget's own
base style, so existing per-widget styles (e.g. the blue-filled channel
toggle buttons) keep their look.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QPushButton, QWidget

ON_BOARD = "on_board"
NOT_ON_BOARD = "not_on_board"
UNKNOWN = "unknown"

ON_BOARD_COLOR = "#2e9e5b"
NOT_ON_BOARD_COLOR = "#e08a00"
NOT_ON_BOARD_FILL = "#fff1d6"
_BASE_STYLE_PROPERTY = "_board_base_style"


def _selector(widget) -> str:
    """The nearest Qt class name, so the rule matches app subclasses too."""

    for cls in type(widget).__mro__:
        if cls.__module__.startswith("PySide6"):
            return cls.__name__
    return "QWidget"


def style_rule(widget, state: str) -> str:
    """The stylesheet rule ``mark_widget`` appends for ``state``."""

    if state not in (ON_BOARD, NOT_ON_BOARD):
        return ""
    sel = _selector(widget)
    color = ON_BOARD_COLOR if state == ON_BOARD else NOT_ON_BOARD_COLOR
    is_button = isinstance(widget, QAbstractButton)
    fill = "" if is_button or state == ON_BOARD else f" background: {NOT_ON_BOARD_FILL};"
    # Repeat for :checked so a base ":checked" border rule does not win.
    targets = f"{sel}, {sel}:checked" if is_button else sel
    return f"\n{targets} {{ border: 2px solid {color};{fill} }}\n"


def mark_widget(widget, state: str) -> None:
    """Show ``state`` on ``widget`` without losing its own base style.

    The widget's stylesheet at the first call is remembered as its base style;
    call ``set_base_style`` instead of ``setStyleSheet`` afterwards if a
    widget's base style must change.
    """

    if widget.property("boardState") == state:
        return
    base = widget.property(_BASE_STYLE_PROPERTY)
    if base is None:
        base = widget.styleSheet()
        widget.setProperty(_BASE_STYLE_PROPERTY, base)
    widget.setProperty("boardState", state)
    widget.setStyleSheet(base + style_rule(widget, state))


def set_base_style(widget, style: str) -> None:
    """Change ``widget``'s base style, keeping its board-state rule."""

    widget.setProperty(_BASE_STYLE_PROPERTY, style)
    widget.setStyleSheet(style + style_rule(widget, widget.property("boardState") or UNKNOWN))


def _swatch(text: str, color: str, fill: str = "white") -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"border: 2px solid {color}; background: {fill}; padding: 1px 6px;"
                        " border-radius: 2px")
    return label


class BoardStateBar(QWidget):
    """Legend plus "Read from board" button shown above the ASIC-config tabs.

    Public widgets: ``status_label``, ``read_button``. Signal
    ``read_requested`` fires when the button is pressed. Call ``set_status``
    whenever the connection or the known board state changes.
    """

    read_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.addWidget(_swatch("On board", ON_BOARD_COLOR))
        layout.addWidget(_swatch("Not on board", NOT_ON_BOARD_COLOR, NOT_ON_BOARD_FILL))
        layout.addWidget(_swatch("Board unknown", "#9a9a9a"))
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 1)
        self.read_button = QPushButton("Read from board")
        self.read_button.clicked.connect(self.read_requested)
        layout.addWidget(self.read_button)
        self.set_status(connected=False, board_state=None)

    def set_status(self, *, connected: bool, board_state) -> None:
        """Update the text and button for the connection and board state.

        **Inputs**
        - `connected` (`bool`): Whether the worker is connected and idle.
        - `board_state` (`BoardRegisterState | None`): The known board table.
        """

        self.read_button.setEnabled(connected)
        if board_state is None:
            text = ("Not connected: colours off." if not connected else
                    "Board settings unknown since connecting. Press Read from board"
                    " (or Apply defaults / Load config) to compare.")
        elif board_state.source == "read_back":
            text = "Compared with the settings just read back from the board."
        else:
            text = ("Compared with the board's last read-back or full write, plus every"
                    " change this app has written since.")
        self.status_label.setText(text)
