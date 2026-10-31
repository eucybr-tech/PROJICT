import sqlite3
from datetime import datetime, time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from models import Admin
from services.schedule_manager import ScheduleManager
from ui.base_page import BasePage
from ui.scrollable_dialog import ScrollableDialog


class BreakDialog(ScrollableDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add break")
        self._label = QLineEdit()
        self._start = QTimeEdit()
        self._end = QTimeEdit()
        self._start.setDisplayFormat("h:mm AP")
        self._end.setDisplayFormat("h:mm AP")
        self._start.setTime(time(12, 0))
        self._end.setTime(time(13, 0))
        form = QFormLayout()
        form.addRow("Label", self._label)
        form.addRow("Start", self._start)
        form.addRow("End", self._end)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    @property
    def values(self) -> tuple[str, time, time]:
        return (
            self._label.text().strip(),
            self._start.time().toPyTime(),
            self._end.time().toPyTime(),
        )


class ClosureDialog(ScrollableDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add closure")
        self._start = QDateTimeEdit(datetime.now())
        self._start.setCalendarPopup(True)
        self._start.setDisplayFormat("yyyy-MM-dd h:mm AP")
        self._end = QDateTimeEdit(datetime.now())
        self._end.setCalendarPopup(True)
        self._end.setDisplayFormat("yyyy-MM-dd h:mm AP")
        self._end.setDateTime(self._end.dateTime().addSecs(3600))
        self._reason = QLineEdit()
        form = QFormLayout()
        form.addRow("Starts", self._start)
        form.addRow("Ends", self._end)
        form.addRow("Reason", self._reason)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    @property
    def values(self) -> tuple[datetime, datetime, str]:
        return (
            self._start.dateTime().toPyDateTime(),
            self._end.dateTime().toPyDateTime(),
            self._reason.text().strip(),
        )


class ScheduleScreen(BasePage):
    """Admin editor for weekly hours, daily breaks, and dated closures."""

    _WEEKDAYS = ScheduleManager.WEEKDAYS

    def __init__(
        self,
        schedule_manager: ScheduleManager,
        role: Admin,
        parent: QWidget | None = None,
    ) -> None:
        if "manage_schedule" not in role.get_permissions():
            raise PermissionError("This role cannot manage the studio schedule")
        # Inheritance and dependency injection: Admin receives schedule logic, not SQL access.
        self._schedule_manager = schedule_manager
        self._role = role
        self._weekly_rows: list[tuple[QCheckBox, QTimeEdit, QTimeEdit]] = []
        super().__init__(
            {"schedule_manager": schedule_manager, "role": role}, parent
        )
        self.refresh()

    @property
    def schedule_manager(self) -> ScheduleManager:
        return self._schedule_manager

    @property
    def role(self) -> Admin:
        return self._role

    def build_ui(self) -> None:
        self._tabs = QTabWidget()
        self._build_weekly_tab()
        self._build_breaks_tab()
        self._build_closures_tab()
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)

    def _build_weekly_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        for weekday in self._WEEKDAYS:
            opened = QCheckBox("Open")
            opening = QTimeEdit()
            closing = QTimeEdit()
            opening.setDisplayFormat("h:mm AP")
            closing.setDisplayFormat("h:mm AP")
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(opened)
            row_layout.addWidget(QLabel("From"))
            row_layout.addWidget(opening)
            row_layout.addWidget(QLabel("to"))
            row_layout.addWidget(closing)
            form.addRow(weekday, row)
            self._weekly_rows.append((opened, opening, closing))
        save = QPushButton("Save weekly hours")
        save.clicked.connect(self.save_weekly_hours)
        layout.addLayout(form)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        self._tabs.addTab(page, "Weekly hours")

    def _build_breaks_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._break_list = QListWidget()
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self.add_break)
        remove.clicked.connect(self.remove_break)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addWidget(self._break_list)
        layout.addLayout(buttons)
        self._tabs.addTab(page, "Breaks")

    def _build_closures_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._closure_list = QListWidget()
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self.add_closure)
        remove.clicked.connect(self.remove_closure)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addWidget(self._closure_list)
        layout.addLayout(buttons)
        self._tabs.addTab(page, "Closures")

    def refresh(self) -> None:
        try:
            hours = self._schedule_manager.get_weekly_hours()
            for row, entry in zip(self._weekly_rows, hours, strict=True):
                opened, start, end = row
                opened.setChecked(bool(entry["is_open"]))
                start.setTime(self._time_value(entry["open_time"]))
                end.setTime(self._time_value(entry["close_time"]))
            self._refresh_breaks()
            self._refresh_closures()
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not load schedule", str(error))

    def save_weekly_hours(self) -> None:
        entries = []
        for weekday, (opened, start, end) in enumerate(self._weekly_rows):
            if end.time() <= start.time():
                QMessageBox.warning(
                    self,
                    "Invalid hours",
                    f"Closing time must be after opening time on {self._WEEKDAYS[weekday]}.",
                )
                return
            entries.append(
                {
                    "weekday": weekday,
                    "is_open": opened.isChecked(),
                    "open_time": start.time().toPyTime(),
                    "close_time": end.time().toPyTime(),
                }
            )
        try:
            self._schedule_manager.save_weekly_hours(entries)
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Could not save weekly hours", str(error))
            return
        QMessageBox.information(self, "Schedule", "Weekly hours saved.")

    def add_break(self) -> None:
        dialog = BreakDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        label, start, end = dialog.values
        try:
            self._schedule_manager.add_break(label, start, end)
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid break", str(error))
            return
        self._refresh_breaks()

    def remove_break(self) -> None:
        item = self._break_list.currentItem()
        if item is None:
            return
        break_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._schedule_manager.remove_break(break_id)
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Could not remove break", str(error))
            return
        self._refresh_breaks()

    def add_closure(self) -> None:
        dialog = ClosureDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        start, end, reason = dialog.values
        try:
            self._schedule_manager.add_closure(start, end, reason)
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid closure", str(error))
            return
        self._refresh_closures()

    def remove_closure(self) -> None:
        item = self._closure_list.currentItem()
        if item is None:
            return
        closure_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            self._schedule_manager.remove_closure(closure_id)
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Could not remove closure", str(error))
            return
        self._refresh_closures()

    def _refresh_breaks(self) -> None:
        self._break_list.clear()
        for entry in self._schedule_manager.get_breaks():
            item = QListWidgetItem(
                f"{entry['label']}: {entry['start_time']} – {entry['end_time']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry["break_id"])
            self._break_list.addItem(item)

    def _refresh_closures(self) -> None:
        self._closure_list.clear()
        now = datetime.now()
        for entry in self._schedule_manager.get_closures():
            start = datetime.fromisoformat(str(entry["start_datetime"]))
            end = datetime.fromisoformat(str(entry["end_datetime"]))
            item = QListWidgetItem(
                f"{start:%Y-%m-%d %H:%M} – {end:%Y-%m-%d %H:%M}: {entry['reason']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry["closure_id"])
            if end < now:
                item.setForeground(QColor("#999999"))
            self._closure_list.addItem(item)

    @staticmethod
    def _time_value(value: object):
        from PyQt6.QtCore import QTime

        return QTime.fromString(str(value), "HH:mm")
