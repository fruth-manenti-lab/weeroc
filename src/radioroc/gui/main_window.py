"""Shared shell: one connection/channel-config area, an Acquisition area, and
a Calibration area.

Mirrors the vendor app's actual shape (see ``local_artifacts/app_pics``): a
persistent sidebar switches between top-level areas, ASIC config (connection +
per-channel config) is one shared area rather than duplicated per workflow.
Acquisition is its own top-level sidebar page, not a Calibration sub-tab --
calibrating and collecting data are distinct phases of the student workflow
(see ``PLINT_STUDENT_MVP_DIRECTIVE.md``'s target workflow: calibrate first,
then collect). The remaining scan workflows are sub-tabs of one "Calibration"
area, not independent top-level windows each owning their own connection.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .acquisition_window import AcquisitionWindow
from .autocalibration_window import AutocalibrationWindow
from .channel_config_panel import ChannelConfigPanel
from .connection_panel import ConnectionPanel
from .hint_bar import HintBar
from .hold_scan_window import HoldScanWindow
from .input_dac_grid_panel import InputDacGridPanel
from .main_panel import MainPanel
from .probes_masks_panel import ProbesMasksPanel
from .raw_register_panel import RawRegisterPanel
from .scurve_window import ScurveWindow
from .threshold_calibration_panel import ThresholdCalibrationPanel
from .threshold_window import ThresholdWindow

# Approximate vendor palette (local_artifacts/app_pics): dark navy sidebar,
# teal title/status chrome, red power/connection accent.
_SIDEBAR_BG = "#1b3a5c"
_SIDEBAR_SELECTED = "#2c6e86"
_TITLE_BG = "#12768a"
_STATUS_OK_BG = "#1b6e63"
_STATUS_FAULT_BG = "#8a3b1b"
_POWER_RED = "#c0392b"


def _scrollable(widget):
    """Wrap an ASIC-config panel in a vertically scrolling area.

    Keeps the panel's own preferred (natural) width so 64-channel grids are
    unaffected, while letting content taller than the available window
    height scroll rather than clip.
    """

    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    return scroll


class MainWindow(QMainWindow):
    """Top-level shell: sidebar (ASIC config / Acquisition / Calibration) over one connection."""

    def __init__(self, *, connection_worker_factory=None):
        super().__init__()
        self.setWindowTitle("RADIOROC")
        # A fixed 1280x900 used to be requested unconditionally, which is
        # exactly as tall as a 1600x900 screen with no margin for the window
        # manager's own decorations (title bar, panels) -- guaranteeing the
        # window's bottom (Apply buttons, status text) renders off-screen on
        # that size or anything smaller. Clamp to the actual available
        # desktop area instead, leaving a small margin for decorations.
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width = min(1280, available.width() - 40) if available is not None else 1280
        height = min(900, available.height() - 60) if available is not None else 900
        self.resize(max(width, 640), max(height, 480))

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
        for label in ("ASIC config.", "Acquisition", "Calibration"):
            QListWidgetItem(label, self.sidebar)
        body_layout.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        body_layout.addWidget(self.pages, 1)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)

        # -- One shared connection area, over per-topic ASIC-config sub-tabs -
        # (mirrors the vendor app's "ASIC config." sidebar page, whose own
        # tab bar is Main / input DAC / Threshold calibration / Probes-Masks,
        # in that order. "Registers" (F06, raw add/subadd read-all/write-one)
        # has no vendor sidebar-page equivalent tab; it is this app's own
        # home for that feature, not a stand-in for the vendor's separate
        # "Register mode" toggle on each existing tab.)
        asic_page = QWidget()
        asic_layout = QVBoxLayout(asic_page)
        asic_layout.setContentsMargins(0, 0, 0, 0)
        self.connection_panel = ConnectionPanel(
            connection_worker_factory=connection_worker_factory or self._default_worker_factory())
        asic_layout.addWidget(self.connection_panel)

        self.main_panel = MainPanel(None)
        self.channel_config_panel = ChannelConfigPanel(None)
        self.input_dac_grid_panel = InputDacGridPanel(None)
        self.threshold_calibration_panel = ThresholdCalibrationPanel(None)
        self.probes_masks_panel = ProbesMasksPanel(None)
        self.raw_register_panel = RawRegisterPanel(None)
        self.asic_config_tabs = QTabWidget()
        # Each panel is wrapped in its own scroll area: the tab bar and the
        # connection panel above it always stay visible, and a panel taller
        # than the available window height (MainPanel's three stacked group
        # boxes, in particular -- see IMPLEMENTATION_STATUS.md RADIOROC 31)
        # scrolls instead of pushing its own Apply button/status text off the
        # bottom of the screen.
        self.asic_config_tabs.addTab(_scrollable(self.main_panel), "Main")
        self.asic_config_tabs.addTab(_scrollable(self.channel_config_panel), "Channel config")
        self.asic_config_tabs.addTab(_scrollable(self.input_dac_grid_panel), "input DAC")
        self.asic_config_tabs.addTab(
            _scrollable(self.threshold_calibration_panel), "Threshold calibration")
        self.asic_config_tabs.addTab(_scrollable(self.probes_masks_panel), "Probes/Masks")
        self.asic_config_tabs.addTab(_scrollable(self.raw_register_panel), "Registers")
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
        self.main_panel.connection_worker = worker
        self.channel_config_panel.connection_worker = worker
        self.input_dac_grid_panel.connection_worker = worker
        self.threshold_calibration_panel.connection_worker = worker
        self.probes_masks_panel.connection_worker = worker
        self.raw_register_panel.connection_worker = worker
        # The worker is already running at this point (unlike a standalone
        # scan window, which stays lazy until the user does something), so
        # there is no reason to also make the user click Refresh once before
        # a USB board candidate shows up at all.
        self.connection_panel.refresh()

        # -- Hover-hint status line: mirrors the vendor app's own help line
        # (see radioroc.gui.hint_bar.HintBar and the three scan windows,
        # which each already attach hints to their own status bar). These
        # six panels and ConnectionPanel are plain QWidget subclasses with no
        # status bar of their own, so they report into this window's.
        self.hint = HintBar(
            self.statusBar(),
            "RADIOROC: manage the board connection and ASIC configuration here, "
            "switch to Acquisition to collect data, or Calibration for the scan "
            "workflows. Hover a control to see what it does.")
        self.connection_panel.attach_hints(self.hint)
        self.main_panel.attach_hints(self.hint)
        self.channel_config_panel.attach_hints(self.hint)
        self.input_dac_grid_panel.attach_hints(self.hint)
        self.threshold_calibration_panel.attach_hints(self.hint)
        self.probes_masks_panel.attach_hints(self.hint)
        self.raw_register_panel.attach_hints(self.hint)

        # -- Acquisition: its own top-level sidebar page, ahead of
        # Calibration in the sidebar -- collecting data is a distinct phase
        # from calibrating, not one more Calibration sub-tab. -----------------
        acquisition_page = QWidget()
        acquisition_layout = QVBoxLayout(acquisition_page)
        acquisition_layout.setContentsMargins(0, 0, 0, 0)
        self.acquisition_window = AcquisitionWindow(connection_worker=worker)
        acquisition_layout.addWidget(self.acquisition_window)
        self.pages.addWidget(acquisition_page)

        # -- Calibration: the remaining scan workflows as sub-tabs -----------
        calibration_page = QWidget()
        calibration_layout = QVBoxLayout(calibration_page)
        calibration_layout.setContentsMargins(0, 0, 0, 0)
        self.calibration_tabs = QTabWidget()
        calibration_layout.addWidget(self.calibration_tabs)
        self.threshold_window = ThresholdWindow(connection_worker=worker)
        self.hold_scan_window = HoldScanWindow(connection_worker=worker)
        self.scurve_window = ScurveWindow(connection_worker=worker)
        self.autocalibration_window = AutocalibrationWindow(connection_worker=worker)
        self.calibration_tabs.addTab(self.threshold_window, "Threshold scan")
        self.calibration_tabs.addTab(self.hold_scan_window, "Hold scan")
        self.calibration_tabs.addTab(self.scurve_window, "S-curve")
        self.calibration_tabs.addTab(self.autocalibration_window, "Autocalibration")
        self.pages.addWidget(calibration_page)

        # An injected connection_worker means each scan window's own
        # ConnectionPanel-owning code path (which self-wires this on the
        # panel it owns) never runs, so nothing tells it the shared
        # connection changed state -- its run/cancel button gating would
        # otherwise never leave its just-constructed "not connected" state.
        for scan_window in self._scan_windows():
            self.connection_panel.status_changed.connect(scan_window.poll_connection_worker)

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
        return (self.threshold_window, self.hold_scan_window, self.scurve_window,
                self.autocalibration_window, self.acquisition_window)

    def _busy(self):
        scanning = any(window.worker is not None for window in self._scan_windows())
        worker = self.connection_panel.connection_worker
        connecting = worker is not None and worker.snapshot().state != "stopped"
        return scanning or connecting

    def _finish_close_if_idle(self):
        worker = self.connection_panel.connection_worker
        if worker is not None:
            state = worker.snapshot().state
            if state == "stopped":
                self.connection_panel.forget_worker()
            elif state == "faulted":
                # ConnectionWorker's own documented contract: a job fault
                # that races a queued shutdown holds the worker alive at
                # "faulted" for exactly one required explicit retry (see
                # test_new_job_fault_during_shutdown_stays_alive_for_explicit_retry
                # in tests/test_connection_worker.py) -- without this, a
                # hardware fault during a run's cleanup, timed against the
                # user closing the app, left the window unclosable forever
                # (RADIOROC 40/41's own defect-hunt found this live). Safe to
                # retry every tick: shutdown() raises (caught) if one is
                # already in flight, and this only runs while _closing is
                # already true, never during ordinary operation -- an
                # unrelated fault outside of an active close attempt still
                # stays visible and blocks further runs, untouched.
                try:
                    worker.shutdown()
                except Exception:
                    pass
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
