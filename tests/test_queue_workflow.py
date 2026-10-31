import os
import sqlite3
import threading
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton

from database import Database
from models import (
    Appointment,
    AppointmentStatus,
    Customer,
    QueueEntry,
    QueueEntryType,
    Service,
)
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.notification_service import (
    EmailCallback,
    NotificationService,
)
from services.pricing_calculator import PricingCalculator
from services.queue_manager import QueueManager
from ui.customer_screens.queue_screen import QueueScreen
from ui.queue_panel import QueuePanel


class MockNotificationService(NotificationService):
    def __init__(self) -> None:
        self.appointment_emails: list[tuple[str, str]] = []
        self.queue_emails: list[str] = []

    def send_appointment_status_async(
        self, email: str, appointment_summary: str, callback: EmailCallback
    ) -> threading.Thread:
        self.appointment_emails.append((email, appointment_summary))
        callback(True, None)
        return threading.Thread()

    def send_queue_called_async(
        self, email: str, callback: EmailCallback
    ) -> threading.Thread:
        self.queue_emails.append(email)
        callback(True, None)
        return threading.Thread()


class QueueWorkflowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.temporary_directory.name) / "queue-checks.sqlite"
        )
        self.database.initialize_schema()
        self.email = "queue-check@example.test"
        self.database.add_client(
            Customer("Queue Check", self.email, deposit_paid=True)
        )
        service = self.database.add_service(
            Service("Queue Check Service", 100, duration_minutes=60)
        )
        if service.service_id is None:
            raise AssertionError("The test service was not persisted")
        self.service_id = service.service_id
        self.notifications = MockNotificationService()
        self.appointments = AppointmentManager(
            self.database,
            PricingCalculator(),
            self.notifications,
            LoyaltyManager(self.database),
        )
        self.queue = QueueManager(self.database, self.appointments)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def test_daily_order_skip_reschedule_and_customer_lookup(self) -> None:
        today = date.today()
        late = self._create_confirmed_appointment(today, time(11, 0))
        early = self._create_confirmed_appointment(today, time(9, 0))
        late_id = self._appointment_id(late)
        early_id = self._appointment_id(early)
        early_entry = self.database.get_queue_entry_by_appointment(
            early_id
        )
        late_entry = self.database.get_queue_entry_by_appointment(late_id)
        self.assertIsNotNone(early_entry)
        self.assertIsNotNone(late_entry)
        if early_entry is None or late_entry is None:
            raise AssertionError("Confirmed appointments must have queue entries")
        early_entry_id = self._queue_entry_id(early_entry)
        late_entry_id = self._queue_entry_id(late_entry)
        self.assertEqual(self.queue.get_position(early_entry_id), 1)
        self.assertEqual(self.queue.get_position(late_entry_id), 2)
        duplicate_enrollment = self.queue.enroll_booked(late_id)
        self.assertEqual(self._queue_entry_id(duplicate_enrollment), late_entry_id)
        self.assertIn(
            "is 001 right now (appointment at 11:00 AM)",
            self.notifications.appointment_emails[0][1],
        )
        self.assertIn(
            "is 001 right now (appointment at 09:00 AM)",
            self.notifications.appointment_emails[1][1],
        )

        serving = self.queue.call_next()
        self.assertEqual(serving.appointment_id, early_id)
        with self.assertRaises(ValueError):
            self.queue.call_next()
        self.queue.mark_done(self._queue_entry_id(serving))
        late_entry = self.database.get_queue_entry_by_appointment(late_id)
        if late_entry is None:
            raise AssertionError("The later appointment must retain its queue entry")
        late_entry_id = self._queue_entry_id(late_entry)
        self.assertEqual(self.queue.get_position(late_entry_id), 1)
        self.assertEqual(
            self.appointments.get_appointment(early_id).status,
            AppointmentStatus.COMPLETED,
        )
        self.assertEqual(self.notifications.queue_emails, [self.email])

        walk_in_time = datetime.combine(today, time(10, 0))
        walk_in = self.database.add_queue_entry(
            QueueEntry(
                "Walk In",
                QueueEntryType.WALK_IN,
                created_at=walk_in_time,
                queue_date=today,
                sort_time=walk_in_time,
            )
        )
        walk_in_id = self._queue_entry_id(walk_in)
        walk_in_ticket = walk_in.ticket_number
        self.assertEqual(self.queue.get_position(walk_in_id), 1)
        self.assertEqual(self.queue.get_position(late_entry_id), 2)
        self.queue.skip_next()
        self.assertEqual(self.queue.get_position(late_entry_id), 1)
        self.assertEqual(self.queue.get_position(walk_in_id), 2)
        skipped_walk_in = self.database.get_queue_entry(walk_in_id)
        if skipped_walk_in is None:
            raise AssertionError("The skipped walk-in must retain its entry")
        self.assertEqual(skipped_walk_in.ticket_number, walk_in_ticket)
        self.queue.cancel_entry(walk_in_id)
        self.assertEqual(self.queue.get_position(late_entry_id), 1)

        next_date = today + timedelta(days=2)
        self.appointments.reschedule(
            late_id,
            datetime.combine(next_date, time(11, 0)),
            lambda _success, _error: None,
            late_confirmation=True,
            allow_outside_schedule=True,
        )
        self.assertEqual(self.queue.get_queue(today), [])
        rescheduled = self.database.get_queue_entry_by_appointment(late_id)
        if rescheduled is None:
            raise AssertionError("The rescheduled appointment must retain its entry")
        self.assertEqual(rescheduled.queue_date, next_date)
        rescheduled_id = self._queue_entry_id(rescheduled)
        self.assertEqual(self.queue.get_position(rescheduled_id), 1)
        self.assertIsNone(self.queue.get_position(early_entry_id))
        self.assertEqual(self.notifications.queue_emails, [self.email])
        found_entry = self.queue.find_entry(self.email)
        self.assertIsNotNone(found_entry)
        if found_entry is None:
            raise AssertionError("The customer email should find the active entry")
        self.assertEqual(found_entry.entry_id, rescheduled.entry_id)

        screen = QueueScreen(self.queue)
        self.assertEqual(screen._refresh_timer.interval(), 10_000)
        self.assertEqual(screen._short_name("Queue Check"), "Queue C.")
        screen._lookup_box.setText(self.email)
        screen._find_my_position()
        self.assertTrue(
            screen._position_label.text().startswith(
                f"Your queue number is 001 for {next_date:%A, %B %d, %Y}"
            )
        )
        self.assertTrue(screen._position_label.text().endswith("0 ahead of you"))
        self.assertEqual(
            screen._ticket_label.text(),
            f"Ticket: {rescheduled.ticket_number or ''}",
        )
        panel = QueuePanel(self.queue)
        button_labels = {
            button.text()
            for button in panel.findChildren(QPushButton)
        }
        self.assertNotIn("Check In", button_labels)
        self.assertIn("Skip (not here yet)", button_labels)
        self.assertEqual(panel._entries, [])
        screen.close()
        panel.close()

        self.queue.add_walk_in("Walk In Caller")
        self.queue.call_next()
        self.assertEqual(self.notifications.queue_emails, [self.email])

    def test_cancelled_and_no_show_appointments_leave_the_line(self) -> None:
        today = date.today()
        cancelled = self._create_confirmed_appointment(today, time(14, 0))
        no_show = self._create_confirmed_appointment(today, time(16, 0))
        cancelled_id = self._appointment_id(cancelled)
        no_show_id = self._appointment_id(no_show)
        cancelled_entry = self.database.get_queue_entry_by_appointment(cancelled_id)
        no_show_entry = self.database.get_queue_entry_by_appointment(no_show_id)
        if cancelled_entry is None or no_show_entry is None:
            raise AssertionError("Confirmed appointments must have queue entries")

        self.appointments.update_status(
            cancelled_id,
            AppointmentStatus.CANCELLED,
            lambda _success, _error: None,
            late_confirmation=True,
        )
        self.appointments.update_status(
            no_show_id,
            AppointmentStatus.NO_SHOW,
            lambda _success, _error: None,
        )
        self.assertIsNone(self.queue.get_position(self._queue_entry_id(cancelled_entry)))
        self.assertIsNone(self.queue.get_position(self._queue_entry_id(no_show_entry)))

    def test_legacy_queue_rows_are_backfilled(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite"
        connection = sqlite3.connect(legacy_path)
        connection.execute(
            """
            CREATE TABLE queue_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                client_email TEXT,
                appointment_id INTEGER,
                entry_type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ticket_number TEXT NOT NULL,
                ticket_date TEXT NOT NULL
            )
            """
        )
        created_at = datetime.now().replace(microsecond=0)
        connection.execute(
            """
            INSERT INTO queue_entries
                (client_name, entry_type, status, created_at, ticket_number, ticket_date)
            VALUES (?, 'WALK_IN', 'WAITING', ?, 'A-007', ?)
            """,
            ("Existing Client", created_at.isoformat(), created_at.date().isoformat()),
        )
        connection.commit()
        connection.close()

        legacy_database = Database(legacy_path)
        try:
            legacy_database.initialize_schema()
            legacy_database.initialize_schema()
            old_entry = legacy_database.get_queue_entries()[0]
            self.assertEqual(old_entry.ticket_number, "A-007")
            self.assertEqual(old_entry.queue_date, created_at.date())
            self.assertEqual(old_entry.sort_time, created_at)
        finally:
            legacy_database.close()

    def test_queue_email_runs_in_background_and_reports_missing_smtp(self) -> None:
        with patch.object(NotificationService, "_send_message") as send_message:
            NotificationService().send_queue_called(self.email)
        send_message.assert_called_once_with(
            self.email,
            "You are next at Pearl's SigNAILture",
            "You are next at Pearl's SigNAILture",
        )

        results: list[tuple[bool, str | None]] = []
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "",
                "SMTP_PORT": "",
                "SMTP_USER": "",
                "SMTP_PASSWORD": "",
                "SENDER_NAME": "",
            },
        ):
            thread = NotificationService().send_queue_called_async(
                self.email, lambda success, error: results.append((success, error))
            )
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [(False, "SMTP email settings are incomplete")])

    def _create_confirmed_appointment(self, appointment_date, appointment_time):
        appointment = self.database.add_appointment(
            Appointment(
                self.email,
                self.service_id,
                datetime.combine(appointment_date, appointment_time),
                duration_minutes=60,
            )
        )
        appointment_id = self._appointment_id(appointment)
        return self.appointments.update_status(
            appointment_id,
            AppointmentStatus.CONFIRMED,
            lambda _success, _error: None,
        )

    @staticmethod
    def _appointment_id(appointment: Appointment) -> int:
        if appointment.appointment_id is None:
            raise AssertionError("The test appointment was not persisted")
        return appointment.appointment_id

    @staticmethod
    def _queue_entry_id(entry: QueueEntry) -> int:
        if entry.entry_id is None:
            raise AssertionError("The test queue entry was not persisted")
        return entry.entry_id


if __name__ == "__main__":
    unittest.main()
