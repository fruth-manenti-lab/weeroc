"""The "input DAC" grid sub-tab: 64 independent per-channel raw DAC codes.

Sibling of ``ChannelConfigPanel`` (the shared single-range/single-value
panel); both stay independently usable. This one matches the vendor's
8x8 grid, one raw 0..255 DAC code per channel, plus the shared HiZ
impedance switch and "All ON"/"All OFF" buttons.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from radioroc.application.channel_config import ChannelConfigOperation

N_CHANNELS = 64
GRID_COLUMNS = 8


class InputDacGridPanel(QWidget):
    """Public widgets: ``channel_value_spinboxes`` (64, index == channel),
    ``hiz_checkbox``, ``all_on_button``, ``all_off_button``, ``apply_button``,
    ``status_label``.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        grid = QGridLayout()
        self.channel_value_spinboxes = []
        for channel in range(N_CHANNELS):
            row, col = divmod(channel, GRID_COLUMNS)
            cell = QHBoxLayout()
            cell.addWidget(QLabel(str(channel)))
            spinbox = QSpinBox()
            spinbox.setRange(0, 255)
            spinbox.setValue(128)
            cell.addWidget(spinbox)
            self.channel_value_spinboxes.append(spinbox)
            grid.addLayout(cell, row, col)
        outer.addLayout(grid)

        # Vendor screenshot doesn't disambiguate polarity; checked -> high
        # impedance (False), unchecked -> low ~150 Ohm (True), consistent
        # with ChannelConfigOperation.input_dac_impedance's low/high convention.
        self.hiz_checkbox = QCheckBox("HiZ input (need external resistor)")
        outer.addWidget(self.hiz_checkbox)

        buttons = QHBoxLayout()
        self.all_on_button = QPushButton("All ON")
        self.all_off_button = QPushButton("All OFF")
        self.apply_button = QPushButton("Write all")
        buttons.addWidget(self.all_on_button)
        buttons.addWidget(self.all_off_button)
        buttons.addWidget(self.apply_button)
        outer.addLayout(buttons)

        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # Single embedder, no competing error-routing, so this panel wires
        # its own buttons (unlike ChannelConfigPanel's Apply).
        self.apply_button.clicked.connect(self.apply)
        self.all_on_button.clicked.connect(self.all_on)
        self.all_off_button.clicked.connect(self.all_off)

        # apply_channel_config is asynchronous (the worker only enqueues it
        # and returns immediately); showing the snapshot the instant it's
        # submitted reliably shows a stale or empty result, not the one just
        # requested. Poll until the worker leaves its busy state instead.
        self._applying = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def apply(self):
        """Validate, submit the 64-value grid plus impedance, and report
        errors on ``status_label`` instead of raising."""
        if self.connection_worker is None or self._applying:
            return None
        operation = ChannelConfigOperation(
            input_dac_values={channel: spin.value()
                              for channel, spin in enumerate(self.channel_value_spinboxes)},
            input_dac_impedance=False if self.hiz_checkbox.isChecked() else True,
            verify=True,
        )
        try:
            operation.validate()
        except ValueError as exc:
            self.status_label.setText(f"Invalid input DAC configuration: {exc}")
            return None
        return self._submit(operation)

    def _apply_enable(self, enable_value: bool):
        # "All ON"/"All OFF" set the input-DAC enable bit for every channel;
        # the raw-value grid above is written separately via apply().
        if self.connection_worker is None or self._applying:
            return None
        operation = ChannelConfigOperation(
            input_dac_enable_channels=tuple(range(N_CHANNELS)),
            input_dac_enable_value=enable_value,
            verify=True,
        )
        try:
            operation.validate()
        except ValueError as exc:
            self.status_label.setText(f"Invalid input DAC configuration: {exc}")
            return None
        return self._submit(operation)

    def _submit(self, operation):
        try:
            self.connection_worker.apply_channel_config(operation)
        except Exception as exc:
            self.status_label.setText(
                f"Input DAC error · {type(exc).__name__}: {exc}")
            return None
        self._applying = True
        self.status_label.setText("Applying input DAC config…")
        self.timer.start()
        return operation

    def _poll(self):
        if self.connection_worker is None:
            self.timer.stop()
            self._applying = False
            return
        if self.connection_worker.snapshot().state == "configuring":
            return  # still in flight
        self.timer.stop()
        self._applying = False
        self.show_snapshot()

    def all_on(self):
        return self._apply_enable(True)

    def all_off(self):
        return self._apply_enable(False)

    def show_snapshot(self):
        worker = self.connection_worker
        result = worker.channel_config_snapshot() if worker is not None else None
        if result is None:
            return
        parts = [f"{len(result.applied)} write(s)", f"{result.touched_rows} row(s) touched"]
        if result.verify_mismatches:
            parts.append(f"{len(result.verify_mismatches)} VERIFY MISMATCH(ES)")
        else:
            parts.append("verified")
        if result.restored:
            parts.append("restored" if not result.restore_mismatches
                         else f"{len(result.restore_mismatches)} RESTORE MISMATCH(ES)")
        self.status_label.setText(
            "Input DAC: " + "; ".join(parts) + (
                (" · " + "; ".join(result.applied)) if result.applied else ""))
