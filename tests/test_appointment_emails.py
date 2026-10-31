import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from database import Database
from models import Appointment, AppointmentStatus, Customer, Service
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.notification_service import NotificationService
from services.pricing_calculator import PricingCalculator
from services.queue_manager import QueueManager


class MockEmailSender(NotificationService):
    def __init__(self) -> None:
        self.booking: list[tuple[str, str, str, datetime]] = []
        self.reminders: list[tuple[str, str, str, datetime]] = []
        self.thank_you: list[tuple[str, str, str, datetime]] = []
        self.status: list[tuple[str, str]] = []

    def send_booking_received(
        self, email: str, first_name: str, service_name: str, appointment_time: datetime
    ) -> None:
        self.booking.append((email, first_name, service_name, appointment_time))

    def send_appointment_reminder(
        self, email: str, first_name: str, service_name: str, appointment_time: datetime
    ) -> None:
        self.reminders.append((email, first_name, service_name, appointment_time))

    def send_appointment_thank_you(
        self, email: str, first_name: str, service_name: str, appointment_time: datetime
    ) -> None:
        self.thank_you.append((email, first_name, service_name, appointment_time))

    def send_appointment_status_async(self, email, appointment_summary, callback):
        self.status.append((email, appointment_summary))
        callback(True, None)
        return None


class AppointmentEmailFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="appointment_email_test_")
        self.path = Path(self.temp.name) / "appointment-emails.sqlite"
        self.database = Database(self.path)
        self.database.initialize_schema()
        self.email = "one-client@example.test"
        self.database.add_client(
            Customer("Taylor Test", self.email, deposit_paid=True)
        )
        service = self.database.add_service(
            Service("Test Manicure", 100, duration_minutes=60)
        )
        if service.service_id is None:
            self.fail("Test service was not persisted")
        self.service_id = service.service_id
        self.sender = MockEmailSender()
        self.manager = AppointmentManager(
            self.database,
            PricingCalculator(),
            self.sender,
            LoyaltyManager(self.database),
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_booking_email_sent_once_with_only_requested_fields(self) -> None:
        appointment = self.manager.create_appointment(
            self.email,
            self.service_id,
            "",
            [],
            datetime.now() + timedelta(days=4),
            allow_outside_schedule=True,
        )
        self.assertEqual(len(self.sender.booking), 1)
        self.assertEqual(
            self.sender.booking[0][:-1],
            (self.email, "Taylor", "Test Manicure"),
        )
        appointment_id = self._id(appointment)
        self.manager._send_booking_email(appointment)
        self.assertEqual(len(self.sender.booking), 1)
        self.assertIsNotNone(
            self.database.get_appointment_email_sent_at(appointment_id, "booking")
        )
        self.manager.update_status(
            appointment_id,
            AppointmentStatus.CONFIRMED,
            lambda _success, _error: None,
        )
        self.assertEqual(len(self.sender.booking), 1)
        self.assertEqual(len(self.sender.status), 1)
        self.assertNotIn("total", self.sender.status[0][1].lower())

    def test_reminder_sent_once_for_tomorrow_and_survives_restart(self) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment = self._add_appointment(
            datetime.combine(now.date() + timedelta(days=1), time(14, 30))
        )
        self.assertEqual(self.manager.send_due_reminders(now), 1)
        self.assertEqual(self.manager.send_due_reminders(now), 0)
        self.assertEqual(len(self.sender.reminders), 1)
        self.assertEqual(self.sender.reminders[0][1:3], ("Taylor", "Test Manicure"))
        appointment_id = self._id(appointment)
        self.assertIsNotNone(
            self.database.get_appointment_email_sent_at(appointment_id, "reminder")
        )

        self.database.close()
        self.database = Database(self.path)
        self.database.initialize_schema()
        self.sender = MockEmailSender()
        self.manager = AppointmentManager(
            self.database,
            PricingCalculator(),
            self.sender,
            LoyaltyManager(self.database),
        )
        self.assertEqual(self.manager.send_due_reminders(now), 0)
        self.assertEqual(self.sender.reminders, [])

    def test_cancelled_appointment_gets_no_reminder(self) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment = self._add_appointment(
            datetime.combine(now.date() + timedelta(days=1), time(11, 0))
        )
        self.manager.update_status(
            self._id(appointment),
            AppointmentStatus.CANCELLED,
            lambda _success, _error: None,
            late_confirmation=True,
        )
        self.assertEqual(self.manager.send_due_reminders(now), 0)
        self.assertEqual(self.sender.reminders, [])

    def test_failed_reminder_is_retried_on_next_check(self) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment = self._add_appointment(
            datetime.combine(now.date() + timedelta(days=1), time(12, 0))
        )
        appointment_id = self._id(appointment)
        with self.assertLogs("services.appointment_manager", level="ERROR"):
            with patch.object(
                self.sender,
                "send_appointment_reminder",
                side_effect=OSError("simulated offline sender"),
            ):
                self.assertEqual(self.manager.send_due_reminders(now), 0)
        self.assertIsNone(
            self.database.get_appointment_email_sent_at(appointment_id, "reminder")
        )
        self.assertEqual(self.manager.send_due_reminders(now), 1)
        self.assertEqual(len(self.sender.reminders), 1)

    def test_rescheduled_appointment_reminder_follows_new_date(self) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment = self._add_appointment(
            datetime.combine(now.date() + timedelta(days=3), time(11, 0))
        )
        appointment_id = self._id(appointment)
        self.assertTrue(
            self.database.mark_appointment_email_sent(
                appointment_id, "reminder", now
            )
        )
        self.manager.reschedule(
            appointment_id,
            datetime.combine(now.date() + timedelta(days=1), time(15, 15)),
            lambda _success, _error: None,
            late_confirmation=True,
            allow_outside_schedule=True,
        )
        self.assertIsNone(
            self.database.get_appointment_email_sent_at(appointment_id, "reminder")
        )
        self.assertEqual(self.manager.send_due_reminders(now), 1)
        self.assertEqual(len(self.sender.reminders), 1)
        self.assertEqual(self.sender.reminders[0][3].date(), now.date() + timedelta(days=1))
        self.assertEqual(self.sender.reminders[0][3].time(), time(15, 15))

    def test_completion_sends_one_thank_you_and_no_price(self) -> None:
        appointment = self._add_appointment(
            datetime.combine(date.today(), time(15, 0))
        )
        appointment_id = self._id(appointment)
        self.manager.update_status(
            appointment_id,
            AppointmentStatus.CONFIRMED,
            lambda _success, _error: None,
        )
        self.manager.update_status(
            appointment_id,
            AppointmentStatus.COMPLETED,
            lambda _success, _error: None,
        )
        self.assertEqual(len(self.sender.thank_you), 1)
        self.assertEqual(
            self.sender.thank_you[0][:3],
            (self.email, "Taylor", "Test Manicure"),
        )
        self.assertIsNotNone(
            self.database.get_appointment_email_sent_at(appointment_id, "thank_you")
        )
        self.database.close()
        self.database = Database(self.path)
        self.database.initialize_schema()
        self.sender = MockEmailSender()
        self.manager = AppointmentManager(
            self.database,
            PricingCalculator(),
            self.sender,
            LoyaltyManager(self.database),
        )
        self.manager._send_thank_you_email(
            self.manager.get_appointment(appointment_id)
        )
        self.assertEqual(self.sender.thank_you, [])

    def test_queue_contains_today_only_and_does_not_enroll_future(self) -> None:
        queue = QueueManager(self.database, self.manager)
        today = self._add_appointment(datetime.combine(date.today(), time(10, 0)))
        future = self._add_appointment(
            datetime.combine(date.today() + timedelta(days=1), time(10, 0))
        )
        self.manager.update_status(
            self._id(today),
            AppointmentStatus.CONFIRMED,
            lambda _success, _error: None,
        )
        self.manager.update_status(
            self._id(future),
            AppointmentStatus.CONFIRMED,
            lambda _success, _error: None,
        )
        self.assertIsNotNone(self.database.get_queue_entry_by_appointment(self._id(today)))
        self.assertIsNone(self.database.get_queue_entry_by_appointment(self._id(future)))
        self.assertEqual(len(queue.get_queue()), 1)
        self.assertEqual(queue.get_queue(date.today() + timedelta(days=1)), [])

    def test_old_appointment_table_migrates_with_null_email_markers(self) -> None:
        old_path = Path(self.temp.name) / "old.sqlite"
        connection = sqlite3.connect(old_path)
        connection.executescript(
            """
            CREATE TABLE clients (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT NOT NULL,
                phone TEXT,
                notes TEXT
            );
            INSERT INTO clients (email, name) VALUES ('old@example.test', 'Old Client');
            CREATE TABLE services (
                service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                base_price REAL NOT NULL,
                length_prices TEXT NOT NULL,
                design_add_on_prices TEXT NOT NULL
            );
            INSERT INTO services
                (name, base_price, length_prices, design_add_on_prices)
                VALUES ('Old Service', 10, '{}', '{}');
            CREATE TABLE appointments (
                appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_email TEXT NOT NULL,
                service_id INTEGER NOT NULL,
                appointment_time TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                nail_length TEXT NOT NULL DEFAULT '',
                design_add_ons TEXT NOT NULL DEFAULT '[]',
                selected_extras TEXT NOT NULL DEFAULT '{}',
                total_price REAL NOT NULL DEFAULT 0,
                duration_minutes INTEGER NOT NULL DEFAULT 120,
                cancellation_fee REAL NOT NULL DEFAULT 0,
                allergies TEXT NOT NULL DEFAULT '',
                travel_fee REAL NOT NULL DEFAULT 0,
                discount REAL NOT NULL DEFAULT 0,
                amount_paid REAL NOT NULL DEFAULT 0,
                payment_note TEXT NOT NULL DEFAULT '',
                visit_type TEXT NOT NULL DEFAULT 'STUDIO',
                service_address TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO appointments
                (client_email, service_id, appointment_time, status)
                VALUES ('old@example.test', 1, '2020-01-01T10:00:00', 'COMPLETED');
            """
        )
        connection.commit()
        connection.close()

        old_database = Database(old_path)
        try:
            old_database.initialize_schema()
            appointment_id = old_database._connection.execute(
                "SELECT appointment_id FROM appointments"
            ).fetchone()["appointment_id"]
            for email_type in ("booking", "reminder", "thank_you"):
                self.assertIsNone(
                    old_database.get_appointment_email_sent_at(
                        appointment_id, email_type
                    )
                )
            old_row = old_database._connection.execute(
                "SELECT status, appointment_time FROM appointments WHERE appointment_id = ?",
                (appointment_id,),
            ).fetchone()
            self.assertEqual(old_row["status"], "COMPLETED")
            self.assertEqual(old_row["appointment_time"], "2020-01-01T10:00:00")
        finally:
            old_database.close()

    def test_notification_templates_use_only_requested_appointment_details(self) -> None:
        appointment_time = datetime(2026, 11, 1, 13, 30)
        with patch.object(NotificationService, "_send_message") as send_message:
            service = NotificationService()
            service.send_booking_received(
                self.email, "Taylor", "Test Manicure", appointment_time
            )
            service.send_appointment_reminder(
                self.email, "Taylor", "Test Manicure", appointment_time
            )
            service.send_appointment_thank_you(
                self.email, "Taylor", "Test Manicure", appointment_time
            )

        self.assertEqual(send_message.call_count, 3)
        for call in send_message.call_args_list:
            recipient, _subject, body = call.args
            self.assertEqual(recipient, self.email)
            self.assertIn("Taylor", body)
            self.assertIn("Test Manicure", body)
            self.assertIn("November 01, 2026", body)
            self.assertIn("01:30 PM", body)
            self.assertIn("Pearl's Signature", body)
            self.assertNotIn(self.email, body)
            self.assertNotIn("100", body)
            self.assertNotIn("address", body.lower())
        self.assertIn("We received your booking", send_message.call_args_list[0].args[2])
        self.assertIn(
            "You have an appointment tomorrow at 01:30 PM",
            send_message.call_args_list[1].args[2],
        )
        self.assertIn("Thank you for visiting", send_message.call_args_list[2].args[2])

    def _add_appointment(self, appointment_time: datetime) -> Appointment:
        appointment = self.database.add_appointment(
            Appointment(
                self.email,
                self.service_id,
                appointment_time,
                duration_minutes=60,
            )
        )
        return appointment

    @staticmethod
    def _id(appointment: Appointment) -> int:
        if appointment.appointment_id is None:
            raise AssertionError("Appointment was not persisted")
        return appointment.appointment_id


if __name__ == "__main__":
    unittest.main()
