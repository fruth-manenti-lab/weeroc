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

from radioroc_client import FPGA_IO_NAMES, HoldScanConfig
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.hold_scan import HoldScanJob, HoldScanJobConfig
from radioroc.application.hold_scan_worker import HoldScanWorker
from radioroc.data.hold_reader import read_hold_run
from radioroc.gui.channel_config_panel import ChannelConfigPanel
from radioroc.gui.channel_select import ChannelSelectGrid
from radioroc.gui.connection_panel import ConnectionPanel
from radioroc.gui.hint_bar import HintBar
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
                 connection_worker_factory=ConnectionWorker, connection_worker=None):
        super().__init__()
        self.setWindowTitle("RADIOROC · Hold-scan workflow")
        self.resize(1180, 820)
        self.worker_factory = worker_factory
        self.worker = None
        self.connection_worker_factory = connection_worker_factory
        self._connection_panel = None
        self._channel_config_panel = None
        self._connection_worker = None
        self._accepted_mode = 1
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
        self.mode.setCurrentIndex(1)
        form.addRow("Device / mode", self.mode)

        if connection_worker is None:
            self._connection_panel = ConnectionPanel(connection_worker_factory=connection_worker_factory)
            self._channel_config_panel = ChannelConfigPanel(None)
            self.connection_group = self._connection_panel.connection_group
            self.port_select = self._connection_panel.port_select
            self.baud = self._connection_panel.baud
            self.timeout_s = self._connection_panel.timeout_s
            self.refresh_button = self._connection_panel.refresh_button
            self.connect_button = self._connection_panel.connect_button
            self.read_status_button = self._connection_panel.read_status_button
            self.disconnect_button = self._connection_panel.disconnect_button
            self.review_fault_button = self._connection_panel.review_fault_button
            self.connection_status = self._connection_panel.connection_status
            self.firmware_status = self._connection_panel.firmware_status
            self.channel_config_group = self._channel_config_panel.channel_config_group
            self.channel_config_channels = self._channel_config_panel.channel_config_channels
            self.channel_config_set_tq_mask = self._channel_config_panel.channel_config_set_tq_mask
            self.channel_config_tq_mask_value = self._channel_config_panel.channel_config_tq_mask_value
            self.channel_config_set_input_dac_enable = (
                self._channel_config_panel.channel_config_set_input_dac_enable)
            self.channel_config_input_dac_enable_value = (
                self._channel_config_panel.channel_config_input_dac_enable_value)
            self.channel_config_set_input_dac_value = (
                self._channel_config_panel.channel_config_set_input_dac_value)
            self.channel_config_input_dac_value = self._channel_config_panel.channel_config_input_dac_value
            self.channel_config_impedance = self._channel_config_panel.channel_config_impedance
            self.channel_config_restore = self._channel_config_panel.channel_config_restore
            self.channel_config_apply_button = self._channel_config_panel.channel_config_apply_button
            self.channel_config_status = self._channel_config_panel.channel_config_status
            form.addRow(self._connection_panel)
            form.addRow(self._channel_config_panel)
        else:
            self._connection_worker = connection_worker
            self.connection_label = QLabel()
            self.connection_label.setWordWrap(True)
            form.addRow("Connection", self.connection_label)

        self.channel_select = ChannelSelectGrid(initial_channels=(4, 5))
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
        form.addRow(self.channel_select)
        for label, field in [("Trigger channel", self.trigger_channel),
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
        self.output = QLineEdit(_new_directory("hardware" if self.mode.currentIndex() == 1 else "simulation"))
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
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll_worker)
        if self._connection_panel is not None:
            self.port_select.currentIndexChanged.connect(self._update_connection_controls)
            self.refresh_button.clicked.connect(self.refresh_connections)
            self.connect_button.clicked.connect(self.connect_hardware)
            self.read_status_button.clicked.connect(self.read_hardware_status)
            self.disconnect_button.clicked.connect(self.disconnect_hardware)
            self.review_fault_button.clicked.connect(self.review_hardware_fault)
            self.channel_config_apply_button.clicked.connect(self.apply_channel_config)
            self._connection_panel.status_changed.connect(self.poll_connection_worker)
        else:
            self.timer.timeout.connect(self._refresh_connection_label)
            self.timer.start()
            self._refresh_connection_label()
        self.hint = HintBar(
            self.statusBar(),
            "Hold scan: sweeps the hold delay to trace the peak-detector's held "
            "value over time, for a real pulse injected via Ctest or an external "
            "generator. Hover a control to see what it does.")
        self.hint.attach(self.mode, "Simulation previews a synthetic curve with no "
                          "board attached; Hardware connection runs on the real ASIC/FPGA.")
        self.hint.attach(self.channel_select.toggle_button,
                         "Channels to record and plot. Click to choose which channels.")
        self.hint.attach(self.channel_select.select_all_button, "Select every channel.")
        self.hint.attach(self.channel_select.select_none_button, "Deselect every channel.")
        self.hint.attach(self.trigger_channel, "Channel whose discriminator/Ctest pulse "
                          "times the acquisition.")
        self.hint.attach(self.hold_mode, "Internal sweeps the ASIC's own delay-cell code "
                          "(coarse, on-chip). External sweeps the FPGA-generated hold delay "
                          "in nanoseconds (finer, matches a real injected pulse's timing).")
        self.hint.attach(self.hold_min, "First hold delay/code in the sweep.")
        self.hint.attach(self.hold_max, "Last hold delay/code in the sweep.")
        self.hint.attach(self.hold_step, "Step size between sweep points.")
        self.hint.attach(self.acquisitions, "ADC acquisitions requested per hold-delay "
                          "point; the hardware may report back a different actual count.")
        self.hint.attach(self.timeout_s_scan, "Maximum time to wait for each batch of "
                          "acquisitions before giving up.")
        self.hint.attach(self.discriminator, "Which ASIC discriminator output (T1/T2) "
                          "provides the trigger timing reference.")
        self.hint.attach(self.set_threshold_dac, "Write the threshold DAC below to the "
                          "trigger channel before running, instead of using its current value.")
        self.hint.attach(self.threshold_dac, "Threshold DAC code to apply when the checkbox "
                          "to its left is enabled. Keep it above the noise floor (see the "
                          "threshold-scan tab) or the ASIC's own discriminator will "
                          "self-trigger on noise and contaminate the hold-scan samples.")
        self.hint.attach(self.mask, "Mask every channel except the ones being scanned, "
                          "so only their signals are read out.")
        self.hint.attach(self.ctest, "Enable Ctest: routes the ASIC's internal test-charge "
                          "injector into the selected channel(s), producing a repeatable "
                          "calibration pulse without needing an external pulse generator.")
        self.hint.attach(self.synchro_trigger, "Pulse FPGA synchro trigger per ADC batch: "
                          "before each batch of acquisitions, the FPGA emits a sync pulse on "
                          "the Sync IO line below, used to fire an external pulse generator "
                          "(or the on-board Ctest path) and the ADC read-out in lockstep so "
                          "the hold scan can track a real pulse's timing precisely.")
        self.hint.attach(self.initialize, "Re-initialize the FPGA before running. This is a "
                          "persistent board change, not just a scan setting -- leave it off "
                          "unless you specifically need to reset FPGA state.")
        self.hint.attach(self.defaults, "Apply the ASIC's packaged default register values "
                          "before running. This is a persistent board change -- leave it off "
                          "to keep whatever configuration is already on the ASIC.")
        self.hint.attach(self.sync_io, "FPGA IO line that carries the synchro trigger pulse "
                          "to an external pulse generator.")
        self.hint.attach(self.set_sync_io_mux, "Set the Sync IO mux index below before "
                          "running, instead of using whatever it is currently set to.")
        self.hint.attach(self.sync_io_mux_index, "Mux index selecting which internal signal "
                          "the Sync IO line carries when the checkbox to its left is enabled.")
        self.hint.attach(self.conversion_delay_ns, "Delay after the trigger before the ADC "
                          "starts converting, in external hold mode.")
        self.hint.attach(self.trigger_type, "Vendor ADC trigger-type code for external hold "
                          "mode acquisitions.")
        self.hint.attach(self.trigger_source, "Vendor ADC trigger-source code: which signal "
                          "arms the ADC acquisition (e.g. a specific channel's discriminator, "
                          "or the FPGA synchro pulse) in external hold mode.")
        self.hint.attach(self.adc_window_ns, "Length of the ADC's acquisition window, in "
                          "nanoseconds, in external hold mode.")
        self.hint.attach(self.adc_nb_trig, "Number of ADC triggers to accept per acquisition "
                          "window, in external hold mode.")
        self.hint.attach(self.rstn_manual, "Drive the ADC reset line manually instead of "
                          "letting the FPGA sequence it automatically.")
        self.hint.attach(self.external_trigger, "Use an external signal (instead of the "
                          "ASIC's own discriminator) to arm the ASIC's acquisition trigger.")
        self.hint.attach(self.peak_sensing, "Use the vendor's peak-sensing read-out path "
                          "instead of the default sampling path.")
        self.hint.attach(self.trigger_preamp_gain, "Override the trigger-path preamp gain "
                          "code before running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.high_gain_code, "Override the high-gain shaper code before "
                          "running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.low_gain_code, "Override the low-gain shaper code before "
                          "running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.config_path, "Optional ASIC register CSV to load instead of "
                          "the packaged defaults.")
        self.hint.attach(self.output, "Directory the run's data and metadata will be saved to.")
        self.hint.attach(self.new_output, "Choose a different parent directory for the run "
                          "output above.")
        self.hint.attach(self.preview_button, "Preview the sweep/simulation settings without "
                          "recording a run to disk.")
        self.hint.attach(self.run_button, "Start the hold scan and record its result to the "
                          "run directory above.")
        self.hint.attach(self.cancel_button, "Cancel the run currently in progress.")
        self.hint.attach(self.reopen_button, "Open a previously saved hold-scan run to view "
                          "its plot and data again.")
        if self._connection_panel is not None:
            self.hint.attach(self.port_select, "USB serial port candidate to connect to.")
            self.hint.attach(self.refresh_button, "Re-scan for USB port candidates.")
            self.hint.attach(self.connect_button, "Open a connection to the selected port.")
            self.hint.attach(self.read_status_button, "Read the board's current firmware/"
                              "connection status.")
            self.hint.attach(self.disconnect_button, "Close the current hardware connection.")
            self.hint.attach(self.review_fault_button, "Show details of the last connection "
                              "fault.")
            self.hint.attach(self.channel_config_apply_button, "Apply the channel "
                              "configuration fields above to the connected hardware.")
        self._mode_changed()
        self._hold_mode_changed()
        self._plot((), "hold_delay_ns", "Simulation — no data yet")

    # -- connection_worker: a plain attribute in "injected" mode, or a
    # mirror of the internal ConnectionPanel's worker otherwise, so both
    # existing tests (which set `window.connection_worker = ...` directly)
    # and the injected-worker case share one attribute name. --------------

    @property
    def connection_worker(self):
        if self._connection_panel is not None:
            return self._connection_panel.connection_worker
        return self._connection_worker

    @connection_worker.setter
    def connection_worker(self, value):
        if self._connection_panel is not None:
            self._connection_panel.connection_worker = value
        else:
            self._connection_worker = value

    def _mode_changed(self):
        previous_mode = self._accepted_mode
        requested = self.mode.currentIndex()
        if requested != self._accepted_mode and self._mode_switch_locked():
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(self._accepted_mode)
            self.mode.blockSignals(False)
            if self._connection_panel is not None:
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
        if self._connection_panel is None:
            # Shared connection: this window doesn't own its lifecycle, so
            # the shared worker's own state (e.g. "connected", because some
            # other page connected it) is none of this window's business --
            # only this window's own in-flight hardware run should lock its
            # mode selector.
            return self._hardware_running
        if self.connection_worker is None:
            return False
        return self.connection_worker.snapshot().state in self._CONNECTION_LOCKS_MODE

    def _after_connection_command(self, succeeded):
        # On success the panel's own poll already refreshed the connection
        # display from a fresh snapshot; layer the full window-level cascade
        # (run_button/mode/channel-config enablement) on top of it. On
        # failure the panel already put the error on connection_status --
        # only the window-level cascade is still needed, not a snapshot
        # re-read, which would overwrite that error message.
        if succeeded:
            self.poll_connection_worker()
        else:
            self._update_connection_controls()

    def refresh_connections(self):
        if self._connection_panel is None:
            return
        if self.mode.currentIndex() == 1 and self.worker is None and not self._hardware_running:
            self._after_connection_command(self._connection_panel.refresh())

    def connect_hardware(self):
        if self._connection_panel is None:
            return
        candidate = self.port_select.currentData()
        if (self.mode.currentIndex() != 1 or candidate is None or self.worker is not None
                or self._hardware_running):
            return
        self._after_connection_command(self._connection_panel.connect_selected())

    def read_hardware_status(self):
        if self._connection_panel is None:
            return
        if self.mode.currentIndex() == 1:
            self._after_connection_command(self._connection_panel.read_status())

    def disconnect_hardware(self):
        if self._connection_panel is None:
            return
        if self.connection_worker is not None:
            self._after_connection_command(self._connection_panel.disconnect())

    def review_hardware_fault(self):
        if self._connection_panel is None:
            return
        if self.connection_worker is not None:
            self._after_connection_command(self._connection_panel.review_fault())

    def apply_channel_config(self):
        if self._channel_config_panel is None:
            return
        if self.mode.currentIndex() != 1 or self.connection_worker is None:
            return
        try:
            operation = self._channel_config_panel.build_operation()
        except ValueError as exc:
            self.channel_config_status.setText(f"Invalid channel configuration: {exc}")
            return
        try:
            self.connection_worker.apply_channel_config(operation)
            self.poll_connection_worker()
        except Exception as exc:
            self.connection_status.setText(
                f"Connection error · {type(exc).__name__}: {exc}")
            self._update_connection_controls()

    def _refresh_connection_label(self):
        worker = self.connection_worker
        if worker is None:
            self.connection_label.setText("Connection: not available")
            return
        snapshot = worker.snapshot()
        text = f"Connection: {snapshot.state}"
        port = getattr(snapshot, "port", None)
        if port:
            text += f" · {port}"
        fault = getattr(snapshot, "fault", None)
        if fault:
            text += f" · fault review required: {fault}"
        self.connection_label.setText(text)

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
        if self._connection_panel is not None:
            self._connection_panel.sync_ports(snapshot.ports)
            self._connection_panel.show_snapshot(snapshot)
        if self._channel_config_panel is not None:
            self._channel_config_panel.connection_worker = worker
            self._channel_config_panel.show_snapshot()
        if snapshot.state == "close_failed" and self._closing:
            # A failed window-close attempt stays open for review. A later close
            # event is the explicit request to try shutdown again.
            self._closing = False
        if snapshot.state == "stopped" and not worker.is_alive:
            worker.join()
            if self._connection_panel is not None:
                self._connection_panel.forget_worker()
            else:
                self._connection_worker = None
            if self._channel_config_panel is not None:
                self._channel_config_panel.connection_worker = None
            if self._closing:
                self.close()
                return
        self._update_connection_controls()

    def _update_connection_controls(self):
        hardware = self.mode.currentIndex() == 1
        worker = self.connection_worker
        snapshot = worker.snapshot() if worker is not None else None
        state = snapshot.state if snapshot is not None else "idle"
        fault = getattr(snapshot, "fault", None) if snapshot is not None else None
        commands_available = not self._closing
        if self._connection_panel is None:
            # Shared connection: this window doesn't own its lifecycle, so
            # its own state (e.g. permanently "connected" because another
            # page connected it) says nothing about whether this window can
            # start a simulation or switch its own mode -- only this
            # window's own in-flight work does.
            simulation_available = self.worker is None
            mode_available = commands_available and self.worker is None and not self._hardware_running
        else:
            busy = state in self._CONNECTION_BUSY
            session = state in {"connected", "close_failed", "faulted"}
            simulation_available = self.worker is None and not busy and not session
            mode_available = commands_available and self.worker is None and not busy and not session
        self.mode.setEnabled(mode_available)
        hardware_run_available = (self.worker is None and not self._hardware_running and
                                  state == "connected" and not fault
                                  and not self._closing)
        self.run_button.setEnabled((self.mode.currentIndex() == 0 and simulation_available) or
                                   (self.mode.currentIndex() == 1 and hardware_run_available))
        if self._connection_panel is not None:
            self._connection_panel.update_controls(commands_available=commands_available)
            self.connection_group.setEnabled(hardware and self.worker is None)
        if self._channel_config_panel is not None:
            self.channel_config_group.setEnabled(hardware)
            self.channel_config_apply_button.setEnabled(hardware_run_available)

    def operation(self):
        channels = self.channel_select.selected_channels()
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
                candidate = (self.port_select.currentData()
                            if self._connection_panel is not None else None)
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
        elif self._connection_panel is not None and self.connection_worker is not None:
            event.ignore()
            self._closing = True
            try:
                self.connection_worker.shutdown()
                self._connection_panel.timer.start()
                self._update_connection_controls()
            except Exception as exc:
                self._closing = False
                self.connection_status.setText(
                    f"Could not close connection · {type(exc).__name__}: {exc}")
                self._update_connection_controls()
        elif self._connection_panel is None and self._hardware_running and self.connection_worker is not None:
            # A connection_worker injected from outside is not this window's
            # to shut down (another page may still be using it) -- just
            # wait for the in-flight scan this window started to reach a
            # terminal snapshot, same as the SIMULATION close-wait path.
            event.ignore()
            self._closing = True
        else:
            self.timer.stop()
            event.accept()
