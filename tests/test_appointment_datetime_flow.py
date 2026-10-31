import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QDate, QTime, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
)

from database import Database
from models import Admin, Appointment, Customer
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.notification_service import NotificationService
from services.pricing_calculator import PricingCalculator
from ui.appointment_panel import (
    AppointmentPanel,
    EditDurationDialog,
    NewAppointmentDialog,
    RescheduleDialog,
)


class AppointmentDatetimeFlowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.temporary_directory.name) / "appointment-datetime.sqlite"
        )
        self.database.initialize_schema()
        self.client_email = "eucybr@gmail.com"
        self.database.add_client(Customer("Eucy", self.client_email))
        service = next(
            (
                service
                for service in self.database.get_services()
                if service.name == "Smart Pedicure + Nail Reconstruction"
            ),
            None,
        )
        self.assertIsNotNone(service, "The regression service was not seeded")
        if service is None:
            self.fail("The regression service was not seeded")
        if service.service_id is None:
            self.fail("The regression service was not persisted")
        self.service_id = service.service_id
        self.pricing_calculator = PricingCalculator()
        self.appointments = AppointmentManager(
            self.database,
            self.pricing_calculator,
            NotificationService(),
            LoyaltyManager(self.database),
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def test_new_appointment_dialog_creates_datetime_and_persists(self) -> None:
        dialog = NewAppointmentDialog(
            self.appointments,
            self.pricing_calculator,
            date(2026, 10, 30),
            Admin("Regression Admin", "admin@example.test"),
        )
        callback_errors: list[Exception] = []

        def fill_and_save() -> None:
            try:
                dialog._client_email.setCurrentText(self.client_email)
                dialog._service.setCurrentIndex(
                    dialog._service.findText(
                        "Smart Pedicure + Nail Reconstruction"
                    )
                )
                dialog._date.setDate(QDate(2026, 10, 30))
                dialog._time.setTime(QTime(13, 0))
                dialog._duration.setValue(140)
                extra_row = next(
                    row
                    for row in range(dialog._extras_list.count())
                    if dialog._extras_list.item(row).data(
                        Qt.ItemDataRole.UserRole
                    )
                    == "Minimalist"
                )
                dialog._extras_list.item(extra_row).setCheckState(
                    Qt.CheckState.Checked
                )
                save_button = dialog.footer.findChild(
                    QDialogButtonBox
                ).button(QDialogButtonBox.StandardButton.Save)
                QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
            except Exception as error:
                callback_errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, fill_and_save)
        dialog.exec()

        self.assertEqual(callback_errors, [])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        (
            email,
            service_id,
            nail_length,
            add_ons,
            selected_extras,
            appointment_start,
            duration_minutes,
            visit_type,
            service_address,
            travel_fee,
        ) = dialog.get_appointment_values()
        with patch.object(NotificationService, "send_booking_received"):
            self.appointments.create_appointment(
                email,
                service_id,
                nail_length,
                add_ons,
                appointment_start,
                duration_minutes,
                visit_type=visit_type,
                service_address=service_address,
                travel_fee=travel_fee,
                selected_extra_names=selected_extras,
            )
        appointments = self.database.get_appointments()
        self.assertEqual(len(appointments), 1)
        saved = appointments[0]
        self.assertEqual(
            self._as_datetime(saved.appointment_time),
            datetime(2026, 10, 30, 13, 0),
        )
        self.assertEqual(saved.duration_minutes, 140)
        self.assertEqual(saved.total_price, 770)

    def test_reschedule_dialog_returns_and_persists_full_datetime(self) -> None:
        appointment = self._add_appointment(datetime(2026, 10, 30, 13, 0))
        dialog = RescheduleDialog(self._as_datetime(appointment.appointment_time))
        callback_errors: list[Exception] = []

        def fill_and_save() -> None:
            try:
                dialog._date.setDate(QDate(2026, 10, 31))
                dialog._time.setTime(QTime(14, 30))
                save_button = dialog.footer.findChild(
                    QDialogButtonBox
                ).button(QDialogButtonBox.StandardButton.Save)
                QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
            except Exception as error:
                callback_errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, fill_and_save)
        dialog.exec()

        self.assertEqual(callback_errors, [])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        new_start = dialog.get_datetime()
        self.assertEqual(new_start, datetime(2026, 10, 31, 14, 30))
        appointment_id = appointment.appointment_id
        if appointment_id is None:
            self.fail("The reschedule appointment was not persisted")
        self.appointments.reschedule(
            appointment_id,
            new_start,
            lambda _success, _error: None,
            late_confirmation=True,
            allow_outside_schedule=True,
        )
        saved = self.database.get_appointment(appointment_id)
        self.assertIsNotNone(saved)
        if saved is not None:
            self.assertEqual(self._as_datetime(saved.appointment_time), new_start)
            self.assertEqual(saved.duration_minutes, 120)

    def test_edit_duration_dialog_preserves_persisted_datetime(self) -> None:
        start = datetime(2026, 10, 30, 13, 0)
        appointment = self._add_appointment(start)
        appointment_id = appointment.appointment_id
        if appointment_id is None:
            self.fail("The duration appointment was not persisted")

        panel = AppointmentPanel(
            self.appointments,
            self.pricing_calculator,
            Admin("Regression Admin", "admin@example.test"),
        )
        panel._calendar.setSelectedDate(QDate(2026, 10, 30))
        panel.refresh()
        panel._select_appointment(appointment_id)
        opened_dialog: list[EditDurationDialog] = []

        def fill_and_save() -> None:
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, EditDurationDialog)
            if not isinstance(dialog, EditDurationDialog):
                return
            opened_dialog.append(dialog)
            dialog._duration.setValue(140)
            save_button = dialog.footer.findChild(
                QDialogButtonBox
            ).button(QDialogButtonBox.StandardButton.Save)
            QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, fill_and_save)
        panel.edit_duration_selected()

        self.assertEqual(len(opened_dialog), 1)
        self.assertEqual(opened_dialog[0].result(), QDialog.DialogCode.Accepted)
        saved = self.database.get_appointment(appointment_id)
        self.assertIsNotNone(saved)
        if saved is not None:
            self.assertEqual(self._as_datetime(saved.appointment_time), start)
            self.assertEqual(saved.duration_minutes, 140)

    @staticmethod
    def _as_datetime(value: datetime | str) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)

    def _add_appointment(self, start: datetime) -> Appointment:
        return self.database.add_appointment(
            Appointment(
                self.client_email,
                self.service_id,
                start,
                duration_minutes=120,
            )
        )


if __name__ == "__main__":
    unittest.main()
