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
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGraphicsItem, QGraphicsLineItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QGroupBox,
    QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from radioroc.data import muon_analysis, muon_simulator
from radioroc.data.muon_types import (
    N_CHANNELS, DetectorLayout, LayoutError, MuonEvent, SiPMPlacement,
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


class MuonView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = DetectorLayout.grid(4, 8, 10.0, layers=2)
        self.events: list[MuonEvent] = []
        self.analyses: list = []
        self._pedestals: dict[int, float] = {}
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
        self.replay_box = QWidget()
        rv = QVBoxLayout(self.replay_box)
        rv.setContentsMargins(0, 0, 0, 0)
        r1 = QHBoxLayout()
        self.step_back_button = self._button("Step back", "Step back", "Previous event", lambda: self.step(-1))
        self.play_button = self._button("Play", "Play or pause", "Replay the events automatically", self._toggle_play)
        self.step_button = self._button("Step forward", "Step forward", "Next event", lambda: self.step(1))
        self.coinc_check = QCheckBox("Coincidences only")
        self.coinc_check.setAccessibleName("Coincidences only")
        self.coinc_check.setToolTip("Skip events that do not hit every layer")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName("Event index")
        self.slider.valueChanged.connect(self._slider_changed)
        for w in (self.step_back_button, self.play_button, self.step_button, self.coinc_check):
            r1.addWidget(w)
        r1.addWidget(self.slider, 1)
        r2 = QHBoxLayout()
        self.speed_spin = self._spin(0.1, 1000, 2.0, "Replay speed", "Events per second", 1, 0.5)
        self.glow_spin = self._spin(10, 20000, 600, "Glow time", "Time constant of the glow decay (ms)", 0, 50)
        r2.addWidget(QLabel("Speed (events/s)"))
        r2.addWidget(self.speed_spin)
        r2.addWidget(QLabel("Glow time (ms)"))
        r2.addWidget(self.glow_spin)
        r2.addStretch(1)
        rv.addLayout(r1)
        rv.addLayout(r2)
        left.addWidget(self.replay_box)
        root.addLayout(left, 1)

        # Right column: layout / events / detection, scrollable.
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 4, 0)

        lbox = QGroupBox("Layout")
        lf = QFormLayout(lbox)
        self.layers_spin = self._spin(1, 2, 2, "Layers", "Number of SiPM layers (1 or 2)")
        self.rows_spin = self._spin(1, 64, 4, "Rows", "SiPM rows per layer")
        self.cols_spin = self._spin(1, 64, 8, "Columns", "SiPM columns per layer")
        self.pitch_spin = self._spin(1, 200, 10, "Pitch", "Centre-to-centre spacing (mm)", 1, 1)
        self.spacing_spin = self._spin(1, 5000, 100, "Layer spacing", "Distance between the layers (mm)", 1, 5)
        self.size_spin = self._spin(1, 100, 6, "SiPM size", "Side of one SiPM (mm)", 1, 0.5)
        for text, w in (("Layers", self.layers_spin), ("Rows", self.rows_spin), ("Columns", self.cols_spin),
                        ("Pitch (mm)", self.pitch_spin), ("Layer spacing (mm)", self.spacing_spin),
                        ("SiPM size (mm)", self.size_spin)):
            lf.addRow(text, w)
        self.rebuild_button = self._button("Rebuild grid", "Rebuild grid", "Replace the layout by a regular grid",
                                           self._rebuild_clicked)
        lf.addRow(self.rebuild_button)
        self.spacing_spin.valueChanged.connect(self._spacing_changed)
        self.size_spin.valueChanged.connect(self._size_changed)
        self.edit_check = QCheckBox("Edit layout")
        self.edit_check.setAccessibleName("Edit layout")
        self.edit_check.setToolTip("Drag SiPMs with the mouse; replay is disabled while editing")
        self.edit_check.toggled.connect(self._set_edit_mode)
        lf.addRow(self.edit_check)
        self.add_button = self._button("Add SiPM", "Add SiPM", "Add a SiPM with the next free channel", self._add_clicked)
        self.remove_button = self._button("Remove selected", "Remove selected", "Remove the selected SiPMs",
                                          self._remove_clicked)
        self.save_button = self._button("Save layout…", "Save layout", "Save the layout as JSON", self._save_clicked)
        self.load_button = self._button("Load layout…", "Load layout", "Load a layout JSON file", self._load_clicked)
        for b in (self.add_button, self.remove_button, self.save_button, self.load_button):
            lf.addRow(b)
        sv.addWidget(lbox)

        ebox = QGroupBox("Events")
        ef = QFormLayout(ebox)
        self.n_spin = self._spin(1, 100000, 200, "Number of events", "How many events to simulate")
        self.seed_spin = self._spin(0, 2_000_000_000, 1, "Seed", "Random seed (same seed, same events)")
        self.fraction_spin = self._spin(0, 1, 0.8, "Muon fraction", "Share of events that are muon tracks", 2, 0.05)
        ef.addRow("Number of events", self.n_spin)
        ef.addRow("Seed", self.seed_spin)
        ef.addRow("Muon fraction", self.fraction_spin)
        self.generate_button = self._button("Generate events", "Generate events", "Simulate events for this layout",
                                            self._generate_clicked)
        self.open_button = self._button("Open saved run…", "Open saved run", "Load events from an acquisition run folder",
                                        self._open_clicked)
        ef.addRow(self.generate_button)
        ef.addRow(self.open_button)
        sv.addWidget(ebox)

        dbox = QGroupBox("Detection")
        df = QFormLayout(dbox)
        self.threshold_spin = self._spin(0, 100000, 40, "Detection threshold", "Counts above pedestal to count as a hit", 0, 5)
        self.full_scale_spin = self._spin(1, 100000, 400, "Full-scale brightness", "Counts that light a SiPM fully", 0, 50)
        self.threshold_spin.valueChanged.connect(lambda _v: self._reanalyse())
        df.addRow("Threshold (counts)", self.threshold_spin)
        df.addRow("Full scale (counts)", self.full_scale_spin)
        self.pedestal_label = QLabel("Pedestals: no events")
        self.pedestal_label.setWordWrap(True)
        self.pedestal_label.setAccessibleName("Pedestals")
        df.addRow(self.pedestal_label)
        sv.addWidget(dbox)
        sv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(side.sizeHint().width() + 24)
        root.addWidget(scroll)

    def attach_hints(self, hint):
        for w in (self.rebuild_button, self.edit_check, self.add_button, self.remove_button, self.save_button,
                  self.load_button, self.generate_button, self.open_button, self.play_button, self.coinc_check,
                  self.threshold_spin, self.full_scale_spin, self.glow_spin, self.speed_spin):
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
        self._after_layout_change(structural=True)

    def _sync_layout_controls(self):
        lay = self._layout
        for w in (self.layers_spin, self.spacing_spin, self.size_spin):
            w.blockSignals(True)
        self.layers_spin.setValue(max(1, len(lay.layers())))
        self.spacing_spin.setValue(lay.layer_spacing_mm)
        self.size_spin.setValue(lay.sipm_size_mm)
        for w in (self.layers_spin, self.spacing_spin, self.size_spin):
            w.blockSignals(False)

    def rebuild_grid(self, rows, cols, pitch_mm, layers):
        try:
            layout = DetectorLayout.grid(rows, cols, pitch_mm, layers=layers,
                                         layer_spacing_mm=self._layout.layer_spacing_mm,
                                         sipm_size_mm=self._layout.sipm_size_mm, name=self._layout.name)
        except (LayoutError, ValueError) as exc:
            self._set_status(f"Cannot build grid: {exc}")
            return False
        self._layout = layout
        self._after_layout_change(structural=True)
        self._set_status(f"Grid {rows} x {cols} x {layers} layer(s): {len(layout.sipms)} SiPMs.")
        return True

    def _replace_placement(self, channel, **changes):
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

    def add_sipm(self, layer=0):
        used = set(self._layout.channels())
        free = [c for c in range(N_CHANNELS) if c not in used]
        if not free:
            self._set_status("All 64 channels are in use.")
            return None
        if layer not in (0, 1) or (layer == 1 and len(self._layout.layers()) < 2 and self._layout.sipms):
            layer = 0 if not self._layout.layers() else self._layout.layers()[0]
        occupied = {(s.x_mm, s.y_mm) for s in self._layout.in_layer(layer)}
        x = 0.0
        step = max(1.0, round(self._layout.sipm_size_mm))
        while (x, 0.0) in occupied and abs(x) < self._panel_half:
            x += step
        channel = free[0]
        self._layout.sipms.append(SiPMPlacement(channel, layer, x, 0.0))
        self._after_layout_change(structural=True)
        self._set_status(f"Added SiPM channel {channel} to layer {layer}.")
        return channel

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

    def _after_layout_change(self, structural):
        self._reanalyse(refresh=False)
        if structural:
            self._rebuild_scene()
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
        ext_x = max([abs(s.x_mm) for s in lay.sipms] + [0.0]) + pad
        ext_y = max([abs(s.y_mm) for s in lay.sipms] + [0.0]) + pad
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

    def _item_dragged(self, item):
        if self._building:
            return
        placement = self._layout.placement(item.channel)
        cx = self._panel_centre_x(placement.layer)
        self._replace_placement(item.channel, x_mm=float(round(item.pos().x() - cx)),
                                y_mm=float(-round(item.pos().y())))
        self._reanalyse(refresh=False)
        self._refresh_items()

    def _selection_changed(self):
        self._update_controls()

    def _selected_channels(self):
        try:
            return [i.channel for i in self.scene.selectedItems() if isinstance(i, SipmItem)]
        except RuntimeError:
            return []

    # -------------------------------------------------------- edit mode --
    def _set_edit_mode(self, on):
        self._edit_mode = bool(on)
        if on:
            self.pause()
        self._editing_items = self._edit_mode
        self._apply_edit_flags()
        self._update_controls()
        self._set_status("Edit mode: drag SiPMs to move them (1 mm steps)." if on else "")

    def _update_controls(self):
        editing = self._edit_mode
        has_events = bool(self.events)
        self.replay_box.setEnabled(has_events and not editing)
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
        self.add_sipm(layer)

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
            pedestals = muon_analysis.estimate_pedestals(events, gain="hg")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not open run: {exc}")
            return False
        self._install_events(events, dict(pedestals))
        data = {c for e in events for c in e.hg}
        extra = sorted(data - set(self._layout.channels()))
        note = f" Ignored channels not in the layout: {extra}." if extra else ""
        self._set_status(f"Loaded {len(events)} events from {path}.{note}")
        return True

    def append_events(self, events):
        """Hook for a future live feed: add events to the replay list."""
        self.events.extend(events)
        self._data_channels |= {c for e in events for c in e.hg}
        self._reanalyse()

    def _install_events(self, events, pedestals):
        self.pause()
        self.events = events
        self._pedestals = pedestals
        self._data_channels = {c for e in events for c in e.hg}
        self._brightness.clear()
        self.current_index = -1
        self._reanalyse(refresh=False)
        if pedestals:
            vals = sorted(pedestals.values())
            self.pedestal_label.setText(
                f"Pedestals (HG, {len(vals)} ch): median {vals[len(vals) // 2]:.0f}, range {vals[0]:.0f}..{vals[-1]:.0f}")
        else:
            self.pedestal_label.setText("Pedestals: none")
        self._update_controls()
        if events:
            self.show_event(0)
        else:
            self._refresh_items()

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
