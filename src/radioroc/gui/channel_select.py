"""Shared 64-channel multi-select grid, matching the vendor app's own
"set ignore channel" panel.

The vendor GUI's S-curve/threshold-scan tabs have a collapsible panel of
checkable channel buttons (`WCheckBox` instances inside a `QGroupBox` that
slides open/closed via a `QPropertyAnimation`, see
`Radioroc2.slide_groupbox`/`set_all_checked` in the vendor's extracted
`main.pyc`) instead of a typed channel list -- clicking a channel toggles
it, "select all"/"select none" buttons cover the common cases, and a
checked channel is filled in the app's blue theme color. This widget
reproduces that shape (a collapsible grid of checkable buttons, the same
blue fill/border when checked, "Select all"/"Select none") for reuse by
every scan window and by `ProbesMasksPanel`'s three mask grids, replacing
free-text channel entry and plain checkboxes respectively.

The vendor's own open/close animation (a 200ms `QPropertyAnimation` on the
groupbox's height) is not reproduced -- a plain show/hide toggle gets the
same "collapsed by default, one click to edit" behavior without adding
animation-timing surface to test.

Colors recovered from the vendor's own compiled `WCheckBox.draw_checked`
(`uiroc/weedgets.pyc`): pen `QColor(2,65,103)` = `#024167`, fill
`QColor(0,121,144)` = `#007990`. See `IMPLEMENTATION_STATUS.md` for the
full recovery record.
"""

from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
)

from radioroc_client import N_CHANNELS, format_channels

_GRID_COLUMNS = 8

CHECKED_FILL = "#007990"
CHECKED_BORDER = "#024167"

CHANNEL_BUTTON_STYLE = f"""
QPushButton {{
    min-width: 26px; max-width: 26px; min-height: 22px; max-height: 22px;
    border: 1px solid #9a9a9a; border-radius: 2px; background: white; color: #222;
}}
QPushButton:checked {{
    background: {CHECKED_FILL}; border: 1px solid {CHECKED_BORDER}; color: white;
}}
"""


class ChannelSelectGrid(QWidget):
    """Public widgets: ``toggle_button``, ``select_all_button``,
    ``select_none_button``, ``channel_buttons`` (64-entry list, index ==
    channel number). Public API: ``set_channels(channels)``,
    ``selected_channels() -> list[int]``.

    Starts collapsed, showing only ``toggle_button`` with a one-line
    summary of the current selection (``format_channels``); clicking it
    reveals the grid plus the select-all/none buttons.
    """

    def __init__(self, initial_channels=(4,), parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.toggled.connect(self._set_expanded)
        outer.addWidget(self.toggle_button)

        self.grid_group = QGroupBox("Channels")
        group_layout = QVBoxLayout(self.grid_group)
        grid = QGridLayout()
        group_layout.addLayout(grid)
        self.channel_buttons = []
        for channel in range(N_CHANNELS):
            button = QPushButton(str(channel))
            button.setCheckable(True)
            button.setStyleSheet(CHANNEL_BUTTON_STYLE)
            button.toggled.connect(self._update_summary)
            grid.addWidget(button, channel // _GRID_COLUMNS, channel % _GRID_COLUMNS)
            self.channel_buttons.append(button)

        buttons_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_none_button = QPushButton("Select none")
        self.select_all_button.clicked.connect(lambda: self._set_all(True))
        self.select_none_button.clicked.connect(lambda: self._set_all(False))
        buttons_row.addWidget(self.select_all_button)
        buttons_row.addWidget(self.select_none_button)
        group_layout.addLayout(buttons_row)
        outer.addWidget(self.grid_group)

        self.set_channels(initial_channels)
        self.grid_group.setVisible(False)

    def _set_expanded(self, expanded):
        self.grid_group.setVisible(expanded)

    def _set_all(self, checked):
        for button in self.channel_buttons:
            button.setChecked(checked)

    def _update_summary(self):
        self.toggle_button.setText(f"Channels: {format_channels(self.selected_channels())}")

    def selected_channels(self) -> list:
        return [channel for channel, button in enumerate(self.channel_buttons) if button.isChecked()]

    def set_channels(self, channels) -> None:
        selected = set(channels)
        for channel, button in enumerate(self.channel_buttons):
            button.setChecked(channel in selected)
        self._update_summary()
