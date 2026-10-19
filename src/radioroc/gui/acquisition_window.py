"""Acquisition controls and presentation; measurement belongs to the shared job.

Mirrors ``radioroc.gui.threshold_window.ThresholdWindow``'s dual-mode shape
(owned ``ConnectionPanel``/``AcquisitionWorker`` in standalone mode, shared
injected ``connection_worker`` in embedded mode) field-for-field wherever the
two workflows share a shape. It deliberately differs in one place: threshold
plots a full DAC-vs-rate curve because every "point" is one scalar per DAC
code, but one acquisition "point" event is a whole batch's raw per-channel
sample lists (see ``radioroc.application.acquisition_worker``), so this
window keeps the compact live batches-completed/total progress bar plus a
per-channel count/min/max/mean summary of the most recent batch, and adds a
histogram of the raw per-channel HG/LG values alongside it.

The acquisition mailbox deliberately never retains raw per-event samples in
memory (see ``summarize_acquisition_event``/``MAX_RETAINED_BATCHES``) --
only the bounded batch summary above, because every raw sample is already
durably written to the run's own ``events.csv`` by the job. Spectra
rendering therefore does not add a second in-memory raw-sample buffer to
route around that: it periodically re-reads the run's own ``events.csv``
from disk (incrementally, by byte offset: ``_LiveEventsReader``) and
accumulates bounded fixed-bin histograms, throttled to roughly once per
second (``_LIVE_REFRESH_EVERY_TICKS`` poll ticks) rather than on every
100ms timer tick, so a long run doesn't spend all its time re-parsing a
growing CSV. The same histogram also renders a previously saved run
(``open_saved``) or an imported vendor-format file (``import_vendor_file``).
"""

import csv
import os
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
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import NullFormatter

from radioroc_client import FPGA_IO_NAMES, AcquisitionConfig
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig
from radioroc.application.acquisition_worker import AcquisitionWorker
from radioroc.application.connection_worker import ConnectionWorker
from radioroc.data.acquisition_reader import read_acquisition_run
from radioroc.data.vendor_acquisition import read_vendor_acquisition_file
from radioroc.gui.layout_util import fit_controls_pane, fit_special_text, wrap_plot_title
from radioroc.gui.channel_config_panel import ChannelConfigPanel
from radioroc.gui.channel_select import ChannelSelectGrid
from radioroc.gui.connection_panel import ConnectionPanel
from radioroc.gui.hint_bar import HintBar
from radioroc.transport.acquisition_simulator import AcquisitionSimulationConfig
from radioroc.gui.output_paths import guard_output, refresh_auto_output

# The filename `AcquisitionRunWriter`/`AcquisitionJob` write events to inside
# a run's `out_dir` (see `radioroc/data/acquisition.py`'s `self.csv_path` and
# `radioroc/application/acquisition.py`'s `AcquisitionResult.csv_path`).
# `radioroc.data.acquisition_reader` knows this same name internally but
# does not export it, so it is repeated here rather than imported.
_EVENTS_CSV_NAME = "events.csv"


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


def _format_batch_summary(mode, row):
    """Render one `summarize_acquisition_event`-shaped row for display.

    `row` is a ``(key, value)`` tuple sequence with one ``"batch"`` entry
    plus ``{name}_count``/``{name}_min``/``{name}_max``/``{name}_mean``
    quadruples per channel/gain (e.g. ``ch4_hg``, ``ch4_lg``).
    """
    values = dict(row)
    batch = values.pop("batch", None)
    groups: dict[str, dict[str, object]] = {}
    for key, value in values.items():
        name, _, stat = key.rpartition("_")
        groups.setdefault(name, {})[stat] = value
    lines = [f"{mode} · most recent batch: {batch}"]
    for name in sorted(groups):
        stats = groups[name]
        count = stats.get("count", 0)
        if count:
            lines.append(f"  {name}: n={count}  min={stats['min']:.1f}  "
                         f"max={stats['max']:.1f}  mean={stats['mean']:.1f}")
        else:
            lines.append(f"  {name}: n=0")
    return "\n".join(lines)


def _count_events(rows):
    """Physical events = distinct (batch, event); the CSV has one row per channel."""
    return len({(row["batch"], row["event"]) for row in rows
                if "batch" in row and "event" in row})


def _events_text(rows):
    if isinstance(rows, _SpectraData):
        return f"{rows.events} events ({rows.rows} channel rows)"
    events = _count_events(rows)
    return f"{events} events ({len(rows)} channel rows)"


# ADC values are 12-bit; the display histograms use one fixed bin per ADC
# count (out-of-range values clamp into the edge bins) and are re-binned to
# the user's "bins" setting only at draw time, so memory is
# O(channels x 2 x 4096) regardless of run length. No existing display
# feature needs raw rows, so no row ring buffer is kept.
_ADC_BINS = 4096
# Cap on CSV lines parsed per refresh tick so a tick never blocks the GUI
# for long; the remainder is picked up on the following ticks.
_MAX_LINES_PER_TICK = 20_000


class _SpectraData:
    """Bounded display state: fixed-bin HG/LG counts per channel plus counts."""

    def __init__(self):
        self.hg = {}
        self.lg = {}
        self.rows = 0
        self._finished_events = 0
        self._batch = None
        self._batch_events = set()

    @property
    def events(self):
        """Physical events = distinct (batch, event).

        Rows are channel-major within a batch (every event of ch0, then ch1,
        ...) but a batch's rows are appended contiguously, so only the
        current batch's event ids are kept in memory (bounded by the
        acquisitions-per-batch setting).
        """
        return self._finished_events + len(self._batch_events)

    def __bool__(self):
        return self.rows > 0

    def _note_event(self, batch, event):
        if batch != self._batch:
            self._finished_events += len(self._batch_events)
            self._batch_events = set()
            self._batch = batch
        self._batch_events.add(event)

    def add_arrays(self, channels, hg, lg):
        channels = np.asarray(channels)
        hg_bins = np.clip(np.floor(np.asarray(hg, dtype=float)), 0, _ADC_BINS - 1).astype(np.int64)
        lg_bins = np.clip(np.floor(np.asarray(lg, dtype=float)), 0, _ADC_BINS - 1).astype(np.int64)
        for channel in np.unique(channels):
            mask = channels == channel
            key = int(channel)
            if key not in self.hg:
                self.hg[key] = np.zeros(_ADC_BINS, dtype=np.int64)
                self.lg[key] = np.zeros(_ADC_BINS, dtype=np.int64)
            self.hg[key] += np.bincount(hg_bins[mask], minlength=_ADC_BINS)
            self.lg[key] += np.bincount(lg_bins[mask], minlength=_ADC_BINS)
        self.rows += len(channels)

    def add_rows(self, rows):
        """Add dict rows (saved-run / vendor shapes); used for one-shot loads."""
        rows = list(rows)
        if not rows:
            return
        for row in rows:
            if "batch" in row and "event" in row:
                self._note_event(row["batch"], row["event"])
        self.add_arrays([r["channel"] for r in rows], [r["hg"] for r in rows],
                        [r["lg"] for r in rows])


class _LiveEventsReader:
    """Incremental tail reader for a run's ``events.csv``.

    Remembers the byte offset and header; each ``poll`` parses only newly
    appended *complete* lines (a partially written last line is left for the
    next poll), at most ``_MAX_LINES_PER_TICK`` of them. A truncated or
    replaced file (smaller size or different inode) resets the state.
    """

    def __init__(self, path):
        self.path = path
        self._reset()

    def _reset(self):
        self.data = _SpectraData()
        self._offset = 0
        self._header = None
        self._ident = None

    def poll(self, max_lines=None):
        """Parse newly appended lines; return True if the data changed."""
        max_lines = max_lines or _MAX_LINES_PER_TICK
        try:
            stat = os.stat(self.path)
            ident = (stat.st_dev, stat.st_ino)
            if (self._ident is not None and ident != self._ident) or stat.st_size < self._offset:
                self._reset()
            self._ident = ident
            if stat.st_size == self._offset:
                return False
            with open(self.path, "rb") as stream:
                stream.seek(self._offset)
                lines = []
                offset = self._offset
                while len(lines) < max_lines:
                    line = stream.readline()
                    if not line.endswith(b"\n"):
                        break  # EOF or torn last line: retry next poll
                    offset += len(line)
                    lines.append(line)
        except OSError:
            return False
        self._offset = offset
        if not lines:
            return False
        text = [line.decode("utf-8", "replace") for line in lines]
        if self._header is None:
            self._header = next(csv.reader([text[0]]), [])
            text = text[1:]
        try:
            index = {name: self._header.index(name) for name in ("channel", "hg", "lg")}
        except ValueError:
            return False
        b_idx = self._header.index("batch") if "batch" in self._header else None
        e_idx = self._header.index("event") if "event" in self._header else None
        channels, hgs, lgs = [], [], []
        for fields in csv.reader(text):
            try:
                channel = int(fields[index["channel"]])
                hg = float(fields[index["hg"]])
                lg = float(fields[index["lg"]])
                key = None
                if b_idx is not None and e_idx is not None and fields[b_idx] and fields[e_idx]:
                    key = (int(fields[b_idx]), int(fields[e_idx]))
            except (IndexError, ValueError):
                continue
            if key is not None:
                self.data._note_event(*key)
            channels.append(channel)
            hgs.append(hg)
            lgs.append(lg)
        if channels:
            self.data.add_arrays(channels, hgs, lgs)
        return True


def _read_live_events(path):
    """Re-read a run's ``events.csv`` for display, tolerating a concurrent writer.

    Deliberately lighter than ``read_acquisition_run``: this is called on a
    throttled timer while a run may still be appending to the file (a torn
    last line is expected, not an error), and a per-tick display refresh has
    no use for that reader's manifest cross-validation -- only ``channel``/
    ``hg``/``lg`` are needed to render a histogram. Unparseable rows
    (including a partially flushed final line) are skipped rather than
    truncating the whole read, since the writer may still be mid-append.
    """
    rows = []
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                try:
                    entry = {
                        "channel": int(row["channel"]),
                        "hg": float(row["hg"]),
                        "lg": float(row["lg"]),
                    }
                    if row.get("batch") not in (None, "") and row.get("event") not in (None, ""):
                        entry["batch"] = int(row["batch"])
                        entry["event"] = int(row["event"])
                    rows.append(entry)
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return ()
    return tuple(rows)


class AcquisitionWindow(QMainWindow):
    _CONNECTION_BUSY = {"discovering", "connecting", "reading", "disconnecting", "scanning",
                        "configuring"}
    _CONNECTION_LOCKS_MODE = _CONNECTION_BUSY | {"connected", "close_failed", "faulted"}
    # Poll ticks (the 100ms timer driving `poll_worker`) between live
    # spectra disk re-reads -- 10 ticks is roughly once per second, so a
    # long run spends its time on the job, not re-parsing a growing CSV.
    _LIVE_REFRESH_EVERY_TICKS = 10

    def __init__(self, *, worker_factory=AcquisitionWorker,
                 connection_worker_factory=ConnectionWorker, connection_worker=None):
        super().__init__()
        self.setWindowTitle("RADIOROC · Acquisition workflow")
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
        self._live_csv_path = None
        self._live_refresh_tick = 0
        self._spectra = _SpectraData()
        self._live_reader = None
        self._spectra_title = "No data yet"
        self.spectra_channel_checks = {}

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("RADIOROC  |  Acquisition workflow")
        title.setStyleSheet("font-size: 18px; font-weight: 600; padding: 2px 0")
        layout.addWidget(title)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background: #173e58; color: white; padding: 4px 8px; border-radius: 5px")
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
            self.timeout_s_connection = self._connection_panel.timeout_s
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

        self.channel_select = ChannelSelectGrid(initial_channels=(4,))
        self.trigger_channel = _integer(0, 63, 4)
        self.threshold_dac = _integer(0, 1023, 0)
        self.threshold_dac.setSpecialValueText("Keep current")
        fit_special_text(self.threshold_dac)
        self.hold_delay_ns = _integer(0, 100000, 530)
        self.hold_delay_ns.setSingleStep(5)
        self.conversion_delay_ns = _integer(0, 100000, 400)
        self.conversion_delay_ns.setSingleStep(40)
        self.acquisitions_per_batch = _integer(1, 255, 50)
        self.batches = _integer(1, 1000000, 10)
        self.timeout_s = _decimal(0.001, 3600, 5.0)
        self.trigger_preamp_gain = _integer(0, 63, 0)
        self.trigger_preamp_gain.setSpecialValueText("Keep current")
        fit_special_text(self.trigger_preamp_gain)
        self.high_gain_code = _integer(0, 15, 0)
        self.high_gain_code.setSpecialValueText("Keep current")
        fit_special_text(self.high_gain_code)
        self.low_gain_code = _integer(0, 15, 0)
        self.low_gain_code.setSpecialValueText("Keep current")
        fit_special_text(self.low_gain_code)
        self.discriminator = QComboBox()
        self.discriminator.addItems(["T1", "T2"])
        # Vendor ADC DAQ tab combo items, recovered from radioroc2UI.pyc/
        # adc.pyc disassembly (IMPLEMENTATION_STATUS.md RADIOROC 39). Trigger
        # channel/mode fields below are always visible rather than mirroring
        # the vendor app's show/hide-by-mode behavior, to keep this first
        # cut simple; irrelevant fields for a given trigger type are simply
        # unused by AcquisitionConfig.validate().
        self.trigger_type = QComboBox()
        self.trigger_type.addItems(["Simple trigger", "2 channels coincidence", "Time window"])
        self.trigger_source = QComboBox()
        self.trigger_source.addItems(["NORT1", "NORT2", "NORTQ", "Individual trigger", "OR64 (FPGA)"])
        self.trigger_source.setCurrentIndex(3)
        self.trigger_source_2 = QComboBox()
        self.trigger_source_2.addItems(["NORT1", "NORT2", "NORTQ", "Individual trigger", "OR64 (FPGA)"])
        self.trigger_channel_2 = _integer(0, 63, 5)
        self.adc_window_ns = _integer(0, 10000, 50)
        self.adc_window_ns.setSingleStep(5)
        self.adc_nb_trig = _integer(0, 63, 1)
        form.addRow(self.channel_select)
        for label, field in [("Trigger type", self.trigger_type),
                             ("Trigger channel (T1 slot)", self.trigger_channel),
                             ("Trigger source (T1 slot)", self.trigger_source),
                             ("Trigger channel (T2 slot)", self.trigger_channel_2),
                             ("Trigger source (T2 slot)", self.trigger_source_2),
                             ("Coincidence/time window (ns)", self.adc_window_ns),
                             ("Time-window trigger count", self.adc_nb_trig),
                             ("Threshold DAC", self.threshold_dac),
                             ("Hold delay (ns)", self.hold_delay_ns),
                             ("Conversion delay (ns)", self.conversion_delay_ns),
                             ("Acquisitions per batch", self.acquisitions_per_batch),
                             ("Batches", self.batches),
                             ("Timeout (s)", self.timeout_s),
                             ("Trigger preamp gain code", self.trigger_preamp_gain),
                             ("High-gain shaper code", self.high_gain_code),
                             ("Low-gain shaper code", self.low_gain_code),
                             ("Discriminator", self.discriminator)]:
            form.addRow(label, field)
        self.mask = QCheckBox("Mask other channels")
        self.mask.setChecked(True)
        form.addRow(self.mask)
        self.rstn_manual = QCheckBox("Reset-n manual")
        form.addRow(self.rstn_manual)
        self.external_trigger = QCheckBox("Use external ASIC acquisition trigger (IO_FPGA6)")
        form.addRow(self.external_trigger)
        self.synchro_trigger = QCheckBox("Pulse FPGA synchro trigger per ADC batch")
        form.addRow(self.synchro_trigger)
        self.sync_io = QComboBox()
        self.sync_io.addItems(list(FPGA_IO_NAMES))
        self.sync_io.setCurrentText("io1")
        form.addRow("Sync IO", self.sync_io)
        self.set_sync_io_mux = QCheckBox("Set sync IO mux index before run")
        self.sync_io_mux_index = _integer(0, 7, 5)
        sync_io_mux_row = QHBoxLayout()
        sync_io_mux_row.addWidget(self.set_sync_io_mux)
        sync_io_mux_row.addWidget(self.sync_io_mux_index)
        form.addRow("Sync IO mux index", sync_io_mux_row)
        self.output = QLineEdit(_new_directory("hardware" if self.mode.currentIndex() == 1 else "simulation"))
        self.output.setMinimumWidth(220)
        form.addRow("New run directory", self.output)
        self.new_output = QPushButton("Choose output parent…")
        self.new_output.clicked.connect(self.choose_output)
        form.addRow(self.new_output)

        self.sim_group = QGroupBox("Deterministic synthetic ADC response")
        sim_form = QFormLayout(self.sim_group)
        sim_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.hg_mean = _decimal(0, 65535, 800.0)
        self.hg_stdev = _decimal(0, 65535, 40.0)
        self.lg_mean = _decimal(0, 65535, 120.0)
        self.lg_stdev = _decimal(0, 65535, 15.0)
        self.spacing = _decimal(-65535, 65535, 0.0)
        for label, field in [("High-gain mean (counts)", self.hg_mean),
                             ("High-gain std dev (counts)", self.hg_stdev),
                             ("Low-gain mean (counts)", self.lg_mean),
                             ("Low-gain std dev (counts)", self.lg_stdev),
                             ("Channel spacing (counts)", self.spacing)]:
            sim_form.addRow(label, field)
        form.addRow(self.sim_group)
        split.addWidget(scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.spectra_group = QGroupBox("Spectra display")
        spectra_layout = QVBoxLayout(self.spectra_group)
        spectra_layout.setContentsMargins(6, 4, 6, 4)
        spectra_layout.setSpacing(2)
        spectra_controls = QHBoxLayout()
        spectra_controls.addWidget(QLabel("Gain:"))
        self.spectra_gain = QComboBox()
        self.spectra_gain.addItems(["High gain (HG)", "Low gain (LG)"])
        spectra_controls.addWidget(self.spectra_gain)
        spectra_controls.addWidget(QLabel("Bins:"))
        self.spectra_bins = _integer(2, 500, 50)
        spectra_controls.addWidget(self.spectra_bins)
        self.spectra_log_y = QCheckBox("Log Y")
        spectra_controls.addWidget(self.spectra_log_y)
        spectra_controls.addStretch(1)
        spectra_layout.addLayout(spectra_controls)
        spectra_buttons = QHBoxLayout()
        self.spectra_clear_button = QPushButton("Clear plot")
        spectra_buttons.addWidget(self.spectra_clear_button)
        self.import_vendor_button = QPushButton("Import vendor file…")
        spectra_buttons.addWidget(self.import_vendor_button)
        spectra_buttons.addStretch(1)
        spectra_layout.addLayout(spectra_buttons)
        self.spectra_channels_widget = QWidget()
        self.spectra_channels_layout = QHBoxLayout(self.spectra_channels_widget)
        self.spectra_channels_layout.setContentsMargins(0, 0, 0, 0)
        spectra_layout.addWidget(self.spectra_channels_widget)
        right_layout.addWidget(self.spectra_group)

        self.figure = Figure(figsize=(6, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.canvas.setMinimumHeight(180)
        # Vertical splitter: the plot gets priority; the text panes below are
        # user-resizable and collapsible so they cannot squeeze the axes.
        self.right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split.addWidget(self.canvas)

        self.batch_summary = QPlainTextEdit()
        self.batch_summary.setReadOnly(True)
        self.batch_summary.setPlaceholderText(
            "The most recent batch's per-channel event count/min/max/mean "
            "appears here while a run is in progress.")
        self.right_split.addWidget(self.batch_summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Preview, run provenance and cleanup details appear here.")
        self.right_split.addWidget(self.details)
        # Let the text panes shrink so the window can fit a 1024x768 display.
        self.batch_summary.setMinimumHeight(28)
        self.details.setMinimumHeight(28)
        self.right_split.setChildrenCollapsible(True)
        self.right_split.setStretchFactor(0, 6)
        self.right_split.setStretchFactor(1, 1)
        self.right_split.setStretchFactor(2, 1)
        self.right_split.setSizes([420, 80, 80])
        right_layout.addWidget(self.right_split, 1)
        split.addWidget(right)
        fit_controls_pane(split, scroll, self.controls)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.run_button = QPushButton("Run simulation")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.reopen_button = QPushButton("Open saved run…")
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
        self.spectra_gain.currentIndexChanged.connect(self._refresh_spectra)
        self.spectra_bins.valueChanged.connect(self._refresh_spectra)
        self.spectra_log_y.toggled.connect(self._refresh_spectra)
        self.spectra_clear_button.clicked.connect(self.clear_spectra)
        self.import_vendor_button.clicked.connect(self.choose_vendor_file)
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
        self.hint = HintBar(
            self.statusBar(),
            "Acquisition: collects repeated ADC batches at one fixed hold/"
            "timing operating point and saves every raw event to disk. "
            "Hover a control to see what it does.")
        self.hint.attach(self.mode, "Simulation previews a synthetic fixed-point ADC "
                          "response with no board attached; Hardware connection runs on "
                          "the real ASIC/FPGA.")
        self.hint.attach(self.channel_select.toggle_button,
                         "Channels to save. Click to choose which channels.")
        self.hint.attach(self.channel_select.select_all_button, "Select every channel.")
        self.hint.attach(self.channel_select.select_none_button, "Deselect every channel.")
        self.hint.attach(self.trigger_channel, "Channel used for the ADC trigger setup.")
        self.hint.attach(self.threshold_dac, "Optional T1/T2 threshold DAC to set before "
                          "running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.hold_delay_ns, "External hold delay in nanoseconds, "
                          "divisible by 5.")
        self.hint.attach(self.conversion_delay_ns, "ADC conversion delay in nanoseconds, "
                          "divisible by 40.")
        self.hint.attach(self.acquisitions_per_batch, "Requested ADC acquisitions per batch.")
        self.hint.attach(self.batches, "Number of acquisition batches to run.")
        self.hint.attach(self.timeout_s, "Per-batch ADC timeout, in seconds.")
        self.hint.attach(self.trigger_preamp_gain, "Optional trigger-path preamp gain code "
                          "to set before running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.high_gain_code, "Optional high-gain shaper code to set before "
                          "running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.low_gain_code, "Optional low-gain shaper code to set before "
                          "running; leave at 'Keep current' to leave it alone.")
        self.hint.attach(self.discriminator, "Which ASIC discriminator (T1/T2) the "
                          "threshold DAC and trigger apply to.")
        self.hint.attach(self.rstn_manual, "Drive the ADC reset line manually instead of "
                          "letting the FPGA sequence it automatically. The July dark-count "
                          "finger plot (and the October one) needs this on; without it the "
                          "single-photoelectron peaks did not appear.")
        self.hint.attach(self.external_trigger, "Record on an external pulse (2.5 V TTL into "
                          "the board's External Synchro SMA, IO_FPGA6) instead of the ASIC "
                          "discriminator, so small pulses are not cut off. Without a pulse the "
                          "run times out.")
        self.hint.attach(self.synchro_trigger, "Pulse FPGA synchro trigger per ADC batch: "
                          "before each batch the FPGA emits a sync pulse on the Sync IO line, "
                          "used to fire an external pulse generator (set to triggered burst) "
                          "in lockstep with the read-out, so every event is a real pulse.")
        self.hint.attach(self.sync_io, "FPGA IO line that carries the synchro trigger pulse "
                          "to an external pulse generator.")
        self.hint.attach(self.set_sync_io_mux, "Set the Sync IO mux index below before "
                          "running, instead of using whatever it is currently set to.")
        self.hint.attach(self.sync_io_mux_index, "Mux index selecting which internal signal "
                          "the Sync IO line carries when the checkbox to its left is enabled "
                          "(5 = the sync pulse).")
        self.hint.attach(self.mask, "Mask every channel except the trigger channel, "
                          "so only its signal is read out.")
        self.hint.attach(self.output, "Directory the run's data and metadata will be saved to.")
        self.hint.attach(self.new_output, "Choose a different parent directory for the run "
                          "output above.")
        self.hint.attach(self.preview_button, "Preview the acquisition/simulation settings "
                          "without recording a run to disk.")
        self.hint.attach(self.run_button, "Start the acquisition and record its result to "
                          "the run directory above.")
        self.hint.attach(self.cancel_button, "Cancel the run currently in progress.")
        self.hint.attach(self.reopen_button, "Open a previously saved acquisition run to "
                          "view its status and data again.")
        self.hint.attach(self.spectra_gain, "Which gain's values the histogram below "
                          "plots -- high gain (HG) or low gain (LG).")
        self.hint.attach(self.spectra_bins, "Number of histogram bins.")
        self.hint.attach(self.spectra_log_y, "Plot the histogram's counts axis (Y) on a "
                          "log scale instead of linear.")
        self.hint.attach(self.spectra_clear_button, "Clear the histogram display. This does "
                          "not delete any saved data -- it only resets what's shown here.")
        self.hint.attach(self.import_vendor_button, "Load a real vendor-collected "
                          "readable_adc_acq.txt file and plot its HG/LG values here, for "
                          "comparison with this app's own runs.")
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
        self._set_spectra_channels(())
        self._refresh_spectra()

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
        if previous_mode != self._accepted_mode:
            refresh_auto_output(self.output, "simulation" if simulation else "hardware", _new_directory)
        self.run_button.setText("Run simulation" if simulation else "Run hardware acquisition")
        self.sim_group.setEnabled(simulation and self.worker is None)
        self._update_connection_controls()

    def _show_mode_banner(self):
        self.banner.setText(
            "SIMULATION · Synthetic ADC response, not measured lab data. No board connection."
            if self.mode.currentIndex() == 0 else
            "HARDWARE · USB candidates are unverified. Masking/gain/threshold overrides are "
            "temporary scan settings, restored after the run. Restoration readback "
            "verification is mandatory.")

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
        # behind a scan.  Consume its terminal acquisition snapshot before
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
        output = guard_output(self.output, "hardware" if self.mode.currentIndex() == 1 else "simulation",
                              _new_directory)
        acquisition = AcquisitionConfig(
            channels, trigger_channel=self.trigger_channel.value(),
            threshold_dac=self.threshold_dac.value() or None,
            hold_delay_ns=self.hold_delay_ns.value(),
            conversion_delay_ns=self.conversion_delay_ns.value(),
            acquisitions_per_batch=self.acquisitions_per_batch.value(),
            batches=self.batches.value(), timeout_s=self.timeout_s.value(),
            trigger_preamp_gain=self.trigger_preamp_gain.value() or None,
            high_gain_code=self.high_gain_code.value() or None,
            low_gain_code=self.low_gain_code.value() or None,
            t1=self.discriminator.currentIndex() == 0, use_mask=self.mask.isChecked(),
            trigger_type=self.trigger_type.currentIndex(),
            trigger_source=self.trigger_source.currentIndex(),
            trigger_source_2=self.trigger_source_2.currentIndex(),
            trigger_channel_2=self.trigger_channel_2.value(),
            adc_window_ns=self.adc_window_ns.value(),
            adc_nb_trig=self.adc_nb_trig.value(),
            synchro_trigger=self.synchro_trigger.isChecked(),
            rstn_manual=self.rstn_manual.isChecked(),
            external_trigger=self.external_trigger.isChecked(),
            sync_io=self.sync_io.currentText(),
            sync_io_mux_index=self.sync_io_mux_index.value() if self.set_sync_io_mux.isChecked() else None,
            out_dir=Path(output).expanduser(),
        )
        return AcquisitionJobConfig(acquisition)

    def simulation(self):
        settings = AcquisitionSimulationConfig(
            hg_mean=self.hg_mean.value(), hg_stdev=self.hg_stdev.value(),
            lg_mean=self.lg_mean.value(), lg_stdev=self.lg_stdev.value(),
            channel_spacing=self.spacing.value())
        settings.validate()
        return settings

    def preview(self):
        try:
            operation = self.operation()
            data = AcquisitionJob.preview(operation)
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
                    "acquisition_run_available": (self.connection_worker is not None and
                                                  self.connection_worker.snapshot().state == "connected" and
                                                  not getattr(self.connection_worker.snapshot(), "fault", None)),
                    "restoration_verification": "mandatory",
                }
            self.details.setPlainText(json.dumps(data, indent=2))
            self.status.setText(f"Preview valid · {data['total_points']} batches · no output created")
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
                self._active_directory = Path(operation.acquisition.out_dir)
                self.progress.setValue(0)
                self._show_run_banner("HARDWARE", self._active_directory)
                self.batch_summary.clear()
                self._start_live_spectra(operation.acquisition.channels, "HARDWARE")
                self._hardware_running = True
                self._set_running(True)
                self.status.setText("Hardware · preparing · mandatory restoration verification")
                worker.run_acquisition(operation)
                self.timer.start()
            except Exception as exc:
                self._hardware_running = False
                self._set_running(False)
                self.status.setText(f"Could not start hardware acquisition: {exc}")
            return
        try:
            worker = self.worker_factory(operation, self.simulation())
            self._last_rows = ()
            self._active_directory = Path(operation.acquisition.out_dir)
            self._mode_changed()
            self.progress.setValue(0)
            self._show_run_banner("SIMULATION", self._active_directory)
            self.batch_summary.clear()
            self._start_live_spectra(operation.acquisition.channels, "SIMULATION")
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
        self.import_vendor_button.setEnabled(not running)
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
                self.connection_worker.cancel_acquisition()
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
            snapshot = self.connection_worker.acquisition_snapshot()
            mode = "HARDWARE"
            # ConnectionWorker stays alive for review/retry after the one job.
            alive = snapshot.outcome is None
        else:
            return
        if snapshot.rows and snapshot.rows != self._last_rows:
            self._last_rows = snapshot.rows
            self.batch_summary.setPlainText(_format_batch_summary(mode, snapshot.rows[-1]))
        if snapshot.event:
            event = snapshot.event
            self.progress.setRange(0, event.total_points)
            self.progress.setValue(event.completed_points)
            if self.cancel_button.isEnabled():
                state = event.status
                if mode == "SIMULATION" and state in {"completed", "cancelled", "failed", "disconnected"}:
                    state = "closing session"
                self.status.setText(f"{mode.title()} · {state} · "
                                    f"{event.completed_points}/{event.total_points} batches")
        still_running = snapshot.outcome is None or alive
        if still_running:
            self._live_refresh_tick += 1
            if self._live_refresh_tick >= self._LIVE_REFRESH_EVERY_TICKS:
                self._live_refresh_tick = 0
                self._refresh_live_spectra(mode, running=True)
            return
        if self.worker is not None:
            self.worker.join()
            self.worker = None
        self.timer.stop()
        self._set_running(False)
        self._hardware_running = False
        self._refresh_live_spectra(mode, running=False)
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
            self.status.setText(f"{mode} · {terminal} · {result.points} batches · "
                                f"cleanup: {result.cleanup_status}")
            summary = {"status": terminal, "execution_mode": result.execution_mode,
                       "directory": str(self._active_directory), "points": result.points,
                       "cleanup": result.cleanup_status,
                       "verification": verification_summary,
                       "problems": problems, "warnings": result.warnings,
                       "display_events_coalesced": snapshot.coalesced_events,
                       "saved_data": "All completed batches and events are saved independently of display updates."}
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

    # -- spectra: histogram of raw per-channel HG/LG values, from either a
    # live run's own events.csv (re-read on a throttled timer, never from an
    # in-memory raw-sample buffer -- see the module docstring), a saved
    # run's rows, or an imported vendor file. ---------------------------

    def _start_live_spectra(self, channels, mode):
        self._live_csv_path = self._active_directory / _EVENTS_CSV_NAME
        self._live_refresh_tick = 0
        self._set_spectra_channels(channels)
        self._live_reader = _LiveEventsReader(self._live_csv_path)
        self._spectra = self._live_reader.data
        self._spectra_title = f"{mode} · running · waiting for the first batch"
        self._refresh_spectra()

    def _refresh_live_spectra(self, mode, running):
        path = self._live_csv_path
        if path is None or not path.exists():
            return
        if self._live_reader is None or self._live_reader.path != path:
            self._live_reader = _LiveEventsReader(path)
        changed = self._live_reader.poll()
        if not running:
            # Final refresh: drain whatever the per-tick cap left behind.
            while self._live_reader.poll():
                changed = True
        self._spectra = self._live_reader.data
        state = "running" if running else "finished"
        if changed or not running:
            self._spectra_title = f"{mode} · {state} · {_events_text(self._spectra)} on disk"
            self._refresh_spectra()

    def _set_spectra_channels(self, channels):
        while self.spectra_channels_layout.count():
            item = self.spectra_channels_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.spectra_channel_checks = {}
        for channel in sorted(channels):
            box = QCheckBox(f"ch{channel}")
            box.setChecked(True)
            box.setToolTip(f"Show/hide channel {channel} in the histogram below.")
            box.toggled.connect(self._refresh_spectra)
            self.spectra_channels_layout.addWidget(box)
            self.spectra_channel_checks[channel] = box
        self.spectra_channels_layout.addStretch(1)

    def _refresh_spectra(self):
        self._render_spectra(self._spectra, self._spectra_title)

    def _render_spectra(self, rows, title):
        self.axes.clear()
        self.axes.set_title(wrap_plot_title(title), fontsize=10)
        gain_field = "hg" if self.spectra_gain.currentIndex() == 0 else "lg"
        gain_label = "HG" if gain_field == "hg" else "LG"
        self.axes.set_xlabel(f"{gain_label} (ADC counts)")
        self.axes.set_ylabel("Counts")
        self.axes.set_yscale("log" if self.spectra_log_y.isChecked() else "linear")
        # Log scale: matplotlib auto-labels minor ticks (2x10^0, 3x10^0, ...)
        # whenever the data spans less than ~1 decade, which crowds into an
        # unreadable cluster on this window's compact plot area. Major
        # decade ticks (10^0, 10^1, ...) stay labelled; only the minor
        # in-between labels are suppressed.
        self.axes.yaxis.set_minor_formatter(NullFormatter())
        self.axes.grid(True, alpha=0.2)
        bins = self.spectra_bins.value()
        selected = [channel for channel, box in sorted(self.spectra_channel_checks.items())
                   if box.isChecked()]
        plotted = False
        if rows and selected:
            table = rows.hg if gain_field == "hg" else rows.lg
            for channel in selected:
                counts = table.get(channel)
                if counts is None:
                    continue
                nonzero = np.flatnonzero(counts)
                if not len(nonzero):
                    continue
                lo, hi = int(nonzero[0]), int(nonzero[-1]) + 1
                edges = np.linspace(lo, hi, bins + 1)
                weights, _ = np.histogram(np.arange(lo, hi) + 0.5, bins=edges,
                                          weights=counts[lo:hi])
                self.axes.hist(edges[:-1] + np.diff(edges) / 2, bins=edges, weights=weights,
                               alpha=0.55, label=f"ch{channel}")
                plotted = True
        if plotted:
            # Fixed outside-axes placement instead of loc="best": "best"
            # re-picks a position from the current data shape on every
            # redraw, which visibly jumps around during a live run and can
            # land the legend box on top of the title above it.
            self.axes.legend(fontsize=7, ncol=1, handlelength=1.0, labelspacing=0.3, loc="upper left", bbox_to_anchor=(1.02, 1.0),
                             borderaxespad=0.0)
        self.canvas.draw_idle()

    def clear_spectra(self):
        self._spectra = _SpectraData()
        self._live_reader = None
        self._spectra_title = "Cleared — no data displayed (saved data is untouched)"
        self._refresh_spectra()

    def choose_vendor_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import vendor acquisition file", "",
            "Vendor readable ADC files (*.txt);;All files (*)")
        if path:
            self.import_vendor_file(Path(path))

    def import_vendor_file(self, path):
        if self.worker is not None or self._hardware_running:
            return
        try:
            vendor = read_vendor_acquisition_file(Path(path))
            channels = sorted({row["channel"] for row in vendor.rows})
            self.banner.setText(f"VENDOR FILE · {path}")
            self._set_spectra_channels(channels)
            self._live_reader = None
            self._spectra = _SpectraData()
            self._spectra.add_rows(vendor.rows)
            self._spectra_title = f"VENDOR FILE · {Path(path).name} · {len(vendor.rows)} rows"
            self._refresh_spectra()
            status = f"Imported vendor file · {len(vendor.rows)} rows · channels {channels}"
            self.status.setText(status + (" · " + "; ".join(vendor.warnings) if vendor.warnings else ""))
            self.details.setPlainText(json.dumps({
                "vendor_file": str(path), "row_count": len(vendor.rows),
                "channels": channels, "setup_text": vendor.setup_text,
                "warnings": vendor.warnings,
            }, indent=2))
        except Exception as exc:
            self.status.setText(f"Cannot import vendor file: {exc}")

    def choose_output(self):
        label = "simulation" if self.mode.currentIndex() == 0 else "hardware"
        directory = QFileDialog.getExistingDirectory(self, f"Choose parent for a new {label} run")
        if directory:
            self.output.setText(str(Path(directory) / Path(_new_directory()).name))

    def choose_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open acquisition run", "",
                                             "Acquisition runs (metadata.json events.csv);;CSV (*.csv)")
        if path:
            self.open_saved(Path(path))

    def open_saved(self, path):
        if self.worker is not None or self._hardware_running:
            return
        try:
            saved = read_acquisition_run(Path(path))
            label = saved.execution_mode.upper()
            self.banner.setText(f"SAVED RUN · {label} · {saved.status} · {saved.directory} · Controls show current settings, not this run's")
            manifest_batches = None
            if saved.manifest:
                manifest_batches = saved.manifest.get("operation", {}).get("acquisition", {}).get("batches")
            status = (f"{label} · {saved.status} · {_events_text(saved.current_segment_rows)} in this "
                     f"run's segment ({_events_text(saved.rows)} total in file) · channels {saved.channels}")
            self.status.setText(status + (" · " + "; ".join(saved.warnings) if saved.warnings else ""))
            self.details.setPlainText(json.dumps({
                "status": saved.status, "execution_mode": saved.execution_mode,
                "channels": saved.channels, "row_count": len(saved.rows),
                "current_segment_row_count": len(saved.current_segment_rows),
                "event_count": _count_events(saved.rows),
                "current_segment_event_count": _count_events(saved.current_segment_rows),
                "warnings": saved.warnings, "manifest": saved.manifest,
            }, indent=2))
            completed = (saved.manifest.get("completed_points") if saved.manifest else None) or 0
            self.progress.setRange(0, max(1, manifest_batches or completed or 1))
            self.progress.setValue(completed)
            self.batch_summary.clear()
            # This run's own segment (not the whole, possibly multi-run
            # append-mode CSV history) matches the manifest's declared
            # channels -- see read_acquisition_run's module docstring.
            self._set_spectra_channels(saved.channels)
            self._live_reader = None
            self._spectra = _SpectraData()
            self._spectra.add_rows(saved.current_segment_rows)
            self._spectra_title = (f"{label} · {saved.status} · "
                                   f"{_events_text(saved.current_segment_rows)} in this run's segment")
            self._refresh_spectra()
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
            # wait for the in-flight run this window started to reach a
            # terminal snapshot, same as the SIMULATION close-wait path.
            event.ignore()
            self._closing = True
        else:
            self.timer.stop()
            event.accept()
