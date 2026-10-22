"""Channel/trigger selection widget shown once above the Calibration sub-tabs,
plus the helper the scan windows use to follow the shared selection."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QSpinBox, QWidget,
)

from radioroc.gui.calibration_selection import CalibrationSelection
from radioroc.gui.channel_select import ChannelSelectGrid


def bind_shared_selection(selection, form, grid, trigger_1=None, trigger_2=None):
    """Make a scan window follow ``selection``.

    Hides the window's own channel grid and trigger spin boxes (rows of ``form``)
    and keeps the hidden widgets mirrored from the model, so the window's job
    config code keeps working unchanged. Returns a callable that pushes the
    model state into the widgets (already called once).
    """
    def sync_channels(*_):
        try:
            if grid.selected_channels() != selection.channels():
                grid.set_channels(selection.channels())
        except RuntimeError:  # window already destroyed
            pass

    def sync_triggers(*_):
        try:
            if trigger_1 is not None:
                trigger_1.setValue(selection.trigger_channel)
            if trigger_2 is not None:
                trigger_2.setValue(selection.trigger_channel_2)
        except RuntimeError:
            pass

    def sync_all():
        sync_channels()
        sync_triggers()

    for widget in (grid, trigger_1, trigger_2):
        if widget is not None:
            form.setRowVisible(widget, False)
    selection.channels_changed.connect(sync_channels)
    selection.triggers_changed.connect(sync_triggers)
    sync_all()
    return sync_all


class CalibrationSelectionPanel(QWidget):
    def __init__(self, selection: CalibrationSelection, parent=None):
        super().__init__(parent)
        self.selection = selection
        self.setAccessibleName("Calibration channel selection")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 0)
        layout.setSpacing(12)

        self.channel_select = ChannelSelectGrid(initial_channels=selection.channels())
        self.channel_select.toggle_button.setAccessibleName("Selected channels")
        self.channel_select.toggle_button.setFixedHeight(24)
        layout.addWidget(self.channel_select, 1, Qt.AlignTop)

        row = QHBoxLayout()
        self.trigger_channel = QSpinBox()
        self.trigger_channel.setRange(0, 63)
        self.trigger_channel.setAccessibleName("Trigger channel (T1)")
        self.trigger_channel_2 = QSpinBox()
        self.trigger_channel_2.setRange(0, 63)
        self.trigger_channel_2.setAccessibleName("Trigger channel (T2)")
        self.auto_checkbox = QCheckBox("Choose trigger channels automatically")
        self.auto_checkbox.setAccessibleName("Choose trigger channels automatically")
        row.addWidget(QLabel("Trigger channel (T1)"))
        row.addWidget(self.trigger_channel)
        row.addWidget(QLabel("Trigger channel (T2)"))
        row.addWidget(self.trigger_channel_2)
        row.addWidget(self.auto_checkbox)
        for spin in (self.trigger_channel, self.trigger_channel_2):
            spin.setFixedHeight(24)
        layout.addLayout(row)

        self._syncing = False
        self._sync_from_model()
        for button in self.channel_select.channel_buttons:
            button.toggled.connect(self._grid_changed)
        self.trigger_channel.valueChanged.connect(self._trigger_edited)
        self.trigger_channel_2.valueChanged.connect(self._trigger_edited)
        self.auto_checkbox.toggled.connect(self._auto_toggled)
        selection.channels_changed.connect(self._sync_from_model)
        selection.triggers_changed.connect(self._sync_from_model)
        selection.auto_changed.connect(self._sync_from_model)

    def _sync_from_model(self, *_):
        sel = self.selection
        self._syncing = True
        try:
            if self.channel_select.selected_channels() != sel.channels():
                self.channel_select.set_channels(sel.channels())
            self.trigger_channel.setValue(sel.trigger_channel)
            self.trigger_channel_2.setValue(sel.trigger_channel_2)
            self.auto_checkbox.setChecked(sel.auto_triggers)
        finally:
            self._syncing = False

    def _grid_changed(self, *_):
        if not self._syncing:
            self.selection.set_channels(self.channel_select.selected_channels())

    def _trigger_edited(self, *_):
        if not self._syncing:
            self.selection.set_trigger_channels(
                self.trigger_channel.value(), self.trigger_channel_2.value())

    def _auto_toggled(self, checked):
        if not self._syncing:
            self.selection.set_auto_triggers(checked)

    def attach_hints(self, hint):
        hint.attach(self.channel_select.toggle_button,
                    "Channels used by every Calibration tab and Acquisition. Click to edit.")
        hint.attach(self.channel_select.select_all_button, "Select every channel.")
        hint.attach(self.channel_select.select_none_button, "Deselect every channel.")
        hint.attach(self.trigger_channel, "Channel for the T1 trigger slot.")
        hint.attach(self.trigger_channel_2, "Channel for the T2 trigger slot.")
        hint.attach(self.auto_checkbox,
                    "Follow the lowest selected channels for T1/T2; editing a trigger channel turns this off.")
