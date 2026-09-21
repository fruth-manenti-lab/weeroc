"""The "Threshold calibration" tab: two 64-channel T1/T2 trim-DAC grids.

Sibling of ``InputDacGridPanel``/``ProbesMasksPanel``: same 8x8 grid shape,
one ``QSpinBox`` per channel, plus a per-grid "Set all" control and an
Apply button.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from radioroc_client import N_CHANNELS
from radioroc.application.channel_config import ChannelConfigOperation

_GRID_COLUMNS = 8


def _build_dac_grid(title, prefix, panel):
    group = QGroupBox(title)
    outer = QVBoxLayout(group)
    grid = QGridLayout()
    outer.addLayout(grid)
    spinboxes = []
    for channel in range(N_CHANNELS):
        cell = QHBoxLayout()
        cell.addWidget(QLabel(str(channel)))
        spinbox = QSpinBox()
        spinbox.setRange(0, 63)
        spinbox.setValue(32)  # Vendor screenshot's and the default config CSV's default.
        cell.addWidget(spinbox)
        grid.addLayout(cell, channel // _GRID_COLUMNS, channel % _GRID_COLUMNS)
        spinboxes.append(spinbox)
    setattr(panel, f"{prefix}_spinboxes", spinboxes)

    set_all_row = QHBoxLayout()
    set_all_row.addWidget(QLabel("Set all"))
    set_all_spinbox = QSpinBox()
    set_all_spinbox.setRange(0, 63)
    set_all_spinbox.setValue(32)
    set_all_button = QPushButton("Apply")
    set_all_button.clicked.connect(lambda: _set_all(spinboxes, set_all_spinbox.value()))
    set_all_row.addWidget(set_all_spinbox)
    set_all_row.addWidget(set_all_button)
    outer.addLayout(set_all_row)
    setattr(panel, f"{prefix}_set_all_spinbox", set_all_spinbox)
    setattr(panel, f"{prefix}_set_all_button", set_all_button)
    return group


def _set_all(spinboxes, value):
    for spinbox in spinboxes:
        spinbox.setValue(value)


class ThresholdCalibrationPanel(QWidget):
    """Public widgets: ``t1_spinboxes``/``t2_spinboxes`` (64-entry, index ==
    channel number), ``t1_set_all_spinbox``/``t1_set_all_button`` and the t2
    equivalents, ``apply_button``, ``status_label``.

    Like ``ProbesMasksPanel``, this panel does not own a connection: it is
    handed an existing ``ConnectionWorker`` (or ``None``) via
    ``self.connection_worker``, and has no embedder-specific error routing
    to preserve, so its own Apply button is wired directly here.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        grids_row = QHBoxLayout()
        grids_row.addWidget(_build_dac_grid("Calibration DAC T1", "t1", self))
        grids_row.addWidget(_build_dac_grid("Calibration DAC T2", "t2", self))
        outer.addLayout(grids_row)

        self.apply_button = QPushButton("Apply calibration")
        self.apply_button.clicked.connect(self.apply)
        outer.addWidget(self.apply_button)
        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # apply_channel_config is asynchronous (the worker only enqueues it
        # and returns immediately); showing the snapshot the instant it's
        # submitted reliably shows a stale or empty result, not the one just
        # requested. Poll until the worker leaves its busy state instead.
        self._applying = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def build_operation(self):
        operation = ChannelConfigOperation(
            t1_calibration_dac_values={ch: spin.value() for ch, spin in enumerate(self.t1_spinboxes)},
            t2_calibration_dac_values={ch: spin.value() for ch, spin in enumerate(self.t2_spinboxes)},
            verify=True,
        )
        operation.validate()
        return operation

    def apply(self):
        if self.connection_worker is None or self._applying:
            return None
        try:
            operation = self.build_operation()
        except ValueError as exc:
            self.status_label.setText(f"Invalid calibration configuration: {exc}")
            return None
        try:
            self.connection_worker.apply_channel_config(operation)
        except Exception as exc:
            self.status_label.setText(f"Calibration apply error · {type(exc).__name__}: {exc}")
            return None
        self._applying = True
        self.status_label.setText("Applying calibration…")
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
            "Calibration: " + "; ".join(parts) + (
                (" · " + "; ".join(result.applied)) if result.applied else ""))
