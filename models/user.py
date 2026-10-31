from abc import ABC, abstractmethod
from datetime import date, datetime

from ._validation import validate_nonempty_text, validate_optional_text


class User(ABC):
    """Abstract role identity shared by the system's user types."""

    def __init__(self, name: str, email: str) -> None:
        self._name = validate_nonempty_text(name, "name")
        self._email = validate_nonempty_text(email, "email").lower()

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = validate_nonempty_text(value, "name")

    @property
    def email(self) -> str:
        return self._email

    @email.setter
    def email(self, value: str) -> None:
        self._email = validate_nonempty_text(value, "email").lower()

    # Abstraction: every concrete role must define its role-specific behavior.
    @abstractmethod
    def get_permissions(self) -> tuple[str, ...]:
        raise NotImplementedError

    @abstractmethod
    def get_role_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_dashboard_title(self) -> str:
        raise NotImplementedError


class Admin(User):
    # Inheritance and polymorphism: Admin supplies role-specific implementations.
    def get_permissions(self) -> tuple[str, ...]:
        return (
            "manage_appointments",
            "manage_clients",
            "delete_clients",
            "view_health_notes",
            "edit_client_profile",
            "manage_services",
            "manage_loyalty",
            "manage_gallery",
            "manage_queue",
            "manage_schedule",
            "view_dashboard",
            "view_reports",
            "record_payments",
            "view_payments",
        )

    def get_role_name(self) -> str:
        return "Admin"

    def get_dashboard_title(self) -> str:
        return "Admin Dashboard"


class Staff(User):
    # Inheritance and polymorphism: Staff supplies role-specific implementations.
    def get_permissions(self) -> tuple[str, ...]:
        return (
            "manage_appointments",
            "manage_clients",
            "manage_queue",
            "view_health_notes",
            "edit_client_profile",
            "view_dashboard",
        )

    def get_role_name(self) -> str:
        return "Staff"

    def get_dashboard_title(self) -> str:
        return "Staff Dashboard"


class Customer(User):
    def __init__(
        self,
        name: str,
        email: str,
        phone: str | None = None,
        notes: str | None = None,
        deposit_paid: bool = False,
        address: str = "",
        nail_condition: str = "",
        health_notes: str = "",
        deposit_paid_on: date | None = None,
    ) -> None:
        super().__init__(name, email)
        self._phone = validate_optional_text(phone, "phone")
        self._notes = validate_optional_text(notes, "notes")
        self._deposit_paid = self._validate_deposit_paid(deposit_paid)
        self._address = self._validate_profile_text(address, "address")
        self._nail_condition = self._validate_profile_text(
            nail_condition, "nail_condition"
        )
        self._health_notes = self._validate_profile_text(
            health_notes, "health_notes"
        )
        self._deposit_paid_on = self._validate_deposit_paid_on(deposit_paid_on)

    @property
    def phone(self) -> str | None:
        return self._phone

    @phone.setter
    def phone(self, value: str | None) -> None:
        self._phone = validate_optional_text(value, "phone")

    @property
    def notes(self) -> str | None:
        return self._notes

    @notes.setter
    def notes(self, value: str | None) -> None:
        self._notes = validate_optional_text(value, "notes")

    @property
    def deposit_paid(self) -> bool:
        return self._deposit_paid

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, value: str) -> None:
        self._address = self._validate_profile_text(value, "address")

    @property
    def nail_condition(self) -> str:
        return self._nail_condition

    @nail_condition.setter
    def nail_condition(self, value: str) -> None:
        self._nail_condition = self._validate_profile_text(value, "nail_condition")

    @property
    def health_notes(self) -> str:
        return self._health_notes

    @health_notes.setter
    def health_notes(self, value: str) -> None:
        self._health_notes = self._validate_profile_text(value, "health_notes")

    @property
    def deposit_paid_on(self) -> date | None:
        return self._deposit_paid_on

    @deposit_paid_on.setter
    def deposit_paid_on(self, value: date | None) -> None:
        self._deposit_paid_on = self._validate_deposit_paid_on(value)

    @staticmethod
    def _validate_deposit_paid_on(value: date | None) -> date | None:
        if value is not None and (
            not isinstance(value, date) or isinstance(value, datetime)
        ):
            raise TypeError("deposit_paid_on must be a date or None")
        return value

    @staticmethod
    def _validate_profile_text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        return value.strip()

    # Encapsulation: only the explicit operation can change the lifetime deposit flag.
    @staticmethod
    def _validate_deposit_paid(value: bool) -> bool:
        if not isinstance(value, bool):
            raise TypeError("deposit_paid must be a bool")
        return value

    def mark_deposit_paid(self) -> None:
        self._deposit_paid = True
        self._deposit_paid_on = date.today()

    def get_booking_history(self, appointments: list[object]) -> list[object]:
        return [
            appointment
            for appointment in appointments
            if getattr(appointment, "client_email", "").lower() == self.email
        ]

    # Inheritance and polymorphism: Customer defines its own role behavior.
    def get_permissions(self) -> tuple[str, ...]:
        return ("request_appointment", "view_catalog", "view_loyalty", "view_gallery", "view_queue")

    def get_role_name(self) -> str:
        return "Customer"

    def get_dashboard_title(self) -> str:
        return "Customer View"
