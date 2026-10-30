"""The vendor "Main" tab: one channel's analog front end (trigger preamp /
energy measurement) plus the ASIC-wide common thresholds, trigger selection
and delay controls.

Sibling of ``ThresholdCalibrationPanel``, built the same way (same async
apply/poll/show_snapshot pattern), but this vendor tab shows one channel at a
time -- unlike the 64-cell grids in ``ThresholdCalibrationPanel``/
``InputDacGridPanel``/``ProbesMasksPanel`` -- because there is no per-channel
readback path for these registers.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from radioroc.application.channel_config import ChannelConfigOperation
from radioroc.application.asic_config_file import load_asic_config, save_asic_config
from radioroc.application.chip_init import ChipInitOperation

# Packaged default config's channel-0 values (configs/radio_default_i2c.csv,
# subadd 1: "00001000" -> compensation=0, gain=8; subadd 2: "10001000" ->
# high_gain=8, low_gain=8; subadd 3: "01000100" -> high_gain_shaping=4,
# low_gain_shaping=4; subadd 7: "00001111" -> both shaping LSB selects
# unchecked, i.e. 20 ns/code). Used to seed any channel the operator has not
# yet visited, so its fields aren't just zero.
_DEFAULT_CHANNEL_VALUES = {
    "trigger_preamp_compensation": 0,
    "trigger_preamp_gain": 8,
    "high_gain": 8,
    "high_gain_shaping": 4,
    "high_gain_shaping_slow": False,
    "low_gain": 8,
    "low_gain_shaping": 4,
    "low_gain_shaping_slow": False,
}

# Packaged default config's address-65 values. The threshold DACs use the
# hardware-validated layout (subadd 1 = dac1[7:0]; subadd 2 = {dac2[5:0],
# dac1[9:8]}; subadd 3 = {dacQ[3:0], dac2[9:6]}; subadd 4 = {NC*2, dacQ[9:4]}),
# which decodes the defaults to 512 for all three. (An earlier decode gave
# 0 / 2 / 520, and applying the tab unedited then wrote those and broke the
# trigger.) subadd 8 -> delay=255; subadd 9 -> slope=4.
_DEFAULT_T1_THRESHOLD_DAC = 512
_DEFAULT_T2_THRESHOLD_DAC = 512
_DEFAULT_TQ_THRESHOLD_DAC = 512
_DEFAULT_DELAY_CODE = 255
_DEFAULT_DELAY_SLOPE = 4

# Vendor "Trigger selection" combo box order/labels; index maps 1:1 to
# RadiorocDevice.TRIGGER_SELECTION_CODES keys.
_TRIGGER_SELECTION_ITEMS = (
    ("External", "external"),
    ("Local T1", "local_t1"),
    ("Local T2", "local_t2"),
    ("Local TQ", "local_tq"),
    ("Global T1", "global_t1"),
    ("Global T2", "global_t2"),
    ("Global TQ", "global_tq"),
)
_DEFAULT_TRIGGER_SELECTION_INDEX = 4  # "Global T1", matches the packaged default (subadd 12).


def _spinbox(low, high, value):
    field = QSpinBox()
    field.setRange(low, high)
    field.setValue(value)
    return field


class MainPanel(QWidget):
    """Public widgets: ``channel_spin`` (N° channel selector),
    ``compensation_spin``/``preamp_gain_spin`` (Trigger preamplifier),
    ``high_gain_spin``/``high_gain_shaping_spin``/``high_gain_shaping_slow_check``
    and the ``low_gain_*`` equivalents (Energy measurement), ``t1_threshold_spin``/
    ``t2_threshold_spin``/``tq_threshold_spin``/``trigger_selection_combo``/
    ``delay_spin``/``slope_spin`` (Common thresholds and timing), ``apply_button``,
    ``status_label``.

    Unlike ``ThresholdCalibrationPanel``'s 64-cell grids, this panel shows one
    channel's analog front end at a time and there is no per-channel readback
    path, so per-channel edits are accumulated in ``self._channel_values``
    (channel -> field name -> value) as the operator switches channels,
    seeded from ``_DEFAULT_CHANNEL_VALUES`` on first visit. Like
    ``ProbesMasksPanel``, this panel does not own a connection: it is handed
    an existing ``ConnectionWorker`` (or ``None``) via
    ``self.connection_worker``, and has no embedder-specific error routing to
    preserve, so its own Apply button is wired directly here.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker
        self._channel_values: dict[int, dict[str, int | bool]] = {}
        self._current_channel = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("N° channel"))
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, 63)
        channel_row.addWidget(self.channel_spin)
        channel_row.addStretch(1)
        outer.addLayout(channel_row)

        front_end_row = QHBoxLayout()
        front_end_row.addWidget(self._build_preamp_group())
        front_end_row.addWidget(self._build_energy_group())
        outer.addLayout(front_end_row)

        outer.addWidget(self._build_common_group())

        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply)
        outer.addWidget(self.apply_button)
        init_row = QHBoxLayout()
        self.initialize_fpga_button = QPushButton("Initialize FPGA")
        self.initialize_fpga_button.setToolTip(
            "Re-initialize the FPGA control words (persists).")
        self.initialize_fpga_button.clicked.connect(lambda _checked=False: self.initialize_fpga())
        init_row.addWidget(self.initialize_fpga_button)
        self.apply_defaults_button = QPushButton("Apply defaults")
        self.apply_defaults_button.setToolTip(
            "Write packaged default registers; wipes autocalibration trims (persists).")
        self.apply_defaults_button.clicked.connect(lambda _checked=False: self.apply_defaults())
        init_row.addWidget(self.apply_defaults_button)
        self.save_config_button = QPushButton("Save config…")
        self.save_config_button.setToolTip(
            "Read every ASIC register from the chip and save it to a CSV file.")
        self.save_config_button.clicked.connect(lambda _checked=False: self.save_config())
        init_row.addWidget(self.save_config_button)
        self.load_config_button = QPushButton("Load config…")
        self.load_config_button.setToolTip(
            "Write a saved ASIC config file to the chip; wipes autocalibration trims (persists).")
        self.load_config_button.clicked.connect(lambda _checked=False: self.load_config())
        init_row.addWidget(self.load_config_button)
        init_row.addStretch(1)
        outer.addLayout(init_row)
        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self._init_pending = None
        self._save_path = None

        self._load_channel(0)
        self.channel_spin.valueChanged.connect(self._on_channel_changed)

        # apply_channel_config is asynchronous (the worker only enqueues it
        # and returns immediately); showing the snapshot the instant it's
        # submitted reliably shows a stale or empty result, not the one just
        # requested. Poll until the worker leaves its busy state instead.
        self._applying = False
        self.update_controls()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def _build_preamp_group(self):
        group = QGroupBox("Trigger preamplifier (paT)")
        form = QFormLayout(group)
        self.compensation_spin = _spinbox(
            0, 3, _DEFAULT_CHANNEL_VALUES["trigger_preamp_compensation"])
        form.addRow("Compensation", self.compensation_spin)
        self.preamp_gain_spin = _spinbox(0, 63, _DEFAULT_CHANNEL_VALUES["trigger_preamp_gain"])
        form.addRow("Gain", self.preamp_gain_spin)
        return group

    def _build_energy_group(self):
        group = QGroupBox("Energy measurement")
        outer = QVBoxLayout(group)
        (self.high_gain_spin, self.high_gain_shaping_spin,
         self.high_gain_shaping_slow_check) = self._build_gain_subgroup(
            outer, "High gain", "Gain (paHG)", "high_gain", "high_gain_shaping",
            "high_gain_shaping_slow")
        (self.low_gain_spin, self.low_gain_shaping_spin,
         self.low_gain_shaping_slow_check) = self._build_gain_subgroup(
            outer, "Low gain", "Gain (paLG)", "low_gain", "low_gain_shaping",
            "low_gain_shaping_slow")
        return group

    @staticmethod
    def _build_gain_subgroup(outer, title, gain_label, gain_key, shaping_key, slow_key):
        group = QGroupBox(title)
        form = QFormLayout(group)
        gain_spin = _spinbox(0, 15, _DEFAULT_CHANNEL_VALUES[gain_key])
        form.addRow(gain_label, gain_spin)
        shaping_spin = _spinbox(0, 15, _DEFAULT_CHANNEL_VALUES[shaping_key])
        form.addRow("Shaping time", shaping_spin)
        slow_check = QCheckBox("shaping LSB = 120 ns")
        slow_check.setChecked(_DEFAULT_CHANNEL_VALUES[slow_key])
        form.addRow(slow_check)
        outer.addWidget(group)
        return gain_spin, shaping_spin, slow_check

    def _build_common_group(self):
        group = QGroupBox("Common thresholds and timing")
        form = QFormLayout(group)
        self.t1_threshold_spin = _spinbox(0, 1023, _DEFAULT_T1_THRESHOLD_DAC)
        self.t1_threshold_spin.setToolTip("Threshold for trigger T1")
        form.addRow("Threshold1", self.t1_threshold_spin)
        self.t2_threshold_spin = _spinbox(0, 1023, _DEFAULT_T2_THRESHOLD_DAC)
        self.t2_threshold_spin.setToolTip("Threshold for trigger T2")
        form.addRow("Threshold2", self.t2_threshold_spin)
        self.tq_threshold_spin = _spinbox(0, 1023, _DEFAULT_TQ_THRESHOLD_DAC)
        self.tq_threshold_spin.setToolTip("Threshold for trigger TQ")
        form.addRow("ThresholdQ", self.tq_threshold_spin)
        self.trigger_selection_combo = QComboBox()
        self.trigger_selection_combo.addItems([label for label, _ in _TRIGGER_SELECTION_ITEMS])
        self.trigger_selection_combo.setCurrentIndex(_DEFAULT_TRIGGER_SELECTION_INDEX)
        form.addRow("Trigger selection", self.trigger_selection_combo)
        self.delay_spin = _spinbox(0, 255, _DEFAULT_DELAY_CODE)
        form.addRow("Delay", self.delay_spin)
        self.slope_spin = _spinbox(0, 15, _DEFAULT_DELAY_SLOPE)
        form.addRow("Slope", self.slope_spin)
        return group

    def _save_current_channel(self):
        """Save the on-screen values for ``self._current_channel`` into
        ``self._channel_values``. Called on every channel-selector change and
        again by ``build_operation`` (which may be invoked without a
        preceding channel switch), so both paths see consistent state."""
        self._channel_values[self._current_channel] = {
            "trigger_preamp_compensation": self.compensation_spin.value(),
            "trigger_preamp_gain": self.preamp_gain_spin.value(),
            "high_gain": self.high_gain_spin.value(),
            "high_gain_shaping": self.high_gain_shaping_spin.value(),
            "high_gain_shaping_slow": self.high_gain_shaping_slow_check.isChecked(),
            "low_gain": self.low_gain_spin.value(),
            "low_gain_shaping": self.low_gain_shaping_spin.value(),
            "low_gain_shaping_slow": self.low_gain_shaping_slow_check.isChecked(),
        }

    def _load_channel(self, channel):
        values = self._channel_values.get(channel, dict(_DEFAULT_CHANNEL_VALUES))
        self.compensation_spin.setValue(values["trigger_preamp_compensation"])
        self.preamp_gain_spin.setValue(values["trigger_preamp_gain"])
        self.high_gain_spin.setValue(values["high_gain"])
        self.high_gain_shaping_spin.setValue(values["high_gain_shaping"])
        self.high_gain_shaping_slow_check.setChecked(values["high_gain_shaping_slow"])
        self.low_gain_spin.setValue(values["low_gain"])
        self.low_gain_shaping_spin.setValue(values["low_gain_shaping"])
        self.low_gain_shaping_slow_check.setChecked(values["low_gain_shaping_slow"])
        self._current_channel = channel

    def _on_channel_changed(self, channel):
        self._save_current_channel()
        self._load_channel(channel)

    def build_operation(self):
        self._save_current_channel()
        _, mode = _TRIGGER_SELECTION_ITEMS[self.trigger_selection_combo.currentIndex()]
        operation = ChannelConfigOperation(
            trigger_preamp_gain_values={
                ch: v["trigger_preamp_gain"] for ch, v in self._channel_values.items()},
            trigger_preamp_compensation_values={
                ch: v["trigger_preamp_compensation"] for ch, v in self._channel_values.items()},
            high_gain_values={ch: v["high_gain"] for ch, v in self._channel_values.items()},
            low_gain_values={ch: v["low_gain"] for ch, v in self._channel_values.items()},
            high_gain_shaping_values={
                ch: v["high_gain_shaping"] for ch, v in self._channel_values.items()},
            low_gain_shaping_values={
                ch: v["low_gain_shaping"] for ch, v in self._channel_values.items()},
            high_gain_shaping_slow_states={
                ch: v["high_gain_shaping_slow"] for ch, v in self._channel_values.items()},
            low_gain_shaping_slow_states={
                ch: v["low_gain_shaping_slow"] for ch, v in self._channel_values.items()},
            t1_threshold_dac=self.t1_threshold_spin.value(),
            t2_threshold_dac=self.t2_threshold_spin.value(),
            tq_threshold_dac=self.tq_threshold_spin.value(),
            trigger_selection=mode,
            delay_code=self.delay_spin.value(),
            delay_slope=self.slope_spin.value(),
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
            self.status_label.setText(f"Invalid main configuration: {exc}")
            return None
        try:
            self.connection_worker.apply_channel_config(operation)
        except Exception as exc:
            self.status_label.setText(f"Main apply error · {type(exc).__name__}: {exc}")
            return None
        self._applying = True
        self.status_label.setText("Applying…")
        self.update_controls()
        self.timer.start()
        return operation

    def _poll(self):
        if self.connection_worker is None:
            self.timer.stop()
            self._applying = False
            self._init_pending = None
            self.update_controls()
            return
        snapshot = self.connection_worker.snapshot()
        if snapshot.state in ("configuring", "reading"):
            return  # still in flight
        self.timer.stop()
        self._applying = False
        if self._save_path is not None:
            self._finish_save(snapshot)
            self.update_controls()
            return
        if self._init_pending is not None:
            label, self._init_pending = self._init_pending, None
            error = getattr(snapshot, "error", None) or getattr(snapshot, "fault", None)
            if snapshot.state == "connected" and not error:
                self.status_label.setText(f"{label}: done")
            else:
                self.status_label.setText(f"{label} FAILED · {error or snapshot.state}")
        else:
            self.show_snapshot()
        self.update_controls()

    def update_controls(self):
        """Enable the chip-init buttons only when connected and idle."""
        worker = self.connection_worker
        ready = (worker is not None and not self._applying
                 and worker.snapshot().state == "connected")
        self.initialize_fpga_button.setEnabled(ready)
        self.apply_defaults_button.setEnabled(ready)
        self.save_config_button.setEnabled(ready)
        self.load_config_button.setEnabled(ready)

    def initialize_fpga(self):
        return self._run_chip_init(
            ChipInitOperation(initialize_fpga=True), "Initialize FPGA", None)

    def apply_defaults(self):
        return self._run_chip_init(
            ChipInitOperation(apply_defaults=True), "Apply defaults",
            "Apply defaults resets every setting on the chip to the packaged "
            "defaults and wipes autocalibration trims. Continue?")

    def save_config(self, path=None):
        """Read every register back from the chip and save the table as CSV."""
        worker = self.connection_worker
        if worker is None or self._applying:
            return None
        if worker.snapshot().state != "connected":
            self.status_label.setText("Save config: not connected")
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save ASIC config", "asic_config.csv", "ASIC config (*.csv)")
            if not path:
                self.status_label.setText("Save config: cancelled")
                return None
        try:
            worker.read_all_registers()
        except Exception as exc:
            self.status_label.setText(f"Save config error · {type(exc).__name__}: {exc}")
            return None
        self._save_path = path
        self._applying = True
        self.status_label.setText("Reading ASIC registers…")
        self.update_controls()
        self.timer.start()
        return path

    def _finish_save(self, snapshot):
        path, self._save_path = self._save_path, None
        error = getattr(snapshot, "error", None) or getattr(snapshot, "fault", None)
        rows = self.connection_worker.raw_registers_snapshot()
        if snapshot.state != "connected" or error or not rows:
            self.status_label.setText(f"Save config FAILED · {error or snapshot.state}")
            return
        try:
            count = save_asic_config(rows, path)
        except OSError as exc:
            self.status_label.setText(f"Save config FAILED · {exc}")
            return
        self.status_label.setText(f"Saved {count} registers to {path}")

    def load_config(self, path=None):
        """Write a saved ASIC config file to the chip (replaces every setting)."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load ASIC config", "", "ASIC config (*.csv)")
            if not path:
                return None
        try:
            rows = load_asic_config(path)
        except ValueError as exc:
            self.status_label.setText(f"Load config: {exc}")
            return None
        return self._run_chip_init(
            ChipInitOperation(apply_defaults=True, config_path=path), "Load config",
            f"Load config writes {len(rows)} registers from {path} to the chip, "
            "replacing every setting and wiping autocalibration trims. Continue?")

    def _confirm(self, text):
        return QMessageBox.question(
            self, "Apply defaults", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _run_chip_init(self, operation, label, confirm_text):
        worker = self.connection_worker
        if worker is None or self._applying:
            return None
        if worker.snapshot().state != "connected":
            self.status_label.setText(f"{label}: not connected")
            return None
        if confirm_text is not None and not self._confirm(confirm_text):
            self.status_label.setText(f"{label}: cancelled")
            return None
        try:
            worker.chip_init(operation)
        except Exception as exc:
            self.status_label.setText(f"{label} error · {type(exc).__name__}: {exc}")
            return None
        self._applying = True
        self._init_pending = label
        self.status_label.setText(f"{label}…")
        self.update_controls()
        self.timer.start()
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
            "Main: " + "; ".join(parts) + (
                (" · " + "; ".join(result.applied)) if result.applied else ""))

    def attach_hints(self, hint_bar):
        """Wire hover-hint text for this panel's controls into ``hint_bar``."""
        hint_bar.attach(self.channel_spin,
                        "Channel whose analog front end the fields below show/edit.")
        hint_bar.attach(self.compensation_spin,
                        "Trigger preamplifier (paT) compensation code (0-3); leave at 0 "
                        "unless you know you need otherwise.")
        hint_bar.attach(self.preamp_gain_spin,
                        "Trigger preamplifier (paT) gain code (1=max gain, 63=min gain, "
                        "0=open loop).")
        hint_bar.attach(self.high_gain_spin, "Energy measurement high-gain (paHG) code.")
        hint_bar.attach(self.high_gain_shaping_spin,
                        "High-gain shaping time code; actual time is this code times "
                        "20 ns or 120 ns, depending on the shaping-LSB checkbox.")
        hint_bar.attach(self.high_gain_shaping_slow_check,
                        "Use 120 ns per code for high-gain shaping instead of 20 ns.")
        hint_bar.attach(self.low_gain_spin, "Energy measurement low-gain (paLG) code.")
        hint_bar.attach(self.low_gain_shaping_spin,
                        "Low-gain shaping time code; actual time is this code times "
                        "20 ns or 120 ns, depending on the shaping-LSB checkbox.")
        hint_bar.attach(self.low_gain_shaping_slow_check,
                        "Use 120 ns per code for low-gain shaping instead of 20 ns.")
        hint_bar.attach(self.t1_threshold_spin, "Threshold for trigger T1 (ASIC-wide, "
                        "not per channel).")
        hint_bar.attach(self.t2_threshold_spin, "Threshold for trigger T2 (ASIC-wide, "
                        "not per channel).")
        hint_bar.attach(self.tq_threshold_spin, "Threshold for trigger TQ (ASIC-wide, "
                        "not per channel).")
        hint_bar.attach(self.trigger_selection_combo,
                        "Which trigger source feeds the readout (ASIC-wide).")
        hint_bar.attach(self.delay_spin, "Trigger delay code (ASIC-wide).")
        hint_bar.attach(self.slope_spin, "Trigger delay slope code (ASIC-wide).")
        hint_bar.attach(self.apply_button,
                        "Apply the front-end and common-threshold settings above to "
                        "the connected hardware.")
        hint_bar.attach(self.initialize_fpga_button,
                        "Re-initialize the FPGA control words (same as the scan option "
                        "'Initialize FPGA'). Persists on the board.")
        hint_bar.attach(self.save_config_button,
                        "Read all ASIC registers from the chip and save them as a CSV file "
                        "you can load again later.")
        hint_bar.attach(self.load_config_button,
                        "Write a saved ASIC config CSV to the chip. Resets every setting and "
                        "wipes autocalibration trims.")
        hint_bar.attach(self.apply_defaults_button,
                        "Write the packaged default registers to the chip (same as the scan "
                        "option 'Apply defaults'). Resets every setting and wipes "
                        "autocalibration trims.")
