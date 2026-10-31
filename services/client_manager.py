import re
import sqlite3
from datetime import datetime
from typing import TypedDict

from database import Database
from models import Customer


class BookingHistoryRecord(TypedDict):
    date: str
    service: str
    status: str
    total_price: float


class ClientManager:
    """Client and booking-history operations, isolated from the UI and SQL."""

    _EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_clients(self) -> list[Customer]:
        return self._database.get_clients()

    def add_client(self, client: Customer) -> Customer:
        self._validate_client(client)
        if self._find_client(client.email) is not None:
            raise ValueError(f"A client with email {client.email!r} already exists")
        try:
            return self._database.add_client(client)
        except sqlite3.IntegrityError as error:
            raise ValueError(f"A client with email {client.email!r} already exists") from error

    def update_client(
        self,
        original_email: str,
        client: Customer,
        clear_fields: set[str] | None = None,
    ) -> None:
        self._validate_client(client)
        clear_fields = set(clear_fields or ())
        profile_fields = {"address", "nail_condition", "health_notes"}
        unknown_fields = clear_fields - profile_fields
        if unknown_fields:
            raise ValueError(
                f"Unsupported profile fields to clear: {', '.join(sorted(unknown_fields))}"
            )
        normalized_original = self._normalize_email(original_email)
        normalized_updated = self._normalize_email(client.email)
        if normalized_updated != normalized_original:
            raise ValueError("A client's email cannot be changed because it is their identifier")
        current_client = self._database.get_client(normalized_original)
        if current_client is None:
            raise KeyError(f"No client found for {normalized_original}")
        if current_client.deposit_paid:
            client.mark_deposit_paid()
            client.deposit_paid_on = current_client.deposit_paid_on
        for field_name in profile_fields:
            submitted_value = getattr(client, field_name)
            if field_name in clear_fields:
                setattr(client, field_name, "")
            elif not submitted_value:
                setattr(client, field_name, getattr(current_client, field_name))
        self._database.update_client(client)

    def delete_client(self, email: str) -> None:
        self._database.delete_client(self._normalize_email(email))

    def mark_deposit_paid(self, email: str) -> Customer:
        client = self._database.get_client(self._normalize_email(email))
        if client is None:
            raise KeyError(f"No client found with email {email!r}")
        client.mark_deposit_paid()
        self._database.update_client(client)
        return client

    def get_booking_history(self, client_email: str) -> list[BookingHistoryRecord]:
        appointments = self._database.get_booking_history(self._normalize_email(client_email))
        history: list[BookingHistoryRecord] = []
        for appointment in appointments:
            service = self._database.get_service(appointment.service_id)
            if service is None:
                service_name = f"Service #{appointment.service_id}"
            else:
                service_name = service.name

            appointment_time = appointment.appointment_time
            if isinstance(appointment_time, datetime):
                formatted_date = appointment_time.strftime("%Y-%m-%d %H:%M")
            else:
                try:
                    formatted_date = datetime.fromisoformat(appointment_time).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except ValueError:
                    formatted_date = appointment_time
            history.append(
                {
                    "date": formatted_date,
                    "service": service_name,
                    "status": appointment.status.value,
                    "total_price": appointment.total_price,
                }
            )
        return history

    def _find_client(self, email: str) -> Customer | None:
        normalized_email = self._normalize_email(email)
        return next(
            (
                client
                for client in self._database.get_clients()
                if self._normalize_email(client.email) == normalized_email
            ),
            None,
        )

    @classmethod
    def _validate_client(cls, client: Customer) -> None:
        if not isinstance(client, Customer):
            raise TypeError("client must be a Customer")
        if not client.name.strip():
            raise ValueError("Client name is required")
        normalized_email = cls._normalize_email(client.email)
        if not cls._EMAIL_PATTERN.fullmatch(normalized_email):
            raise ValueError("Enter a valid email address")

    @staticmethod
    def _normalize_email(email: str) -> str:
        if not isinstance(email, str):
            raise TypeError("Email must be text")
        return email.strip().lower()
