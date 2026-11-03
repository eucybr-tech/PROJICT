import sqlite3
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from models import User
from services.report_manager import ReportManager
from ui.appointment_panel import AppointmentPanel
from ui.base_page import BasePage


class DashboardScreen(BasePage):
    """Role-aware appointment dashboard built from read-only reports."""

    def __init__(
        self,
        report_manager: ReportManager,
        appointment_panel: AppointmentPanel,
        role: User,
        parent=None,
    ) -> None:
        if "view_dashboard" not in role.get_permissions():
            raise PermissionError("This role cannot view the dashboard")
        # Inheritance and dependency injection: BasePage uses report and appointment services.
        self._report_manager = report_manager
        self._appointment_panel = appointment_panel
        self._role = role
        super().__init__(
            {
                "report_manager": report_manager,
                "appointment_panel": appointment_panel,
            },
            parent,
        )
        self.refresh()

    @property
    def report_manager(self) -> ReportManager:
        return self._report_manager

    @property
    def appointment_panel(self) -> AppointmentPanel:
        return self._appointment_panel

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(self._role.get_dashboard_title())
        title.setObjectName("appTitle")
        layout.addWidget(title)

        self._cards_layout = QGridLayout()
        layout.addLayout(self._cards_layout)
        self._card_values: dict[str, QLabel] = {}
        card_specs = [
            ("today", "Today's appointments"),
            ("pending", "Pending requests"),
            ("upcoming", "Upcoming (7 days)"),
        ]
        permissions = self._role.get_permissions()
        if "view_payments" in permissions:
            card_specs.append(("payments", "Pending payments"))
        if "view_reports" in permissions:
            card_specs.append(("revenue", "Revenue this month"))
        for index, (key, label) in enumerate(card_specs):
            card = QFrame()
            card.setProperty("card", True)
            card_layout = QVBoxLayout(card)
            label_widget = QLabel(label)
            label_widget.setWordWrap(True)
            value = QLabel("—")
            value.setStyleSheet(
                "font-size: 20px; font-weight: 700; color: #765f43;"
            )
            card_layout.addWidget(label_widget)
            card_layout.addWidget(value)
            self._cards_layout.addWidget(card, index // 3, index % 3)
            self._card_values[key] = value

        self._today_table = self._create_table()
        self._upcoming_table = self._create_table()
        layout.addWidget(QLabel("Today's appointments"))
        layout.addWidget(self._today_table, 1)
        layout.addWidget(QLabel("Next 7 days"))
        layout.addWidget(self._upcoming_table, 1)
        self._today_table.cellDoubleClicked.connect(
            lambda row, _column: self._open_details(self._today_table, row)
        )
        self._upcoming_table.cellDoubleClicked.connect(
            lambda row, _column: self._open_details(self._upcoming_table, row)
        )

    @staticmethod
    def _create_table() -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(
            ["Time", "Client", "Service", "Visit type", "Status"]
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        header = table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        return table

    def refresh(self) -> None:
        try:
            today_rows = self._report_manager.today_appointments(self._role)
            upcoming_rows = self._report_manager.upcoming_appointments(self._role, 7)
            self._card_values["today"].setText(str(len(today_rows)))
            self._card_values["pending"].setText(
                str(self._report_manager.pending_request_count())
            )
            self._card_values["upcoming"].setText(str(len(upcoming_rows)))
            if "view_payments" in self._role.get_permissions():
                payments = self._report_manager.pending_payments(self._role)
                self._card_values["payments"].setText(
                    f"₱ {payments['total_balance']:,.2f}"
                )
            if "view_reports" in self._role.get_permissions():
                today = datetime.now().date()
                first_day = today.replace(day=1)
                self._card_values["revenue"].setText(
                    f"₱ {self._report_manager.revenue(first_day, today, self._role):,.2f}"
                )
            self._populate_table(self._today_table, today_rows, show_date=False)
            self._populate_table(self._upcoming_table, upcoming_rows, show_date=True)
        except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not load dashboard", str(error))

    @staticmethod
    def _populate_table(
        table: QTableWidget, rows: list[dict[str, object]], show_date: bool
    ) -> None:
        table.setRowCount(0)
        for record in rows:
            row = table.rowCount()
            table.insertRow(row)
            appointment_time = datetime.fromisoformat(str(record["appointment_time"]))
            time_text = (
                f"{appointment_time:%a %d %b %H:%M}"
                if show_date
                else f"{appointment_time:%H:%M}"
            )
            values = (
                time_text,
                str(record["client_name"]),
                str(record["service_name"]),
                str(record["visit_type"]).replace("_", " ").title(),
                str(record["status"]).replace("_", " ").title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole, record["appointment_id"]
                    )
                table.setItem(row, column, item)

    def _open_details(self, table: QTableWidget, row: int) -> None:
        item = table.item(row, 0)
        if item is None:
            return
        appointment_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(appointment_id, int):
            self._appointment_panel.show_appointment_details(appointment_id)
