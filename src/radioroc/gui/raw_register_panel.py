"""The "Registers" sub-tab: view/edit/write raw ASIC I2C registers (F06).

Sibling of ``ChannelConfigPanel``/``InputDacGridPanel``/etc, but edits the
raw I2C table directly (any ``(add, subadd)``, an arbitrary byte) instead of
a named parameter -- the vendor app's "Register mode" toggle. Unlike those
panels, a read/write here can take long enough (a full-table read is one
batched multi-row FIFO transaction, not a single register) that this panel
polls for completion through its own ``QTimer`` rather than assuming the
result is ready the instant the command is submitted -- the same "submit,
then poll a busy state until it clears" shape as the scan workflow windows,
not the "submit, then show a snapshot immediately" shape the other
channel-config-family panels use (fine there since their writes are one or a
few registers, fast enough that timing has not yet caught them out).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from radioroc.application.raw_registers import RawRegisterWrite

_BUSY_STATES = {"reading", "configuring"}


class RawRegisterPanel(QWidget):
    """Public widgets: ``table`` (columns Address/Subaddress/Binary/Hex),
    ``read_all_button``, ``write_address``/``write_subaddress``/
    ``write_data``, ``write_button``, ``status_label``.
    """

    def __init__(self, connection_worker=None, parent=None):
        super().__init__(parent)
        self.connection_worker = connection_worker
        self._pending = None  # "read" or "write" while a command is in flight

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.read_all_button = QPushButton("Read all")
        self.read_all_button.clicked.connect(self.read_all)
        outer.addWidget(self.read_all_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Address", "Subaddress", "Binary", "Hex"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        outer.addWidget(self.table, 1)

        write_row = QHBoxLayout()
        write_row.addWidget(QLabel("Address"))
        self.write_address = QLineEdit()
        self.write_address.setPlaceholderText("0-255")
        write_row.addWidget(self.write_address)
        write_row.addWidget(QLabel("Subaddress"))
        self.write_subaddress = QLineEdit()
        self.write_subaddress.setPlaceholderText("0-255")
        write_row.addWidget(self.write_subaddress)
        write_row.addWidget(QLabel("Data (binary, 8 bits)"))
        self.write_data = QLineEdit()
        self.write_data.setPlaceholderText("00000000")
        write_row.addWidget(self.write_data)
        self.write_button = QPushButton("Write")
        self.write_button.clicked.connect(self.write_register)
        write_row.addWidget(self.write_button)
        outer.addLayout(write_row)

        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # Not started until a command is submitted -- nothing to poll for
        # before then, and this panel has no other reason to wake up.
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def _selection_changed(self):
        model = self.table.selectionModel()
        rows = model.selectedRows() if model is not None else []
        if not rows:
            return
        row = rows[0].row()
        self.write_address.setText(self.table.item(row, 0).text())
        self.write_subaddress.setText(self.table.item(row, 1).text())
        self.write_data.setText(self.table.item(row, 2).text())

    def read_all(self):
        if self.connection_worker is None or self._pending is not None:
            return
        try:
            self.connection_worker.read_all_registers()
        except Exception as exc:
            self.status_label.setText(f"Read error · {type(exc).__name__}: {exc}")
            return
        self._pending = "read"
        self.status_label.setText("Reading all registers…")
        self.timer.start()

    def write_register(self):
        if self.connection_worker is None or self._pending is not None:
            return
        try:
            add = int(self.write_address.text().strip())
            subadd = int(self.write_subaddress.text().strip())
            data = self.write_data.text().strip()
            write = RawRegisterWrite(add, subadd, data)
            write.validate()
        except ValueError as exc:
            self.status_label.setText(f"Invalid register write: {exc}")
            return
        try:
            self.connection_worker.write_raw_register(write)
        except Exception as exc:
            self.status_label.setText(f"Write error · {type(exc).__name__}: {exc}")
            return
        self._pending = "write"
        self.status_label.setText(f"Writing add={add} subadd={subadd}…")
        self.timer.start()

    def _poll(self):
        if self.connection_worker is None:
            self.timer.stop()
            self._pending = None
            return
        if self.connection_worker.snapshot().state in _BUSY_STATES:
            return  # still in flight
        self.timer.stop()
        pending, self._pending = self._pending, None
        if pending == "read":
            self._show_read_result()
        elif pending == "write":
            self._show_write_result()

    def _show_read_result(self):
        rows = self.connection_worker.raw_registers_snapshot()
        if rows is None:
            self.status_label.setText("Read failed; see connection status.")
            return
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(row.add)))
            self.table.setItem(i, 1, QTableWidgetItem(str(row.subadd)))
            self.table.setItem(i, 2, QTableWidgetItem(row.data))
            self.table.setItem(i, 3, QTableWidgetItem(f"{int(row.data, 2):02X}"))
        self.status_label.setText(f"Read {len(rows)} register(s).")

    def _show_write_result(self):
        result = self.connection_worker.raw_register_write_snapshot()
        if result is None:
            self.status_label.setText("Write failed; see connection status.")
            return
        parts = [f"add={result.add} subadd={result.subadd} -> {result.written}"]
        if result.observed is not None:
            parts.append("MISMATCH" if result.mismatch else "verified")
        self.status_label.setText("Write: " + " · ".join(parts))
