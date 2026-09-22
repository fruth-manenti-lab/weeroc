"""Shared "Hardware connection" widget: UI plus its lazy-worker/poll behavior.

Lifted out of ``radioroc.gui.threshold_window.ThresholdWindow`` (the canonical
source for this behavior before the extraction) so the Threshold/Hold-scan/
S-curve workflow windows can each embed one instance instead of independently
duplicating the connection group box, its lazy ``ConnectionWorker`` creation,
and its poll loop. A window that owns this panel still performs its own
mode/scan gating (e.g. "don't allow Connect while a simulation is running")
before calling into the panel's action methods -- that gating is inherently
window-specific and is not lifted here.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from radioroc.application.connection_worker import ConnectionWorker
from radioroc.transport.config import (
    DEFAULT_BAUD, DEFAULT_TIMEOUT_SECONDS, RadiorocConnectionConfig,
)


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


class ConnectionPanel(QWidget):
    """Owns exactly one ``ConnectionWorker``, created lazily on first use.

    Public widgets (same names/behavior as the former inline group box):
    ``port_select``, ``baud``, ``timeout_s``, ``refresh_button``,
    ``connect_button``, ``read_status_button``, ``disconnect_button``,
    ``review_fault_button``, ``connection_status``, ``firmware_status``, plus
    ``connection_group`` (the ``QGroupBox`` that visually contains them, for
    callers that want to enable/disable the whole group at once).

    Nothing here is auto-wired to the buttons' ``clicked`` signals: an
    embedder (a scan window, or a test) decides what gating each button
    click should go through and connects it explicitly. This avoids a
    click firing both a window's gated handler and a panel-internal one.
    """

    status_changed = Signal()

    _CONNECTION_BUSY = {"discovering", "connecting", "reading", "disconnecting", "scanning",
                        "configuring"}
    _CONNECTION_LOCKS_MODE = _CONNECTION_BUSY | {"connected", "close_failed", "faulted"}

    def __init__(self, connection_worker_factory=ConnectionWorker, parent=None):
        super().__init__(parent)
        self.connection_worker_factory = connection_worker_factory
        self.connection_worker = None
        self._connection_ports = ()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.connection_group = QGroupBox("Hardware connection")
        outer.addWidget(self.connection_group)

        connection_form = QFormLayout(self.connection_group)
        connection_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        connection_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.port_select = QComboBox()
        self.port_select.addItem("Select a USB port candidate…", None)
        connection_form.addRow("Port", self.port_select)
        self.baud = _integer(1, 100_000_000, DEFAULT_BAUD)
        self.timeout_s = _decimal(0.001, 3600, DEFAULT_TIMEOUT_SECONDS)
        connection_form.addRow("Baud", self.baud)
        connection_form.addRow("Timeout (s)", self.timeout_s)
        connection_buttons_top = QHBoxLayout()
        connection_buttons_bottom = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.read_status_button = QPushButton("Read status")
        self.disconnect_button = QPushButton("Disconnect")
        self.review_fault_button = QPushButton("Acknowledge fault review")
        connection_buttons_top.addWidget(self.refresh_button)
        connection_buttons_top.addWidget(self.connect_button)
        connection_buttons_bottom.addWidget(self.read_status_button)
        connection_buttons_bottom.addWidget(self.disconnect_button)
        connection_buttons_bottom.addWidget(self.review_fault_button)
        connection_form.addRow(connection_buttons_top)
        connection_form.addRow(connection_buttons_bottom)
        self.connection_status = QLabel("Not connected · refresh to list USB port candidates")
        self.connection_status.setWordWrap(True)
        self.connection_status.setMinimumHeight(42)
        connection_form.addRow(self.connection_status)
        self.firmware_status = QLabel("—")
        connection_form.addRow("Firmware status", self.firmware_status)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

        self.update_controls()

    # -- worker lifecycle -------------------------------------------------

    def ensure_worker(self):
        if self.connection_worker is None:
            worker = self.connection_worker_factory()
            worker.start()
            self.connection_worker = worker
            self.timer.start()
        return self.connection_worker

    def forget_worker(self):
        """Drop an already-stopped worker and reset ephemeral display state.

        A caller (a window's own poll loop) decides *when* a worker has
        reached a terminal "stopped" snapshot and is safe to drop; this
        just performs the drop.
        """
        self.connection_worker = None
        self.timer.stop()
        self._connection_ports = ()

    def _run(self, command):
        """Run a worker command, refreshing the display on success.

        Returns True if the command was issued and the display already
        reflects the resulting snapshot (a caller wanting the full,
        window-level cascade can safely poll again); returns False if the
        command itself raised, in which case ``connection_status`` carries
        the error message and callers must NOT re-derive it from the
        snapshot (that would overwrite the error with a stale state).
        """
        try:
            command(self.ensure_worker())
            self.poll()
            return True
        except Exception as exc:
            self.connection_status.setText(
                f"Connection error · {type(exc).__name__}: {exc}")
            self.update_controls()
            return False

    # -- actions ------------------------------------------------------------

    def refresh(self):
        return self._run(lambda worker: worker.refresh())

    def connect_to(self, config):
        return self._run(lambda worker: worker.connect(config))

    def connect_selected(self):
        candidate = self.port_select.currentData()
        if candidate is None:
            return False
        return self.connect_to(RadiorocConnectionConfig(candidate.port, self.baud.value(),
                                                        self.timeout_s.value()))

    def read_status(self):
        return self._run(lambda worker: worker.read_status())

    def disconnect(self):
        if self.connection_worker is None:
            return False
        return self._run(lambda worker: worker.disconnect())

    def review_fault(self):
        if self.connection_worker is None:
            return False
        return self._run(lambda worker: worker.review_fault())

    # -- display ------------------------------------------------------------

    def show_snapshot(self, snapshot):
        state = snapshot.state
        if state == "idle":
            message = "Not connected"
            if snapshot.ports:
                message += f" · {len(snapshot.ports)} board candidate(s)"
            else:
                message += " · no board candidates found"
            retained = [problem for problem in (snapshot.error, snapshot.close_error) if problem]
            if retained:
                message += " · previous errors: " + "; ".join(retained)
        elif state == "connected":
            message = f"Connected · {snapshot.port}"
        elif state == "faulted":
            message = f"Hardware fault · {snapshot.fault or snapshot.error or 'review required'}"
        elif state == "close_failed":
            problems = [problem for problem in (snapshot.error, snapshot.close_error) if problem]
            message = f"Close failed · {'; '.join(problems)} · retry close"
        elif state == "error":
            message = f"Connection error · {snapshot.error}"
        elif state == "stopped":
            message = "Connection worker stopped"
        else:
            message = state.replace("_", " ").capitalize()
            if snapshot.port:
                message += f" · {snapshot.port}"
        if getattr(snapshot, "fault", None) and state != "faulted":
            message += f" · fault review required: {snapshot.fault}"
        self.connection_status.setText(message)
        self.firmware_status.setText(
            "—" if snapshot.status_word is None
            else f"0x{snapshot.status_word:02X} ({snapshot.status_word})")

    def sync_ports(self, ports):
        ports = tuple(ports)
        if ports == self._connection_ports:
            return
        selected = self.port_select.currentData()
        selected_port = selected.port if selected is not None else None
        self._connection_ports = ports
        self.port_select.blockSignals(True)
        self.port_select.clear()
        self.port_select.addItem("Select a USB port candidate…", None)
        selected_index = 0
        for candidate in ports:
            label = candidate.port
            if candidate.description:
                label += f" — {candidate.description}"
            self.port_select.addItem(label, candidate)
            if candidate.port == selected_port:
                selected_index = self.port_select.count() - 1
        self.port_select.setCurrentIndex(selected_index)
        self.port_select.blockSignals(False)

    def poll(self):
        """Refresh the display from the current worker snapshot.

        Does not drop a "stopped" worker: an embedding window may need to
        react specially to that transition (e.g. finish closing), so it
        owns that decision. Called by this panel's own timer, and safe for
        an embedder to call again after issuing a command.
        """
        worker = self.connection_worker
        if worker is None:
            return
        snapshot = worker.snapshot()
        self.sync_ports(snapshot.ports)
        self.show_snapshot(snapshot)
        self.update_controls()
        self.status_changed.emit()

    def update_controls(self, *, commands_available=True):
        worker = self.connection_worker
        state = worker.snapshot().state if worker is not None else "idle"
        fault = getattr(worker.snapshot(), "fault", None) if worker is not None else None
        busy = state in self._CONNECTION_BUSY
        session = state in {"connected", "close_failed", "faulted"}
        selectable = commands_available and not busy and not session and not fault
        self.port_select.setEnabled(selectable)
        self.baud.setEnabled(selectable)
        self.timeout_s.setEnabled(selectable)
        self.refresh_button.setEnabled(selectable)
        self.connect_button.setEnabled(selectable and self.port_select.currentData() is not None)
        self.read_status_button.setEnabled(commands_available and state == "connected")
        self.disconnect_button.setEnabled(
            commands_available and state in {"connected", "close_failed", "faulted"})
        self.disconnect_button.setText("Retry close" if state == "close_failed" else "Disconnect")
        self.review_fault_button.setEnabled(
            commands_available and not busy and bool(fault) and state in {"idle", "error"})

    def mode_locked(self):
        """Whether the connection alone makes it unsafe to switch device mode.

        Mirrors the connection half of what callers used to check via
        ``_CONNECTION_LOCKS_MODE`` before this panel existed; a caller that
        also has its own scan worker should additionally check that.
        """
        return (self.connection_worker is not None and
                self.connection_worker.snapshot().state in self._CONNECTION_LOCKS_MODE)

    def attach_hints(self, hint_bar):
        """Wire hover-hint text for this panel's controls into ``hint_bar``.

        ``ConnectionPanel`` has no status bar of its own -- an embedder (e.g.
        ``MainWindow``) owns the ``HintBar`` and passes it in here, the same
        way the three scan windows attach hints for their own embedded copy
        of this panel.
        """
        hint_bar.attach(self.port_select, "USB serial port candidate to connect to.")
        hint_bar.attach(self.baud, "Serial baud rate for the connection.")
        hint_bar.attach(self.timeout_s, "Serial read/write timeout, in seconds.")
        hint_bar.attach(self.refresh_button, "Re-scan for USB port candidates.")
        hint_bar.attach(self.connect_button, "Open a connection to the selected port.")
        hint_bar.attach(self.read_status_button, "Read the board's current firmware/"
                        "connection status.")
        hint_bar.attach(self.disconnect_button, "Close the current hardware connection.")
        hint_bar.attach(self.review_fault_button, "Show details of the last connection fault.")
