from datetime import date, datetime, timedelta
from typing import TypedDict

from database import Database
from models import AppointmentStatus


class PendingPayments(TypedDict):
    appointments: list[dict[str, object]]
    total_balance: float


class StatusCounts(TypedDict):
    counts: dict[str, int]
    cancellation_fees: float


class ReportManager:
    """Read-only appointment and payment reporting through the database boundary."""

    _STATUSES = tuple(status.value for status in AppointmentStatus)

    def __init__(self, database: Database) -> None:
        # Dependency injection keeps report queries inside Database.
        self._database = database

    @property
    def database(self) -> Database:
        return self._database

    def today_appointments(self) -> list[dict[str, object]]:
        today = date.today()
        return self._database.get_report_appointments(today, today)

    def upcoming_appointments(self, days: int = 7) -> list[dict[str, object]]:
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError("days must be a positive whole number")
        now = datetime.now()
        cutoff = now + timedelta(days=days)
        rows = self._database.get_report_appointments(
            now.date(), cutoff.date()
        )
        return [
            row
            for row in rows
            if str(row["status"]) in ("PENDING", "CONFIRMED")
            and now
            <= datetime.fromisoformat(str(row["appointment_time"]))
            <= cutoff
        ]

    def pending_request_count(self) -> int:
        return self._database.get_pending_request_count()

    def pending_payments(self) -> PendingPayments:
        rows = self._database.get_pending_payment_rows()
        return {
            "appointments": rows,
            "total_balance": sum(
                self._number(row["balance"], "balance") for row in rows
            ),
        }

    def revenue(self, start_date: date, end_date: date) -> float:
        self._validate_date_range(start_date, end_date)
        return self._database.get_report_revenue(start_date, end_date)

    def status_counts(self, start_date: date, end_date: date) -> StatusCounts:
        self._validate_date_range(start_date, end_date)
        rows = self._database.get_report_status_counts(start_date, end_date)
        counts = {status: 0 for status in self._STATUSES}
        cancellation_fees = 0.0
        for row in rows:
            status = str(row["status"])
            counts[status] = int(
                self._number(row["appointment_count"], "appointment_count")
            )
            cancellation_fees += self._number(
                row["cancellation_fees"] or 0, "cancellation_fees"
            )
        return {
            "counts": counts,
            "cancellation_fees": cancellation_fees,
        }

    def by_service(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        self._validate_date_range(start_date, end_date)
        return self._database.get_report_by_service(start_date, end_date)

    def by_visit_type(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        self._validate_date_range(start_date, end_date)
        rows = self._database.get_report_by_visit_type(start_date, end_date)
        by_type = {str(row["visit_type"]): row for row in rows}
        return [
            by_type.get(
                visit_type,
                {
                    "visit_type": visit_type,
                    "appointment_count": 0,
                    "revenue": 0.0,
                    "travel_fees": 0.0,
                },
            )
            for visit_type in ("STUDIO", "HOME_SERVICE")
        ]

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if not isinstance(start_date, date) or isinstance(start_date, datetime):
            raise TypeError("start_date must be a date")
        if not isinstance(end_date, date) or isinstance(end_date, datetime):
            raise TypeError("end_date must be a date")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")

    @staticmethod
    def _number(value: object, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be numeric in the report query")
        return float(value)
