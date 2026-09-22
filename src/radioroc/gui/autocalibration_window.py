"""Automatic threshold calibration (F08) controls and presentation.

Mirrors ``radioroc.gui.scurve_window.ScurveWindow`` field-for-field and
behavior-for-behavior wherever the two workflows share a shape (config-form
idioms, preview/run/cancel/close, saved-run reopen). See that module for the
design rationale of each piece.

Unlike every other scan workflow window, this one is HARDWARE-ONLY: there is
no standalone simulation mode, no owned ``ConnectionPanel``/
``ChannelConfigPanel``, and no mode combo box. Building a believable
synthetic 4-step calibration-convergence simulator is out of scope; this
window only drives the real, shared ``ConnectionWorker`` injected by
``MainWindow`` (the same worker the other three scan windows share).
"""

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from radioroc.application.autocalibration import AutocalibrationJob, AutocalibrationJobConfig
from radioroc.data.autocalibration_reader import read_autocalibration_run
from radioroc.gui.channel_select import ChannelSelectGrid
from radioroc.gui.hint_bar import HintBar

_STEP_ORDER = ("step1_zero", "step1_full", "step2", "final")


def _integer(low, high, value):
    field = QSpinBox()
    field.setRange(low, high)
    field.setValue(value)
    return field


def _new_directory():
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return str(Path.cwd() / "radioroc_runs" / "hardware" / name)


class AutocalibrationWindow(QMainWindow):
    def __init__(self, *, connection_worker=None):
        super().__init__()
        self.setWindowTitle("RADIOROC · Autocalibration workflow")
        self.resize(1180, 820)
        # This window is hardware-only: connection_worker is a plain
        # attribute (not the dual-mode property ScurveWindow needs for its
        # own-ConnectionPanel-or-injected constructor paths), and `worker`
        # never gets assigned -- it exists solely so MainWindow._busy()/
        # closeEvent() (both generic over whatever _scan_windows() returns)
        # keep working unmodified.
        self.connection_worker = connection_worker
        self.worker = None
        self._closing = False
        self._hardware_running = False
        self._last_key = (None, ())
        self._active_directory = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("RADIOROC  |  Autocalibration workflow")
        title.setStyleSheet("font-size: 22px; font-weight: 600; padding: 8px 0")
        layout.addWidget(title)
        self.banner = QLabel(
            "HARDWARE · Automatic threshold calibration. FPGA initialization and "
            "apply-defaults are off by default; masking/Ctest/gain are temporary scan "
            "settings. Restoration verification is mandatory. Initialization and defaults "
            "are persistent changes -- so are the corrected calibration DAC values this "
            "workflow writes.")
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

        self.connection_label = QLabel()
        self.connection_label.setWordWrap(True)
        form.addRow("Connection", self.connection_label)

        # Autocalibration needs at least a reference channel plus others to
        # align against, unlike a single-channel S-curve default.
        self.channel_select = ChannelSelectGrid(initial_channels=(4, 5))
        self.discriminator = QComboBox()
        self.discriminator.addItems(["T1", "T2"])
        form.addRow(self.channel_select)
        form.addRow("Discriminator", self.discriminator)
        self.use_mask = QCheckBox("Mask other channels")
        self.use_mask.setChecked(True)
        self.use_ctest = QCheckBox("Enable Ctest")
        self.clock_index = _integer(0, 3, 3)
        self.trigger_level = QCheckBox("Count trigger level instead of rising edge")
        for field in (self.use_mask, self.use_ctest):
            form.addRow(field)
        form.addRow("S-curve clock index (0..3)", self.clock_index)
        form.addRow(self.trigger_level)

        self.gain_group = QGroupBox("Optional gain override")
        gain_form = QFormLayout(self.gain_group)
        self.trigger_preamp_gain = _integer(0, 63, 0)
        self.trigger_preamp_gain.setSpecialValueText("Keep current")
        gain_form.addRow("Trigger preamp gain code", self.trigger_preamp_gain)
        form.addRow(self.gain_group)

        self.probe_group = QGroupBox("Step 1: reference-channel LSB-ratio probe")
        probe_form = QFormLayout(self.probe_group)
        self.probe_dac_min = _integer(0, 1023, 0)
        self.probe_dac_max = _integer(0, 1023, 1000)
        self.probe_dac_step = _integer(1, 1023, 50)
        for label, field in [("First DAC code", self.probe_dac_min),
                             ("Last DAC code", self.probe_dac_max),
                             ("DAC step", self.probe_dac_step)]:
            probe_form.addRow(label, field)
        form.addRow(self.probe_group)

        self.transition_group = QGroupBox("Step 2: transition scan across selected channels")
        transition_form = QFormLayout(self.transition_group)
        self.transition_dac_step = _integer(1, 1023, 10)
        self.transition_margin = _integer(0, 1023, 150)
        self.transition_dac_floor = _integer(0, 1023, 300)
        self.transition_dac_cap = _integer(0, 1023, 1023)
        for label, field in [("DAC step", self.transition_dac_step),
                             ("Upper-bound margin", self.transition_margin),
                             ("Upper-bound floor", self.transition_dac_floor),
                             ("Upper-bound cap", self.transition_dac_cap)]:
            transition_form.addRow(label, field)
        form.addRow(self.transition_group)

        self.final_group = QGroupBox("Final: verification scan window")
        final_form = QFormLayout(self.final_group)
        self.final_window_before = _integer(0, 1023, 50)
        self.final_window_after = _integer(0, 1023, 120)
        self.final_dac_step = _integer(1, 1023, 2)
        for label, field in [("Codes before mean crossing", self.final_window_before),
                             ("Codes after mean crossing", self.final_window_after),
                             ("DAC step", self.final_dac_step)]:
            final_form.addRow(label, field)
        form.addRow(self.final_group)

        self.initialize_fpga = QCheckBox("Initialize FPGA (persists)")
        self.apply_defaults = QCheckBox("Apply defaults (persists)")
        for field in (self.initialize_fpga, self.apply_defaults):
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
        split.addWidget(scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.figure = Figure(figsize=(6, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        right_layout.addWidget(self.canvas, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Preview and run/result details appear here.")
        right_layout.addWidget(self.details, 2)
        split.addWidget(right)
        split.setSizes([410, 750])

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.run_button = QPushButton("Run autocalibration")
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
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll_worker)
        self.timer.timeout.connect(self._refresh_connection_label)
        self.timer.start()
        self._refresh_connection_label()

        self.hint = HintBar(
            self.statusBar(),
            "Autocalibration: probes a reference channel to estimate the calibration trim "
            "DAC's codes-per-LSB ratio, scans every selected channel's threshold crossing, "
            "corrects each channel's calibration trim DAC to align them on the mean crossing, "
            "then runs one final scan to verify the alignment. Hover a control to see what it "
            "does.")
        self.hint.attach(self.channel_select.toggle_button,
                         "Channels to calibrate together. Click to choose which channels; "
                          "the first channel is the reference used for the LSB-ratio probe.")
        self.hint.attach(self.channel_select.select_all_button, "Select every channel.")
        self.hint.attach(self.channel_select.select_none_button, "Deselect every channel.")
        self.hint.attach(self.discriminator, "Which ASIC discriminator output (T1/T2) -- and "
                          "which channel's calibration trim DAC -- this run calibrates.")
        self.hint.attach(self.use_mask, "Mask every channel except the one(s) being scanned in "
                          "each sub-scan, so only their signals are read out.")
        self.hint.attach(self.use_ctest, "Enable Ctest: routes the ASIC's internal test-charge "
                          "injector into the selected channel(s), producing the repeated "
                          "calibration pulse each sub-scan needs without an external generator.")
        self.hint.attach(self.clock_index, "Vendor S-curve clock index (0..3) selecting which "
                          "internal clock phase times the pulse counting in every sub-scan.")
        self.hint.attach(self.trigger_level, "Count time spent above threshold (level) instead "
                          "of counting rising-edge crossings, in every sub-scan.")
        self.hint.attach(self.trigger_preamp_gain, "Override the trigger-path preamp gain code "
                          "before running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.probe_dac_min, "First DAC code of the two coarse step-1 probes "
                          "(calibration trim 0, then 63) on the reference channel.")
        self.hint.attach(self.probe_dac_max, "Last DAC code of the two coarse step-1 probes on "
                          "the reference channel.")
        self.hint.attach(self.probe_dac_step, "DAC step for the two step-1 probes.")
        self.hint.attach(self.transition_dac_step, "DAC step for the step-2 scan across every "
                          "selected channel.")
        self.hint.attach(self.transition_margin, "Added past the higher of the two step-1 "
                          "crossing estimates to pick the step-2 scan's upper bound.")
        self.hint.attach(self.transition_dac_floor, "Lower bound clamping the computed step-2 "
                          "scan's upper bound.")
        self.hint.attach(self.transition_dac_cap, "Upper bound clamping the computed step-2 "
                          "scan's upper bound.")
        self.hint.attach(self.final_window_before, "How far below the step-2 mean crossing the "
                          "final verification scan starts.")
        self.hint.attach(self.final_window_after, "How far above the step-2 mean crossing the "
                          "final verification scan ends.")
        self.hint.attach(self.final_dac_step, "DAC step for the final verification scan.")
        self.hint.attach(self.initialize_fpga, "Re-initialize the FPGA before running. This is "
                          "a persistent board change, not just a scan setting -- leave it off "
                          "unless you specifically need to reset FPGA state.")
        self.hint.attach(self.apply_defaults, "Apply the ASIC's packaged default register "
                          "values before running. This is a persistent board change -- leave "
                          "it off to keep whatever configuration is already on the ASIC.")
        self.hint.attach(self.config_path, "Optional ASIC register CSV to load instead of the "
                          "packaged defaults.")
        self.hint.attach(self.output, "Directory the run's manifest and each sub-scan's data "
                          "will be saved to.")
        self.hint.attach(self.new_output, "Choose a different parent directory for the run "
                          "output above.")
        self.hint.attach(self.preview_button, "Preview the calibration settings without "
                          "recording a run to disk.")
        self.hint.attach(self.run_button, "Start the four-step calibration sequence and record "
                          "its result to the run directory above.")
        self.hint.attach(self.cancel_button, "Cancel the run currently in progress.")
        self.hint.attach(self.reopen_button, "Open a previously saved autocalibration run to "
                          "view its sub-scans and result again.")

        self._update_connection_controls()
        self._plot((), "HARDWARE — no data yet")

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
        # behind a run.  Consume its terminal snapshot before dropping the
        # owner and losing the partial-result/fault summary.
        if self._hardware_running:
            self.poll_worker()
        snapshot = worker.snapshot()
        if snapshot.state == "close_failed" and self._closing:
            # A failed window-close attempt stays open for review. A later
            # close event is the explicit request to try shutdown again.
            self._closing = False
        if snapshot.state == "stopped" and not worker.is_alive:
            worker.join()
            self.connection_worker = None
            if self._closing:
                self.close()
                return
        self._update_connection_controls()

    def _hardware_run_available(self):
        worker = self.connection_worker
        if worker is None or self._hardware_running or self._closing:
            return False
        snapshot = worker.snapshot()
        return snapshot.state == "connected" and not getattr(snapshot, "fault", None)

    def _update_connection_controls(self):
        self.run_button.setEnabled(self._hardware_run_available())

    def operation(self):
        channels = self.channel_select.selected_channels()
        output = self.output.text().strip()
        if not output:
            raise ValueError("choose a new run directory")
        config = self.config_path.text().strip()
        return AutocalibrationJobConfig(
            channels=channels, t1=self.discriminator.currentIndex() == 0,
            use_mask=self.use_mask.isChecked(), use_ctest=self.use_ctest.isChecked(),
            clock_index=self.clock_index.value(), trigger_level=self.trigger_level.isChecked(),
            trigger_preamp_gain=self.trigger_preamp_gain.value() or None,
            out_dir=Path(output).expanduser(),
            config_path=Path(config).expanduser() if config else None,
            initialize_fpga=self.initialize_fpga.isChecked(),
            apply_defaults=self.apply_defaults.isChecked(),
            probe_dac_min=self.probe_dac_min.value(), probe_dac_max=self.probe_dac_max.value(),
            probe_dac_step=self.probe_dac_step.value(),
            transition_dac_step=self.transition_dac_step.value(),
            transition_margin=self.transition_margin.value(),
            transition_dac_floor=self.transition_dac_floor.value(),
            transition_dac_cap=self.transition_dac_cap.value(),
            final_window_before=self.final_window_before.value(),
            final_window_after=self.final_window_after.value(),
            final_dac_step=self.final_dac_step.value(),
        )

    def preview(self):
        try:
            operation = self.operation()
            data = AutocalibrationJob.preview(operation)
            worker = self.connection_worker
            data["hardware"] = {
                "connection_state": worker.snapshot().state if worker is not None else "idle",
                "autocalibration_available": self._hardware_run_available(),
                "restoration_verification": "mandatory",
            }
            self.details.setPlainText(json.dumps(data, indent=2))
            self.status.setText(
                f"Preview valid · reference channel {data['reference_channel']} · "
                f"{data['step1_points_per_probe']} points per step-1 probe · no output created")
            return operation
        except Exception as exc:
            self.status.setText(f"Preview failed: {exc}")
            return None

    def start_run(self):
        if self._hardware_running:
            return
        operation = self.preview()
        if operation is None:
            return
        worker = self.connection_worker
        if worker is None or not self._hardware_run_available():
            return
        try:
            self._last_key = (None, ())
            self._active_directory = Path(operation.out_dir)
            self.progress.setValue(0)
            self.banner.setText(
                f"HARDWARE · RUN · {self._active_directory} · Results shown here are from "
                "this run.")
            self._plot((), "HARDWARE · running autocalibration")
            self._hardware_running = True
            self._set_running(True)
            self.status.setText("Hardware · preparing · mandatory restoration verification")
            worker.run_autocalibration(operation)
            self.timer.start()
        except Exception as exc:
            self._hardware_running = False
            self._set_running(False)
            self.status.setText(f"Could not start hardware autocalibration: {exc}")

    def _set_running(self, running):
        self.controls.setEnabled(not running)
        self.preview_button.setEnabled(not running)
        self.reopen_button.setEnabled(not running)
        self.run_button.setEnabled(not running and self._hardware_run_available())
        self.cancel_button.setEnabled(running)

    def cancel_run(self):
        if self.connection_worker is None:
            return
        try:
            self.connection_worker.cancel_autocalibration()
        except Exception:
            return
        self.cancel_button.setEnabled(False)
        suffix = ("cleanup and disconnect…" if self._closing
                  else "sub-scan cleanup and restoration verification…")
        self.status.setText(f"Cancelling · waiting for {suffix}")

    def poll_worker(self):
        if self.connection_worker is None or not self._hardware_running:
            return
        snapshot = self.connection_worker.autocalibration_snapshot()
        key = (snapshot.step, snapshot.rows)
        if key != self._last_key:
            self._last_key = key
            title = f"HARDWARE · {snapshot.step} · live response"
            self._plot(tuple(dict(row) for row in snapshot.rows), title)
        if snapshot.event:
            event = snapshot.event
            self.progress.setRange(0, event.total_points)
            self.progress.setValue(event.completed_points)
            if self.cancel_button.isEnabled():
                self.status.setText(
                    f"HARDWARE · {snapshot.step} · {event.status} · "
                    f"{event.completed_points}/{event.total_points} points")
        if snapshot.outcome is None:
            return
        self.timer.stop()
        self._set_running(False)
        self._hardware_running = False
        outcome = snapshot.outcome
        result = outcome.result
        hardware_fault = getattr(self.connection_worker.snapshot(), "fault", None)
        problems = [p for p in (outcome.error, outcome.close_error) if p]
        if result:
            if result.error:
                problems.append(f"{type(result.error).__name__}: {result.error}")
            terminal = "failed" if (outcome.close_error or hardware_fault) else result.status
            self.status.setText(
                f"HARDWARE · {terminal} · reference ch{result.reference_channel} · "
                f"corrections: {result.calibration_after}")
            summary = {
                "status": terminal, "execution_mode": result.execution_mode,
                "directory": str(self._active_directory),
                "reference_channel": result.reference_channel,
                "lsb_ratio": result.lsb_ratio,
                "crossings": result.crossings,
                "mean_position": result.mean_position,
                "calibration_before": result.calibration_before,
                "calibration_after": result.calibration_after,
                "sub_runs": {name: str(path) for name, path in result.sub_runs.items()},
                "reference_restored": result.reference_restored,
                "warnings": result.warnings,
                "problems": problems,
                "display_events_coalesced": snapshot.coalesced_events,
                "saved_data": "All completed points are saved independently of display updates.",
            }
            self.details.setPlainText(json.dumps(summary, indent=2))
        else:
            self.status.setText("Hardware did not acquire data: " + "; ".join(problems))
            self.details.setPlainText("\n".join(problems))
        self.output.setText(_new_directory())
        self._update_connection_controls()
        if self._closing:
            if outcome.error or outcome.close_error or hardware_fault or (
                    result and result.status in {"failed", "disconnected"}):
                self._closing = False
                self.status.setText(self.status.text() + " · Review errors before closing.")
            else:
                self.close()

    def _plot(self, rows, title):
        self.axes.clear()
        self.axes.set_title(title, fontsize=11)
        self.axes.set_xlabel("Threshold DAC code")
        self.axes.set_ylabel("Turn-on (%)")
        self.axes.set_ylim(-5, 105)
        self.axes.grid(True, alpha=0.2)
        if rows:
            xs = [row["DAC"] for row in rows]
            channels = sorted(int(name[2:]) for name in rows[0] if name.startswith("ch"))
            for channel in channels:
                key = f"ch{channel}"
                ys = [row.get(key) for row in rows]
                self.axes.plot(xs, ys, marker=".", linewidth=1.2, label=f"ch{channel}")
            self.axes.legend(fontsize=8)
        self.canvas.draw_idle()

    def choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose parent for a new hardware run")
        if directory:
            self.output.setText(str(Path(directory) / Path(_new_directory()).name))

    def choose_saved(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open autocalibration result", "",
            "Autocalibration results (autocalibration_metadata.json);;All files (*)")
        if path:
            self.open_saved(Path(path))

    def open_saved(self, path):
        if self._hardware_running:
            return
        try:
            saved = read_autocalibration_run(Path(path))
            self.banner.setText(f"SAVED RESULT · {saved.status} · {saved.directory}")
            step = next((name for name in reversed(_STEP_ORDER) if name in saved.sub_runs), None)
            if step is None:
                self._plot((), "No sub-scans recorded for this saved run")
                status = f"{saved.status} · no sub-scan data"
            else:
                sub_run = saved.sub_runs[step]
                self._plot(sub_run.rows,
                          f"{step} · {sub_run.status} · {len(sub_run.rows)} saved points")
                status = f"{saved.status} · showing {step} · {len(sub_run.rows)} points"
            if saved.warnings:
                status += " · " + "; ".join(saved.warnings)
            self.status.setText(status)
            summary = {
                "status": saved.status,
                "warnings": list(saved.warnings),
                "sub_run_points": {name: len(run.rows) for name, run in saved.sub_runs.items()},
                "manifest": saved.manifest,
            }
            self.details.setPlainText(json.dumps(summary, indent=2))
        except Exception as exc:
            self.status.setText(f"Cannot open result: {exc}")

    def closeEvent(self, event):
        if self._hardware_running and self.connection_worker is not None:
            # A connection_worker injected from outside is not this window's
            # to shut down (another page may still be using it) -- just wait
            # for the in-flight run this window started to reach a terminal
            # snapshot.
            event.ignore()
            self._closing = True
        else:
            self.timer.stop()
            event.accept()
