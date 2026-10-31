import sqlite3

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.queue_manager import QueueManager
from ui.base_page import BasePage


class QueueScreen(BasePage):
    """Customer-facing mobile queue view with privacy-shortened names."""

    # Dependency injection: queue data arrives through QueueManager, not SQL.
    def __init__(self, queue_manager: QueueManager, parent=None) -> None:
        self._queue_manager = queue_manager
        super().__init__({"queue_manager": queue_manager}, parent)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10_000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    @property
    def queue_manager(self) -> QueueManager:
        return self._queue_manager

    def build_ui(self) -> None:
        self._now_serving_label = QLabel("Now serving: Nobody")
        self._now_serving_label.setObjectName("appTitle")

        self._queue_table = QTableWidget(0, 3)
        self._queue_table.setHorizontalHeaderLabels(["Position", "Ticket", "Name"])
        self._queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._queue_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._queue_table.horizontalHeader().setStretchLastSection(True)

        self._lookup_box = QLineEdit()
        self._lookup_box.setPlaceholderText("Enter your ticket number or email")
        self._lookup_box.returnPressed.connect(self._find_my_position)
        self._position_label = QLabel("Enter your ticket number or email to find your place.")
        self._position_label.setWordWrap(True)
        self._ticket_label = QLabel()
        self._ticket_label.setStyleSheet("font-size: 10px; color: #766b70;")

        lookup_box = QGroupBox("Find your place")
        lookup_form = QFormLayout(lookup_box)
        lookup_form.addRow("Ticket or email", self._lookup_box)
        lookup_form.addRow(self._position_label)
        lookup_form.addRow(self._ticket_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self._now_serving_label)
        layout.addWidget(self._queue_table, 1)
        layout.addWidget(lookup_box)

    def refresh(self) -> None:
        try:
            entries = self._queue_manager.get_queue()
            now_serving = self._queue_manager.get_now_serving()
        except (sqlite3.Error, ValueError, TypeError, RuntimeError) as error:
            self._now_serving_label.setText(f"Queue unavailable: {error}")
            return

        self._now_serving_label.setText(
            "Now serving: Nobody"
            if now_serving is None
            else f"Now serving: {now_serving.ticket_number} — "
            f"{self._short_name(now_serving.client_name)}"
        )
        self._queue_table.setRowCount(0)
        for entry in entries:
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
                self._short_name(entry.client_name),
            )
            for column, value in enumerate(values):
                self._queue_table.setItem(row, column, QTableWidgetItem(value))
        if not entries:
            self._queue_table.setRowCount(1)
            empty = QTableWidgetItem("There is no one in line right now.")
            empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._queue_table.setItem(0, 0, empty)
            self._queue_table.setSpan(0, 0, 1, 3)
        if self._lookup_box.text().strip():
            self._find_my_position()

    def _find_my_position(self) -> None:
        query = self._lookup_box.text().strip()
        if not query:
            self._position_label.setText(
                "Enter your ticket number or email to find your place."
            )
            self._ticket_label.clear()
            return
        try:
            entry = self._queue_manager.find_entry(query)
            position = (
                self._queue_manager.get_position(entry.entry_id)
                if entry is not None and entry.entry_id is not None
                else None
            )
        except (sqlite3.Error, ValueError, TypeError, RuntimeError) as error:
            self._position_label.setText(f"Could not check your position: {error}")
            return
        if entry is None or position is None:
            self._position_label.setText(
                "We couldn't find you in today's active line. Please check your ticket or email."
            )
            self._ticket_label.clear()
            return
        self._position_label.setText(
            f"Your queue number is {position:03d} for "
            f"{entry.queue_date:%A, %B %d, %Y}\n"
            f"{position - 1} ahead of you"
        )
        self._ticket_label.setText(f"Ticket: {entry.ticket_number or '—'}")

    @staticmethod
    def _short_name(name: str) -> str:
        parts = name.split()
        if len(parts) < 2:
            return parts[0] if parts else ""
        return f"{parts[0]} {parts[-1][0]}."
