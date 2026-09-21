"""Shared shell: one connection/channel-config area plus a Calibration area.

Mirrors the vendor app's actual shape (see ``local_artifacts/app_pics``): a
persistent sidebar switches between top-level areas, ASIC config (connection +
per-channel config) is one shared area rather than duplicated per workflow,
and the scan workflows are sub-tabs of one "Calibration" area, not three
independent top-level windows each owning their own connection.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .channel_config_panel import ChannelConfigPanel
from .connection_panel import ConnectionPanel
from .hold_scan_window import HoldScanWindow
from .input_dac_grid_panel import InputDacGridPanel
from .probes_masks_panel import ProbesMasksPanel
from .scurve_window import ScurveWindow
from .threshold_window import ThresholdWindow

# Approximate vendor palette (local_artifacts/app_pics): dark navy sidebar,
# teal title/status chrome, red power/connection accent.
_SIDEBAR_BG = "#1b3a5c"
_SIDEBAR_SELECTED = "#2c6e86"
_TITLE_BG = "#12768a"
_STATUS_OK_BG = "#1b6e63"
_STATUS_FAULT_BG = "#8a3b1b"
_POWER_RED = "#c0392b"


class MainWindow(QMainWindow):
    """Top-level shell: sidebar (ASIC config / Calibration) over one connection."""

    def __init__(self, *, connection_worker_factory=None):
        super().__init__()
        self.setWindowTitle("RADIOROC")
        self.resize(1280, 900)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title = QLabel("Radioroc2  |  User Interface")
        title.setStyleSheet(
            f"background: {_TITLE_BG}; color: white; font-size: 15px; "
            f"font-weight: 600; padding: 8px 12px;")
        outer.addWidget(title)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        outer.addWidget(body, 1)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        self.sidebar.setStyleSheet(f"""
            QListWidget {{ background: {_SIDEBAR_BG}; color: white; border: none;
                          font-size: 14px; outline: none; }}
            QListWidget::item {{ padding: 14px 10px; }}
            QListWidget::item:selected {{ background: {_SIDEBAR_SELECTED}; }}
        """)
        for label in ("ASIC config.", "Calibration"):
            QListWidgetItem(label, self.sidebar)
        body_layout.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        body_layout.addWidget(self.pages, 1)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)

        # -- One shared connection area, over per-topic ASIC-config sub-tabs -
        # (mirrors the vendor app's "ASIC config." sidebar page, whose own
        # tab bar is Main / input DAC / Threshold calibration / Probes-Masks;
        # Main and Threshold calibration need register mappings this
        # codebase doesn't have yet, so only the two backed by an existing,
        # tested core -- input DAC and the T1/T2/TQ mask grids -- are built.)
        asic_page = QWidget()
        asic_layout = QVBoxLayout(asic_page)
        asic_layout.setContentsMargins(0, 0, 0, 0)
        self.connection_panel = ConnectionPanel(
            connection_worker_factory=connection_worker_factory or self._default_worker_factory())
        asic_layout.addWidget(self.connection_panel)

        self.channel_config_panel = ChannelConfigPanel(None)
        self.input_dac_grid_panel = InputDacGridPanel(None)
        self.probes_masks_panel = ProbesMasksPanel(None)
        self.asic_config_tabs = QTabWidget()
        self.asic_config_tabs.addTab(self.channel_config_panel, "Channel config")
        self.asic_config_tabs.addTab(self.input_dac_grid_panel, "input DAC")
        self.asic_config_tabs.addTab(self.probes_masks_panel, "Probes/Masks")
        asic_layout.addWidget(self.asic_config_tabs, 1)
        self.pages.addWidget(asic_page)

        self.connection_panel.refresh_button.clicked.connect(self.connection_panel.refresh)
        self.connection_panel.connect_button.clicked.connect(self._connect)
        self.connection_panel.read_status_button.clicked.connect(self.connection_panel.read_status)
        self.connection_panel.disconnect_button.clicked.connect(self.connection_panel.disconnect)
        self.connection_panel.review_fault_button.clicked.connect(self.connection_panel.review_fault)
        self.connection_panel.port_select.currentIndexChanged.connect(
            lambda _index: self.connection_panel.update_controls())
        self.channel_config_panel.channel_config_apply_button.clicked.connect(
            self.channel_config_panel.apply)

        # The three scan workflows need a real (started) worker at construction
        # time, since an injected worker is never created by the window itself.
        worker = self.connection_panel.ensure_worker()
        self.channel_config_panel.connection_worker = worker
        self.input_dac_grid_panel.connection_worker = worker
        self.probes_masks_panel.connection_worker = worker

        # -- Calibration: the three scan workflows as sub-tabs ---------------
        calibration_page = QWidget()
        calibration_layout = QVBoxLayout(calibration_page)
        calibration_layout.setContentsMargins(0, 0, 0, 0)
        self.calibration_tabs = QTabWidget()
        calibration_layout.addWidget(self.calibration_tabs)
        self.threshold_window = ThresholdWindow(connection_worker=worker)
        self.hold_scan_window = HoldScanWindow(connection_worker=worker)
        self.scurve_window = ScurveWindow(connection_worker=worker)
        self.calibration_tabs.addTab(self.threshold_window, "Threshold scan")
        self.calibration_tabs.addTab(self.hold_scan_window, "Hold scan")
        self.calibration_tabs.addTab(self.scurve_window, "S-curve")
        self.pages.addWidget(calibration_page)

        self.sidebar.setCurrentRow(0)

        # -- Persistent connection status strip (mirrors the vendor app's
        # bottom power-button/status bar, visible regardless of the active
        # sidebar page) -------------------------------------------------------
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(12, 0, 0, 0)
        status_layout.setSpacing(10)
        self.power_indicator = QLabel()
        self.power_indicator.setFixedSize(22, 22)
        status_layout.addWidget(self.power_indicator)
        self.status_strip = QLabel("Not connected")
        self.status_strip.setWordWrap(True)
        status_layout.addWidget(self.status_strip, 1)
        status_row.setMinimumHeight(40)
        outer.addWidget(status_row)
        self.connection_panel.status_changed.connect(self._refresh_status_strip)
        self._refresh_status_strip()

        self._closing = False
        self._finish_timer = QTimer(self)
        self._finish_timer.setInterval(150)
        self._finish_timer.timeout.connect(self._finish_close_if_idle)

    @staticmethod
    def _default_worker_factory():
        from radioroc.application.connection_worker import ConnectionWorker
        return ConnectionWorker

    def _connect(self):
        self.connection_panel.connect_selected()

    def _refresh_status_strip(self):
        worker = self.connection_panel.connection_worker
        connected = worker is not None and worker.snapshot().state == "connected"
        faulted = worker is not None and (
            worker.snapshot().state == "faulted" or bool(getattr(worker.snapshot(), "fault", None)))
        text = "Not connected" if worker is None else self.connection_panel.connection_status.text()
        self.status_strip.setText(text)
        row_bg = _STATUS_FAULT_BG if faulted else (_STATUS_OK_BG if connected else "#2f2f2f")
        self.status_strip.parentWidget().setStyleSheet(f"background: {row_bg};")
        self.status_strip.setStyleSheet("color: white;")
        indicator_color = _STATUS_FAULT_BG if faulted else (_STATUS_OK_BG if connected else _POWER_RED)
        self.power_indicator.setStyleSheet(
            f"background: {indicator_color}; border-radius: 11px;")

    def _scan_windows(self):
        return (self.threshold_window, self.hold_scan_window, self.scurve_window)

    def _busy(self):
        scanning = any(window.worker is not None for window in self._scan_windows())
        worker = self.connection_panel.connection_worker
        connecting = worker is not None and worker.snapshot().state != "stopped"
        return scanning or connecting

    def _finish_close_if_idle(self):
        worker = self.connection_panel.connection_worker
        if worker is not None and worker.snapshot().state == "stopped":
            self.connection_panel.forget_worker()
        if not self._busy():
            self._finish_timer.stop()
            self.close()

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            for window in self._scan_windows():
                if window.worker is not None:
                    window.close()
            worker = self.connection_panel.connection_worker
            if worker is not None and worker.snapshot().state != "stopped":
                try:
                    worker.shutdown()
                except Exception:
                    pass
                self.connection_panel.timer.start()
        if self._busy():
            event.ignore()
            self._finish_timer.start()
        else:
            event.accept()
