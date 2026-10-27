"""Muon detector view: a demo top-view of the SiPM layers with event replay.

Fully offline: events come from the synthetic simulator or a saved acquisition run.
No device logic and no board connection here; the physics lives in
``radioroc.data.muon_simulator`` / ``muon_analysis``. A future live feed can call
``append_events`` to add events while the view is open.
"""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QRadioButton,
    QScrollArea, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from radioroc.data import muon_analysis, muon_rate, muon_simulator
from radioroc.data.muon_types import (
    N_CHANNELS, DetectorLayout, LayoutError, MuonEvent, PlintSpec, SiPMPlacement, format_channel_list,
    parse_channel_list,
)

_IDLE = (52, 54, 60)
_YELLOW = (255, 200, 0)
_WHITE = (255, 255, 235)
_FRAME_MS = 30
_LAYER_TITLES = {0: "Layer 0 (bottom)", 1: "Layer 1 (top)"}


def glow_colour(level: float) -> QColor:
    """Dark grey -> bright yellow (level 0.5) -> white (level 1)."""
    level = min(1.0, max(0.0, level))
    if level <= 0.5:
        t, a, b = level / 0.5, _IDLE, _YELLOW
    else:
        t, a, b = (level - 0.5) / 0.5, _YELLOW, _WHITE
    return QColor(*(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))


class SipmItem(QGraphicsRectItem):
    """One SiPM: a rounded square centred on its scene position, with the channel number."""

    def __init__(self, view, channel, size_mm):
        half = size_mm / 2
        super().__init__(-half, -half, size_mm, size_mm)
        self._view = view
        self.channel = channel
        self.setPen(QPen(QColor(20, 20, 24), 0.3))
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.label = QGraphicsSimpleTextItem(str(channel), self)
        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        self.label.setFont(font)
        rect = self.label.boundingRect()
        scale = size_mm * 0.42 / 10.0
        self.label.setScale(scale)
        self.label.setPos(-rect.width() * scale / 2, -rect.height() * scale / 2)
        self.label.setAcceptedMouseButtons(Qt.NoButton)
        self.level = 0.0
        self.has_data = True
        self.is_seed = False
        self.restyle()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        radius = self.rect().width() * 0.18
        painter.drawRoundedRect(self.rect(), radius, radius)

    def restyle(self):
        colour = glow_colour(self.level)
        if self.has_data:
            self.setBrush(QBrush(colour))
        else:
            self.setBrush(QBrush(QColor(86, 88, 94), Qt.BDiagPattern))
        if self.is_seed:
            self.setPen(QPen(QColor(80, 220, 255), 0.7))
        else:
            self.setPen(QPen(QColor(20, 20, 24), 0.3))
        dark = self.level > 0.45
        self.label.setBrush(QBrush(QColor(20, 20, 20) if dark else QColor(210, 210, 215)))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._view._editing_items:
            # Snap to 1 mm and stay inside the layer panel (scene y points down).
            cx, half = self._view._panel_centre_x(self._view_layer()), self._view._panel_half
            half_y = self._view._panel_half_y
            x = min(cx + half, max(cx - half, round(value.x() - cx) + cx))
            y = min(half_y, max(-half_y, round(value.y())))
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged and self._view._editing_items:
            self._view._item_dragged(self)
        return super().itemChange(change, value)

    def _view_layer(self):
        return self._view.layout.placement(self.channel).layer

    def contextMenuEvent(self, event):
        view = self._view
        if not view.edit_mode or len(view._panel_layers) < 2:
            return
        menu = QMenu()
        act = menu.addAction("Move to other layer")
        if menu.exec(event.screenPos()) is act:
            view.move_to_other_layer(self.channel)


class PlintItem(QGraphicsRectItem):
    """One plint (scintillator bar): translucent blue-grey rounded rectangle behind the SiPMs of its panel."""

    def __init__(self, view, index, width_mm, length_mm):
        super().__init__(-width_mm / 2, -length_mm / 2, width_mm, length_mm)
        self._view = view
        self.index = index
        self.setBrush(QBrush(QColor(110, 140, 175, 70)))
        pen = QPen(QColor(140, 170, 205, 200), 0.0)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        radius = min(self.rect().width(), self.rect().height()) * 0.08
        painter.drawRoundedRect(self.rect(), radius, radius)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._view._editing_items:
            layer = self._view._plint_layer(self.index)
            cx = self._view._panel_centre_x(layer)
            x = min(cx + self._view._panel_half, max(cx - self._view._panel_half, round(value.x() - cx) + cx))
            y = min(self._view._panel_half_y, max(-self._view._panel_half_y, round(value.y())))
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged and self._view._editing_items:
            self._view._plint_dragged(self)
        return super().itemChange(change, value)


class ManualPedestalDialog(QDialog):
    """Small table channel -> pedestal value, with a 'Set all to' box."""

    def __init__(self, channels, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual pedestals (high gain)")
        self.channels = list(channels)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.all_spin = QDoubleSpinBox()
        self.all_spin.setRange(0, 4095)
        self.all_spin.setDecimals(1)
        self.all_spin.setValue(float(sorted(values.values())[len(values) // 2]) if values else 100.0)
        self.all_spin.setAccessibleName("Set all pedestals to")
        set_all = QPushButton("Set all")
        set_all.clicked.connect(lambda _c=False: self.set_all(self.all_spin.value()))
        top.addWidget(QLabel("Set all to"))
        top.addWidget(self.all_spin)
        top.addWidget(set_all)
        lay.addLayout(top)
        self.table = QTableWidget(len(self.channels), 2)
        self.table.setHorizontalHeaderLabels(["Channel", "Pedestal (counts)"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, ch in enumerate(self.channels):
            item = QTableWidgetItem(str(ch))
            item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(f"{values.get(ch, self.all_spin.value()):g}"))
        lay.addWidget(self.table)
        row = QHBoxLayout()
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.resize(300, 380)

    def set_all(self, value):
        for row in range(self.table.rowCount()):
            self.table.item(row, 1).setText(f"{float(value):g}")

    def values(self) -> dict:
        """Channel -> value; raises ValueError naming the bad channel."""
        out = {}
        for row, ch in enumerate(self.channels):
            try:
                v = float(self.table.item(row, 1).text())
            except ValueError:
                raise ValueError(f"channel {ch}: not a number") from None
            if not 0 <= v <= 4095:
                raise ValueError(f"channel {ch}: pedestal must be 0..4095")
            out[ch] = v
        return out

    def accept(self):
        try:
            self.values()
        except ValueError:
            return
        super().accept()


class AddSipmDialog(QDialog):
    """Small form for one new SiPM: layer, free channel and position (mm)."""

    def __init__(self, layers, used_channels, position_for_layer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add SiPM")
        self._used = set(used_channels)
        self._position_for_layer = position_for_layer
        form = QFormLayout(self)
        self.layer_combo = QComboBox()
        for layer in layers:
            self.layer_combo.addItem(f"Layer {layer}", layer)
        self.layer_combo.setAccessibleName("New SiPM layer")
        free = [c for c in range(N_CHANNELS) if c not in self._used]
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, N_CHANNELS - 1)
        self.channel_spin.setValue(free[0] if free else 0)
        self.channel_spin.setAccessibleName("New SiPM channel")
        self.x_spin = QDoubleSpinBox()
        self.y_spin = QDoubleSpinBox()
        for box, name in ((self.x_spin, "New SiPM x"), (self.y_spin, "New SiPM y")):
            box.setRange(-100000, 100000)
            box.setDecimals(1)
            box.setAccessibleName(name)
        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #e6a23c;")
        form.addRow("Layer", self.layer_combo)
        form.addRow("Channel", self.channel_spin)
        form.addRow("X (mm)", self.x_spin)
        form.addRow("Y (mm)", self.y_spin)
        form.addRow(self.message_label)
        row = QHBoxLayout()
        ok, cancel = QPushButton("Add"), QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        form.addRow(row)
        self.layer_combo.currentIndexChanged.connect(lambda _i: self._reset_position())
        self._reset_position()

    def set_layer(self, layer):
        index = self.layer_combo.findData(layer)
        if index >= 0:
            self.layer_combo.setCurrentIndex(index)

    def _reset_position(self):
        x, y = self._position_for_layer(self.layer_combo.currentData())
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)

    def values(self):
        """(layer, channel, x_mm, y_mm)."""
        return (self.layer_combo.currentData(), self.channel_spin.value(), self.x_spin.value(), self.y_spin.value())

    def accept(self):
        channel = self.channel_spin.value()
        if channel in self._used:
            self.message_label.setText(f"Channel {channel} is already used; choose another.")
            return
        super().accept()


class MuonView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = DetectorLayout.grid(4, 8, 10.0, layers=2)
        self.events: list[MuonEvent] = []
        self.analyses: list = []
        self._pedestals: dict[int, float] = {}
        self._pedestal_mode = "auto"
        self._file_pedestals: dict[int, float] = {}
        self._manual_pedestals: dict[int, float] = {}
        self._pedestals_from_simulator = False
        self._pedestal_warning = ""
        self._run_pedestal_set = None  # PedestalSet saved with the loaded run (pedestals.json), if in use
        self._no_run_pedestals = False  # a real run was loaded without saved pedestals
        self._timing = None             # RunTiming of a loaded real run (None: simulated / nothing loaded)
        self._run_rate = None
        self._background = None         # (path, RunRate) of the background run
        self._rate_net = None
        self._area_user_set = False
        self._plint_items: list[PlintItem] = []
        self._plint_table_busy = False
        self._sipm_table_busy = False
        self._select_busy = False
        self._data_channels: set[int] = set()
        self.current_index = -1
        self._brightness: dict[int, float] = {}
        self._items: dict[int, SipmItem] = {}
        self._crosses: list = []
        self._editing_items = False
        self._playing = False
        self._accum_ms = 0.0
        self._panel_layers: list[int] = []
        self._panel_half = 40.0
        self._panel_half_y = 40.0
        self._edit_mode = False
        self._building = False
        self.setAccessibleName("Muon detector view")

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor(28, 29, 33)))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setMinimumSize(380, 260)
        self.view.setAccessibleName("Detector canvas")
        self.view.setAccessibleDescription("Top view of the SiPM layers; lit SiPMs show the current event.")
        self.scene.selectionChanged.connect(self._selection_changed)

        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(_FRAME_MS)
        self.timer.timeout.connect(lambda: self.advance(_FRAME_MS))
        self.timer.start()
        self._sync_layout_controls()
        self._rebuild_scene()
        self._fill_plint_table()
        self._fill_sipm_table()
        self._update_controls()

    # ---------------------------------------------------------------- UI --
    def _spin(self, lo, hi, value, name, tip, decimals=None, step=None):
        if decimals is None:
            box = QSpinBox()
            box.setRange(int(lo), int(hi))
            box.setValue(int(value))
        else:
            box = QDoubleSpinBox()
            box.setDecimals(decimals)
            box.setRange(lo, hi)
            box.setValue(value)
            box.setSingleStep(step or 1.0)
        box.setAccessibleName(name)
        box.setToolTip(tip)
        box.setFocusPolicy(Qt.StrongFocus)
        return box

    def _button(self, text, name, tip, slot):
        b = QPushButton(text)
        b.setAccessibleName(name)
        b.setToolTip(tip)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        left.addWidget(self.view, 1)

        self.info_label = QLabel("No events yet. Generate simulated events or open a saved run.")
        self.info_label.setWordWrap(True)
        self.info_label.setAccessibleName("Current event")
        self.stats_label = QLabel("")
        self.stats_label.setAccessibleName("Statistics")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Muon view status")
        for lab in (self.info_label, self.stats_label, self.status_label):
            lab.setMinimumWidth(100)
        left.addWidget(self.info_label)
        left.addWidget(self.stats_label)
        left.addWidget(self.status_label)

        # Replay controls under the canvas.
        replay_panel = QWidget()
        rv = QVBoxLayout(replay_panel)
        rv.setContentsMargins(0, 0, 0, 0)
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self.generate_button = self._button("Generate events", "Generate events", "Simulate events for this layout",
                                            self._generate_clicked)
        self.open_button = self._button("Open saved run…", "Open saved run", "Load events from an acquisition run folder",
                                        self._open_clicked)
        self.open_run_button = self.open_button
        self.replay_box = QWidget()      # the replay controls proper; disabled without events or while editing
        rr = QHBoxLayout(self.replay_box)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(4)
        self.step_back_button = self._button("Step back", "Step back", "Previous event", lambda: self.step(-1))
        self.play_button = self._button("Play", "Play or pause", "Replay the events automatically", self._toggle_play)
        self.step_button = self._button("Step forward", "Step forward", "Next event", lambda: self.step(1))
        self.coinc_check = QCheckBox("Coincidences only")
        self.coinc_check.setAccessibleName("Coincidences only")
        self.coinc_check.setToolTip("Skip events that do not hit every layer")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName("Event index")
        self.slider.valueChanged.connect(self._slider_changed)
        for w in (self.step_back_button, self.play_button, self.step_button):
            rr.addWidget(w)
        rr.addStretch(1)
        r1.addWidget(self.generate_button)
        r1.addWidget(self.open_button)
        r1.addWidget(self.replay_box, 1)
        self.replay_options = QWidget()
        r2 = QHBoxLayout(self.replay_options)
        r2.setContentsMargins(0, 0, 0, 0)
        self.speed_spin = self._spin(0.1, 1000, 2.0, "Replay speed", "Events per second", 1, 0.5)
        self.glow_spin = self._spin(10, 20000, 600, "Glow time", "Time constant of the glow decay (ms)", 0, 50)
        r2.addWidget(self.coinc_check)
        r2.addWidget(QLabel("Speed (events/s)"))
        r2.addWidget(self.speed_spin)
        r2.addWidget(QLabel("Glow time (ms)"))
        r2.addWidget(self.glow_spin)
        r2.addStretch(1)
        rv.addLayout(r1)
        rv.addWidget(self.replay_options)
        rv.addWidget(self.slider)
        left.addWidget(replay_panel)
        root.addLayout(left, 1)

        # Right column: layout / events / detection, scrollable.
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 4, 0)

        lbox = QGroupBox("Layout")
        lv = QVBoxLayout(lbox)
        lg = QGridLayout()
        self.layers_spin = self._spin(1, 2, 2, "Layers", "Number of SiPM layers (1 or 2)")
        self.rows_spin = self._spin(1, 64, 4, "Rows", "SiPM rows per layer")
        self.cols_spin = self._spin(1, 64, 8, "Columns", "SiPM columns per layer (SiPMs per row)")
        self.pitch_spin = self._spin(1, 200, 10, "Pitch", "Centre-to-centre spacing of SiPMs in a layer (mm)", 1, 1)
        self.spacing_spin = self._spin(1, 5000, 100, "Layer spacing", "Distance between the two layers (mm)", 1, 5)
        self.size_spin = self._spin(1, 100, 6, "SiPM size", "Side of one SiPM square (mm)", 1, 0.5)
        for i, (text, w) in enumerate((("Layers", self.layers_spin), ("Rows", self.rows_spin),
                                       ("Columns", self.cols_spin), ("Pitch", self.pitch_spin),
                                       ("Spacing", self.spacing_spin), ("Size", self.size_spin))):
            lg.addWidget(QLabel(text), i // 2, (i % 2) * 2)
            lg.addWidget(w, i // 2, (i % 2) * 2 + 1)
        lv.addLayout(lg)
        self.rebuild_button = self._button("Rebuild grid", "Rebuild grid", "Replace the layout by a regular grid",
                                           self._rebuild_clicked)
        lv.addWidget(self.rebuild_button)
        cf = QFormLayout()
        self.layer0_edit = QLineEdit()
        self.layer0_edit.setPlaceholderText("0-31")
        self.layer0_edit.setAccessibleName("Layer 0 channels")
        self.layer0_edit.setToolTip("Board channels of layer 0, e.g. 0-31 or 6, 7, 9-12")
        self.layer1_edit = QLineEdit()
        self.layer1_edit.setPlaceholderText("32-63")
        self.layer1_edit.setAccessibleName("Layer 1 channels")
        self.layer1_edit.setToolTip("Board channels of layer 1 (needs Layers = 2), e.g. 32-63")
        cf.addRow("Layer 0 channels", self.layer0_edit)
        cf.addRow("Layer 1 channels", self.layer1_edit)
        lv.addLayout(cf)
        self.build_channels_button = self._button(
            "Build from channel lists", "Build from channel lists",
            "Lay out each layer's channels in rows of Columns SiPMs at the given Pitch", self._build_channels_clicked)
        lv.addWidget(self.build_channels_button)
        self.layers_spin.valueChanged.connect(lambda _v: self._update_channel_fields())
        self.spacing_spin.valueChanged.connect(self._spacing_changed)
        self.size_spin.valueChanged.connect(self._size_changed)

        self.sipm_table = QTableWidget(0, 4)
        self.sipm_table.setHorizontalHeaderLabels(["Channel", "Layer", "X (mm)", "Y (mm)"])
        self.sipm_table.verticalHeader().setVisible(False)
        self.sipm_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sipm_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sipm_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sipm_table.setFixedHeight(150)
        self.sipm_table.setAccessibleName("SiPMs")
        self.sipm_table.setToolTip("One row per SiPM. Edit a cell to change its channel, layer or position.")
        self.sipm_table.itemChanged.connect(self._sipm_cell_changed)
        self.sipm_table.itemSelectionChanged.connect(self._sipm_table_selection_changed)
        lv.addWidget(QLabel("SiPMs"))
        lv.addWidget(self.sipm_table)

        self.edit_check = QCheckBox("Edit layout")
        self.edit_check.setAccessibleName("Edit layout")
        self.edit_check.setToolTip("Drag SiPMs with the mouse; replay is disabled while editing")
        self.edit_check.toggled.connect(self._set_edit_mode)
        lv.addWidget(self.edit_check)
        self.add_button = self._button("Add SiPM", "Add SiPM", "Add a SiPM: choose layer, channel and position",
                                       self._add_clicked)
        self.remove_button = self._button("Remove selected", "Remove selected", "Remove the selected SiPMs",
                                          self._remove_clicked)
        self.save_button = self._button("Save layout…", "Save layout", "Save the layout as JSON", self._save_clicked)
        self.load_button = self._button("Load layout…", "Load layout", "Load a layout JSON file", self._load_clicked)
        brow1, brow2 = QHBoxLayout(), QHBoxLayout()
        for b in (self.add_button, self.remove_button):
            brow1.addWidget(b)
        for b in (self.save_button, self.load_button):
            brow2.addWidget(b)
        lv.addLayout(brow1)
        lv.addLayout(brow2)
        sv.addWidget(lbox)

        pbox = QGroupBox("Plints")
        pv = QVBoxLayout(pbox)
        self.plint_table = QTableWidget(0, 6)
        self.plint_table.setHorizontalHeaderLabels(["Layer", "Centre\nX (mm)", "Centre\nY (mm)", "Width\n(mm)",
                                                    "Length\n(mm)", "Thick.\n(mm)"])
        for col, tip in ((1, "Centre of the plint in the layer panel, mm, x to the right"),
                         (2, "Centre of the plint in the layer panel, mm, y upwards"),
                         (5, "Thickness of the plint (mm)")):
            self.plint_table.horizontalHeaderItem(col).setToolTip(tip)
        self.plint_table.verticalHeader().setVisible(False)
        self.plint_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.plint_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.plint_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.plint_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plint_table.horizontalHeader().setMinimumSectionSize(40)
        self.plint_table.setFixedHeight(130)
        self.plint_table.setMinimumWidth(260)
        self.plint_table.setAccessibleName("Plints")
        self.plint_table.setToolTip("Scintillator bars; x extent = width, y extent = length. Edit a cell to change it.")
        self.plint_table.itemChanged.connect(self._plint_cell_changed)
        pv.addWidget(self.plint_table)
        prow = QHBoxLayout()
        self.add_plint_button = self._button("Add plint", "Add plint", "Add a plint to the table", self._add_plint_clicked)
        self.remove_plint_button = self._button("Remove plint", "Remove plint", "Remove the selected plint",
                                                self._remove_plint_clicked)
        self.autofit_button = self._button("Auto-fit", "Auto-fit plints",
                                           "Drop the explicit plints; use one plint per layer around the SiPMs",
                                           self.auto_fit_plints)
        for b in (self.add_plint_button, self.remove_plint_button, self.autofit_button):
            prow.addWidget(b)
        pv.addLayout(prow)
        sv.addWidget(pbox)

        ebox = QGroupBox("Events")
        ef = QFormLayout(ebox)
        self.n_spin = self._spin(1, 100000, 200, "Number of events", "How many events to simulate")
        self.seed_spin = self._spin(0, 2_000_000_000, 1, "Seed", "Random seed (same seed, same events)")
        self.fraction_spin = self._spin(0, 1, 0.8, "Muon fraction", "Share of events that are muon tracks", 2, 0.05)
        ef.addRow("Number of events", self.n_spin)
        ef.addRow("Seed", self.seed_spin)
        ef.addRow("Muon fraction", self.fraction_spin)
        sv.addWidget(ebox)

        dbox = QGroupBox("Detection")
        df = QFormLayout(dbox)
        self.threshold_spin = self._spin(0, 100000, 40, "Detection threshold", "Counts above pedestal to count as a hit", 0, 5)
        self.full_scale_spin = self._spin(1, 100000, 400, "Full-scale brightness", "Counts that light a SiPM fully", 0, 50)
        self.threshold_spin.valueChanged.connect(lambda _v: (self._update_pedestal_labels(), self._reanalyse()))
        df.addRow("Threshold (counts)", self.threshold_spin)
        df.addRow("Full scale (counts)", self.full_scale_spin)
        sv.addWidget(dbox)

        qbox = QGroupBox("Pedestals")
        qv = QVBoxLayout(qbox)
        self.ped_auto_radio = QRadioButton("Estimate from events (median)")
        self.ped_file_radio = QRadioButton("From a pedestal run/file…")
        self.ped_manual_radio = QRadioButton("Manual…")
        self._ped_group = QButtonGroup(self)
        for mode, radio in (("auto", self.ped_auto_radio), ("file", self.ped_file_radio),
                            ("manual", self.ped_manual_radio)):
            self._ped_group.addButton(radio)
            radio.setAccessibleName(radio.text())
            radio.clicked.connect(lambda _c=False, m=mode: self._pedestal_radio_clicked(m))
            qv.addWidget(radio)
        self.ped_auto_radio.setChecked(True)
        self.ped_file_button = self._button("Pedestal file…", "Pedestal file", "Choose a pedestal JSON file",
                                            self._pedestal_file_clicked)
        self.ped_run_button = self._button("Pedestal run folder…", "Pedestal run folder",
                                           "Choose a saved acquisition run recorded without muons",
                                           self._pedestal_run_clicked)
        self.ped_save_button = self._button("Save pedestals…", "Save pedestals", "Save the effective pedestals as JSON",
                                            self._save_pedestals_clicked)
        qrow = QHBoxLayout()
        qrow.addWidget(self.ped_file_button)
        qrow.addWidget(self.ped_run_button)
        qv.addLayout(qrow)
        qv.addWidget(self.ped_save_button)
        self.pedestal_label = QLabel("Pedestals: no events")
        self.pedestal_label.setWordWrap(True)
        self.pedestal_label.setAccessibleName("Pedestals")
        self.pedestal_warning_label = QLabel("")
        self.pedestal_warning_label.setWordWrap(True)
        self.pedestal_warning_label.setStyleSheet("color: #e6a23c; font-weight: bold;")
        self.pedestal_warning_label.setAccessibleName("Pedestal warning")
        self.pedestal_warning_label.setVisible(False)
        qv.addWidget(self.pedestal_label)
        qv.addWidget(self.pedestal_warning_label)
        sv.addWidget(qbox)

        rbox = QGroupBox("Rate")
        rv = QVBoxLayout(rbox)
        self.rate_label = QLabel("Rate needs a saved run.")
        self.rate_label.setWordWrap(True)
        self.rate_label.setAccessibleName("Muon rate")
        self.rate_label.setMinimumWidth(100)
        rv.addWidget(self.rate_label)
        self.background_button = self._button("Background run…", "Background run",
                                              "Choose a run recorded without muon signal; it is analysed with the "
                                              "same layout, threshold and pedestals and subtracted",
                                              self._background_clicked)
        rv.addWidget(self.background_button)
        self.background_label = QLabel("")
        self.background_label.setWordWrap(True)
        self.background_label.setAccessibleName("Background rate")
        self.background_label.setMinimumWidth(100)
        rv.addWidget(self.background_label)
        self.area_spin = self._spin(0, 1_000_000, 0, "Coincidence area",
                                    "Area in cm2 for the flux per cm2 (0 = none); default from the plints", 2, 10)
        self.area_spin.valueChanged.connect(self._area_changed)
        arow = QFormLayout()
        arow.addRow("Area (cm2)", self.area_spin)
        rv.addLayout(arow)
        self.flux_label = QLabel("")
        self.flux_label.setWordWrap(True)
        self.flux_label.setAccessibleName("Flux")
        self.flux_label.setMinimumWidth(100)
        rv.addWidget(self.flux_label)
        self.copy_summary_button = self._button("Copy summary", "Copy rate summary",
                                                "Copy the rate summary to the clipboard", self.copy_summary)
        self.save_summary_button = self._button("Save summary…", "Save rate summary",
                                                "Save the rate summary as a text file (not in a run folder)",
                                                self._save_summary_clicked)
        brow = QHBoxLayout()
        brow.addWidget(self.copy_summary_button)
        brow.addWidget(self.save_summary_button)
        rv.addLayout(brow)
        sv.addWidget(rbox)
        sv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(side.sizeHint().width() + 24)
        root.addWidget(scroll)

    def attach_hints(self, hint):
        for w in (self.rebuild_button, self.edit_check, self.add_button, self.remove_button, self.save_button,
                  self.load_button, self.generate_button, self.open_button, self.add_plint_button, self.remove_plint_button,
                  self.autofit_button, self.ped_file_button, self.ped_run_button, self.ped_save_button,
                  self.background_button, self.copy_summary_button, self.save_summary_button,
                  self.play_button, self.coinc_check,
                  self.threshold_spin, self.full_scale_spin, self.glow_spin, self.speed_spin, self.area_spin):
            tip = w.toolTip()
            if tip:
                hint.attach(w, tip)

    # ------------------------------------------------------ layout model --
    @property
    def layout(self) -> DetectorLayout:
        return self._layout

    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    @edit_mode.setter
    def edit_mode(self, on):
        self.edit_check.setChecked(bool(on))

    def _set_status(self, text):
        self.status_label.setText(text)

    def set_layout(self, layout: DetectorLayout):
        layout.validate()
        self._layout = layout
        self._sync_layout_controls()
        if hasattr(self, "area_spin") and not self._area_user_set:
            self._set_default_area()
        self._after_layout_change(structural=True)
        self._recompute_pedestals()

    def _sync_layout_controls(self):
        lay = self._layout
        for w in (self.layers_spin, self.spacing_spin, self.size_spin):
            w.blockSignals(True)
        self.layers_spin.setValue(max(1, len(lay.layers()), 2 if 1 in lay.layers() else 1))
        self.spacing_spin.setValue(lay.layer_spacing_mm)
        self.size_spin.setValue(lay.sipm_size_mm)
        for w in (self.layers_spin, self.spacing_spin, self.size_spin):
            w.blockSignals(False)
        self._update_channel_fields()

    # ------------------------------------------------- channel lists ------
    def _update_channel_fields(self):
        """Pre-fill the channel list fields from the layout; layer 1 only editable with two layers."""
        for layer, edit in ((0, self.layer0_edit), (1, self.layer1_edit)):
            edit.setText(format_channel_list(s.channel for s in self._layout.in_layer(layer)))
        self.layer1_edit.setEnabled(self.layers_spin.value() == 2)

    def channel_list_text(self, layer) -> str:
        return (self.layer0_edit if layer == 0 else self.layer1_edit).text()

    def set_channel_lists(self, layer0_text, layer1_text):
        """Parse both lists and rebuild the layout from them (Columns = SiPMs per row, Pitch from the spin boxes).
        Returns False, with the reason in the status label and the layout unchanged, on any error."""
        try:
            lists = {0: parse_channel_list(layer0_text)}
            if self.layers_spin.value() == 2:
                lists[1] = parse_channel_list(layer1_text)
            elif str(layer1_text).strip():
                raise LayoutError("layer 1 is off: set Layers to 2 to use it")
            layout = DetectorLayout.from_channel_lists(
                lists, int(self.cols_spin.value()), float(self.pitch_spin.value()),
                self._layout.layer_spacing_mm, self._layout.sipm_size_mm, self._layout.name)
        except LayoutError as exc:
            self._set_status(f"Cannot build from channel lists: {exc}")
            return False
        layout.plints = [p for p in self._layout.plints if p.layer in layout.layers()]
        self._layout = layout
        self._sync_layout_controls()
        self._after_layout_change(structural=True)
        self._set_status(f"Built {len(layout.sipms)} SiPMs from the channel lists.")
        return True

    def _build_channels_clicked(self):
        self.set_channel_lists(self.layer0_edit.text(), self.layer1_edit.text())

    # ------------------------------------------------------ SiPM table -----
    def _fill_sipm_table(self):
        selected = set(self._table_channels())
        self._sipm_table_busy = True
        try:
            rows = sorted(self._layout.sipms, key=lambda s: s.channel)
            self.sipm_table.setRowCount(len(rows))
            for row, s in enumerate(rows):
                for col, text in enumerate((str(s.channel), str(s.layer), f"{s.x_mm:g}", f"{s.y_mm:g}")):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setData(Qt.UserRole, s.channel)
                    self.sipm_table.setItem(row, col, item)
        finally:
            self._sipm_table_busy = False
        self._set_table_selection(selected)

    def _set_table_selection(self, wanted):
        wanted = set(wanted)
        previous = self._sipm_table_busy
        self._sipm_table_busy = True
        try:
            self.sipm_table.clearSelection()
            for row in range(self.sipm_table.rowCount()):
                if self.sipm_table.item(row, 0).data(Qt.UserRole) in wanted:
                    for col in range(4):
                        self.sipm_table.item(row, col).setSelected(True)
        finally:
            self._sipm_table_busy = previous

    def _table_channels(self):
        rows = {i.row() for i in self.sipm_table.selectedItems()}
        out = []
        for row in sorted(rows):
            item = self.sipm_table.item(row, 0)
            if item is not None:
                out.append(item.data(Qt.UserRole))
        return out

    def _scene_channels(self):
        try:
            return [i.channel for i in self.scene.selectedItems() if isinstance(i, SipmItem)]
        except RuntimeError:
            return []

    def select_channels(self, channels):
        """Select these SiPMs in the table and (in edit mode, where they are selectable) on the canvas."""
        wanted = set(channels)
        self._select_busy = True
        try:
            self._set_table_selection(wanted)
            for ch, item in self._items.items():
                if item.isSelected() != (ch in wanted) and (ch not in wanted or self._edit_mode):
                    item.setSelected(ch in wanted)
        finally:
            self._select_busy = False
        self._update_controls()

    def _sipm_table_selection_changed(self):
        if self._sipm_table_busy or self._select_busy:
            return
        self.select_channels(self._table_channels())

    _SIPM_ERROR = "SiPM table: "

    def _sipm_cell_changed(self, item):
        if self._sipm_table_busy:
            return
        channel, col, text = item.data(Qt.UserRole), item.column(), item.text().strip()
        placement = next((s for s in self._layout.sipms if s.channel == channel), None)
        if placement is None:
            return
        try:
            if col == 0:
                value = int(text)
                if not 0 <= value < N_CHANNELS:
                    raise ValueError(f"channel {value} is outside 0..{N_CHANNELS - 1}")
                if value != channel and value in self._layout.channels():
                    raise ValueError(f"channel {value} is already used")
                changes = {"channel": value}
            elif col == 1:
                value = int(text)
                if value not in (0, 1):
                    raise ValueError("layer must be 0 or 1")
                if not self._layer_allowed(value):
                    raise ValueError("layer 1 needs Layers = 2")
                changes = {"layer": value}
            else:
                value = float(text)
                if not math.isfinite(value) or abs(value) > 1e5:
                    raise ValueError(f"{text!r} is not a usable number of millimetres")
                changes = {"x_mm" if col == 2 else "y_mm": value}
        except ValueError as exc:
            reason = str(exc)
            if reason.startswith("invalid literal") or reason.startswith("could not convert"):
                reason = f"{text!r} is not a number"
            self._set_status(f"{self._SIPM_ERROR}{reason}; value restored.")
            self._fill_sipm_table()
            return
        keep = {changes.get("channel", channel) if ch == channel else ch for ch in self._selected_channels()}
        self._replace_placement(channel, **changes)
        self._after_layout_change(structural=True)
        self.select_channels(keep)
        self._set_status("")

    def rebuild_grid(self, rows, cols, pitch_mm, layers):
        try:
            layout = DetectorLayout.grid(rows, cols, pitch_mm, layers=layers,
                                         layer_spacing_mm=self._layout.layer_spacing_mm,
                                         sipm_size_mm=self._layout.sipm_size_mm, name=self._layout.name)
            layout.plints = [p for p in self._layout.plints if p.layer < layers]
        except (LayoutError, ValueError) as exc:
            self._set_status(f"Cannot build grid: {exc}")
            return False
        self._layout = layout
        self._sync_layout_controls()
        self._after_layout_change(structural=True)
        self._set_status(f"Grid {rows} x {cols} x {layers} layer(s): {len(layout.sipms)} SiPMs.")
        return True

    def _replace_placement(self, channel, /, **changes):
        sipms = self._layout.sipms
        for i, s in enumerate(sipms):
            if s.channel == channel:
                sipms[i] = replace(s, **changes)
                return
        raise KeyError(channel)

    def move_sipm(self, channel, x_mm, y_mm):
        """Move a SiPM within its layer (snapped to 1 mm and kept inside the panel); updates the layout."""
        placement = self._layout.placement(channel)
        half, half_y = self._panel_half, self._panel_half_y
        x = float(min(half, max(-half, round(x_mm))))
        y = float(min(half_y, max(-half_y, round(y_mm))))
        self._replace_placement(channel, x_mm=x, y_mm=y)
        item = self._items.get(channel)
        if item is not None:
            cx = self._panel_centre_x(placement.layer)
            self._editing_items = False
            item.setPos(cx + x, -y)
            self._editing_items = self._edit_mode
        self._after_layout_change(structural=False)

    def _layer_allowed(self, layer):
        """Layer 1 is available when Layers = 2 or the layout already has a layer 1."""
        return layer == 0 or (layer == 1 and (self.layers_spin.value() == 2 or 1 in self._layout.layers()))

    def _free_channels(self):
        used = set(self._layout.channels())
        return [c for c in range(N_CHANNELS) if c not in used]

    def _default_position(self, layer):
        """Next free slot: just right of the layer's rightmost SiPM by the current Pitch, or (0, 0) if empty."""
        same = self._layout.in_layer(layer)
        if not same:
            return 0.0, 0.0
        last = max(same, key=lambda s: (s.x_mm, s.y_mm))
        return last.x_mm + float(self.pitch_spin.value()), last.y_mm

    def add_sipm(self, layer=0, channel=None, x_mm=None, y_mm=None):
        free = self._free_channels()
        if not free:
            self._set_status("All 64 channels are in use.")
            return None
        if layer not in (0, 1) or not self._layer_allowed(layer):
            layer = 0 if not self._layout.layers() else self._layout.layers()[0]
        if channel is None:
            channel = free[0]
        elif channel not in free:
            self._set_status(f"Channel {channel} is not free (use 0..{N_CHANNELS - 1} once).")
            return None
        dx, dy = self._default_position(layer)
        x = dx if x_mm is None else float(x_mm)
        y = dy if y_mm is None else float(y_mm)
        self._layout.sipms.append(SiPMPlacement(int(channel), layer, x, y))
        try:
            self._layout.validate()
        except LayoutError as exc:
            self._layout.sipms.pop()
            self._set_status(f"Cannot add SiPM: {exc}")
            return None
        self._after_layout_change(structural=True)
        self._set_status(f"Added SiPM channel {channel} to layer {layer}.")
        return channel

    def add_sipm_dialog(self, layer=0):
        layers = [0, 1] if self._layer_allowed(1) else [0]
        dialog = AddSipmDialog(layers, self._layout.channels(), self._default_position, self)
        dialog.set_layer(layer if layer in layers else 0)
        return dialog

    def remove_sipm(self, channel):
        before = len(self._layout.sipms)
        self._layout.sipms[:] = [s for s in self._layout.sipms if s.channel != channel]
        if len(self._layout.sipms) != before:
            self._after_layout_change(structural=True)

    def move_to_other_layer(self, channel):
        layers = self._layout.layers()
        if len(layers) < 2:
            return
        current = self._layout.placement(channel).layer
        self._replace_placement(channel, layer=1 - current)
        self._after_layout_change(structural=True)

    # ----------------------------------------------------------- plints ---
    @property
    def plints(self) -> list[PlintSpec]:
        """The effective plints: the explicit ones, or the auto plints around the SiPMs."""
        return self._layout.effective_plints()

    @property
    def plints_are_explicit(self) -> bool:
        return bool(self._layout.plints)

    def _make_explicit(self):
        if not self._layout.plints:
            self._layout.plints = self._layout.effective_plints()

    def _plint_layer(self, index):
        plints = self.plints
        return plints[index].layer if 0 <= index < len(plints) else 0

    def add_plint(self, layer=0, x_mm=0.0, y_mm=0.0, width_mm=100.0, length_mm=50.0, thickness_mm=10.0):
        spec = PlintSpec(int(layer), float(x_mm), float(y_mm), float(width_mm), float(length_mm), float(thickness_mm))
        old = list(self._layout.plints)
        self._make_explicit()
        self._layout.plints.append(spec)
        try:
            self._layout.validate()
        except LayoutError as exc:
            self._layout.plints = old
            self._set_status(f"Cannot add plint: {exc}")
            return None
        self._plints_changed()
        return len(self._layout.plints) - 1

    def remove_plint(self, index):
        plints = self.plints
        if not 0 <= index < len(plints):
            return False
        self._make_explicit()
        del self._layout.plints[index]
        self._plints_changed()
        return True

    def set_plint(self, index, **fields):
        plints = self.plints
        if not 0 <= index < len(plints):
            raise IndexError(index)
        unknown = set(fields) - {"layer", "x_mm", "y_mm", "width_mm", "length_mm", "thickness_mm"}
        if unknown:
            raise TypeError(f"unknown plint fields {sorted(unknown)}")
        old = list(self._layout.plints)
        self._make_explicit()
        self._layout.plints[index] = replace(self._layout.plints[index], **fields)
        try:
            self._layout.validate()
        except LayoutError as exc:
            self._layout.plints = old
            self._set_status(f"Invalid plint value: {exc}")
            self._fill_plint_table()
            return False
        self._plints_changed()
        return True

    def auto_fit_plints(self):
        """Clear the explicit plints; the auto plint around each layer's SiPMs is used again."""
        self._layout.plints = []
        self._plints_changed()
        self._set_status("Plints fitted to the SiPMs.")

    def _plints_changed(self):
        self._rebuild_scene()
        self._fill_plint_table()
        self._update_controls()
        self._refresh_items()

    def _fill_plint_table(self):
        self._plint_table_busy = True
        try:
            explicit = self.plints_are_explicit
            plints = self.plints
            self.plint_table.setRowCount(len(plints))
            for row, p in enumerate(plints):
                for col, text in enumerate((str(p.layer), f"{p.x_mm:g}", f"{p.y_mm:g}", f"{p.width_mm:g}",
                                            f"{p.length_mm:g}", f"{p.thickness_mm:g}")):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    if not explicit:
                        item.setForeground(QBrush(QColor(140, 140, 150)))
                        font = item.font()
                        font.setItalic(True)
                        item.setFont(font)
                        item.setToolTip("Automatic plint around the SiPMs; edit a cell to make it explicit")
                    self.plint_table.setItem(row, col, item)
        finally:
            self._plint_table_busy = False

    _PLINT_FIELDS = ("layer", "x_mm", "y_mm", "width_mm", "length_mm", "thickness_mm")

    def _plint_cell_changed(self, item):
        if self._plint_table_busy:
            return
        row, col = item.row(), item.column()
        try:
            text = item.text().strip()
            value = int(text) if col == 0 else float(text)
        except ValueError:
            self._set_status(f"Plint value {item.text()!r} is not a number.")
            self._fill_plint_table()
            return
        self.set_plint(row, **{self._PLINT_FIELDS[col]: value})

    def _add_plint_clicked(self):
        row = self.plint_table.currentRow()
        plints = self.plints
        layer = plints[row].layer if 0 <= row < len(plints) else (self._layout.layers() or [0])[0]
        same = [p for p in plints if p.layer == layer]
        base = same[-1] if same else None
        if base is None:
            self.add_plint(layer)
        else:
            self.add_plint(layer, base.x_mm, base.y_mm, base.width_mm, base.length_mm, base.thickness_mm)

    def _remove_plint_clicked(self):
        row = self.plint_table.currentRow()
        if row < 0:
            self._set_status("Select a plint row to remove.")
            return
        self.remove_plint(row)

    def _plint_dragged(self, item):
        if self._building or item.index >= len(self.plints):
            return
        layer = self._plint_layer(item.index)
        cx = self._panel_centre_x(layer)
        self._make_explicit()
        self._layout.plints[item.index] = replace(self._layout.plints[item.index],
                                                  x_mm=float(round(item.pos().x() - cx)),
                                                  y_mm=float(-round(item.pos().y())))
        self._fill_plint_table()

    def _after_layout_change(self, structural):
        keep = set(self._selected_channels()) & set(self._layout.channels())
        self._reanalyse(refresh=False)
        if structural:
            self._rebuild_scene()
            self._fill_plint_table()
            self._update_channel_fields()
        self._fill_sipm_table()
        if keep:
            self.select_channels(keep)
        self._update_controls()
        self._refresh_items()

    # ---------------------------------------------------------- scene ----
    def _panel_centre_x(self, layer):
        index = self._panel_layers.index(layer) if layer in self._panel_layers else 0
        return index * (2 * self._panel_half + self._panel_gap)

    @property
    def _panel_gap(self):
        return 14.0

    def _rebuild_scene(self):
        self._building = True
        self._editing_items = False
        self.scene.blockSignals(True)
        self.scene.clear()
        self.scene.blockSignals(False)
        self._items.clear()
        self._crosses.clear()
        lay = self._layout
        self._panel_layers = lay.layers() or [0]
        pad = lay.sipm_size_mm / 2 + 6
        plints = [p for p in lay.effective_plints() if p.layer in self._panel_layers]
        ext_x = max([abs(s.x_mm) for s in lay.sipms] + [0.0]) + pad
        ext_y = max([abs(s.y_mm) for s in lay.sipms] + [0.0]) + pad
        ext_x = max([ext_x] + [abs(p.x_mm) + p.width_mm / 2 + 2.0 for p in plints])
        ext_y = max([ext_y] + [abs(p.y_mm) + p.length_mm / 2 + 2.0 for p in plints])
        self._panel_half = float(max(30.0, math.ceil(ext_x / 5.0) * 5.0))
        self._panel_half_y = float(max(30.0, math.ceil(ext_y / 5.0) * 5.0))
        half, half_y = self._panel_half, self._panel_half_y
        for layer in self._panel_layers:
            cx = self._panel_centre_x(layer)
            frame = self.scene.addRect(cx - half, -half_y, 2 * half, 2 * half_y, QPen(QColor(90, 92, 100), 0.6),
                                       QBrush(QColor(36, 37, 42)))
            frame.setZValue(-2)
            title = QGraphicsSimpleTextItem(_LAYER_TITLES.get(layer, f"Layer {layer}")
                                            if len(self._panel_layers) > 1 else "Layer 0")
            font = QFont()
            font.setPixelSize(10)
            font.setBold(True)
            title.setFont(font)
            title.setBrush(QBrush(QColor(220, 220, 225)))
            scale = max(0.5, half / 40.0 * 0.5)
            title.setScale(scale)
            title.setPos(cx - title.boundingRect().width() * scale / 2, -half_y - 12 * scale - 2)
            self.scene.addItem(title)
            cross = [self.scene.addLine(0, 0, 0, 0, QPen(QColor(80, 220, 255), 0.8)) for _ in range(2)]
            for c in cross:
                c.setZValue(5)
                c.setVisible(False)
            self._crosses.append((layer, cross))
        self._plint_items = []
        for index, p in enumerate(lay.effective_plints()):
            if p.layer not in self._panel_layers:
                continue
            pitem = PlintItem(self, index, p.width_mm, p.length_mm)
            pitem.setPos(self._panel_centre_x(p.layer) + p.x_mm, -p.y_mm)
            pitem.setZValue(0)
            pitem.setToolTip(f"Plint: {p.width_mm:g} x {p.length_mm:g} x {p.thickness_mm:g} mm")
            self.scene.addItem(pitem)
            self._plint_items.append(pitem)
        for s in lay.sipms:
            item = SipmItem(self, s.channel, lay.sipm_size_mm)
            item.setPos(self._panel_centre_x(s.layer) + s.x_mm, -s.y_mm)
            item.setZValue(1)
            self.scene.addItem(item)
            self._items[s.channel] = item
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-6, -6, 6, 6))
        self._apply_edit_flags()
        self._building = False
        self._editing_items = self._edit_mode
        self._fit()

    def _fit(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _apply_edit_flags(self):
        for item in self._items.values():
            item.setFlag(QGraphicsItem.ItemIsMovable, self._edit_mode)
            item.setFlag(QGraphicsItem.ItemIsSelectable, self._edit_mode)
            item.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.ArrowCursor)
        for item in self._plint_items:
            item.setFlag(QGraphicsItem.ItemIsMovable, self._edit_mode)
            item.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.ArrowCursor)

    def _item_dragged(self, item):
        if self._building:
            return
        placement = self._layout.placement(item.channel)
        cx = self._panel_centre_x(placement.layer)
        self._replace_placement(item.channel, x_mm=float(round(item.pos().x() - cx)),
                                y_mm=float(-round(item.pos().y())))
        self._reanalyse(refresh=False)
        self._fill_sipm_table()
        self._refresh_items()

    def _selection_changed(self):
        if not self._select_busy and not self._building:
            self._select_busy = True
            try:
                self._set_table_selection(self._scene_channels())
            finally:
                self._select_busy = False
        self._update_controls()

    def _selected_channels(self):
        return sorted(set(self._scene_channels()) | set(self._table_channels()))

    # -------------------------------------------------------- edit mode --
    def _set_edit_mode(self, on):
        self._edit_mode = bool(on)
        if on:
            self.pause()
        self._editing_items = self._edit_mode
        if not on and not self._layout.plints:
            self._plints_changed()  # automatic plints follow the SiPMs that were moved
        self._apply_edit_flags()
        self._update_controls()
        self._set_status("Edit mode: drag SiPMs to move them (1 mm steps)." if on else "")

    def _update_controls(self):
        editing = self._edit_mode
        has_events = bool(self.events)
        self.replay_box.setEnabled(has_events and not editing)
        self.replay_options.setEnabled(has_events and not editing)
        self.slider.setEnabled(has_events and not editing)
        self.generate_button.setEnabled(not editing)
        self.open_button.setEnabled(not editing)
        self.add_button.setEnabled(editing and len(self._layout.sipms) < N_CHANNELS)
        self.remove_button.setEnabled(editing and bool(self._selected_channels()))
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(self.events) - 1))
        self.slider.setValue(max(0, self.current_index))
        self.slider.blockSignals(False)
        self.play_button.setText("Pause" if self._playing else "Play")

    # ------------------------------------------------- button handlers ----
    def _rebuild_clicked(self):
        self.rebuild_grid(self.rows_spin.value(), self.cols_spin.value(), self.pitch_spin.value(),
                          self.layers_spin.value())

    def _spacing_changed(self, value):
        self._layout.layer_spacing_mm = float(value)
        self._reanalyse()

    def _size_changed(self, value):
        self._layout.sipm_size_mm = float(value)
        self._after_layout_change(structural=True)

    def _add_clicked(self):
        selected = self._selected_channels()
        layer = self._layout.placement(selected[0]).layer if selected else 0
        dialog = self.add_sipm_dialog(layer)
        if dialog.exec() == QDialog.Accepted:
            self.add_sipm(*dialog.values())

    def _remove_clicked(self):
        for ch in self._selected_channels():
            self.remove_sipm(ch)

    def _default_layout_dir(self):
        return Path.cwd() / "radioroc_runs" / "muon_layouts"

    def _save_clicked(self):
        folder = self._default_layout_dir()
        path, _ = QFileDialog.getSaveFileName(self, "Save layout", str(folder / "layout.json"), "Layout (*.json)")
        if path:
            self.save_layout_to(path)

    def _load_clicked(self):
        folder = self._default_layout_dir()
        path, _ = QFileDialog.getOpenFileName(self, "Load layout", str(folder), "Layout (*.json)")
        if path:
            self.load_layout_from(path)

    def save_layout_to(self, path):
        try:
            saved = self._layout.save_json(path)
        except (LayoutError, OSError) as exc:
            self._set_status(f"Could not save layout: {exc}")
            return False
        self._set_status(f"Layout saved to {saved}")
        return True

    def load_layout_from(self, path):
        try:
            layout = DetectorLayout.load_json(path)
        except (LayoutError, OSError, ValueError) as exc:
            self._set_status(f"Could not load layout: {exc}")
            return False
        self.set_layout(layout)
        self._set_status(f"Layout loaded from {path}")
        return True

    def _generate_clicked(self):
        self.generate_events(self.n_spin.value(), self.seed_spin.value(), self.fraction_spin.value())

    def _open_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Open acquisition run folder", str(Path.cwd() / "radioroc_runs"))
        if folder:
            self.load_run(folder)

    # ----------------------------------------------------------- events ---
    def generate_events(self, n=200, seed=1, muon_fraction=0.8):
        try:
            events, pedestals = muon_simulator.simulate_events(self._layout, int(n), seed=int(seed),
                                                               muon_fraction=float(muon_fraction))
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            self._set_status(f"Could not generate events: {exc}")
            return False
        self._install_events(list(events), dict(pedestals))
        self._set_status(f"Generated {len(self.events)} simulated events (seed {seed}).")
        return True

    def load_run(self, path):
        try:
            events = list(muon_analysis.load_events(Path(path)))
            if not events:
                raise ValueError("the run contains no events")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not open run: {exc}")
            return False
        self._install_events(events, None)
        self._adopt_run_pedestals(Path(path))
        try:
            self._timing = muon_rate.read_run_timing(Path(path))
        except Exception as exc:  # noqa: BLE001 - the page still works without a rate
            self._timing = None
            self._set_status(f"Could not read run timing: {exc}")
        self._area_user_set = False
        self._set_default_area()
        self._update_rate()
        data = {c for e in events for c in e.hg}
        extra = sorted(data - set(self._layout.channels()))
        note = f" Ignored channels not in the layout: {extra}." if extra else ""
        self._set_status(f"Loaded {len(events)} events from {path}.{note}")
        return True

    def _adopt_run_pedestals(self, path):
        """Use pedestals.json saved with the run (from the Calibration page's Pedestals step) if it covers the data."""
        had_run_set = self._run_pedestal_set is not None
        self._run_pedestal_set = None
        self._no_run_pedestals = True
        found = None
        try:
            from radioroc.data.pedestals import find_pedestals_for_run
            found = find_pedestals_for_run(path)
        except Exception as exc:  # noqa: BLE001 - a bad file must not block loading the run
            self._set_status(f"Could not read saved pedestals: {exc}")
        wanted = [c for c in self._layout.channels() if c in self._data_channels]
        if found is not None:
            hg = found.hg()
            if hg and all(c in hg for c in wanted):
                self._file_pedestals = dict(hg)
                self._run_pedestal_set = found
                self._no_run_pedestals = False
                self._pedestals_from_simulator = False
                self._pedestal_mode = "file"
                self._recompute_pedestals()
                return
        if had_run_set and self._pedestal_mode == "file":
            self._pedestal_mode = "auto"
        self._recompute_pedestals()

    def pedestal_source_text(self) -> str:
        """Which pedestals the analysis uses (for the Rate box and the lab-log summary)."""
        from radioroc.data import pedestal_flow
        mode = self._pedestal_mode
        if mode == "file" and self._run_pedestal_set is not None:
            return f"from pedestal run {pedestal_flow.pedestal_time(self._run_pedestal_set)}".rstrip()
        if mode == "file":
            return "file"
        if mode == "manual":
            return "simulator truth" if self._pedestals_from_simulator else "manual"
        return pedestal_flow.MEDIAN_TEXT

    def append_events(self, events):
        """Hook for a future live feed: add events to the replay list."""
        self.events.extend(events)
        self._data_channels |= {c for e in events for c in e.hg}
        self._recompute_pedestals(reanalyse=False)
        self._reanalyse()

    def _install_events(self, events, simulator_pedestals):
        """Install a new event list. ``simulator_pedestals`` (true values) switches to manual mode with
        those values; real data keeps a chosen file/manual source, else uses the median estimate."""
        self.pause()
        self._timing = None
        self._background = None
        self.events = events
        self._data_channels = {c for e in events for c in e.hg}
        if simulator_pedestals is not None:
            self._manual_pedestals = dict(simulator_pedestals)
            self._pedestals_from_simulator = True
            self._pedestal_mode = "manual"
        elif self._pedestals_from_simulator:
            self._pedestals_from_simulator = False
            self._pedestal_mode = "auto"
        self._brightness.clear()
        self.current_index = -1
        self._recompute_pedestals(reanalyse=False)
        self._reanalyse(refresh=False)
        self._update_controls()
        if events:
            self.show_event(0)
        else:
            self._refresh_items()

    # -------------------------------------------------------- pedestals ----
    @property
    def pedestals(self) -> dict[int, float]:
        """The effective high-gain pedestals used by the analysis."""
        return dict(self._pedestals)

    @property
    def pedestal_mode(self) -> str:
        return self._pedestal_mode

    @property
    def pedestal_warning(self) -> str:
        return self._pedestal_warning

    def _recompute_pedestals(self, reanalyse=True):
        mode = self._pedestal_mode
        if mode == "file":
            self._pedestals = dict(self._file_pedestals)
        elif mode == "manual":
            self._pedestals = dict(self._manual_pedestals)
        else:
            self._pedestals = dict(muon_analysis.estimate_pedestals(self.events, gain="hg")) if self.events else {}
        for radio, name in ((self.ped_auto_radio, "auto"), (self.ped_file_radio, "file"),
                            (self.ped_manual_radio, "manual")):
            radio.setChecked(name == mode)
        self._update_pedestal_labels()
        if reanalyse:
            self._reanalyse()

    def _update_pedestal_labels(self):
        peds = self._pedestals
        layout_channels = [c for c in self._layout.channels() if c in peds] or sorted(peds)
        if not peds:
            text = "Pedestals: none" if self.events else "Pedestals: no events"
        elif len(layout_channels) <= 6:
            text = "Pedestals: " + ", ".join(f"ch{c} {peds[c]:.0f}" for c in layout_channels)
        else:
            vals = sorted(peds[c] for c in layout_channels)
            text = f"Pedestals (HG, {len(vals)} ch): median {vals[len(vals) // 2]:.0f}, range {vals[0]:.0f}..{vals[-1]:.0f}"
        source = {"auto": "estimate", "file": "file/run", "manual": "simulator" if self._pedestals_from_simulator
                  else "manual"}[self._pedestal_mode]
        if self._pedestal_mode == "file" and self._run_pedestal_set is not None:
            from radioroc.data import pedestal_flow
            source = f"from pedestal run ({pedestal_flow.pedestal_time(self._run_pedestal_set)})"
        self.pedestal_label.setText(f"{text} ({source})")
        warning = ""
        wanted = [c for c in self._layout.channels() if c in self._data_channels]
        missing = [c for c in wanted if c not in peds]
        if self.events and missing and self._pedestal_mode != "auto":
            warning = f"No pedestal for channel(s) {', '.join(map(str, missing))}: counts are not pedestal-subtracted"
        elif self.events and self._pedestal_mode == "auto":
            biased = [c for c in muon_analysis.pedestals_look_biased(
                self.events, peds, float(self.threshold_spin.value())) if c in wanted]
            if biased:
                warning = ("Estimate may include muon signal: load a pedestal run or enter values")
                if self._no_run_pedestals:
                    from radioroc.data import pedestal_flow
                    warning = pedestal_flow.NOT_SAVED_WARNING + ". " + warning
        self._pedestal_warning = warning
        self.pedestal_warning_label.setText(warning)
        self.pedestal_warning_label.setVisible(bool(warning))

    def set_pedestal_mode(self, mode):
        if mode not in ("auto", "file", "manual"):
            raise ValueError(f"unknown pedestal mode {mode!r}")
        if mode == "file" and not self._file_pedestals:
            self._set_status("Choose a pedestal file or run folder first.")
            self._recompute_pedestals(reanalyse=False)  # restores the radio buttons
            return False
        if mode == "manual" and not self._manual_pedestals:
            self._manual_pedestals = dict(self._pedestals)
        self._pedestal_mode = mode
        self._pedestals_from_simulator = self._pedestals_from_simulator and mode == "manual"
        self._recompute_pedestals()
        return True

    def set_pedestals(self, pedestals):
        """Use these pedestals (channel -> counts) manually."""
        try:
            clean = {int(c): float(v) for c, v in dict(pedestals).items()}
        except (TypeError, ValueError) as exc:
            self._set_status(f"Invalid pedestals: {exc}")
            return False
        if any(not math.isfinite(v) for v in clean.values()):
            self._set_status("Invalid pedestals: values must be finite numbers.")
            return False
        self._manual_pedestals = clean
        self._run_pedestal_set = None
        self._pedestals_from_simulator = False
        self._pedestal_mode = "manual"
        self._recompute_pedestals()
        return True

    def load_pedestal_source(self, path):
        try:
            peds = muon_analysis.load_pedestals(Path(path))
        except (ValueError, OSError) as exc:
            self._set_status(f"Could not load pedestals: {exc}")
            return False
        self._file_pedestals = dict(peds)
        self._run_pedestal_set = None
        self._pedestals_from_simulator = False
        self._pedestal_mode = "file"
        self._recompute_pedestals()
        self._set_status(f"Pedestals loaded from {path} ({len(peds)} channels).")
        return True

    def save_pedestals_to(self, path):
        try:
            saved = muon_analysis.save_pedestals(Path(path), self._pedestals)
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not save pedestals: {exc}")
            return False
        self._set_status(f"Pedestals saved to {saved}")
        return True

    def _pedestal_radio_clicked(self, mode):
        if mode == "manual":
            self._edit_manual_pedestals()
        elif mode == "file" and not self._file_pedestals:
            self._pedestal_file_clicked()
        else:
            self.set_pedestal_mode(mode)

    def _pedestal_file_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open pedestal file", str(Path.cwd() / "radioroc_runs"),
                                              "Pedestal file (*.json)")
        if path:
            self.load_pedestal_source(path)
        else:
            self._recompute_pedestals(reanalyse=False)

    def _pedestal_run_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Open pedestal run folder", str(Path.cwd() / "radioroc_runs"))
        if folder:
            self.load_pedestal_source(folder)
        else:
            self._recompute_pedestals(reanalyse=False)

    def _edit_manual_pedestals(self):
        channels = self._layout.channels() or sorted(self._data_channels)
        start = {**self._pedestals, **self._manual_pedestals} if self._manual_pedestals else dict(self._pedestals)
        dialog = ManualPedestalDialog(channels, start, self)
        if dialog.exec() == QDialog.Accepted:
            self.set_pedestals({**self._manual_pedestals, **dialog.values()})
        else:
            self._recompute_pedestals(reanalyse=False)

    def _save_pedestals_clicked(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save pedestals", str(Path.cwd() / "radioroc_runs" / "pedestals.json"),
                                              "Pedestal file (*.json)")
        if path:
            self.save_pedestals_to(path)

    def _reanalyse(self, refresh=True):
        self.analyses = []
        if self.events:
            try:
                self.analyses = [
                    muon_analysis.analyse_event(e, self._layout, self._pedestals,
                                                threshold_counts=float(self.threshold_spin.value()), gain="hg")
                    for e in self.events]
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Analysis failed: {exc}")
        self._update_stats()
        self._update_rate()
        if refresh:
            self._update_info()
            self._refresh_items()

    def stats(self):
        n = len(self.analyses)
        coincidences = [a for a in self.analyses if a.coincidence]
        angles = [a.angle_deg for a in coincidences if a.angle_deg is not None]
        return {"events": n, "coincidences": len(coincidences),
                "fraction": (len(coincidences) / n) if n else 0.0,
                "mean_angle_deg": (sum(angles) / len(angles)) if angles else None}

    def _update_stats(self):
        s = self.stats()
        angle = "-" if s["mean_angle_deg"] is None else f"{s['mean_angle_deg']:.1f} deg"
        self.stats_label.setText(f"Events {s['events']}  |  coincidences {s['coincidences']} "
                                 f"({s['fraction'] * 100:.0f}%)  |  mean angle {angle}")

    # ------------------------------------------------------------- rate ----
    def _set_default_area(self):
        area = muon_rate.coincidence_area_cm2(self._layout)
        self.area_spin.blockSignals(True)
        self.area_spin.setValue(round(area, 2) if area else 0.0)
        self.area_spin.blockSignals(False)

    def _area_changed(self, _value):
        self._area_user_set = True
        self._update_rate()

    def _settings_key(self):
        return (float(self.threshold_spin.value()), tuple(sorted(self._pedestals.items())),
                repr(self._layout.to_dict()))

    def _update_rate(self):
        if not hasattr(self, "rate_label"):
            return
        self._run_rate = None
        self._rate_net = None
        net = None
        if self._timing is None or not self.events or len(self.analyses) != len(self.events):
            text = "Rate needs a saved run." if self._timing is None else "No analysed events."
            self.rate_label.setText(text)
            self.background_label.setText("")
            self.flux_label.setText("")
            self.background_button.setEnabled(self._timing is not None)
            self.copy_summary_button.setEnabled(False)
            self.save_summary_button.setEnabled(False)
            return
        self._run_rate = muon_rate.evaluate_run(self._timing, self.events, self.analyses)
        result = self._run_rate.result
        self.background_button.setEnabled(True)
        self.copy_summary_button.setEnabled(True)
        self.save_summary_button.setEnabled(True)
        duration = result.batch_seconds if result.batch_seconds is not None else result.wall_seconds
        dur = "unknown" if duration is None else f"{duration:.0f} s"
        lines = [f"Pedestals: {self.pedestal_source_text()}",
                 f"Duration: {dur} ({result.basis} basis)",
                 f"Events {result.trigger_events}, accepted {result.accepted} ({result.accepted_fraction * 100:.0f}%)",
                 f"Rate: {muon_rate._fmt(result.rate_per_min, result.sigma_per_min)}"]
        if result.basis == "batch" and result.wall_rate_per_min is not None:
            lines.append(f"Wall clock: {muon_rate._fmt(result.wall_rate_per_min, result.wall_sigma_per_min)}")
        if self._run_rate.blocks.drift:
            lines.append("Drift between blocks: check bias, temperature, interference.")
        lines += [f"Warning: {w}" for w in result.warnings]
        self.rate_label.setText("\n".join(lines))
        bg = self._background_rate()
        if bg is not None and bg.result.rate_per_min is not None and result.rate_per_min is not None:
            net = muon_rate.subtract_background(result, bg.result)
            self.background_label.setText(
                f"Background: {muon_rate._fmt(bg.result.rate_per_min, bg.result.sigma_per_min)}\n"
                f"Net rate: {muon_rate._fmt(net.rate_per_min, net.sigma_per_min)}")
        else:
            self.background_label.setText("" if self._background is None else "Background rate unavailable.")
        rate, sigma = (net.rate_per_min, net.sigma_per_min) if net else (result.rate_per_min, result.sigma_per_min)
        flux = muon_rate.flux_per_cm2(rate, sigma, self.area_spin.value() or None)
        self.flux_label.setText("" if flux is None else
                                f"Flux{' (net)' if net else ''}: {flux[0]:.4f} ± {flux[1]:.4f} /cm2/min")
        self._rate_net = net

    def _background_rate(self):
        """RunRate of the background run under the current settings (cached per settings)."""
        if self._background is None:
            return None
        path, cached_key, run_rate = self._background
        key = self._settings_key()
        if cached_key != key:
            try:
                run_rate = muon_rate.analyse_run(path, self._layout, self.threshold_spin.value(),
                                                 self._pedestals or None)
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Background analysis failed: {exc}")
                run_rate = None
            self._background = (path, key, run_rate)
        return run_rate

    def load_background(self, path):
        """Choose a background run; it is analysed with the current layout, threshold and pedestals."""
        if self._timing is None:
            self._set_status("Load a saved run before choosing a background run.")
            return False
        try:
            run_rate = muon_rate.analyse_run(Path(path), self._layout, self.threshold_spin.value(),
                                             self._pedestals or None)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not use background run: {exc}")
            return False
        self._background = (Path(path), self._settings_key(), run_rate)
        self._update_rate()
        self._set_status(f"Background run {path} loaded.")
        return True

    def _background_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Open background run folder", str(Path.cwd() / "radioroc_runs"))
        if folder:
            self.load_background(folder)

    def rate_summary_text(self) -> str:
        """Plain-text lab-log summary of the loaded run, or '' without a real run."""
        if self._run_rate is None:
            return ""
        bg = self._background_rate()
        net = getattr(self, "_rate_net", None)
        return muon_rate.format_summary(
            self._timing, self._run_rate.result, blocks=self._run_rate.blocks,
            background=bg.result if bg else None, background_timing=bg.timing if bg else None,
            net=net, area_cm2=self.area_spin.value() or None,
            settings=[f"Layout: {self._layout.name}", f"Detection threshold: {self.threshold_spin.value():g} counts",
                      f"Pedestals: {self.pedestal_source_text()}"])

    def copy_summary(self):
        text = self.rate_summary_text()
        if not text:
            self._set_status("Rate summary needs a saved run.")
            return False
        QApplication.clipboard().setText(text)
        self._set_status("Rate summary copied to the clipboard.")
        return True

    def save_summary_to(self, path):
        text = self.rate_summary_text()
        if not text:
            self._set_status("Rate summary needs a saved run.")
            return False
        run_dirs = [self._timing.directory] + ([self._background[0]] if self._background else [])
        if any(muon_rate.is_inside(path, d) for d in run_dirs):
            self._set_status("Not saved: summaries are never written into a run folder.")
            return False
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            self._set_status(f"Could not save summary: {exc}")
            return False
        self._set_status(f"Rate summary saved to {path}")
        return True

    def _save_summary_clicked(self):
        default = Path.cwd() / "radioroc_runs" / "muon_rate_summary.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save rate summary", str(default), "Text (*.txt)")
        if path:
            self.save_summary_to(path)

    # ----------------------------------------------------------- replay ---
    def show_event(self, index):
        if not self.events:
            return
        index = max(0, min(len(self.events) - 1, int(index)))
        self.current_index = index
        full = max(1.0, float(self.full_scale_spin.value()))
        if index < len(self.analyses):
            for ch, amp in self.analyses[index].amplitudes.items():
                if ch in self._items:
                    level = min(1.0, max(0.0, amp / full))
                    self._brightness[ch] = max(self._brightness.get(ch, 0.0), level)
        self._update_controls()
        self._update_info()
        self._refresh_items()

    def step(self, delta):
        if not self.events:
            return
        direction = 1 if delta >= 0 else -1
        target = self.current_index + delta
        if self.coinc_check.isChecked() and self.analyses:
            i = self.current_index + direction
            while 0 <= i < len(self.analyses) and not self.analyses[i].coincidence:
                i += direction
            if not 0 <= i < len(self.analyses):
                return False
            target = i
        elif not 0 <= target < len(self.events):
            return False
        self.show_event(target)
        return True

    def play(self):
        if not self.events or self._edit_mode:
            return
        self._playing = True
        self._accum_ms = 1000.0 / max(0.1, self.speed_spin.value())  # first step happens at once
        self._update_controls()

    def pause(self):
        self._playing = False
        self._update_controls()

    def _toggle_play(self):
        self.pause() if self._playing else self.play()

    def _slider_changed(self, value):
        if value != self.current_index:
            self.show_event(value)

    def advance(self, dt_ms):
        """Apply one time step: decay the glow, and step the replay if playing."""
        tau = max(1.0, float(self.glow_spin.value()))
        factor = math.exp(-float(dt_ms) / tau)
        for ch in list(self._brightness):
            value = self._brightness[ch] * factor
            self._brightness[ch] = 0.0 if value < 1e-3 else value
        if self._playing:
            self._accum_ms += float(dt_ms)
            period = 1000.0 / max(0.1, self.speed_spin.value())
            while self._accum_ms >= period and self._playing:
                self._accum_ms -= period
                if not self.step(1):
                    self.pause()
        self._refresh_items()

    def brightness(self, channel) -> float:
        return float(self._brightness.get(channel, 0.0))

    # ---------------------------------------------------------- drawing ---
    def _refresh_items(self):
        seeds = set()
        analysis = self.analyses[self.current_index] if 0 <= self.current_index < len(self.analyses) else None
        if analysis is not None:
            for hit in analysis.hits.values():
                if hit is not None and hit.channels:
                    seeds.add(hit.channels[0])
        for ch, item in self._items.items():
            level = self.brightness(ch)
            has_data = (not self._data_channels) or ch in self._data_channels
            seed = ch in seeds
            if level != item.level or has_data != item.has_data or seed != item.is_seed:
                item.level, item.has_data, item.is_seed = level, has_data, seed
                item.restyle()
                item.update()
        for layer, lines in self._crosses:
            hit = analysis.hits.get(layer) if analysis is not None else None
            if hit is None:
                for ln in lines:
                    ln.setVisible(False)
                continue
            cx = self._panel_centre_x(layer) + hit.x_mm
            cy = -hit.y_mm
            r = max(2.0, self._layout.sipm_size_mm * 0.8)
            lines[0].setLine(cx - r, cy, cx + r, cy)
            lines[1].setLine(cx, cy - r, cx, cy + r)
            for ln in lines:
                ln.setVisible(True)

    def _update_info(self):
        if not (0 <= self.current_index < len(self.events)):
            return
        e = self.events[self.current_index]
        a = self.analyses[self.current_index] if self.current_index < len(self.analyses) else None
        parts = [f"Event {self.current_index + 1}/{len(self.events)} (batch {e.batch}, event {e.event})"]
        if a is not None:
            parts.append("coincidence: " + ("yes" if a.coincidence else "no"))
            for layer in self._panel_layers:
                hit = a.hits.get(layer)
                if hit is None:
                    parts.append(f"layer {layer}: no hit")
                else:
                    parts.append(f"layer {layer}: centroid ({hit.x_mm:.1f}, {hit.y_mm:.1f}) mm, seed ch {hit.channels[0]}")
            if a.angle_deg is not None:
                parts.append(f"angle {a.angle_deg:.1f} deg")
        if e.truth and e.truth.get("angle_deg") is not None:
            parts.append(f"truth angle {e.truth['angle_deg']:.1f} deg")
        self.info_label.setText("  |  ".join(parts))
