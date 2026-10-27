"""Calibration "Pedestals" tab: forced-trigger baseline measurement (controls and presentation only).

The measurement is ``radioroc.application.pedestal`` run through the shared connection worker's
verified acquisition job. Channels, trigger gain (paT) and hold delay come from the shared
Calibration selection and bar; the result is stored on ``selection.pedestals``.
"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from radioroc.application.pedestal import DEFAULT_EVENTS, PedestalJobConfig, finish_pedestals
from radioroc.data.pedestals import PedestalSet
from radioroc.gui.spin_util import select_all_on_focus

HG_SD_WARNING_COUNTS = 5.0
_COLUMNS = ("Channel", "HG median", "HG sd", "LG median", "LG sd", "n")
HINT_TEXT = ("Forced trigger: no input needed. Dark box closed, bias on, same gains and hold delay "
             "as the muon run. Channels, trigger gain (paT) and hold delay come from the Calibration "
             "selection and bar.")


def _new_directory():
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return Path.cwd() / "radioroc_runs" / "hardware" / ("pedestals-" + name)


class PedestalWindow(QWidget):
    def __init__(self, *, selection, connection_worker, runs_root=None, parent=None):
        super().__init__(parent)
        self.shared_selection = selection
        self._connection_worker = connection_worker
        self.runs_root = Path(runs_root) if runs_root is not None else None
        self.worker = None  # main window protocol: hardware jobs run on the shared connection worker
        self._running = False
        self._config = None
        self._active_directory = None
        self._closing = False

        layout = QVBoxLayout(self)
        self.hint_label = QLabel(HINT_TEXT)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        self.connection_label = QLabel()
        layout.addWidget(self.connection_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Events"))
        self.events = select_all_on_focus(QSpinBox())
        self.events.setRange(5, 100000)
        self.events.setValue(DEFAULT_EVENTS)
        self.events.setAccessibleName("Pedestal events per channel")
        self.events.setToolTip("Forced-trigger events per channel (collected in batches of 20).")
        row.addWidget(self.events)
        self.run_button = QPushButton("Run")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        row.addWidget(self.run_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #b45309; font-weight: 600")
        self.warning.hide()
        layout.addWidget(self.warning)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll_worker)
        self.run_button.clicked.connect(self.start_run)
        self.cancel_button.clicked.connect(self.cancel_run)
        selection.pedestals_changed.connect(self.show_pedestals)
        self.show_pedestals(selection.pedestals)
        self._update_controls()

    # -- connection ---------------------------------------------------------
    @property
    def connection_worker(self):
        return self._connection_worker

    def _connected(self) -> bool:
        worker = self._connection_worker
        if worker is None:
            return False
        try:
            snapshot = worker.snapshot()
        except Exception:
            return False
        return snapshot.state == "connected" and not getattr(snapshot, "fault", None)

    def poll_connection_worker(self):
        self._update_controls()

    def _update_controls(self):
        self.events.setEnabled(not self._running)
        self.run_button.setEnabled(not self._running and not self._closing and self._connected())
        self.cancel_button.setEnabled(self._running)
        self.connection_label.setText("Board connected." if self._connected() else
                                      "Connect the board (Connection panel) to measure pedestals.")

    # -- running ------------------------------------------------------------
    def operation_config(self) -> PedestalJobConfig:
        sel = self.shared_selection
        root = self.runs_root / "hardware" if self.runs_root is not None else None
        out = (root / _new_directory().name) if root is not None else _new_directory()
        return PedestalJobConfig(sel.channels(), out, hold_delay_ns=sel.hold_delay_ns,
                                 pat_gain=sel.trigger_gain, events=self.events.value())

    def start_run(self):
        if self._running or not self._connected():
            return
        try:
            config = self.operation_config()
            operation = config.acquisition_job_config()
            self._config = config
            self._active_directory = Path(config.out_dir)
            self.progress.setValue(0)
            self.warning.hide()
            self._running = True
            self._update_controls()
            self.status.setText("Hardware · preparing · mandatory restoration verification")
            self._connection_worker.run_acquisition(operation)
            self.timer.start()
        except Exception as exc:
            self._running = False
            self._update_controls()
            self.status.setText(f"Could not start the pedestal run: {exc}")

    def cancel_run(self):
        if not self._running:
            return
        try:
            self._connection_worker.cancel_acquisition()
        except Exception:
            return
        self.cancel_button.setEnabled(False)
        self.status.setText("Cancelling · waiting for cleanup and restoration verification…")

    def poll_worker(self):
        if not self._running:
            return
        snapshot = self._connection_worker.acquisition_snapshot()
        event = snapshot.event
        if event is not None and snapshot.outcome is None:
            self.progress.setRange(0, max(event.total_points, 1))
            self.progress.setValue(event.completed_points)
            if self.cancel_button.isEnabled():
                self.status.setText(f"Hardware · {event.status} · "
                                    f"{event.completed_points}/{event.total_points} batches")
        if snapshot.outcome is None:
            return
        self.timer.stop()
        self._running = False
        outcome = snapshot.outcome
        result = outcome.result
        problems = [p for p in (outcome.error, outcome.close_error) if p]
        if result is None:
            self.status.setText("No pedestals: " + "; ".join(problems or ["acquisition returned no result"]))
        else:
            problems += result.cleanup_errors + result.persistence_errors
            if result.error:
                problems.append(f"{type(result.error).__name__}: {result.error}")
            done = finish_pedestals(self._config, result)
            if done.pedestals is not None and not problems:
                self.shared_selection.set_pedestals(done.pedestals)
                self.status.setText(f"Pedestals measured for {len(done.pedestals.channels)} channels "
                                    f"and saved to {done.path}")
            else:
                if done.error:
                    problems.append(done.error)
                self.status.setText("No pedestals: " + "; ".join(problems))
        self._update_controls()

    # -- presentation -------------------------------------------------------
    def show_pedestals(self, pedestals: PedestalSet | None):
        self.table.setRowCount(0)
        noisy = []
        if pedestals is not None:
            for ch, p in sorted(pedestals.channels.items()):
                cells = (str(ch), f"{p.hg_median:.1f}", f"{p.hg_sd:.2f}",
                         f"{p.lg_median:.1f}", f"{p.lg_sd:.2f}", str(p.n))
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, column, item)
                if p.hg_sd > HG_SD_WARNING_COUNTS:
                    noisy.append(ch)
        if noisy:
            self.warning.setText(
                f"HG sd above {HG_SD_WARNING_COUNTS:g} counts on channel(s) "
                f"{', '.join(map(str, noisy))}: pulses present? Close the dark box, check bias and re-run.")
            self.warning.show()
        else:
            self.warning.hide()

    def closeEvent(self, event):
        self._closing = True
        if self._running:
            self.cancel_run()
        super().closeEvent(event)
