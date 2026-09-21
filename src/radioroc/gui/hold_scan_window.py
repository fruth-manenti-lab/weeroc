"""Hold-scan controls and presentation; measurement belongs to the shared job.

This mirrors ``radioroc.gui.threshold_window.ThresholdWindow`` field-for-field
and behavior-for-behavior wherever the two workflows share a shape (connection
management, channel config, preview/run/cancel/close, saved-run reopen). See
that module for the design rationale of each piece.
"""

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from radioroc_client import FPGA_IO_NAMES, HoldScanConfig, parse_channels
from radioroc.application.channel_config import ChannelConfigOperation
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig
from radioroc.application.hold_scan_worker import HoldScanWorker
from radioroc.data.hold_reader import read_hold_run
from radioroc.transport.config import (
    DEFAULT_BAUD, DEFAULT_TIMEOUT_SECONDS, RadiorocConnectionConfig,
)
from radioroc.transport.hold_scan_simulator import HoldSimulationConfig


def _integer(low, high, value):
    field = QSpinBox()
    field.setRange(low, high)
    field.setValue(value)
    return field


def _decimal(low, high, value):
    field = QDoubleSpinBox()
    field.setDecimals(3)
    field.setRange(low, high)
    field.setValue(value)
    return field


def _new_directory(execution_mode="simulation"):
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return str(Path.cwd() / "radioroc_runs" / execution_mode / name)


class HoldScanWindow(QMainWindow):
    _CONNECTION_BUSY = {"discovering", "connecting", "reading", "disconnecting", "scanning",
                        "configuring"}
    _CONNECTION_LOCKS_MODE = _CONNECTION_BUSY | {"connected", "close_failed", "faulted"}

    def __init__(self, *, worker_factory=HoldScanWorker,
                 connection_worker_factory=ConnectionWorker):
        super().__init__()
        self.setWindowTitle("RADIOROC · Hold-scan workflow")
        self.resize(1180, 820)
        self.worker_factory = worker_factory
        self.worker = None
        self.connection_worker_factory = connection_worker_factory
        self.connection_worker = None
        self._connection_ports = ()
        self._accepted_mode = 0
        self._closing = False
        self._last_rows = ()
        self._active_directory = None
        self._hardware_running = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("RADIOROC  |  Hold-scan workflow")
        title.setStyleSheet("font-size: 22px; font-weight: 600; padding: 8px 0")
        layout.addWidget(title)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background: #173e58; color: white; padding: 10px; border-radius: 5px")
        layout.addWidget(self.banner)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.controls = QWidget()
        scroll.setWidget(self.controls)
        form = QFormLayout(self.controls)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = QComboBox()
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(12)
        self.mode.addItems(["Simulation", "Hardware connection"])
        form.addRow("Device / mode", self.mode)

        self.connection_group = QGroupBox("Hardware connection")
        connection_form = QFormLayout(self.connection_group)
        connection_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        connection_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.port_select = QComboBox()
        self.port_select.addItem("Select a USB port candidate…", None)
        self.port_select.currentIndexChanged.connect(self._update_connection_controls)
        connection_form.addRow("Port", self.port_select)
        self.baud = _integer(1, 100_000_000, DEFAULT_BAUD)
        self.timeout_s = _decimal(0.001, 3600, DEFAULT_TIMEOUT_SECONDS)
        connection_form.addRow("Baud", self.baud)
        connection_form.addRow("Timeout (s)", self.timeout_s)
        connection_buttons_top = QHBoxLayout()
        connection_buttons_bottom = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.read_status_button = QPushButton("Read status")
        self.disconnect_button = QPushButton("Disconnect")
        self.review_fault_button = QPushButton("Acknowledge fault review")
        connection_buttons_top.addWidget(self.refresh_button)
        connection_buttons_top.addWidget(self.connect_button)
        connection_buttons_bottom.addWidget(self.read_status_button)
        connection_buttons_bottom.addWidget(self.disconnect_button)
        connection_buttons_bottom.addWidget(self.review_fault_button)
        connection_form.addRow(connection_buttons_top)
        connection_form.addRow(connection_buttons_bottom)
        self.connection_status = QLabel("Not connected · refresh to list USB port candidates")
        self.connection_status.setWordWrap(True)
        self.connection_status.setMinimumHeight(42)
        connection_form.addRow(self.connection_status)
        self.firmware_status = QLabel("—")
        connection_form.addRow("Firmware status", self.firmware_status)
        form.addRow(self.connection_group)

        self.channel_config_group = QGroupBox("Input DAC / TQ mask (persists unless Restore is checked)")
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
        form.addRow(self.channel_config_group)

        self.channels = QLineEdit("4,5")
        self.trigger_channel = _integer(0, 63, 4)
        self.hold_mode = QComboBox()
        self.hold_mode.addItems(["Internal (ASIC delay-cell code)", "External (FPGA delay, ns)"])
        self.hold_mode.setCurrentIndex(1)
        self.hold_min = _integer(0, 20475, 0)
        self.hold_max = _integer(0, 20475, 800)
        self.hold_step = _integer(1, 20475, 25)
        self.acquisitions = _integer(1, 255, 10)
        self.timeout_s_scan = _decimal(0.001, 3600, 5.0)
        self.discriminator = QComboBox()
        self.discriminator.addItems(["T1", "T2"])
        # threshold_dac's valid range (0..1023) includes 0, so a spinbox
        # special-value sentinel would collide with a legitimate value;
        # use an explicit checkbox instead, matching the channel-config
        # group's "set this value" pattern above.
        self.set_threshold_dac = QCheckBox("Set threshold DAC before scan")
        self.threshold_dac = _integer(0, 1023, 0)
        threshold_dac_row = QHBoxLayout()
        threshold_dac_row.addWidget(self.set_threshold_dac)
        threshold_dac_row.addWidget(self.threshold_dac)
        for label, field in [("Channels (comma separated)", self.channels),
                             ("Trigger channel", self.trigger_channel),
                             ("Hold mode", self.hold_mode),
                             ("First hold code / delay (ns)", self.hold_min),
                             ("Last hold code / delay (ns)", self.hold_max),
                             ("Hold step", self.hold_step),
                             ("Acquisitions per point", self.acquisitions),
                             ("Per-batch timeout (s)", self.timeout_s_scan),
                             ("Discriminator", self.discriminator)]:
            form.addRow(label, field)
        form.addRow("Threshold DAC", threshold_dac_row)
        self.mask = QCheckBox("Mask other channels")
        self.mask.setChecked(True)
        self.ctest = QCheckBox("Enable Ctest")
        self.synchro_trigger = QCheckBox("Pulse FPGA synchro trigger per ADC batch")
        self.initialize = QCheckBox("Initialize FPGA (persists)")
        self.defaults = QCheckBox("Apply defaults (persists)")
        for field in (self.mask, self.ctest, self.synchro_trigger, self.initialize, self.defaults):
            form.addRow(field)
        self.sync_io = QComboBox()
        self.sync_io.addItems(list(FPGA_IO_NAMES))
        self.sync_io.setCurrentText("io1")
        form.addRow("Sync IO", self.sync_io)
        self.set_sync_io_mux = QCheckBox("Set sync IO mux index before scan")
        self.sync_io_mux_index = _integer(0, 7, 5)
        sync_io_mux_row = QHBoxLayout()
        sync_io_mux_row.addWidget(self.set_sync_io_mux)
        sync_io_mux_row.addWidget(self.sync_io_mux_index)
        form.addRow("Sync IO mux index", sync_io_mux_row)

        self.external_group = QGroupBox("External hold mode ADC timing")
        external_form = QFormLayout(self.external_group)
        self.conversion_delay_ns = _integer(0, 10000, 400)
        self.trigger_type = _integer(0, 3, 0)
        self.trigger_source = _integer(0, 7, 3)
        self.adc_window_ns = _integer(0, 10000, 50)
        self.adc_nb_trig = _integer(0, 63, 1)
        self.rstn_manual = QCheckBox("Reset-n manual")
        self.external_trigger = QCheckBox("Use external ASIC acquisition trigger")
        self.peak_sensing = QCheckBox("Use vendor peak-sensing path")
        for label, field in [("Conversion delay (ns)", self.conversion_delay_ns),
                             ("Trigger type", self.trigger_type),
                             ("Trigger source", self.trigger_source),
                             ("ADC window (ns)", self.adc_window_ns),
                             ("ADC trigger count", self.adc_nb_trig)]:
            external_form.addRow(label, field)
        for field in (self.rstn_manual, self.external_trigger, self.peak_sensing):
            external_form.addRow(field)
        form.addRow(self.external_group)

        self.gain_group = QGroupBox("Optional gain overrides")
        gain_form = QFormLayout(self.gain_group)
        self.trigger_preamp_gain = _integer(0, 63, 0)
        self.trigger_preamp_gain.setSpecialValueText("Keep current")
        self.high_gain_code = _integer(0, 15, 0)
        self.high_gain_code.setSpecialValueText("Keep current")
        self.low_gain_code = _integer(0, 15, 0)
        self.low_gain_code.setSpecialValueText("Keep current")
        for label, field in [("Trigger preamp gain code", self.trigger_preamp_gain),
                             ("High-gain shaper code", self.high_gain_code),
                             ("Low-gain shaper code", self.low_gain_code)]:
            gain_form.addRow(label, field)
        form.addRow(self.gain_group)

        self.config_path = QLineEdit()
        self.config_path.setPlaceholderText("Packaged defaults")
        form.addRow("ASIC CSV (optional)", self.config_path)
        self.output = QLineEdit(_new_directory())
        self.output.setMinimumWidth(220)
        form.addRow("New run directory", self.output)
        self.new_output = QPushButton("Choose output parent…")
        self.new_output.clicked.connect(self.choose_output)
        form.addRow(self.new_output)

        self.sim_group = QGroupBox("Synthetic track-and-hold curve (qualitative, not physics-validated)")
        sim_form = QFormLayout(self.sim_group)
        sim_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.baseline_counts = _decimal(0, 1e6, 125)
        self.peak_counts = _decimal(0, 1e6, 800)
        self.rise_width = _decimal(0.001, 1e6, 15)
        self.fall_width = _decimal(0.001, 1e6, 20)
        self.low_gain_ratio = _decimal(0, 10, 0.15)
        for label, field in [("Baseline (counts)", self.baseline_counts), ("Peak (counts)", self.peak_counts),
                             ("Rising-edge width", self.rise_width), ("Falling-edge width", self.fall_width),
                             ("Low-gain ratio", self.low_gain_ratio)]:
            sim_form.addRow(label, field)
        form.addRow(self.sim_group)
        split.addWidget(scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.figure = Figure(figsize=(6, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        right_layout.addWidget(self.canvas, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Preview, run provenance and cleanup details appear here.")
        right_layout.addWidget(self.details, 2)
        split.addWidget(right)
        split.setSizes([410, 750])

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.run_button = QPushButton("Run simulation")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.reopen_button = QPushButton("Open saved result…")
        for button in (self.preview_button, self.run_button, self.cancel_button, self.reopen_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview_button.clicked.connect(self.preview)
        self.run_button.clicked.connect(self.start_run)
        self.cancel_button.clicked.connect(self.cancel_run)
        self.reopen_button.clicked.connect(self.choose_saved)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.hold_mode.currentIndexChanged.connect(self._hold_mode_changed)
        self.refresh_button.clicked.connect(self.refresh_connections)
        self.connect_button.clicked.connect(self.connect_hardware)
        self.read_status_button.clicked.connect(self.read_hardware_status)
        self.disconnect_button.clicked.connect(self.disconnect_hardware)
        self.review_fault_button.clicked.connect(self.review_hardware_fault)
        self.channel_config_apply_button.clicked.connect(self.apply_channel_config)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll_worker)
        self.connection_timer = QTimer(self)
        self.connection_timer.setInterval(100)
        self.connection_timer.timeout.connect(self.poll_connection_worker)
        self._mode_changed()
        self._hold_mode_changed()
        self._plot((), "hold_delay_ns", "Simulation — no data yet")

    def _mode_changed(self):
        previous_mode = self._accepted_mode
        requested = self.mode.currentIndex()
        if requested != self._accepted_mode and self._mode_switch_locked():
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self._accepted_mode)
            self.mode.blockSignals(False)
            self.connection_status.setText(
                "Finish the active session before changing device mode.")
        else:
            self._accepted_mode = requested
        simulation = self.mode.currentIndex() == 0
        self._show_mode_banner()
        if not simulation and previous_mode != self._accepted_mode:
            self.initialize.setChecked(False)
            self.defaults.setChecked(False)
            if "radioroc_runs" in Path(self.output.text()).parts:
                self.output.setText(_new_directory("hardware"))
        self.run_button.setText("Run simulation" if simulation else "Run hardware hold scan")
        self.sim_group.setEnabled(simulation and self.worker is None)
        self._update_connection_controls()

    def _hold_mode_changed(self):
        internal = self.hold_mode.currentIndex() == 0
        self.external_group.setEnabled(not internal)
        # Keep the default range/step sensible when switching between modes,
        # mirroring scripts/radioroc_hold_scan.py's per-mode defaults.
        if internal:
            self.hold_min.setRange(0, 255)
            self.hold_max.setRange(0, 255)
            if self.hold_max.value() > 255:
                self.hold_max.setValue(255)
            self.hold_step.setValue(min(self.hold_step.value(), 5))
        else:
            self.hold_min.setRange(0, 20475)
            self.hold_max.setRange(0, 20475)

    def _show_mode_banner(self):
        self.banner.setText(
            "SIMULATION · Synthetic ADC counts, not measured lab data. No board connection."
            if self.mode.currentIndex() == 0 else
            "HARDWARE · USB candidates are unverified. FPGA initialization and apply-defaults "
            "are off by default; masking/Ctest/gain are temporary scan settings. Restoration readback "
            "verification is mandatory. Initialization and defaults are persistent changes.")

    def _show_run_banner(self, mode, directory):
        self.banner.setText(
            f"{mode} · RUN · {directory} · Results shown here are from this run."
        )

    def _mode_switch_locked(self):
        if self.worker is not None:
            return True
        if self.connection_worker is None:
            return False
        return self.connection_worker.snapshot().state in self._CONNECTION_LOCKS_MODE

    def _ensure_connection_worker(self):
        if self.connection_worker is None:
            worker = self.connection_worker_factory()
            worker.start()
            self.connection_worker = worker
            self.connection_timer.start()
        return self.connection_worker

    def _connection_command(self, command):
        try:
            command(self._ensure_connection_worker())
            self.poll_connection_worker()
        except Exception as exc:
            self.connection_status.setText(
                f"Connection error · {type(exc).__name__}: {exc}")
            self._update_connection_controls()

    def refresh_connections(self):
        if self.mode.currentIndex() == 1 and self.worker is None and not self._hardware_running:
            self._connection_command(lambda worker: worker.refresh())

    def connect_hardware(self):
        candidate = self.port_select.currentData()
        if (self.mode.currentIndex() != 1 or candidate is None or self.worker is not None
                or self._hardware_running):
            return
        config = RadiorocConnectionConfig(candidate.port, self.baud.value(), self.timeout_s.value())
        self._connection_command(lambda worker: worker.connect(config))

    def read_hardware_status(self):
        if self.mode.currentIndex() == 1:
            self._connection_command(lambda worker: worker.read_status())

    def disconnect_hardware(self):
        if self.connection_worker is not None:
            self._connection_command(lambda worker: worker.disconnect())

    def review_hardware_fault(self):
        if self.connection_worker is not None:
            self._connection_command(lambda worker: worker.review_fault())

    def apply_channel_config(self):
        if self.mode.currentIndex() != 1 or self.connection_worker is None:
            return
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
        try:
            operation.validate()
        except ValueError as exc:
            self.channel_config_status.setText(f"Invalid channel configuration: {exc}")
            return
        self._connection_command(lambda worker: worker.apply_channel_config(operation))

    def _show_channel_config_snapshot(self):
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

    def _show_connection_snapshot(self, snapshot):
        state = snapshot.state
        if state == "idle":
            message = "Not connected"
            if snapshot.ports:
                message += f" · {len(snapshot.ports)} board candidate(s)"
            else:
                message += " · no board candidates found"
            retained = [problem for problem in (snapshot.error, snapshot.close_error) if problem]
            if retained:
                message += " · previous errors: " + "; ".join(retained)
        elif state == "connected":
            message = f"Connected · {snapshot.port}"
        elif state == "faulted":
            message = f"Hardware fault · {snapshot.fault or snapshot.error or 'review required'}"
        elif state == "close_failed":
            problems = [problem for problem in (snapshot.error, snapshot.close_error) if problem]
            message = f"Close failed · {'; '.join(problems)} · retry close"
        elif state == "error":
            message = f"Connection error · {snapshot.error}"
        elif state == "stopped":
            message = "Connection worker stopped"
        else:
            message = state.replace("_", " ").capitalize()
            if snapshot.port:
                message += f" · {snapshot.port}"
        if getattr(snapshot, "fault", None) and state != "faulted":
            message += f" · fault review required: {snapshot.fault}"
        self.connection_status.setText(message)
        self.firmware_status.setText(
            "—" if snapshot.status_word is None
            else f"0x{snapshot.status_word:02X} ({snapshot.status_word})")

    def _sync_connection_ports(self, ports):
        ports = tuple(ports)
        if ports == self._connection_ports:
            return
        selected = self.port_select.currentData()
        selected_port = selected.port if selected is not None else None
        self._connection_ports = ports
        self.port_select.blockSignals(True)
        self.port_select.clear()
        self.port_select.addItem("Select a USB port candidate…", None)
        selected_index = 0
        for candidate in ports:
            label = candidate.port
            if candidate.description:
                label += f" — {candidate.description}"
            self.port_select.addItem(label, candidate)
            if candidate.port == selected_port:
                selected_index = self.port_select.count() - 1
        self.port_select.setCurrentIndex(selected_index)
        self.port_select.blockSignals(False)

    def poll_connection_worker(self):
        worker = self.connection_worker
        if worker is None:
            return
        # A persistent worker can stop immediately after a shutdown queued
        # behind a scan.  Consume its terminal hold-scan snapshot before
        # dropping the owner and losing the partial-result/fault summary.
        if self._hardware_running:
            self.poll_worker()
        snapshot = worker.snapshot()
        self._sync_connection_ports(snapshot.ports)
        self._show_connection_snapshot(snapshot)
        self._show_channel_config_snapshot()
        if snapshot.state == "close_failed" and self._closing:
            # A failed window-close attempt stays open for review. A later close
            # event is the explicit request to try shutdown again.
            self._closing = False
        if snapshot.state == "stopped" and not worker.is_alive:
            worker.join()
            self.connection_worker = None
            self.connection_timer.stop()
            self._connection_ports = ()
            if self._closing:
                self.close()
                return
        self._update_connection_controls()

    def _update_connection_controls(self):
        hardware = self.mode.currentIndex() == 1
        state = "idle"
        if self.connection_worker is not None:
            state = self.connection_worker.snapshot().state
        busy = state in self._CONNECTION_BUSY
        fault = getattr(self.connection_worker.snapshot(), "fault", None) if self.connection_worker else None
        session = state in {"connected", "close_failed", "faulted"}
        simulation_available = self.worker is None and not busy and not session
        commands_available = not self._closing
        self.mode.setEnabled(commands_available and self.worker is None and not busy and not session)
        self.connection_group.setEnabled(hardware and self.worker is None)
        selectable = commands_available and not busy and not session and not fault
        self.port_select.setEnabled(selectable)
        self.baud.setEnabled(selectable)
        self.timeout_s.setEnabled(selectable)
        self.refresh_button.setEnabled(selectable)
        self.connect_button.setEnabled(selectable and
                                       self.port_select.currentData() is not None)
        self.read_status_button.setEnabled(commands_available and state == "connected")
        self.disconnect_button.setEnabled(commands_available and state in {"connected", "close_failed", "faulted"})
        self.disconnect_button.setText("Retry close" if state == "close_failed" else "Disconnect")
        self.review_fault_button.setEnabled(commands_available and not busy and bool(fault) and
                                            state in {"idle", "error"})
        hardware_run_available = (self.worker is None and not self._hardware_running and
                                  state == "connected" and not fault
                                  and not self._closing)
        self.run_button.setEnabled((self.mode.currentIndex() == 0 and simulation_available) or
                                   (self.mode.currentIndex() == 1 and hardware_run_available))
        self.channel_config_group.setEnabled(hardware)
        self.channel_config_apply_button.setEnabled(hardware_run_available)

    def operation(self):
        channels = [int(value.strip()) for value in self.channels.text().split(",")]
        output = self.output.text().strip()
        if not output:
            raise ValueError("choose a new run directory")
        mode = "internal" if self.hold_mode.currentIndex() == 0 else "external"
        scan = HoldScanConfig(
            mode=mode, channels=channels, trigger_channel=self.trigger_channel.value(),
            hold_min=self.hold_min.value(), hold_max=self.hold_max.value(),
            hold_step=self.hold_step.value(),
            threshold_dac=self.threshold_dac.value() if self.set_threshold_dac.isChecked() else None,
            acquisitions=self.acquisitions.value(), conversion_delay_ns=self.conversion_delay_ns.value(),
            trigger_type=self.trigger_type.value(), trigger_source=self.trigger_source.value(),
            rstn_manual=self.rstn_manual.isChecked(), external_trigger=self.external_trigger.isChecked(),
            peak_sensing=self.peak_sensing.isChecked(), adc_window_ns=self.adc_window_ns.value(),
            adc_nb_trig=self.adc_nb_trig.value(), timeout_s=self.timeout_s_scan.value(),
            synchro_trigger=self.synchro_trigger.isChecked(),
            sync_io=self.sync_io.currentText(),
            sync_io_mux_index=self.sync_io_mux_index.value() if self.set_sync_io_mux.isChecked() else None,
            t1=self.discriminator.currentIndex() == 0, use_mask=self.mask.isChecked(),
            use_ctest=self.ctest.isChecked(), trigger_preamp_gain=self.trigger_preamp_gain.value() or None,
            high_gain_code=self.high_gain_code.value() or None,
            low_gain_code=self.low_gain_code.value() or None, out_dir=Path(output).expanduser(),
        )
        config = self.config_path.text().strip()
        return HoldScanJobConfig(scan, Path(config).expanduser() if config else None,
                                 self.initialize.isChecked(), self.defaults.isChecked())

    def simulation(self):
        settings = HoldSimulationConfig(
            baseline_counts=self.baseline_counts.value(), peak_counts=self.peak_counts.value(),
            rise_width=self.rise_width.value(), fall_width=self.fall_width.value(),
            low_gain_ratio=self.low_gain_ratio.value(),
        )
        settings.validate()
        return settings

    def preview(self):
        try:
            operation = self.operation()
            data = HoldScanJob.preview(operation)
            simulation = self.mode.currentIndex() == 0
            data["selected_mode"] = "simulation" if simulation else "hardware"
            if simulation:
                data["simulation"] = self.simulation().as_dict()
            else:
                candidate = self.port_select.currentData()
                data["hardware"] = {
                    "port": candidate.port if candidate is not None else None,
                    "connection_state": (self.connection_worker.snapshot().state
                                         if self.connection_worker is not None else "idle"),
                    "hold_scan_available": (self.connection_worker is not None and
                                            self.connection_worker.snapshot().state == "connected" and
                                            not getattr(self.connection_worker.snapshot(), "fault", None)),
                    "restoration_verification": "mandatory",
                }
            self.details.setPlainText(json.dumps(data, indent=2))
            self.status.setText(f"Preview valid · {data['total_points']} hold points · no output created")
            return operation
        except Exception as exc:
            self.status.setText(f"Preview failed: {exc}")
            return None

    def start_run(self):
        if self.worker is not None or self._hardware_running:
            return
        operation = self.preview()
        if operation is None:
            return
        x_name = "hold_code" if operation.scan.mode == "internal" else "hold_delay_ns"
        if self.mode.currentIndex() == 1:
            worker = self.connection_worker
            if (worker is None or worker.snapshot().state != "connected" or
                    getattr(worker.snapshot(), "fault", None)):
                return
            try:
                self._last_rows = ()
                self._active_directory = Path(operation.scan.out_dir)
                self.progress.setValue(0)
                self._show_run_banner("HARDWARE", self._active_directory)
                self._plot((), x_name, "HARDWARE · running hold scan")
                self._hardware_running = True
                self._set_running(True)
                self.status.setText("Hardware · preparing · mandatory restoration verification")
                worker.run_hold_scan(operation)
                self.timer.start()
            except Exception as exc:
                self._hardware_running = False
                self._set_running(False)
                self.status.setText(f"Could not start hardware scan: {exc}")
            return
        try:
            worker = self.worker_factory(operation, self.simulation())
            self._last_rows = ()
            self._active_directory = Path(operation.scan.out_dir)
            self._mode_changed()
            self.progress.setValue(0)
            self._show_run_banner("SIMULATION", self._active_directory)
            self._plot((), x_name, "SIMULATION · running")
            self.worker = worker
            self._set_running(True)
            self.status.setText("Simulation · preparing")
            worker.start()
            self.timer.start()
        except Exception as exc:
            self.worker = None
            self._set_running(False)
            self.status.setText(f"Could not start: {exc}")

    def _set_running(self, running):
        self.controls.setEnabled(not running)
        self.preview_button.setEnabled(not running)
        self.reopen_button.setEnabled(not running)
        self.run_button.setEnabled(not running and ((self.mode.currentIndex() == 0) or
                                   (self.connection_worker is not None and
                                    self.connection_worker.snapshot().state == "connected" and
                                    not getattr(self.connection_worker.snapshot(), "fault", None))))
        self.cancel_button.setEnabled(running)

    def cancel_run(self):
        if self.worker:
            self.worker.cancel()
        elif self.connection_worker is not None:
            try:
                self.connection_worker.cancel_hold_scan()
            except Exception:
                return
        else:
            return

        if self.worker or self.connection_worker is not None:
            self.cancel_button.setEnabled(False)
            suffix = ("cleanup, restoration verification and disconnect…" if self._closing
                      else "scan cleanup and restoration verification…")
            self.status.setText(f"Cancelling · waiting for {suffix}")

    def poll_worker(self):
        if self.worker is not None:
            snapshot = self.worker.snapshot()
            mode = "SIMULATION"
            alive = self.worker.is_alive
        elif self.connection_worker is not None and self._hardware_running:
            snapshot = self.connection_worker.hold_scan_snapshot()
            mode = "HARDWARE"
            # ConnectionWorker stays alive for review/retry after the one job.
            alive = snapshot.outcome is None
        else:
            return
        x_name = "hold_code" if self.hold_mode.currentIndex() == 0 else "hold_delay_ns"
        if snapshot.rows != self._last_rows:
            self._last_rows = snapshot.rows
            title = "SIMULATION · synthetic hold-scan response" if mode == "SIMULATION" else "HARDWARE · live hold-scan response"
            self._plot(tuple(dict(row) for row in snapshot.rows), x_name, title)
        if snapshot.event:
            event = snapshot.event
            self.progress.setRange(0, event.total_points)
            self.progress.setValue(event.completed_points)
            if self.cancel_button.isEnabled():
                state = event.status
                if mode == "SIMULATION" and state in {"completed", "cancelled", "failed", "disconnected"}:
                    state = "closing session"
                self.status.setText(f"{mode.title()} · {state} · {event.completed_points}/{event.total_points} points")
        if snapshot.outcome is None or alive:
            return
        if self.worker is not None:
            self.worker.join()
            self.worker = None
        self.timer.stop()
        self._set_running(False)
        self._hardware_running = False
        outcome = snapshot.outcome
        result = outcome.result
        hardware_fault = (getattr(self.connection_worker.snapshot(), "fault", None)
                          if mode == "HARDWARE" and self.connection_worker else None)
        problems = [p for p in (outcome.error, outcome.close_error) if p]
        if result:
            problems += result.cleanup_errors + result.persistence_errors
            if result.error:
                problems.append(f"{type(result.error).__name__}: {result.error}")
            terminal = "failed" if (outcome.close_error or hardware_fault) else result.status
            verification = getattr(result, "verification", None)
            verification_summary = (verification.as_dict() if hasattr(verification, "as_dict") else verification)
            self.status.setText(f"{mode} · {terminal} · {result.points} points · "
                                f"cleanup: {result.cleanup_status}")
            summary = {"status": terminal, "execution_mode": result.execution_mode,
                       "directory": str(self._active_directory), "points": result.points,
                       "cleanup": result.cleanup_status,
                       "verification": verification_summary,
                       "problems": problems, "warnings": result.warnings,
                       "display_events_coalesced": snapshot.coalesced_events,
                       "saved_data": "All completed points are saved independently of display updates."}
            self.details.setPlainText(json.dumps(summary, indent=2))
        else:
            self.status.setText(f"{mode.title()} did not acquire data: " + "; ".join(problems))
            self.details.setPlainText("\n".join(problems))
        self.output.setText(_new_directory("simulation" if self.mode.currentIndex() == 0 else "hardware"))
        self._update_connection_controls()
        if self._closing:
            if mode == "HARDWARE":
                # A queued worker shutdown owns the close path.  If the job
                # faulted, leave the window open for its explicit review.
                if outcome.error or outcome.close_error or hardware_fault or (result and
                        (result.cleanup_errors or result.persistence_errors or
                         result.status in {"failed", "disconnected"})):
                    self._closing = False
                return
            # Keep cleanup/storage failures reviewable instead of closing over them.
            if outcome.error or outcome.close_error or (result and
                    (result.cleanup_errors or result.persistence_errors or result.status in {"failed", "disconnected"})):
                self._closing = False
                self.status.setText(self.status.text() + " · Review errors before closing.")
            else:
                self.close()

    def _plot(self, rows, x_name, title):
        self.axes.clear()
        self.axes.set_title(title, fontsize=11)
        self.axes.set_xlabel("Internal hold code" if x_name == "hold_code" else "External hold delay (ns)")
        self.axes.set_ylabel("ADC counts")
        self.axes.grid(True, alpha=0.2)
        if rows:
            xs = [row[x_name] for row in rows]
            channels = sorted({int(name[2:-len("_hg_mean")]) for name in rows[0]
                              if name.endswith("_hg_mean")})
            for channel in channels:
                for gain, style in (("hg", "-"), ("lg", "--")):
                    mean_key, stdev_key = f"ch{channel}_{gain}_mean", f"ch{channel}_{gain}_stdev"
                    if mean_key not in rows[0]:
                        continue
                    means = [row[mean_key] for row in rows]
                    stdevs = [row.get(stdev_key, 0) for row in rows]
                    self.axes.errorbar(xs, means, yerr=stdevs, fmt=style + ".", linewidth=1.2,
                                       capsize=2, label=f"ch{channel} {gain}")
            self.axes.legend(fontsize=8)
        self.canvas.draw_idle()

    def choose_output(self):
        label = "simulation" if self.mode.currentIndex() == 0 else "hardware"
        directory = QFileDialog.getExistingDirectory(self, f"Choose parent for a new {label} run")
        if directory:
            self.output.setText(str(Path(directory) / Path(_new_directory()).name))

    def choose_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open hold-scan result", "",
                                             "Hold-scan results (metadata.json holdscan.csv);;CSV (*.csv)")
        if path:
            self.open_saved(Path(path))

    def open_saved(self, path):
        if self.worker is not None or self._hardware_running:
            return
        try:
            saved = read_hold_run(Path(path))
            label = saved.execution_mode.upper()
            self.banner.setText(f"SAVED RESULT · {label} · {saved.status} · {saved.directory}")
            self._plot(saved.rows, saved.x_name, f"{label} · {saved.status} · {len(saved.rows)} saved points")
            status = f"{label} · {saved.status} · {len(saved.rows)} points"
            self.status.setText(status + (" · " + "; ".join(saved.warnings) if saved.warnings else ""))
            self.details.setPlainText(json.dumps({"warnings": saved.warnings, "manifest": saved.manifest}, indent=2))
            self.progress.setRange(0, max(1, saved.manifest.get("total_points", len(saved.rows))))
            self.progress.setValue(len(saved.rows))
        except Exception as exc:
            self.status.setText(f"Cannot open result: {exc}")

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self._closing = True
            self.cancel_run()
        elif self.connection_worker is not None:
            event.ignore()
            self._closing = True
            try:
                self.connection_worker.shutdown()
                self.connection_timer.start()
                self._update_connection_controls()
            except Exception as exc:
                self._closing = False
                self.connection_status.setText(
                    f"Could not close connection · {type(exc).__name__}: {exc}")
                self._update_connection_controls()
        else:
            self.timer.stop()
            self.connection_timer.stop()
            event.accept()
