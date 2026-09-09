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
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig
from radioroc.application.threshold_worker import ThresholdWorker
from radioroc.data.threshold_reader import read_threshold_run
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


def _new_directory():
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return str(Path.cwd() / "radioroc_runs" / "simulation" / name)


class ThresholdWindow(QMainWindow):
    def __init__(self, *, worker_factory=ThresholdWorker):
        super().__init__()
        self.setWindowTitle("RADIOROC · Threshold simulation")
        self.resize(1180, 820)
        self.worker_factory = worker_factory
        self.worker = None
        self._closing = False
        self._last_rows = ()
        self._active_directory = None

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
        self.mode.addItems(["Simulation", "Hardware — unavailable in this delivery"])
        form.addRow("Device / mode", self.mode)
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

        sim_group = QGroupBox("Deterministic synthetic curve")
        sim_form = QFormLayout(sim_group)
        sim_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.midpoint = _decimal(0, 1023, 500)
        self.width = _decimal(0.001, 1024, 30)
        self.plateau = _decimal(0, 1e9, 100000)
        self.spacing = _decimal(-1023, 1023, 3)
        for label, field in [("Midpoint (DAC)", self.midpoint), ("Width (DAC)", self.width),
                             ("Plateau (Hz)", self.plateau), ("Channel spacing (DAC)", self.spacing)]:
            sim_form.addRow(label, field)
        form.addRow(sim_group)
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
        self._mode_changed()
        self._plot((), "Simulation — no data yet")

    def _mode_changed(self):
        simulation = self.mode.currentIndex() == 0
        self.banner.setText(
            "SIMULATION · Synthetic counts, not measured lab data. No board connection."
            if simulation else "HARDWARE UNAVAILABLE · This desktop delivery supports simulation only.")
        self.run_button.setEnabled(simulation and self.worker is None)

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
            data["selected_mode"] = "simulation" if self.mode.currentIndex() == 0 else "hardware-unavailable"
            data["simulation"] = self.simulation().as_dict()
            self.details.setPlainText(json.dumps(data, indent=2))
            self.status.setText(f"Preview valid · {data['total_points']} DAC points · no output created")
            return operation
        except Exception as exc:
            self.status.setText(f"Preview failed: {exc}")
            return None

    def start_run(self):
        if self.worker is not None or self.mode.currentIndex() != 0:
            return
        operation = self.preview()
        if operation is None:
            return
        try:
            worker = self.worker_factory(operation, self.simulation())
            self._last_rows = ()
            self._active_directory = Path(operation.scan.out_dir)
            self._mode_changed()
            self.progress.setValue(0)
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
        self.run_button.setEnabled(not running and self.mode.currentIndex() == 0)
        self.cancel_button.setEnabled(running)

    def cancel_run(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling · waiting for scan cleanup and session close…")

    def poll_worker(self):
        if self.worker is None:
            return
        snapshot = self.worker.snapshot()
        if snapshot.rows != self._last_rows:
            self._last_rows = snapshot.rows
            self._plot(tuple(dict(row) for row in snapshot.rows), "SIMULATION · synthetic threshold rates")
        if snapshot.event:
            event = snapshot.event
            self.progress.setRange(0, event.total_points)
            self.progress.setValue(event.completed_points)
            if self.cancel_button.isEnabled():
                state = event.status
                if state in {"completed", "cancelled", "failed", "disconnected"}:
                    state = "closing session"
                self.status.setText(f"Simulation · {state} · {event.completed_points}/{event.total_points} points")
        if snapshot.outcome is None or self.worker.is_alive:
            return
        self.worker.join()
        self.worker = None
        self.timer.stop()
        self._set_running(False)
        outcome = snapshot.outcome
        result = outcome.result
        problems = [p for p in (outcome.error, outcome.close_error) if p]
        if result:
            problems += result.cleanup_errors + result.persistence_errors
            if result.error:
                problems.append(f"{type(result.error).__name__}: {result.error}")
            terminal = "failed" if outcome.close_error else result.status
            self.status.setText(f"SIMULATION · {terminal} · {result.points} points / {result.attempts} windows · "
                                f"cleanup: {result.cleanup_status}")
            summary = {"status": terminal, "execution_mode": result.execution_mode,
                       "directory": str(self._active_directory), "points": result.points,
                       "attempts": result.attempts, "cleanup": result.cleanup_status,
                       "problems": problems, "warnings": result.warnings,
                       "display_events_coalesced": snapshot.coalesced_events,
                       "saved_data": "All completed windows and points are saved independently of display updates."}
            self.details.setPlainText(json.dumps(summary, indent=2))
        else:
            self.status.setText("Simulation did not acquire data: " + "; ".join(problems))
            self.details.setPlainText("\n".join(problems))
        self.output.setText(_new_directory())
        if self._closing:
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
        directory = QFileDialog.getExistingDirectory(self, "Choose parent for a new simulation run")
        if directory:
            self.output.setText(str(Path(directory) / Path(_new_directory()).name))

    def choose_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open threshold result", "",
                                             "Threshold results (metadata.json thresholdscan.csv);;CSV (*.csv)")
        if path:
            self.open_saved(Path(path))

    def open_saved(self, path):
        if self.worker is not None:
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
        else:
            self.timer.stop()
            event.accept()
