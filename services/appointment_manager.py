from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, TypedDict

from database import Database
from models import (
    Appointment,
    AppointmentStatus,
    Customer,
    PriceExtra,
    Service,
    StudioPolicy,
    StudioSettings,
    User,
    VisitType,
)
from models._validation import validate_nonnegative_number, validate_optional_text
from services.loyalty_manager import LoyaltyManager
from services.notification_service import EmailCallback, NotificationService
from services.pricing_calculator import PricingCalculator
from services.schedule_manager import ScheduleManager

_LOGGER = logging.getLogger(__name__)


class _ReminderEmailOptions(TypedDict, total=False):
    online_booking_url: str
    calendar_sequence: int
    map_link_url: str


if TYPE_CHECKING:
    from services.queue_manager import QueueManager


class AppointmentManager:
    """Appointment validation, pricing, persistence, and notification orchestration."""

    def __init__(
        self,
        database: Database,
        pricing_calculator: PricingCalculator,
        notification_service: NotificationService,
        loyalty_manager: LoyaltyManager,
        studio_policy: StudioPolicy | None = None,
        schedule_manager: ScheduleManager | None = None,
    ) -> None:
        self._database = database
        self._pricing_calculator = pricing_calculator
        self._notification_service = notification_service
        # Retained for constructor compatibility; completion does not award stamps.
        self._studio_policy = studio_policy or StudioPolicy()
        self._schedule_manager = schedule_manager or ScheduleManager(database)
        self._queue_manager: QueueManager | None = None

    def set_queue_manager(self, queue_manager: QueueManager) -> None:
        self._queue_manager = queue_manager

    def notify_queue_called(
        self, email: str, callback: EmailCallback
    ) -> None:
        self._notification_service.send_queue_called_async(email, callback)

    @property
    def schedule_manager(self) -> ScheduleManager:
        return self._schedule_manager

    def get_appointments(self) -> list[Appointment]:
        return self._database.get_appointments()

    def get_appointments_for_date(self, selected_date: date) -> list[Appointment]:
        return [
            appointment
            for appointment in self.get_appointments()
            if self._as_datetime(appointment.appointment_time).date() == selected_date
        ]

    def get_appointment(self, appointment_id: int) -> Appointment:
        appointment = self._database.get_appointment(appointment_id)
        if appointment is None:
            raise KeyError(f"No appointment found with ID {appointment_id}")
        return appointment

    def get_clients(self) -> list[Customer]:
        return self._database.get_clients()

    def get_services(self) -> list[Service]:
        return self._database.get_services()

    def get_active_price_extras(self) -> list[PriceExtra]:
        return self._database.get_price_extras(active_only=True)

    def get_client_name(self, email: str) -> str:
        client = self._database.get_client(email)
        if client is None:
            raise KeyError(f"No client found with email {email!r}")
        return client.name

    def get_service_name(self, service_id: int) -> str:
        service = self._database.get_service(service_id)
        if service is None:
            raise KeyError(f"No service found with ID {service_id}")
        return service.name

    def get_studio_settings(self) -> StudioSettings:
        return self._database.get_studio_settings()

    def is_home_service_area_allowed(self, town: str) -> bool:
        if not isinstance(town, str):
            raise TypeError("town must be a string")
        normalized_town = town.strip().casefold()
        return bool(normalized_town) and any(
            normalized_town == area.casefold()
            for area in self.get_studio_settings().allowed_areas
        )

    def get_home_service_area_message(self) -> str:
        areas = ", ".join(self.get_studio_settings().allowed_areas)
        return (
            f"Sorry, home service is only available in: {areas}. "
            "Please choose a studio visit or contact the salon."
        )

    @property
    def studio_policy(self) -> StudioPolicy:
        return self._studio_policy

    def requires_late_notice_confirmation(self, appointment_time: datetime) -> bool:
        return appointment_time - datetime.now(appointment_time.tzinfo) < timedelta(
            hours=self._studio_policy.notice_hours
        )

    def create_appointment(
        self,
        client_email: str,
        service_id: int,
        nail_length: str,
        design_add_ons: list[str],
        appointment_time: datetime,
        duration_minutes: int | None = None,
        notes: str | None = None,
        allergies: str = "",
        visit_type: VisitType = VisitType.STUDIO,
        service_address: str = "",
        travel_fee: int | float | None = None,
        allow_outside_schedule: bool = False,
        selected_extra_names: list[str] | None = None,
    ) -> Appointment:
        if not isinstance(appointment_time, datetime):
            raise TypeError("appointment_time must be a datetime")
        client = self._database.get_client(client_email)
        if client is None:
            raise ValueError(f"No client found with email {client_email!r}")
        service = self._database.get_service(service_id)
        if service is None:
            raise ValueError(f"No service found with ID {service_id}")
        requested_extra_names = (
            selected_extra_names if selected_extra_names is not None else []
        )
        if not isinstance(requested_extra_names, list) or any(
            not isinstance(name, str) for name in requested_extra_names
        ):
            raise TypeError("selected_extra_names must be a list of strings")
        if len({name.casefold() for name in requested_extra_names}) != len(
            requested_extra_names
        ):
            raise ValueError("An extra can only be selected once")
        active_extras = {
            extra.name.casefold(): extra
            for extra in self.get_active_price_extras()
        }
        selected_extras: dict[str, float] = {}
        for name in requested_extra_names:
            extra = active_extras.get(name.casefold())
            if extra is None:
                raise ValueError(f"Extra {name!r} is no longer active")
            selected_extras[extra.name] = extra.price
        total_price = self._pricing_calculator.calculate_price(
            service, nail_length, design_add_ons, selected_extras
        )
        if not isinstance(visit_type, VisitType):
            raise ValueError("visit_type must be a VisitType value")
        settings = self.get_studio_settings()
        if visit_type is VisitType.HOME_SERVICE and travel_fee is None:
            travel_fee = settings.default_travel_fee
        if visit_type is VisitType.STUDIO:
            travel_fee = 0
            service_address = ""
        appointment = Appointment(
            client_email=client.email,
            service_id=service_id,
            appointment_time=appointment_time,
            status=AppointmentStatus.PENDING,
            nail_length=nail_length,
            design_add_ons=design_add_ons,
            selected_extras=selected_extras,
            total_price=total_price,
            duration_minutes=(
                service.duration_minutes
                if duration_minutes is None
                else duration_minutes
            ),
            notes=notes,
            allergies=allergies,
            visit_type=visit_type,
            service_address=service_address,
            travel_fee=travel_fee or 0,
        )
        self._validate_schedule(appointment, allow_outside_schedule)
        conflict = self._find_time_conflict(appointment)
        if conflict is not None:
            raise ValueError(self._conflict_message(conflict))
        created = self._database.add_appointment(appointment)
        self._send_booking_email(created)
        return created

    def get_available_slots(
        self,
        selected_date: date,
        duration_minutes: int,
        visit_type: VisitType = VisitType.STUDIO,
    ) -> list[datetime]:
        if not isinstance(selected_date, date) or isinstance(selected_date, datetime):
            raise TypeError("selected_date must be a date")
        if (
            isinstance(duration_minutes, bool)
            or not isinstance(duration_minutes, int)
            or not self._studio_policy.min_minutes
            <= duration_minutes
            <= self._studio_policy.max_minutes
        ):
            raise ValueError(
                f"duration_minutes must be between "
                f"{self._studio_policy.min_minutes} and "
                f"{self._studio_policy.max_minutes}"
            )
        if duration_minutes % 5:
            raise ValueError("duration_minutes must be a multiple of 5")
        if not isinstance(visit_type, VisitType):
            raise ValueError("visit_type must be a VisitType value")

        day_hours = self._schedule_manager.get_day_hours(selected_date)
        if not day_hours["is_open"]:
            return []
        opening_time = time.fromisoformat(str(day_hours["open_time"]))
        closing_time = time.fromisoformat(str(day_hours["close_time"]))
        earliest_start = datetime.now() + timedelta(hours=24)
        appointments = [
            appointment
            for appointment in self.get_appointments()
            if appointment.status
            in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        ]
        slots: list[datetime] = []
        slot_start = datetime.combine(selected_date, opening_time)
        closing_datetime = datetime.combine(selected_date, closing_time)
        while slot_start < closing_datetime:
            if slot_start >= earliest_start:
                candidate = Appointment(
                    client_email="schedule-check@example.invalid",
                    service_id=1,
                    appointment_time=slot_start,
                    duration_minutes=duration_minutes,
                    visit_type=visit_type,
                    service_address=(
                        "Schedule check"
                        if visit_type is VisitType.HOME_SERVICE
                        else ""
                    ),
                )
                issue = self._schedule_manager.get_schedule_issue(
                    slot_start, duration_minutes, visit_type
                )
                conflict = self._find_time_conflict(candidate, appointments=appointments)
                if issue is None and conflict is None:
                    slots.append(slot_start)
            slot_start += timedelta(minutes=15)
        return slots

    def set_home_service_travel_fee(
        self, appointment_id: int, travel_fee: int | float, role: User
    ) -> Appointment:
        self._require_permission(role, "record_payments")
        appointment = self.get_appointment(appointment_id)
        if appointment.visit_type is not VisitType.HOME_SERVICE:
            raise ValueError("Travel fees only apply to home-service appointments")
        if appointment.status is not AppointmentStatus.PENDING:
            raise ValueError("Travel fee can only be changed before confirmation")
        appointment.travel_fee = validate_nonnegative_number(
            travel_fee, "travel_fee"
        )
        if appointment.discount > appointment.total_price + appointment.travel_fee:
            raise ValueError("Discount cannot exceed the final service total")
        self._database.update_appointment(appointment)
        return appointment

    def record_payment(
        self,
        appointment_id: int,
        amount_paid: int | float,
        discount: int | float,
        travel_fee: int | float,
        payment_note: str,
        role: User,
    ) -> Appointment:
        self._require_permission(role, "record_payments")
        appointment = self.get_appointment(appointment_id)
        if appointment.status not in (
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.COMPLETED,
        ):
            raise ValueError(
                "Payments can only be recorded for confirmed or completed appointments"
            )
        validated_amount_paid = validate_nonnegative_number(
            amount_paid, "amount_paid"
        )
        validated_discount = validate_nonnegative_number(discount, "discount")
        validated_travel_fee = validate_nonnegative_number(
            travel_fee, "travel_fee"
        )
        validated_note = validate_optional_text(payment_note, "payment_note") or ""
        subtotal = appointment.total_price + validated_travel_fee
        if validated_discount > subtotal:
            raise ValueError("Discount cannot exceed the service price plus travel fee")
        final_price = subtotal - validated_discount
        if validated_amount_paid > final_price:
            raise ValueError("Amount paid cannot exceed the final price")

        appointment.travel_fee = validated_travel_fee
        appointment.discount = validated_discount
        appointment.amount_paid = validated_amount_paid
        appointment.payment_note = validated_note
        self._database.update_appointment(appointment)
        return appointment

    def update_status(
        self,
        appointment_id: int,
        status: AppointmentStatus,
        email_callback: EmailCallback,
        late_confirmation: bool = False,
        waive_fee: bool = False,
        role: User | None = None,
    ) -> Appointment:
        if waive_fee:
            self._require_admin(role, "waive a cancellation fee")
        appointment = self.get_appointment(appointment_id)
        if (
            status is AppointmentStatus.CONFIRMED
            and appointment.visit_type is VisitType.HOME_SERVICE
            and appointment.travel_fee <= 0
        ):
            raise ValueError("Set the travel fee for this home service first.")
        appointment.update_status(status)
        if status is AppointmentStatus.CONFIRMED:
            client = self._database.get_client(appointment.client_email)
            if client is None:
                raise KeyError(f"No client found with email {appointment.client_email!r}")
            if not client.deposit_paid:
                raise ValueError(
                    "New client: the 100 peso deposit must be paid first"
                )
        is_late = self.requires_late_notice_confirmation(
            self._as_datetime(appointment.appointment_time)
        )
        if status is AppointmentStatus.CANCELLED:
            if is_late and not late_confirmation:
                raise ValueError(
                    "Cancellation is within the 48-hour notice period; confirmation is required"
                )
            if is_late:
                appointment.cancellation_fee = (
                    0 if waive_fee else self._studio_policy.cancellation_fee
                )
        self._database.update_appointment(appointment)
        if self._queue_manager is not None and appointment.appointment_id is not None:
            if status is AppointmentStatus.CONFIRMED:
                if self._as_datetime(appointment.appointment_time).date() == date.today():
                    self._queue_manager.enroll_booked(appointment.appointment_id)
            else:
                self._queue_manager.sync_appointment(appointment.appointment_id)
        if status in (AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED):
            self._send_status_email(appointment, email_callback)
        if status is AppointmentStatus.COMPLETED:
            self._send_thank_you_email(appointment)
        return appointment

    def reschedule(
        self,
        appointment_id: int,
        new_time: datetime,
        email_callback: EmailCallback,
        late_confirmation: bool = False,
        waive_fee: bool = False,
        allow_outside_schedule: bool = False,
        role: User | None = None,
    ) -> Appointment:
        if waive_fee:
            self._require_admin(role, "waive a rescheduling fee")
        if not isinstance(new_time, datetime):
            raise TypeError("new_time must be a datetime")
        appointment = self.get_appointment(appointment_id)
        if appointment.status not in (
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
        ):
            raise ValueError("Only pending or confirmed appointments can be rescheduled")
        is_late = self.requires_late_notice_confirmation(
            self._as_datetime(appointment.appointment_time)
        )
        if is_late and not late_confirmation:
            raise ValueError(
                "Rescheduling is within the 48-hour notice period; confirmation is required"
            )

        appointment.reschedule(new_time)
        self._validate_schedule(appointment, allow_outside_schedule)
        conflict = self._find_time_conflict(
            appointment, exclude_appointment_id=appointment_id
        )
        if conflict is not None:
            raise ValueError(self._conflict_message(conflict))
        if is_late:
            appointment.cancellation_fee = (
                0 if waive_fee else self._studio_policy.cancellation_fee
            )
        self._database.update_appointment(
            appointment, increment_calendar_sequence=True
        )
        if self._queue_manager is not None:
            self._queue_manager.sync_appointment(appointment_id)
        self._send_status_email(appointment, email_callback, "rescheduled")
        return appointment

    def update_duration(
        self,
        appointment_id: int,
        duration_minutes: int,
        allow_outside_schedule: bool = False,
    ) -> Appointment:
        appointment = self.get_appointment(appointment_id)
        if appointment.status not in (
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
        ):
            raise ValueError("Only active appointments can have their duration changed")
        appointment.duration_minutes = duration_minutes
        self._validate_schedule(appointment, allow_outside_schedule)
        conflict = self._find_time_conflict(
            appointment, exclude_appointment_id=appointment_id
        )
        if conflict is not None:
            raise ValueError(self._conflict_message(conflict))
        self._database.update_appointment(appointment)
        return appointment

    def _find_time_conflict(
        self,
        appointment: Appointment,
        exclude_appointment_id: int | None = None,
        appointments: list[Appointment] | None = None,
    ) -> Appointment | None:
        start, end = self._blocked_range(appointment)
        for existing in appointments if appointments is not None else self.get_appointments():
            if existing.appointment_id == exclude_appointment_id:
                continue
            if existing.status not in (
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
            ):
                continue
            existing_start, existing_end = self._blocked_range(existing)
            if start < existing_end and existing_start < end:
                return existing
        return None

    def _blocked_range(self, appointment: Appointment) -> tuple[datetime, datetime]:
        start = self._as_datetime(appointment.appointment_time)
        end = appointment.get_end_time()
        settings = self.get_studio_settings()
        if appointment.visit_type is VisitType.HOME_SERVICE:
            travel = timedelta(minutes=settings.travel_buffer_minutes)
            return (
                start - travel,
                end + travel + timedelta(minutes=settings.cleaning_buffer_minutes),
            )
        return start, end + timedelta(minutes=settings.cleaning_buffer_minutes)

    def _validate_schedule(
        self, appointment: Appointment, allow_outside_schedule: bool
    ) -> None:
        if not isinstance(allow_outside_schedule, bool):
            raise TypeError("allow_outside_schedule must be a bool")
        issue = self._schedule_manager.get_schedule_issue(
            self._as_datetime(appointment.appointment_time),
            appointment.duration_minutes,
            appointment.visit_type,
        )
        if issue is not None and not allow_outside_schedule:
            raise ValueError(f"Outside working hours. {issue}")

    def _conflict_message(self, conflicting: Appointment) -> str:
        start = self._as_datetime(conflicting.appointment_time)
        end = conflicting.get_end_time()
        conflict_start, conflict_end = self._blocked_range(conflicting)
        return (
            "This appointment overlaps an existing appointment from "
            f"{conflict_start:%Y-%m-%d %H:%M} to {conflict_end:%Y-%m-%d %H:%M} "
            f"(service time {start:%H:%M} to {end:%H:%M})"
        )

    @staticmethod
    def _require_permission(role: User, permission: str) -> None:
        if permission not in role.get_permissions():
            raise PermissionError(f"This role cannot {permission.replace('_', ' ')}")

    @staticmethod
    def _require_admin(role: User | None, action: str) -> None:
        if not isinstance(role, User) or "view_payments" not in role.get_permissions():
            raise PermissionError(f"Only an Admin can {action}")

    def _send_status_email(
        self,
        appointment: Appointment,
        callback: EmailCallback,
        email_status: str | None = None,
    ) -> None:
        if not appointment.client_email.strip():
            return
        try:
            client = self._database.get_client(appointment.client_email)
            service = self._database.get_service(appointment.service_id)
            if client is None or service is None:
                raise RuntimeError("Appointment email details are unavailable")
            if appointment.appointment_id is None:
                raise RuntimeError("Appointment email reference is unavailable")
            appointment_time = self._as_datetime(appointment.appointment_time)
            full_name = client.name
            settings = self._database.get_studio_settings()
        except Exception:
            _LOGGER.exception(
                "Could not prepare appointment status email for appointment %s",
                appointment.appointment_id,
            )
            callback(False, "Appointment email details are unavailable")
            return
        self._notification_service.send_appointment_status_async(
            appointment.client_email,
            full_name,
            service.name,
            appointment_time,
            appointment.appointment_id,
            email_status
            or (
                "cancelled"
                if appointment.status is AppointmentStatus.CANCELLED
                else "confirmed"
            ),
            settings.studio_address,
            settings.loyalty_phone,
            callback,
            provider_name=settings.owner_provider_name,
            facebook_page=settings.loyalty_facebook,
            review_url=settings.review_url,
            duration_minutes=appointment.duration_minutes,
            online_booking_url=settings.online_booking_url,
            map_link_url=settings.map_link_url,
        )

    def send_due_reminders(self, now: datetime | None = None) -> int:
        current_time = now or datetime.now()
        due_date = current_time.date() + timedelta(days=1)
        sent_count = 0
        try:
            due_appointments = self._database.get_due_appointment_reminders(due_date)
        except sqlite3.Error:
            _LOGGER.exception("Could not check for due appointment reminders")
            return 0

        for details in due_appointments:
            appointment_id = int(details["appointment_id"])
            email = str(details["client_email"]).strip()
            if not email:
                continue
            try:
                settings = self._database.get_studio_settings()
                email_context: _ReminderEmailOptions = {}
                if settings.online_booking_url:
                    email_context["online_booking_url"] = (
                        settings.online_booking_url
                    )
                if settings.map_link_url:
                    email_context["map_link_url"] = settings.map_link_url
                calendar_sequence = int(details["calendar_sequence"])
                if calendar_sequence:
                    email_context["calendar_sequence"] = calendar_sequence
                self._notification_service.send_appointment_reminder(
                    email,
                    str(details["client_name"]),
                    str(details["service_name"]),
                    self._as_datetime(str(details["appointment_time"])),
                    appointment_id,
                    settings.studio_address,
                    settings.loyalty_phone,
                    settings.owner_provider_name,
                    settings.loyalty_facebook,
                    settings.review_url,
                    int(details["duration_minutes"]),
                    **email_context,
                )
                if self._database.mark_appointment_email_sent(
                    appointment_id, "reminder", current_time
                ):
                    sent_count += 1
            except Exception:
                _LOGGER.exception(
                    "Could not send appointment reminder for appointment %s",
                    appointment_id,
                )
        return sent_count

    def _send_booking_email(self, appointment: Appointment) -> None:
        self._send_one_time_email(appointment, "booking", "send_booking_received")

    def _send_thank_you_email(self, appointment: Appointment) -> None:
        self._send_one_time_email(
            appointment, "thank_you", "send_appointment_thank_you"
        )

    def _send_one_time_email(
        self, appointment: Appointment, email_type: str, sender_name: str
    ) -> None:
        appointment_id = appointment.appointment_id
        if appointment_id is None or not appointment.client_email.strip():
            return
        try:
            if self._database.get_appointment_email_sent_at(
                appointment_id, email_type
            ):
                return
            client = self._database.get_client(appointment.client_email)
            service = self._database.get_service(appointment.service_id)
            if client is None or service is None:
                raise RuntimeError("Appointment email details are unavailable")
            settings = self._database.get_studio_settings()
            sender = getattr(self._notification_service, sender_name)
            sender_arguments = (
                appointment.client_email,
                client.name,
                service.name,
                self._as_datetime(appointment.appointment_time),
                appointment_id,
                settings.studio_address,
                settings.loyalty_phone,
                settings.owner_provider_name,
                settings.loyalty_facebook,
                settings.review_url,
                appointment.duration_minutes,
            )
            if settings.online_booking_url:
                sender_arguments += (settings.online_booking_url,)
            email_context = (
                {"map_link_url": settings.map_link_url}
                if settings.map_link_url
                else {}
            )
            sender(*sender_arguments, **email_context)
            self._database.mark_appointment_email_sent(
                appointment_id, email_type, datetime.now()
            )
        except Exception:
            _LOGGER.exception(
                "Could not send %s email for appointment %s",
                email_type,
                appointment_id,
            )

    @staticmethod
    def _as_datetime(value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)
