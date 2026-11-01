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
from services.studio_settings_manager import StudioSettingsManager


class MockEmailSender(NotificationService):
    def __init__(self) -> None:
        self.booking: list[tuple[str, str, str, datetime, str]] = []
        self.reminders: list[tuple[str, str, str, datetime, str, int]] = []
        self.thank_you: list[tuple[str, str, str, datetime]] = []
        self.status: list[tuple[str, str]] = []

    def send_booking_received(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        _appointment_id: int = 0,
        _studio_address: str = "",
        _studio_phone: str = "",
        _provider_name: str = "",
        _facebook_page: str = "",
        _review_url: str = "",
        _duration_minutes: int = 120,
        online_booking_url: str = "",
    ) -> None:
        self.booking.append(
            (email, first_name, service_name, appointment_time, online_booking_url)
        )

    def send_appointment_reminder(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        _appointment_id: int = 0,
        _studio_address: str = "",
        _studio_phone: str = "",
        _provider_name: str = "",
        _facebook_page: str = "",
        _review_url: str = "",
        _duration_minutes: int = 120,
        online_booking_url: str = "",
        calendar_sequence: int = 0,
    ) -> None:
        self.reminders.append(
            (
                email,
                first_name,
                service_name,
                appointment_time,
                online_booking_url,
                calendar_sequence,
            )
        )

    def send_appointment_thank_you(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        _appointment_id: int = 0,
        _studio_address: str = "",
        _studio_phone: str = "",
        _provider_name: str = "",
        _facebook_page: str = "",
        _review_url: str = "",
        _duration_minutes: int = 120,
        online_booking_url: str = "",
    ) -> None:
        self.thank_you.append((email, first_name, service_name, appointment_time))

    def send_appointment_status_async(
        self,
        email,
        first_name,
        service_name,
        appointment_time,
        appointment_id,
        status,
        studio_address,
        studio_phone,
        callback,
        **_email_context,
    ):
        self.status.append(
            (
                email,
                f"Service: {service_name}\n"
                f"Time: {appointment_time:%I:%M %p}\n"
                f"Booking ID: {appointment_id}\n"
                f"Status: {status}",
            )
        )
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
        settings = self.database.get_studio_settings()
        StudioSettingsManager(self.database).update_settings(
            settings.default_travel_fee,
            settings.travel_buffer_minutes,
            settings.service_area_note,
            online_booking_url="https://booking.example.test/",
        )
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
            self.sender.booking[0][:3],
            (self.email, "Taylor", "Test Manicure"),
        )
        self.assertEqual(
            self.sender.booking[0][4], "https://booking.example.test/"
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
        self.assertEqual(self.sender.reminders[0][5], 1)

    def test_calendar_sequence_increments_for_each_reschedule(self) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment = self._add_appointment(
            datetime.combine(now.date() + timedelta(days=4), time(11, 0))
        )
        appointment_id = self._id(appointment)

        self.manager.reschedule(
            appointment_id,
            datetime.combine(now.date() + timedelta(days=3), time(12, 0)),
            lambda _success, _error: None,
            late_confirmation=True,
            allow_outside_schedule=True,
        )
        self.manager.reschedule(
            appointment_id,
            datetime.combine(now.date() + timedelta(days=1), time(12, 15)),
            lambda _success, _error: None,
            late_confirmation=True,
            allow_outside_schedule=True,
        )

        due_rows = self.database.get_due_appointment_reminders(
            now.date() + timedelta(days=1)
        )
        self.assertEqual(due_rows[0]["calendar_sequence"], 2)
        self.assertEqual(self.manager.send_due_reminders(now), 1)
        self.assertEqual(self.sender.reminders[0][5], 2)

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
                "SELECT status, appointment_time, calendar_sequence FROM appointments "
                "WHERE appointment_id = ?",
                (appointment_id,),
            ).fetchone()
            self.assertEqual(old_row["status"], "COMPLETED")
            self.assertEqual(old_row["appointment_time"], "2020-01-01T10:00:00")
            self.assertEqual(old_row["calendar_sequence"], 0)
        finally:
            old_database.close()

    def test_older_studio_settings_database_migrates_safely(self) -> None:
        old_path = Path(self.temp.name) / "old-studio-settings.sqlite"
        connection = sqlite3.connect(old_path)
        connection.executescript(
            """
            CREATE TABLE studio_settings (
                setting_id INTEGER PRIMARY KEY,
                default_travel_fee REAL NOT NULL DEFAULT 0,
                travel_buffer_minutes INTEGER NOT NULL DEFAULT 30,
                service_area_note TEXT NOT NULL DEFAULT 'Legacy setting'
            );
            INSERT INTO studio_settings (setting_id, service_area_note)
            VALUES (1, 'Keep existing settings');
            """
        )
        connection.commit()
        connection.close()

        old_database = Database(old_path)
        try:
            old_database.initialize_schema()
            settings = old_database.get_studio_settings()
            self.assertEqual(settings.owner_provider_name, "Nicole Pearl Millari Teodoro")
            self.assertEqual(settings.review_url, "")
            self.assertEqual(settings.online_booking_url, "")
            self.assertEqual(settings.service_area_note, "Keep existing settings")

            old_database._connection.execute(
                """
                UPDATE studio_settings
                SET owner_provider_name = ?, review_url = ?, online_booking_url = ?
                WHERE setting_id = 1
                """,
                (
                    "Admin-entered name",
                    "https://reviews.example.test/",
                    "https://booking.example.test/",
                ),
            )
            old_database.initialize_schema()
            migrated = old_database.get_studio_settings()
            self.assertEqual(migrated.owner_provider_name, "Admin-entered name")
            self.assertEqual(migrated.review_url, "https://reviews.example.test/")
            self.assertEqual(
                migrated.online_booking_url, "https://booking.example.test/"
            )

            old_database._connection.execute(
                "UPDATE studio_settings SET owner_provider_name = '' WHERE setting_id = 1"
            )
            old_database.initialize_schema()
            self.assertEqual(old_database.get_studio_settings().owner_provider_name, "")
        finally:
            old_database.close()

    def test_appointment_emails_use_shared_multipart_template(self) -> None:
        appointment_time = datetime(2026, 11, 1, 13, 30)
        logo_path = Path(self.temp.name) / "logo.png"
        logo_path.write_bytes(b"test logo image")
        sent_messages = []

        class MockSMTP:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self):
                pass

            def login(self, *_args):
                pass

            def send_message(self, message):
                sent_messages.append(message)

        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_USER": "sender@example.test",
                    "SMTP_PASSWORD": "test-password",
                    "SENDER_NAME": "Pearl's",
                },
            ),
            patch.object(NotificationService, "_LOGO_PATH", logo_path),
            patch("services.notification_service.smtplib.SMTP", MockSMTP),
        ):
            service = NotificationService()
            service.send_booking_received(
                self.email, "Taylor", "Test Manicure", appointment_time, 42,
                "12 Rose Street, Pila", "09171234567",
                "Nicole Pearl Millari Teodoro",
                "https://facebook.example.test/pearl",
                "https://reviews.example.test/pearl",
                75,
                "https://booking.example.test/",
            )
            service.send_appointment_reminder(
                self.email, "Taylor", "Test Manicure", appointment_time, 42,
                "12 Rose Street, Pila", "09171234567",
                "Nicole Pearl Millari Teodoro",
                "https://facebook.example.test/pearl",
                "https://reviews.example.test/pearl",
                75,
                online_booking_url="",
                calendar_sequence=1,
            )
            service.send_appointment_thank_you(
                self.email, "Taylor", "Test Manicure", appointment_time, 42,
                "12 Rose Street, Pila", "09171234567",
                "Nicole Pearl Millari Teodoro",
                "https://facebook.example.test/pearl",
                "https://reviews.example.test/pearl",
                75,
            )
            for status in ("confirmed", "cancelled", "rescheduled"):
                service.send_appointment_status(
                    self.email,
                    "Taylor",
                    "Test Manicure",
                    appointment_time,
                    42,
                    status,
                    "12 Rose Street, Pila",
                    "09171234567",
                    "Nicole Pearl Millari Teodoro",
                    "https://facebook.example.test/pearl",
                    "https://reviews.example.test/pearl",
                    75,
                )

        self.assertEqual(len(sent_messages), 6)
        for index, message in enumerate(sent_messages):
            self.assertEqual(message["To"], self.email)
            plain_part = next(
                part
                for part in message.walk()
                if part.get_content_type() == "text/plain"
            )
            html_part = next(
                part
                for part in message.walk()
                if part.get_content_type() == "text/html"
            )
            self.assertIn("Taylor", plain_part.get_content())
            self.assertNotIn("Taylor Test", plain_part.get_content())
            self.assertIn("Nicole Pearl Millari Teodoro", plain_part.get_content())
            self.assertIn("Thanks,\nNicole Pearl Millari Teodoro", plain_part.get_content())
            self.assertIn("Test Manicure", plain_part.get_content())
            self.assertIn("Sunday, November 01, 2026 at 01:30 PM", plain_part.get_content())
            self.assertIn("Booking ID: PS-000042", plain_part.get_content())
            self.assertEqual(html_part.get_content_type(), "text/html")
            self.assertEqual(
                message.get_content_subtype(),
                "mixed" if index in (1, 3) else "alternative",
            )
            html_body = html_part.get_content()
            self.assertNotIn("Taylor Test", html_body)
            self.assertIn("Taylor", html_body)
            self.assertIn("Test Manicure", html_body)
            self.assertIn("Sunday, November 01, 2026 at 01:30 PM", html_body)
            self.assertIn("PS-000042", html_body)
            self.assertIn("Provider", html_body)
            self.assertIn("Nicole Pearl Millari Teodoro", html_body)
            self.assertIn("Thanks,<br>Nicole Pearl Millari Teodoro", html_body)
            if index == 0:
                self.assertIn(
                    'href="https://booking.example.test/"',
                    html_body,
                )
                self.assertIn("Book again", html_body)
                self.assertNotIn("Visit our Facebook page", html_body)
            else:
                self.assertIn(
                    'href="https://facebook.example.test/pearl"',
                    html_body,
                )
                self.assertIn("Visit our Facebook page", html_body)
            self.assertIn(
                'href="https://reviews.example.test/pearl"',
                html_body,
            )
            self.assertIn("Write a Review", html_body)
            self.assertIn(
                "https://www.google.com/maps/search/?api=1&amp;query="
                "12%20Rose%20Street%2C%20Pila",
                html_body,
            )
            self.assertIn("cid:studio-logo", html_body)
            self.assertIn("Get Directions", html_body)
            self.assertNotIn("price", plain_part.get_content().lower())
            self.assertNotIn("price", html_body.lower())
            self.assertNotIn("payment", plain_part.get_content().lower())
            self.assertNotIn("payment", html_body.lower())
            self.assertNotIn("100", plain_part.get_content())
            self.assertNotIn(self.email, plain_part.get_content())
            self.assertNotIn(self.email, html_body)
            related_parts = [
                part for part in message.walk()
                if part.get_content_maintype() == "image"
            ]
            self.assertEqual(len(related_parts), 1)
            self.assertEqual(related_parts[0]["Content-ID"], "<studio-logo>")
            self.assertEqual(
                related_parts[0].get_content_disposition(),
                "inline",
            )
            calendar_parts = [
                part
                for part in message.walk()
                if part.get_content_type() == "text/calendar"
            ]
            self.assertEqual(len(calendar_parts), 1 if index in (1, 3) else 0)
            if calendar_parts:
                calendar = calendar_parts[0].get_content()
                self.assertIn("METHOD:PUBLISH", calendar)
                self.assertIn("TZID:Asia/Manila", calendar)
                self.assertIn("DTSTART;TZID=Asia/Manila:20261101T133000", calendar)
                self.assertIn("DTEND;TZID=Asia/Manila:20261101T144500", calendar)
                self.assertIn("SUMMARY:Test Manicure", calendar)
                self.assertIn("LOCATION:12 Rose Street\\, Pila", calendar)
                self.assertIn("UID:PS-000042@pearls-signailture", calendar)
                self.assertIn(
                    f"SEQUENCE:{1 if index == 1 else 0}",
                    calendar,
                )
                self.assertNotIn(self.email, calendar)
                self.assertEqual(calendar_parts[0].get_filename(), "appointment.ics")
                self.assertEqual(calendar_parts[0].get_param("method"), "PUBLISH")
        reminder_calendar = next(
            part
            for part in sent_messages[1].walk()
            if part.get_content_type() == "text/calendar"
        ).get_content()
        confirmation_calendar = next(
            part
            for part in sent_messages[3].walk()
            if part.get_content_type() == "text/calendar"
        ).get_content()
        self.assertIn("UID:PS-000042@pearls-signailture", confirmation_calendar)
        self.assertIn("UID:PS-000042@pearls-signailture", reminder_calendar)
        self.assertIn("SEQUENCE:0", confirmation_calendar)
        self.assertIn("SEQUENCE:1", reminder_calendar)

    def test_booking_and_facebook_links_require_http_urls(self) -> None:
        cases = (
            (
                "https://booking.example.test/?a=1&b=2",
                "https://facebook.example.test/page",
                "Book again",
                'href="https://booking.example.test/?a=1&amp;b=2"',
            ),
            (
                "",
                "https://facebook.example.test/page",
                "Visit our Facebook page",
                'href="https://facebook.example.test/page"',
            ),
            ("", "", None, None),
            (
                "javascript:alert(1)",
                "file:///private",
                None,
                None,
            ),
        )
        for booking_url, facebook_url, expected_label, expected_href in cases:
            with self.subTest(booking_url=booking_url, facebook_url=facebook_url):
                with patch.object(NotificationService, "_send_message") as send_message:
                    NotificationService().send_booking_received(
                        self.email,
                        "Taylor",
                        "Test Manicure",
                        datetime(2026, 11, 1, 13, 30),
                        42,
                        facebook_page=facebook_url,
                        online_booking_url=booking_url,
                    )

                html_body = send_message.call_args.args[3]
                if expected_label is None:
                    self.assertNotIn("Book again", html_body)
                    self.assertNotIn("Visit our Facebook page", html_body)
                else:
                    self.assertIn(expected_label, html_body)
                    self.assertIn(expected_href, html_body)
                self.assertIn("font-size:15px", html_body)
                self.assertIn("font-size:14px", html_body)

    def test_special_characters_are_escaped_in_html(self) -> None:
        with patch.object(NotificationService, "_send_message") as send_message:
            NotificationService().send_booking_received(
                self.email,
                "A<&'",
                "Nails < & ' Deluxe",
                datetime(2026, 11, 1, 13, 30),
                7,
                '12 "Rose" & Vine',
                "",
            )

        html_body = send_message.call_args.args[3]
        self.assertIn("A&lt;&amp;&#x27;", html_body)
        self.assertIn("Nails &lt; &amp; &#x27; Deluxe", html_body)
        self.assertIn("12 &quot;Rose&quot; &amp; Vine", html_body)
        self.assertNotIn("Hi A<&'", html_body)

    def test_calendar_text_escapes_ics_special_characters(self) -> None:
        calendar = NotificationService._calendar_invite(
            "Nails, gel; art\nspecial",
            datetime(2026, 11, 1, 13, 30),
            60,
            "12, Rose; Street\nPila",
            8,
        )
        self.assertIn(r"SUMMARY:Nails\, gel\; art\nspecial", calendar)
        self.assertIn(r"LOCATION:12\, Rose\; Street\nPila", calendar)

    def test_empty_studio_address_and_missing_logo_do_not_crash(self) -> None:
        with (
            patch.object(NotificationService, "_LOGO_PATH", Path(self.temp.name) / "missing.png"),
            patch.object(NotificationService, "_send_message") as send_message,
        ):
            NotificationService().send_booking_received(
                self.email,
                "Taylor",
                "Test Manicure",
                datetime(2026, 11, 1, 13, 30),
                7,
                "",
                "",
            )

        html_body = send_message.call_args.args[3]
        self.assertNotIn("Get Directions", html_body)
        self.assertNotIn("cid:studio-logo", html_body)
        self.assertNotIn("Provider", html_body)
        self.assertNotIn("Thanks,", html_body)
        self.assertNotIn("Visit our Facebook page", html_body)
        self.assertNotIn("Write a Review", html_body)
        self.assertIsNone(send_message.call_args.args[4])

    def test_confirmation_calendar_omits_empty_location(self) -> None:
        with patch.object(NotificationService, "_send_message") as send_message:
            NotificationService().send_appointment_status(
                self.email,
                "Taylor",
                "Test Manicure",
                datetime(2026, 11, 1, 13, 30),
                7,
                "confirmed",
                "",
            )

        calendar = send_message.call_args.args[5]
        self.assertIn("METHOD:PUBLISH", calendar)
        self.assertNotIn("LOCATION:", calendar)

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
