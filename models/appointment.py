from datetime import datetime, timedelta
from enum import Enum

from ._validation import (
    validate_nonempty_text,
    validate_nonnegative_number,
    validate_optional_text,
)
from .studio_policy import StudioPolicy
from .visit_type import VisitType


class AppointmentStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


def format_duration(duration_minutes: int) -> str:
    hours, minutes = divmod(duration_minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} {'hr' if hours == 1 else 'hrs'}")
    if minutes:
        parts.append(f"{minutes} mins")
    return " ".join(parts)


class Appointment:
    # Encapsulation: private state is exposed through properties and validated methods.
    def __init__(
        self,
        client_email: str,
        service_id: int,
        appointment_time: datetime | str,
        status: AppointmentStatus = AppointmentStatus.PENDING,
        notes: str | None = None,
        nail_length: str = "",
        design_add_ons: list[str] | None = None,
        total_price: int | float = 0,
        appointment_id: int | None = None,
        duration_minutes: int = 120,
        cancellation_fee: int | float = 0,
        allergies: str = "",
        travel_fee: int | float = 0,
        discount: int | float = 0,
        amount_paid: int | float = 0,
        payment_note: str = "",
        visit_type: VisitType = VisitType.STUDIO,
        service_address: str = "",
        selected_extras: dict[str, int | float] | None = None,
        allow_missing_service_address: bool = False,
    ) -> None:
        self._appointment_id = appointment_id
        self._client_email = validate_nonempty_text(client_email, "client_email").lower()
        if isinstance(service_id, bool) or not isinstance(service_id, int) or service_id <= 0:
            raise ValueError("service_id must be a positive integer")
        self._service_id = service_id
        self._appointment_time = self._validate_time(appointment_time)
        self._status = self._validate_status(status)
        self._notes = validate_optional_text(notes, "notes")
        self._nail_length = validate_optional_text(nail_length, "nail_length") or ""
        self._design_add_ons = self._validate_add_ons(design_add_ons or [])
        self._selected_extras = self._validate_selected_extras(
            selected_extras if selected_extras is not None else {}
        )
        self._total_price = validate_nonnegative_number(total_price, "total_price")
        self._duration_minutes = self._validate_duration_minutes(duration_minutes)
        self._cancellation_fee = validate_nonnegative_number(
            cancellation_fee, "cancellation_fee"
        )
        self._allergies = validate_optional_text(allergies, "allergies") or ""
        self._travel_fee = validate_nonnegative_number(travel_fee, "travel_fee")
        self._discount = validate_nonnegative_number(discount, "discount")
        self._amount_paid = validate_nonnegative_number(amount_paid, "amount_paid")
        self._payment_note = validate_optional_text(payment_note, "payment_note") or ""
        if not isinstance(visit_type, VisitType):
            raise ValueError("visit_type must be a VisitType value")
        self._visit_type = visit_type
        self._service_address = validate_optional_text(
            service_address, "service_address"
        ) or ""
        if (
            self._visit_type is VisitType.HOME_SERVICE
            and not self._service_address
            and not allow_missing_service_address
        ):
            raise ValueError("A service address is required for home service")

    @staticmethod
    def _validate_time(value: datetime | str) -> datetime | str:
        if isinstance(value, datetime):
            return value
        return validate_nonempty_text(value, "appointment_time")

    @staticmethod
    def _validate_status(value: AppointmentStatus) -> AppointmentStatus:
        if not isinstance(value, AppointmentStatus):
            raise ValueError("status must be an AppointmentStatus value")
        return value

    @staticmethod
    def _validate_add_ons(values: list[str]) -> list[str]:
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise TypeError("design_add_ons must be a list of strings")
        return [item.strip() for item in values]

    @staticmethod
    def _validate_duration_minutes(value: int) -> int:
        policy = StudioPolicy()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("duration_minutes must be a whole number")
        if not policy.min_minutes <= value <= policy.max_minutes:
            raise ValueError(
                f"duration_minutes must be between {policy.min_minutes} and "
                f"{policy.max_minutes}"
            )
        if value % 5:
            raise ValueError("duration_minutes must be a multiple of 5")
        return value

    @property
    def appointment_id(self) -> int | None:
        return self._appointment_id

    @property
    def client_email(self) -> str:
        return self._client_email

    @property
    def service_id(self) -> int:
        return self._service_id

    @property
    def appointment_time(self) -> datetime | str:
        return self._appointment_time

    @property
    def status(self) -> AppointmentStatus:
        return self._status

    @property
    def notes(self) -> str | None:
        return self._notes

    @property
    def nail_length(self) -> str:
        return self._nail_length

    @property
    def design_add_ons(self) -> list[str]:
        return self._design_add_ons.copy()

    @staticmethod
    def _validate_selected_extras(
        values: dict[str, int | float],
    ) -> dict[str, float]:
        if not isinstance(values, dict):
            raise TypeError("selected_extras must be a dictionary")
        return {
            validate_nonempty_text(name, "selected_extras key"):
            validate_nonnegative_number(price, f"selected_extras[{name!r}]")
            for name, price in values.items()
        }

    @property
    def selected_extras(self) -> dict[str, float]:
        return self._selected_extras.copy()

    @property
    def total_price(self) -> float:
        return self._total_price

    @property
    def duration_minutes(self) -> int:
        return self._duration_minutes

    @duration_minutes.setter
    def duration_minutes(self, value: int) -> None:
        self._duration_minutes = self._validate_duration_minutes(value)

    @property
    def cancellation_fee(self) -> float:
        return self._cancellation_fee

    @cancellation_fee.setter
    def cancellation_fee(self, value: int | float) -> None:
        self._cancellation_fee = validate_nonnegative_number(
            value, "cancellation_fee"
        )

    @property
    def allergies(self) -> str:
        return self._allergies

    @property
    def travel_fee(self) -> float:
        return self._travel_fee

    @travel_fee.setter
    def travel_fee(self, value: int | float) -> None:
        self._travel_fee = validate_nonnegative_number(value, "travel_fee")

    @property
    def discount(self) -> float:
        return self._discount

    @discount.setter
    def discount(self, value: int | float) -> None:
        self._discount = validate_nonnegative_number(value, "discount")

    @property
    def amount_paid(self) -> float:
        return self._amount_paid

    @amount_paid.setter
    def amount_paid(self, value: int | float) -> None:
        self._amount_paid = validate_nonnegative_number(value, "amount_paid")

    @property
    def payment_note(self) -> str:
        return self._payment_note

    @payment_note.setter
    def payment_note(self, value: str) -> None:
        self._payment_note = validate_optional_text(value, "payment_note") or ""

    @property
    def final_price(self) -> float:
        return self._total_price + self._travel_fee - self._discount

    @property
    def balance(self) -> float:
        return self.final_price - self._amount_paid

    @property
    def visit_type(self) -> VisitType:
        return self._visit_type

    @property
    def service_address(self) -> str:
        return self._service_address

    def update_status(self, status: AppointmentStatus) -> None:
        status = self._validate_status(status)
        allowed_transitions = {
            AppointmentStatus.PENDING: {
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.CANCELLED,
            },
            AppointmentStatus.CONFIRMED: {
                AppointmentStatus.COMPLETED,
                AppointmentStatus.CANCELLED,
                AppointmentStatus.NO_SHOW,
            },
            AppointmentStatus.COMPLETED: set(),
            AppointmentStatus.CANCELLED: set(),
            AppointmentStatus.NO_SHOW: set(),
        }
        if status not in allowed_transitions[self._status]:
            raise ValueError(
                f"Cannot change appointment status from {self._status.value} "
                f"to {status.value}"
            )
        self._status = status

    def reschedule(self, appointment_time: datetime | str) -> None:
        self._appointment_time = self._validate_time(appointment_time)

    def get_end_time(self) -> datetime:
        start_time = (
            self._appointment_time
            if isinstance(self._appointment_time, datetime)
            else datetime.fromisoformat(self._appointment_time)
        )
        return start_time + timedelta(minutes=self._duration_minutes)

    def get_summary(self) -> str:
        start_time = (
            self._appointment_time
            if isinstance(self._appointment_time, datetime)
            else datetime.fromisoformat(self._appointment_time)
        )
        end_time = self.get_end_time()
        summary = (
            f"Appointment #{self._appointment_id or 'new'} for {self._client_email} "
            f"from {start_time:%Y-%m-%d %H:%M} to {end_time:%Y-%m-%d %H:%M}; "
            f"duration: {format_duration(self._duration_minutes)}; "
            f"status: {self._status.value}; total: {self.final_price:.2f}. "
        )
        if self._visit_type is VisitType.HOME_SERVICE:
            summary += (
                f"Visit type: HOME SERVICE; address: {self._service_address}; "
                f"travel fee: {self._travel_fee:.2f}. "
            )
        else:
            summary += "Visit type: STUDIO. "
        return summary + "Please arrive 5 to 10 minutes early."
