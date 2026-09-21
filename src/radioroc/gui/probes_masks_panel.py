"""Trigger-mask grids from the vendor "ASIC config. / Probes/Masks" tab.

Covers only the three 64-channel mask toggle grids (Enable T1 / Enable T2 /
Enable TQ) plus their per-grid "Enable all"/"Enable none" buttons. Does not
cover that tab's "Analog probe" / "Digital probe" routing radio-button
groups: there is no backend support for probe routing in this codebase yet,
so building it would mean guessing at unconfirmed register behavior.
"""

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from radioroc_client import N_CHANNELS
from radioroc.application.channel_config import ChannelConfigOperation

_GRID_COLUMNS = 8


def _build_mask_grid(title, prefix, panel):
    group = QGroupBox(title)
    outer = QVBoxLayout(group)
    grid = QGridLayout()
    outer.addLayout(grid)
    checkboxes = []
    for channel in range(N_CHANNELS):
        checkbox = QCheckBox(str(channel))
        checkbox.setChecked(True)  # UI-only default; no read-back wiring in scope here.
        grid.addWidget(checkbox, channel // _GRID_COLUMNS, channel % _GRID_COLUMNS)
        checkboxes.append(checkbox)
    setattr(panel, f"{prefix}_checkboxes", checkboxes)

    buttons_row = QHBoxLayout()
    enable_all_button = QPushButton("Enable all")
    enable_none_button = QPushButton("Enable none")
    enable_all_button.clicked.connect(lambda: _set_all(checkboxes, True))
    enable_none_button.clicked.connect(lambda: _set_all(checkboxes, False))
    buttons_row.addWidget(enable_all_button)
    buttons_row.addWidget(enable_none_button)
    outer.addLayout(buttons_row)
    setattr(panel, f"{prefix}_enable_all_button", enable_all_button)
    setattr(panel, f"{prefix}_enable_none_button", enable_none_button)
    return group


def _set_all(checkboxes, checked):
    for checkbox in checkboxes:
        checkbox.setChecked(checked)


class ProbesMasksPanel(QWidget):
    """Public widgets: ``t1_checkboxes``/``t2_checkboxes``/``tq_checkboxes``
    (64-entry, index == channel number), ``t1_enable_all_button``/
    ``t1_enable_none_button`` and the t2/tq equivalents, ``apply_button``,
    ``status_label``.

    Like ``ChannelConfigPanel``, this panel does not own a connection: it is
    handed an existing ``ConnectionWorker`` (or ``None``) via
    ``self.connection_worker``. Unlike that panel's main Apply button, this
    panel has no embedder-specific error routing to preserve, so its own
    Apply button is wired directly here.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        grids_row = QHBoxLayout()
        grids_row.addWidget(_build_mask_grid("Enable T1", "t1", self))
        grids_row.addWidget(_build_mask_grid("Enable T2", "t2", self))
        grids_row.addWidget(_build_mask_grid("Enable TQ", "tq", self))
        outer.addLayout(grids_row)

        self.apply_button = QPushButton("Apply masks")
        self.apply_button.clicked.connect(self.apply)
        outer.addWidget(self.apply_button)
        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

    def build_operation(self):
        operation = ChannelConfigOperation(
            tq_mask_states={ch: cb.isChecked() for ch, cb in enumerate(self.tq_checkboxes)},
            t1_mask_states={ch: cb.isChecked() for ch, cb in enumerate(self.t1_checkboxes)},
            t2_mask_states={ch: cb.isChecked() for ch, cb in enumerate(self.t2_checkboxes)},
            verify=True,
        )
        operation.validate()
        return operation

    def apply(self):
        if self.connection_worker is None:
            return None
        try:
            operation = self.build_operation()
        except ValueError as exc:
            self.status_label.setText(f"Invalid mask configuration: {exc}")
            return None
        try:
            self.connection_worker.apply_channel_config(operation)
        except Exception as exc:
            self.status_label.setText(f"Mask apply error · {type(exc).__name__}: {exc}")
            return None
        self.show_snapshot()
        return operation

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
            "Channel config: " + "; ".join(parts) + (
                (" · " + "; ".join(result.applied)) if result.applied else ""))
