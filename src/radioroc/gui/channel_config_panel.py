"""Shared "Input DAC / TQ mask" widget: UI plus its apply/show-result behavior.

Lifted out of ``radioroc.gui.threshold_window.ThresholdWindow`` (the canonical
source for this behavior before the extraction). Unlike ``ConnectionPanel``,
this panel does not own a connection: it is handed an existing
``ConnectionWorker`` (or ``None`` before one exists) and reads/writes
``self.connection_worker`` directly, so an embedding window can keep it in
sync with whichever worker instance is currently live.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from radioroc_client import parse_channels
from radioroc.application.channel_config import ChannelConfigOperation


def _integer(low, high, value):
    field = QSpinBox()
    field.setRange(low, high)
    field.setValue(value)
    return field


class ChannelConfigPanel(QWidget):
    """Public widgets (same names/behavior as the former inline group box):
    ``channel_config_channels``, ``channel_config_set_tq_mask``,
    ``channel_config_tq_mask_value``, ``channel_config_set_input_dac_enable``,
    ``channel_config_input_dac_enable_value``,
    ``channel_config_set_input_dac_value``, ``channel_config_input_dac_value``,
    ``channel_config_impedance``, ``channel_config_restore``,
    ``channel_config_apply_button``, ``channel_config_status``, plus
    ``channel_config_group`` (the ``QGroupBox`` that visually contains them).

    The Apply button is not auto-wired to ``apply()``: see
    ``ConnectionPanel`` for why an embedder wires its own buttons.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.channel_config_group = QGroupBox(
            "Input DAC / TQ mask (persists unless Restore is checked)")
        outer.addWidget(self.channel_config_group)

        channel_config_form = QFormLayout(self.channel_config_group)
        self.channel_config_channels = QLineEdit()
        self.channel_config_channels.setPlaceholderText("e.g. 4 or 0-15 or all")
        channel_config_form.addRow("Channels", self.channel_config_channels)
        self.channel_config_set_tq_mask = QCheckBox("Set TQ mask")
        self.channel_config_tq_mask_value = QComboBox()
        self.channel_config_tq_mask_value.addItems(["Enabled", "Disabled"])
        tq_row = QHBoxLayout()
        tq_row.addWidget(self.channel_config_set_tq_mask)
        tq_row.addWidget(self.channel_config_tq_mask_value)
        channel_config_form.addRow(tq_row)
        self.channel_config_set_input_dac_enable = QCheckBox("Set input DAC enable")
        self.channel_config_input_dac_enable_value = QComboBox()
        self.channel_config_input_dac_enable_value.addItems(["Enabled", "Disabled"])
        dac_enable_row = QHBoxLayout()
        dac_enable_row.addWidget(self.channel_config_set_input_dac_enable)
        dac_enable_row.addWidget(self.channel_config_input_dac_enable_value)
        channel_config_form.addRow(dac_enable_row)
        self.channel_config_set_input_dac_value = QCheckBox("Set input DAC value")
        self.channel_config_input_dac_value = _integer(0, 255, 0)
        dac_value_row = QHBoxLayout()
        dac_value_row.addWidget(self.channel_config_set_input_dac_value)
        dac_value_row.addWidget(self.channel_config_input_dac_value)
        channel_config_form.addRow(dac_value_row)
        self.channel_config_impedance = QComboBox()
        self.channel_config_impedance.addItems(
            ["Unchanged", "Low (~150 Ohm, all channels)", "High (all channels)"])
        channel_config_form.addRow("Impedance", self.channel_config_impedance)
        self.channel_config_restore = QCheckBox("Restore after (bounded validation, does not persist)")
        channel_config_form.addRow(self.channel_config_restore)
        self.channel_config_apply_button = QPushButton("Apply channel config")
        channel_config_form.addRow(self.channel_config_apply_button)
        self.channel_config_status = QLabel("—")
        self.channel_config_status.setWordWrap(True)
        channel_config_form.addRow(self.channel_config_status)

        # apply_channel_config is asynchronous (the worker only enqueues it
        # and returns immediately); showing the snapshot the instant it's
        # submitted reliably shows a stale or empty result, not the one just
        # requested. Poll until the worker leaves its busy state instead.
        self._applying = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def build_operation(self):
        """Build (and validate) a ``ChannelConfigOperation`` from the widgets.

        Raises ``ValueError`` on invalid input; callers decide how to
        surface that (see ``apply`` below, or
        ``ThresholdWindow.apply_channel_config`` for the embedded version).
        """
        text = self.channel_config_channels.text().strip()
        channels = tuple(parse_channels(text)) if text else ()
        impedance = {0: None, 1: True, 2: False}[self.channel_config_impedance.currentIndex()]
        operation = ChannelConfigOperation(
            tq_mask_channels=channels if self.channel_config_set_tq_mask.isChecked() else (),
            tq_mask_value=self.channel_config_tq_mask_value.currentIndex() == 0,
            input_dac_enable_channels=(
                channels if self.channel_config_set_input_dac_enable.isChecked() else ()),
            input_dac_enable_value=self.channel_config_input_dac_enable_value.currentIndex() == 0,
            input_dac_value_channels=(
                channels if self.channel_config_set_input_dac_value.isChecked() else ()),
            input_dac_value=(self.channel_config_input_dac_value.value()
                             if self.channel_config_set_input_dac_value.isChecked() else None),
            input_dac_impedance=impedance,
            verify=True,
            restore=self.channel_config_restore.isChecked(),
        )
        operation.validate()
        return operation

    def apply(self):
        """Standalone apply: validate, submit to ``self.connection_worker``,
        and report validation/submission errors on this panel's own status
        label. An embedding window with its own error-routing (e.g. sending
        submission errors to a separate connection-status label) should call
        ``build_operation`` + ``self.connection_worker.apply_channel_config``
        itself instead, as ``ThresholdWindow.apply_channel_config`` does.
        """
        if self.connection_worker is None or self._applying:
            return None
        try:
            operation = self.build_operation()
        except ValueError as exc:
            self.channel_config_status.setText(f"Invalid channel configuration: {exc}")
            return None
        try:
            self.connection_worker.apply_channel_config(operation)
        except Exception as exc:
            self.channel_config_status.setText(
                f"Channel config error · {type(exc).__name__}: {exc}")
            return None
        self._applying = True
        self.channel_config_status.setText("Applying channel config…")
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
        self.channel_config_status.setText(
            "Channel config: " + "; ".join(parts) + (
                (" · " + "; ".join(result.applied)) if result.applied else ""))

    def attach_hints(self, hint_bar):
        """Wire hover-hint text for this panel's controls into ``hint_bar``."""
        hint_bar.attach(self.channel_config_channels,
                        "Channels this configuration applies to (e.g. 4 or 0-15 or all).")
        hint_bar.attach(self.channel_config_set_tq_mask,
                        "Set the TQ mask for the channels above; leave unchecked to leave "
                        "TQ masking alone.")
        hint_bar.attach(self.channel_config_tq_mask_value,
                        "Value to write when 'Set TQ mask' is checked.")
        hint_bar.attach(self.channel_config_set_input_dac_enable,
                        "Set the input DAC enable bit for the channels above; leave "
                        "unchecked to leave it alone.")
        hint_bar.attach(self.channel_config_input_dac_enable_value,
                        "Value to write when 'Set input DAC enable' is checked.")
        hint_bar.attach(self.channel_config_set_input_dac_value,
                        "Set the input DAC's raw DC-level code for the channels above; "
                        "leave unchecked to leave it alone.")
        hint_bar.attach(self.channel_config_input_dac_value,
                        "Input DAC code (0-255) to write when 'Set input DAC value' "
                        "is checked.")
        hint_bar.attach(self.channel_config_impedance,
                        "Input impedance for all channels: Low (~150 Ohm) or High; "
                        "leave Unchanged to skip it.")
        hint_bar.attach(self.channel_config_restore,
                        "Read back and restore the previous values after applying, "
                        "instead of leaving this configuration in place. Unchecked, "
                        "this configuration persists on the board.")
        hint_bar.attach(self.channel_config_apply_button,
                        "Apply the channel configuration above to the connected hardware.")
