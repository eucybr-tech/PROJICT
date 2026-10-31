import sqlite3

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import QueueEntry, QueueStatus
from services.queue_manager import QueueManager


class QueueEmailSignals(QObject):
    completed = pyqtSignal(bool, str)


class QueuePanel(QWidget):
    """Reusable staff/admin queue controls and active-line display."""

    # Dependency injection and encapsulation: only queue services and private UI
    # state are held by this shared QWidget.
    def __init__(
        self,
        queue_manager: QueueManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_manager = queue_manager
        self._entries: list[QueueEntry] = []
        self._email_signals = QueueEmailSignals(self)
        self._email_signals.completed.connect(self._show_email_result)
        self._build_ui()
        self.refresh()

    @property
    def queue_manager(self) -> QueueManager:
        return self._queue_manager

    def _build_ui(self) -> None:
        self._now_serving = QLabel("Now serving: Nobody")
        self._now_serving.setObjectName("appTitle")

        self._queue_table = QTableWidget(0, 5)
        self._queue_table.setHorizontalHeaderLabels(
            ["Position", "Ticket", "Name", "Type", "Status"]
        )
        self._queue_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._queue_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._queue_table.horizontalHeader().setStretchLastSection(True)

        self._add_walk_in_button = QPushButton("Add Walk-in")
        self._call_next_button = QPushButton("Call Next")
        self._mark_done_button = QPushButton("Mark Done")
        self._cancel_button = QPushButton("Cancel Entry")
        self._skip_button = QPushButton("Skip (not here yet)")
        self._add_walk_in_button.clicked.connect(self.add_walk_in)
        self._call_next_button.clicked.connect(self.call_next)
        self._mark_done_button.clicked.connect(self.mark_done)
        self._cancel_button.clicked.connect(self.cancel_entry)
        self._skip_button.clicked.connect(self.skip_next)
        self._queue_table.itemSelectionChanged.connect(self._update_actions)

        actions = (
            self._add_walk_in_button,
            self._call_next_button,
            self._mark_done_button,
            self._cancel_button,
            self._skip_button,
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self._now_serving)
        layout.addWidget(self._queue_table, 1)
        for button in actions:
            layout.addWidget(button)

    def refresh(self) -> None:
        try:
            self._entries = self._queue_manager.get_queue()
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load queue", error)
            return
        now_serving = self._queue_manager.get_now_serving()
        self._now_serving.setText(
            "Now serving: Nobody"
            if now_serving is None
            else f"Now serving: {now_serving.ticket_number} — {now_serving.client_name}"
        )
        self._queue_table.setRowCount(0)
        for entry in self._entries:
            row = self._queue_table.rowCount()
            self._queue_table.insertRow(row)
            position = (
                self._queue_manager.get_position(entry.entry_id)
                if entry.entry_id is not None
                else None
            )
            values = (
                f"{position:03d}" if position is not None else "",
                entry.ticket_number or "",
                entry.client_name,
                entry.entry_type.value.replace("_", " ").title(),
                entry.status.value.title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, entry.entry_id)
                self._queue_table.setItem(row, column, item)
        self._update_actions()

    def add_walk_in(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add Walk-in", "Client name:")
        if not accepted:
            return
        try:
            entry = self._queue_manager.add_walk_in(name)
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not add walk-in", error)
            return
        QMessageBox.information(
            self,
            "Walk-in added",
            f"{entry.client_name} was added with ticket {entry.ticket_number}.",
        )
        self.refresh()
        self._select_entry(entry.entry_id)

    def call_next(self) -> None:
        try:
            entry = self._queue_manager.call_next(self._email_callback)
        except (ValueError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not call next client", error)
            return
        self.refresh()
        self._select_entry(entry.entry_id)

    def skip_next(self) -> None:
        try:
            self._queue_manager.skip_next()
        except (ValueError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not skip client", error)
            return
        self.refresh()

    def mark_done(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(
                self, "Select a queue entry", "Choose the serving entry first."
            )
            return
        if entry.entry_id is None:
            self._show_error(
                "Could not mark entry done",
                ValueError("The queue entry has not been saved"),
            )
            return
        try:
            self._queue_manager.mark_done(entry.entry_id)
        except (ValueError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not mark entry done", error)
            return
        self.refresh()

    def cancel_entry(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(
                self, "Select a queue entry", "Choose an active entry to cancel."
            )
            return
        if entry.entry_id is None:
            self._show_error(
                "Could not cancel queue entry",
                ValueError("The queue entry has not been saved"),
            )
            return
        try:
            self._queue_manager.cancel_entry(entry.entry_id)
        except (ValueError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not cancel queue entry", error)
            return
        self.refresh()

    def _selected_entry(self) -> QueueEntry | None:
        row = self._queue_table.currentRow()
        if row < 0:
            return None
        item = self._queue_table.item(row, 0)
        entry_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((entry for entry in self._entries if entry.entry_id == entry_id), None)

    def _select_entry(self, entry_id: int | None) -> None:
        if entry_id is None:
            return
        for row in range(self._queue_table.rowCount()):
            item = self._queue_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == entry_id:
                self._queue_table.selectRow(row)
                return

    def _update_actions(self) -> None:
        selected = self._selected_entry()
        serving = self._queue_manager.get_now_serving()
        self._call_next_button.setEnabled(
            serving is None
            and any(entry.status is QueueStatus.WAITING for entry in self._entries)
        )
        self._mark_done_button.setEnabled(
            selected is not None and selected.status is QueueStatus.SERVING
        )
        self._cancel_button.setEnabled(
            selected is not None
            and selected.status in (QueueStatus.WAITING, QueueStatus.SERVING)
        )
        self._skip_button.setEnabled(
            sum(entry.status is QueueStatus.WAITING for entry in self._entries) > 1
        )

    def _email_callback(self, success: bool, error: str | None) -> None:
        self._email_signals.completed.emit(success, error or "")

    def _show_email_result(self, success: bool, error: str) -> None:
        if not success:
            QMessageBox.warning(
                self,
                "Email notification",
                "Saved, but the email could not be sent"
                + (f": {error}" if error else ""),
            )

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
