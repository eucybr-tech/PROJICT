import sqlite3
from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import User
from services.report_manager import ReportManager
from ui.appointment_panel import AppointmentPanel
from ui.base_page import BasePage


class ReportPaymentsScreen(BasePage):
    """Admin-only reports and outstanding-payment workspace."""

    def __init__(
        self,
        report_manager: ReportManager,
        appointment_panel: AppointmentPanel,
        role: User,
        parent=None,
    ) -> None:
        if "view_reports" not in role.get_permissions():
            raise PermissionError("This role cannot view reports")
        # Inheritance and dependency injection keep reports separate from persistence and UI actions.
        self._report_manager = report_manager
        self._appointment_panel = appointment_panel
        self._role = role
        self._can_view_payments = "view_payments" in role.get_permissions()
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
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_reports_tab(), "Reports")
        if self._can_view_payments:
            self._tabs.addTab(self._build_payments_tab(), "Payments")
        layout.addWidget(self._tabs)

    def _build_reports_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        today = date.today()
        first_day = today.replace(day=1)
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDate(first_day)
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDate(today)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_reports)
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("From"))
        date_row.addWidget(self._from_date)
        date_row.addWidget(QLabel("To"))
        date_row.addWidget(self._to_date)
        date_row.addWidget(refresh_button)
        date_row.addStretch()
        layout.addLayout(date_row)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._status_label)
        layout.addWidget(self._summary_label)

        self._service_table = self._create_table(
            ["Service", "Appointments", "Revenue"]
        )
        self._visit_table = self._create_table(
            ["Visit type", "Appointments", "Revenue", "Travel fees"]
        )
        layout.addWidget(QLabel("By service"))
        layout.addWidget(self._service_table, 1)
        layout.addWidget(QLabel("By visit type"))
        layout.addWidget(self._visit_table, 1)
        return page

    def _build_payments_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._payments_table = self._create_table(
            ["Client", "Date", "Service", "Final price", "Paid", "Balance"]
        )
        self._payments_table.cellDoubleClicked.connect(self._record_payment)
        layout.addWidget(self._payments_table)
        return page

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        header = table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        return table

    def refresh(self) -> None:
        self._refresh_reports()
        if self._can_view_payments:
            self._refresh_payments()

    def _refresh_reports(self) -> None:
        start_date = self._from_date.date().toPyDate()
        end_date = self._to_date.date().toPyDate()
        if start_date > end_date:
            QMessageBox.warning(
                self, "Invalid date range", "From date must not be after To date."
            )
            return
        try:
            status_result = self._report_manager.status_counts(
                start_date, end_date, self._role
            )
            revenue = self._report_manager.revenue(
                start_date, end_date, self._role
            )
            payments = self._report_manager.pending_payments(self._role)
            by_service = self._report_manager.by_service(
                start_date, end_date, self._role
            )
            by_visit = self._report_manager.by_visit_type(
                start_date, end_date, self._role
            )
            counts = status_result["counts"]
            self._status_label.setText(
                "Appointments by status: "
                + " · ".join(
                    f"{status.replace('_', ' ').title()}: {count}"
                    for status, count in counts.items()
                )
                + f"\nCancellation fees recorded: "
                f"₱ {status_result['cancellation_fees']:,.2f}"
            )
            self._summary_label.setText(
                f"Revenue (payments received): ₱ {revenue:,.2f}    "
                f"Outstanding balance: ₱ "
                f"{payments['total_balance']:,.2f}"
            )
            self._populate(
                self._service_table,
                by_service,
                (
                    "service_name",
                    "appointment_count",
                    "revenue",
                ),
                money_columns={2},
            )
            self._populate(
                self._visit_table,
                by_visit,
                (
                    "visit_type",
                    "appointment_count",
                    "revenue",
                    "travel_fees",
                ),
                money_columns={2, 3},
            )
        except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not load reports", str(error))

    def _refresh_payments(self) -> None:
        try:
            rows = self._report_manager.pending_payments(self._role)["appointments"]
            self._payments_table.setRowCount(0)
            for record in rows:
                row = self._payments_table.rowCount()
                self._payments_table.insertRow(row)
                values: tuple[str, str, str, float, float, float] = (
                    str(record["client_name"]),
                    str(record["appointment_time"])[:10],
                    str(record["service_name"]),
                    self._numeric_field(record, "final_price"),
                    self._numeric_field(record, "amount_paid"),
                    self._numeric_field(record, "balance"),
                )
                for column, value in enumerate(values):
                    text = (
                        f"₱ {value:,.2f}"
                        if isinstance(value, float)
                        else str(value)
                    )
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(
                            Qt.ItemDataRole.UserRole, record["appointment_id"]
                        )
                    if column == 5 and isinstance(value, (int, float)) and value > 0:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    self._payments_table.setItem(row, column, item)
        except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not load payments", str(error))

    @classmethod
    def _populate(
        cls,
        table: QTableWidget,
        records: list[dict[str, object]],
        keys: tuple[str, ...],
        money_columns: set[int],
    ) -> None:
        table.setRowCount(0)
        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            for column, key in enumerate(keys):
                value = record[key]
                text = (
                    f"₱ {cls._number(value):,.2f}"
                    if column in money_columns
                    else str(value).replace("_", " ").title()
                    if key == "visit_type"
                    else str(value)
                )
                table.setItem(row, column, QTableWidgetItem(text))

    def _record_payment(self, row: int, _column: int) -> None:
        item = self._payments_table.item(row, 0)
        appointment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(appointment_id, int) and self._appointment_panel.record_payment_for_appointment(
            appointment_id
        ):
            self._refresh_payments()
            self._refresh_reports()

    @staticmethod
    def _numeric_field(record: dict[str, object], field_name: str) -> float:
        return ReportPaymentsScreen._number(record[field_name])

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Report query returned a nonnumeric amount")
        return float(value)
