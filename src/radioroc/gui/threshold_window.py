"""Threshold controls and presentation; measurement belongs to the shared job."""

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

from radioroc_client import ThresholdScanConfig
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig
from radioroc.application.threshold_worker import ThresholdWorker
from radioroc.data.threshold_reader import read_threshold_run
from radioroc.gui.channel_config_panel import ChannelConfigPanel
from radioroc.gui.connection_panel import ConnectionPanel
from radioroc.transport.threshold_simulator import ThresholdSimulationConfig


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


class ThresholdWindow(QMainWindow):
    _CONNECTION_BUSY = {"discovering", "connecting", "reading", "disconnecting", "scanning",
                        "configuring"}
    _CONNECTION_LOCKS_MODE = _CONNECTION_BUSY | {"connected", "close_failed", "faulted"}

    def __init__(self, *, worker_factory=ThresholdWorker,
                 connection_worker_factory=ConnectionWorker, connection_worker=None):
        super().__init__()
        self.setWindowTitle("RADIOROC · Threshold workflow")
        self.resize(1180, 820)
        self.worker_factory = worker_factory
        self.worker = None
        self.connection_worker_factory = connection_worker_factory
        self._connection_panel = None
        self._channel_config_panel = None
        self._connection_worker = None
        self._accepted_mode = 0
        self._closing = False
        self._last_rows = ()
        self._active_directory = None
        self._hardware_running = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("RADIOROC  |  Threshold workflow")
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

        self.channels = QLineEdit("4,5")
        self.dac_min = _integer(0, 1023, 0)
        self.dac_max = _integer(0, 1023, 1000)
        self.dac_step = _integer(1, 1024, 25)
        self.window_ms = _decimal(0.001, 3600000, 50)
        self.averages = _integer(1, 100000, 1)
        self.discriminator = QComboBox()
        self.discriminator.addItems(["T1", "T2"])
        self.gain = _integer(0, 63, 0)
        self.gain.setSpecialValueText("Keep current")
        for label, field in [("Channels (comma separated)", self.channels),
                             ("First DAC", self.dac_min), ("Last DAC", self.dac_max),
                             ("DAC step", self.dac_step), ("Counter window (ms)", self.window_ms),
                             ("Averages", self.averages), ("Discriminator", self.discriminator),
                             ("Trigger gain code", self.gain)]:
            form.addRow(label, field)
        self.mask = QCheckBox("Mask other channels")
        self.mask.setChecked(True)
        self.ctest = QCheckBox("Enable Ctest")
        self.initialize = QCheckBox("Initialize FPGA (persists)")
        self.defaults = QCheckBox("Apply defaults (persists)")
        for field in (self.mask, self.ctest, self.initialize, self.defaults):
            form.addRow(field)
        self.config_path = QLineEdit()
        self.config_path.setPlaceholderText("Packaged defaults")
        form.addRow("ASIC CSV (optional)", self.config_path)
        self.output = QLineEdit(_new_directory())
        self.output.setMinimumWidth(220)
        form.addRow("New run directory", self.output)
        self.new_output = QPushButton("Choose output parent…")
        self.new_output.clicked.connect(self.choose_output)
        form.addRow(self.new_output)

        self.sim_group = QGroupBox("Deterministic synthetic curve")
        sim_form = QFormLayout(self.sim_group)
        sim_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.midpoint = _decimal(0, 1023, 500)
        self.width = _decimal(0.001, 1024, 30)
        self.plateau = _decimal(0, 1e9, 100000)
        self.spacing = _decimal(-1023, 1023, 3)
        for label, field in [("Midpoint (DAC)", self.midpoint), ("Width (DAC)", self.width),
                             ("Plateau (Hz)", self.plateau), ("Channel spacing (DAC)", self.spacing)]:
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
        self._mode_changed()
        self._plot((), "Simulation — no data yet")

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
        self.run_button.setText("Run simulation" if simulation else "Run hardware threshold")
        self.sim_group.setEnabled(simulation and self.worker is None)
        self._update_connection_controls()

    def _show_mode_banner(self):
        self.banner.setText(
            "SIMULATION · Synthetic counts, not measured lab data. No board connection."
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
        # behind a scan.  Consume its terminal threshold snapshot before
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
        busy = state in self._CONNECTION_BUSY
        session = state in {"connected", "close_failed", "faulted"}
        simulation_available = self.worker is None and not busy and not session
        commands_available = not self._closing
        self.mode.setEnabled(commands_available and self.worker is None and not busy and not session)
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
        channels = [int(value.strip()) for value in self.channels.text().split(",")]
        output = self.output.text().strip()
        if not output:
            raise ValueError("choose a new run directory")
        scan = ThresholdScanConfig(
            channels, dac_min=self.dac_min.value(), dac_max=self.dac_max.value(),
            dac_step=self.dac_step.value(), trigger_window_ms=self.window_ms.value(),
            averages=self.averages.value(), t1=self.discriminator.currentIndex() == 0,
            use_mask=self.mask.isChecked(), use_ctest=self.ctest.isChecked(),
            trigger_preamp_gain=self.gain.value() or None, out_dir=Path(output).expanduser(),
        )
        config = self.config_path.text().strip()
        return ThresholdJobConfig(scan, Path(config).expanduser() if config else None,
                                  self.initialize.isChecked(), self.defaults.isChecked())

    def simulation(self):
        settings = ThresholdSimulationConfig(midpoint=self.midpoint.value(), width=self.width.value(),
                                             plateau_hz=self.plateau.value(), channel_spacing=self.spacing.value())
        settings.validate()
        return settings

    def preview(self):
        try:
            operation = self.operation()
            data = ThresholdJob.preview(operation)
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
                    "threshold_run_available": (self.connection_worker is not None and
                                                self.connection_worker.snapshot().state == "connected" and
                                                not getattr(self.connection_worker.snapshot(), "fault", None)),
                    "restoration_verification": "mandatory",
                }
            self.details.setPlainText(json.dumps(data, indent=2))
            self.status.setText(f"Preview valid · {data['total_points']} DAC points · no output created")
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
                self._plot((), "HARDWARE · running threshold rates")
                self._hardware_running = True
                self._set_running(True)
                self.status.setText("Hardware · preparing · mandatory restoration verification")
                worker.run_threshold(operation)
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
            self._plot((), "SIMULATION · running")
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
                self.connection_worker.cancel_threshold()
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
            snapshot = self.connection_worker.threshold_snapshot()
            mode = "HARDWARE"
            # ConnectionWorker stays alive for review/retry after the one job.
            alive = snapshot.outcome is None
        else:
            return
        if snapshot.rows != self._last_rows:
            self._last_rows = snapshot.rows
            title = "SIMULATION · synthetic threshold rates" if mode == "SIMULATION" else "HARDWARE · live threshold rates"
            self._plot(tuple(dict(row) for row in snapshot.rows), title)
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
            self.status.setText(f"{mode} · {terminal} · {result.points} points / {result.attempts} windows · "
                                f"cleanup: {result.cleanup_status}")
            summary = {"status": terminal, "execution_mode": result.execution_mode,
                       "directory": str(self._active_directory), "points": result.points,
                       "attempts": result.attempts, "cleanup": result.cleanup_status,
                       "verification": verification_summary,
                       "problems": problems, "warnings": result.warnings,
                       "display_events_coalesced": snapshot.coalesced_events,
                       "saved_data": "All completed windows and points are saved independently of display updates."}
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

    def _plot(self, rows, title):
        self.axes.clear()
        self.axes.set_title(title, fontsize=11)
        self.axes.set_xlabel("Threshold DAC code")
        self.axes.set_ylabel("Trigger rate (Hz)")
        self.axes.grid(True, alpha=0.2)
        if rows:
            for channel in (name for name in rows[0] if name != "DAC"):
                self.axes.plot([row["DAC"] for row in rows], [row[channel] for row in rows],
                               marker=".", linewidth=1.5, label=channel)
            self.axes.legend()
        self.canvas.draw_idle()

    def choose_output(self):
        label = "simulation" if self.mode.currentIndex() == 0 else "hardware"
        directory = QFileDialog.getExistingDirectory(self, f"Choose parent for a new {label} run")
        if directory:
            self.output.setText(str(Path(directory) / Path(_new_directory()).name))

    def choose_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open threshold result", "",
                                             "Threshold results (metadata.json thresholdscan.csv);;CSV (*.csv)")
        if path:
            self.open_saved(Path(path))

    def open_saved(self, path):
        if self.worker is not None or self._hardware_running:
            return
        try:
            saved = read_threshold_run(Path(path))
            label = saved.execution_mode.upper()
            self.banner.setText(f"SAVED RESULT · {label} · {saved.status} · {saved.directory}")
            self._plot(saved.rows, f"{label} · {saved.status} · {len(saved.rows)} saved points")
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
