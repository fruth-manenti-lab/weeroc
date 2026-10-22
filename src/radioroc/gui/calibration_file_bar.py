"""Save/Load calibration buttons for the Calibration page. UI only; logic is in
``radioroc.application.calibration_file``."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QSizePolicy, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QWidget)

from radioroc.application import calibration_file as cf



class _ElidedStatusLabel(QLabel):
    """One-line status that keeps the bar a single row; the full text is the tooltip."""

    def __init__(self, text=""):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(60)
        self._full = ""
        self.setText(text)

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        self.setVisible(bool(text))
        self._elide()

    def text(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(self.width(), 60))
        QLabel.setText(self, shown)


class CalibrationFileBar(QWidget):
    def __init__(self, selection, connection_worker, autocalibration_window=None, parent=None,
                 runs_root=None):
        super().__init__(parent)
        self.selection = selection
        self.connection_worker = connection_worker
        self.autocalibration_window = autocalibration_window
        self.runs_root = Path(runs_root) if runs_root is not None else Path.cwd() / "radioroc_runs"
        self.folder = self.runs_root / "calibration"

        self.operating_threshold = QSpinBox()
        self.operating_threshold.setRange(0, 1023)
        self.operating_threshold.setValue(selection.operating_threshold)
        self.operating_threshold.valueChanged.connect(selection.set_operating_threshold)
        selection.operating_threshold_changed.connect(self._show_operating_threshold)
        self.trigger_gain = QSpinBox()
        self.trigger_gain.setRange(1, 63)
        self.trigger_gain.setValue(selection.trigger_gain)
        self.trigger_gain.setAccessibleName("Trigger gain (paT)")
        self.trigger_gain.setToolTip(
            "Trigger preamplifier gain code used by every scan and the acquisition "
            "(1 = highest gain). Thresholds only mean the same pulse height at the same gain.")
        self.trigger_gain.valueChanged.connect(selection.set_trigger_gain)
        selection.trigger_gain_changed.connect(self._show_trigger_gain)
        self.operating_threshold.setAccessibleName("Operating threshold DAC")
        self.hold_delay = QSpinBox()
        self.hold_delay.setRange(0, 100000)
        self.hold_delay.setSingleStep(5)
        self.hold_delay.setValue(selection.hold_delay_ns)
        self.hold_delay.setAccessibleName("Hold delay (ns)")
        self.hold_delay.setToolTip("External hold delay in ns, read off the peak of the Hold scan. "
                                   "Saved in the calibration file and used by the Acquisition page.")
        self.hold_delay.valueChanged.connect(selection.set_hold_delay_ns)
        selection.hold_delay_changed.connect(self._show_hold_delay)
        self.bias_text = QLineEdit()
        self.bias_text.setFixedWidth(64)
        self.bias_text.hide()
        self.bias_text.setAccessibleName("Bias voltage (V)")
        self.note_edit = QLineEdit()
        self.note_edit.hide()
        self.note_edit.setAccessibleName("Note")
        self.save_button = QPushButton("Save calibration…")
        self.load_button = QPushButton("Load calibration…")
        self.status_label = _ElidedStatusLabel("")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(row)
        for text, widget in (("Operating threshold", self.operating_threshold),
                             ("Trigger gain (paT)", self.trigger_gain),
                             ("Hold delay (ns)", self.hold_delay)):
            row.addWidget(QLabel(text))
            row.addWidget(widget)
        row.addWidget(self.save_button)
        row.addWidget(self.load_button)
        row.addStretch(1)
        outer.addWidget(self.status_label)
        tip = ("A calibration file keeps the channels, trigger channels, operating threshold, bias, "
               "hold delay, note and the autocalibration trims. It does NOT keep the whole chip: after a power "
               "cycle, apply defaults first, then load the file to re-apply the trims.")
        self.save_button.setToolTip(tip)
        self.load_button.setToolTip(tip)
        self.save_button.clicked.connect(self._choose_save)
        self.load_button.clicked.connect(self._choose_load)

    def _show_operating_threshold(self, value):
        if self.operating_threshold.value() != value:
            self.operating_threshold.setValue(value)

    def _show_trigger_gain(self, value):
        if self.trigger_gain.value() != value:
            self.trigger_gain.setValue(value)

    def _show_hold_delay(self, value):
        if self.hold_delay.value() != value:
            self.hold_delay.setValue(value)

    # -- dialogs ------------------------------------------------------------
    def _choose_save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save calibration", str(self.folder / cf.default_filename()), "JSON (*.json)")
        if path and self._ask_bias_and_note():
            self.save_to(path)

    def _ask_bias_and_note(self) -> bool:
        """Ask for the bias and note, prefilled with the last values."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Calibration details")
        form = QFormLayout(dialog)
        bias = QLineEdit(self.bias_text.text())
        bias.setAccessibleName("Bias voltage (V)")
        note = QLineEdit(self.note_edit.text())
        note.setMinimumWidth(280)
        note.setAccessibleName("Note")
        form.addRow("Bias (V)", bias)
        form.addRow("Note", note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return False
        self.bias_text.setText(bias.text())
        self.note_edit.setText(note.text())
        return True

    def _choose_load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load calibration", str(self.folder), "JSON (*.json)")
        if path:
            self.load_from(path)

    def _confirm_reapply(self, text) -> bool:
        return QMessageBox.question(
            self, "Re-apply trims to chip", text) == QMessageBox.StandardButton.Yes

    # -- save ---------------------------------------------------------------
    def _autocalibration_directory(self):
        return getattr(self.autocalibration_window, "_active_directory", None)

    def save_to(self, path):
        try:
            autocal, reason = cf.find_autocalibration_trims(
                self._autocalibration_directory(), self.runs_root / "hardware")
            doc = cf.build_document(
                channels=self.selection.channels(),
                trigger_channel=self.selection.trigger_channel,
                trigger_channel_2=self.selection.trigger_channel_2,
                auto_triggers=self.selection.auto_triggers,
                operating_threshold_dac=self.operating_threshold.value(),
                bias_voltage_text=self.bias_text.text(), note=self.note_edit.text(),
                autocalibration=autocal,
                hold_scan={"hold_delay_ns": self.hold_delay.value()},
                trigger_gain_code=self.trigger_gain.value())
            written = cf.save_document(path, doc)
        except Exception as exc:
            self.status_label.setText(f"Could not save the calibration file: {exc}")
            return False
        if autocal:
            self.status_label.setText(
                f"Saved {written.name} with {len(autocal['trims'])} channel trims from "
                f"{autocal['run_directory']}.")
        else:
            self.status_label.setText(
                f"Saved {written.name} WITHOUT trims (settings only): {reason}. "
                "Run Autocalibration first if you want the trims kept.")
        return True

    # -- load ---------------------------------------------------------------
    def load_from(self, path):
        try:
            data = cf.load_document(path)
        except cf.CalibrationFileError as exc:
            self.status_label.setText(f"Could not load {Path(path).name}: {exc}. Nothing was changed.")
            return False
        self.selection.set_channels(data["channels"])
        if data["auto_triggers"]:
            self.selection.set_auto_triggers(True)
        else:
            self.selection.set_trigger_channels(data["trigger_channel"], data["trigger_channel_2"])
        self.selection.set_operating_threshold(data["operating_threshold_dac"])
        if data.get("trigger_gain_code") is not None:
            self.selection.set_trigger_gain(data["trigger_gain_code"])
        hold = data.get("hold_scan") or {}
        if "hold_delay_ns" in hold:
            self.selection.set_hold_delay_ns(hold["hold_delay_ns"])
        self.bias_text.setText(data["bias_voltage_text"])
        self.note_edit.setText(data["note"])
        autocal = data["autocalibration"]
        message = f"Loaded {Path(path).name}. Settings restored; the chip was not changed."
        if not autocal:
            self.status_label.setText(message + " The file has no trims.")
            return True
        message += f" The file has {len(autocal['trims'])} channel trims."
        if not self._connected():
            self.status_label.setText(message + " Connect the board to re-apply them to the chip.")
            return True
        if not self._confirm_reapply(
                f"Write {len(autocal['trims'])} saved {autocal['trim_kind']} trims to the chip "
                f"(channels {sorted(autocal['trims'])})? They are read back to verify."):
            self.status_label.setText(message + " Trims were not re-applied.")
            return True
        self.status_label.setText(message + " " + self._reapply(autocal))
        return True

    def _connected(self) -> bool:
        try:
            return self.connection_worker is not None and \
                self.connection_worker.snapshot().state == "connected"
        except Exception:
            return False

    def _reapply(self, autocal) -> str:
        """Send the trims through the existing verified channel-config path."""
        try:
            self.connection_worker.apply_channel_config(cf.build_reapply_operation(autocal))
        except Exception as exc:
            return f"Re-apply failed: {exc}"
        return ("Re-apply sent to the chip (writes are read back; watch the connection state "
                "for a mismatch fault).")
