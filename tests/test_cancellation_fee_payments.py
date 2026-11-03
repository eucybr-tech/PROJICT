import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog

from database import Database
from models import Admin, Appointment, AppointmentStatus, Customer, Service, Staff
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.notification_service import NotificationService
from services.pricing_calculator import PricingCalculator
from services.report_manager import ReportManager
from ui.appointment_panel import AppointmentPanel, PaymentDialog
from ui.admin_screens.report_payments_screen import ReportPaymentsScreen


class CancellationFeePaymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="cancellation_fee_payments_"
        )
        self.database_path = Path(self.temporary_directory.name) / "fees.sqlite"
        self.database = Database(self.database_path)
        self.database.initialize_schema()
        self.email = "fee-client@example.test"
        self.database.add_client(Customer("Fee Client", self.email))
        service = self.database.add_service(Service("Fee service", 600))
        if service.service_id is None:
            self.fail("Fee service was not persisted")
        self.service_id = service.service_id
        self.admin = Admin("Test Admin", "admin@example.test")
        self.staff = Staff("Test Staff", "staff@example.test")
        self.appointment_manager = AppointmentManager(
            self.database,
            PricingCalculator(),
            NotificationService(),
            LoyaltyManager(self.database),
        )
        self.report_manager = ReportManager(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def _create_fee_appointment(
        self,
        fee: float = 450,
        amount_paid: float = 0,
        status: AppointmentStatus = AppointmentStatus.CANCELLED,
    ) -> Appointment:
        return self.database.add_appointment(
            Appointment(
                self.email,
                self.service_id,
                datetime.now(),
                status=status,
                total_price=600,
                cancellation_fee=fee,
                amount_paid=amount_paid,
            )
        )

    def test_unpaid_cancellation_fee_appears_in_admin_pending_payments(self) -> None:
        appointment = self._create_fee_appointment()

        pending = self.report_manager.pending_payments(self.admin)

        self.assertEqual(len(pending["appointments"]), 1)
        row = pending["appointments"][0]
        self.assertEqual(row["appointment_id"], appointment.appointment_id)
        self.assertEqual(row["service_name"], "Cancellation fee")
        self.assertEqual(row["payment_type"], "cancellation_fee")
        self.assertEqual(row["final_price"], 450)
        self.assertEqual(row["balance"], 450)
        self.assertEqual(pending["total_balance"], 450)

    def test_late_reschedule_fee_is_pending_for_confirmed_appointment(self) -> None:
        self._create_fee_appointment(status=AppointmentStatus.CONFIRMED)

        pending = self.report_manager.pending_payments(self.admin)["appointments"]

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["service_name"], "Cancellation fee")

    def test_pending_payments_screen_routes_fee_to_fee_payment_dialog(self) -> None:
        appointment = self._create_fee_appointment()
        panel = AppointmentPanel(
            self.appointment_manager, PricingCalculator(), self.admin
        )
        screen = ReportPaymentsScreen(self.report_manager, panel, self.admin)
        try:
            service_item = screen._payments_table.item(0, 2)
            balance_item = screen._payments_table.item(0, 5)
            appointment_item = screen._payments_table.item(0, 0)
            self.assertIsNotNone(service_item)
            self.assertIsNotNone(balance_item)
            self.assertIsNotNone(appointment_item)
            if (
                service_item is None
                or balance_item is None
                or appointment_item is None
            ):
                self.fail("Pending cancellation fee was not shown in the table")
            self.assertEqual(service_item.text(), "Cancellation fee")
            self.assertEqual(balance_item.text(), "₱ 450.00")
            self.assertEqual(
                appointment_item.data(Qt.ItemDataRole.UserRole + 1),
                "cancellation_fee",
            )
            with patch.object(
                panel, "record_payment_for_appointment", return_value=True
            ) as record_payment:
                screen._record_payment(0, 2)
            record_payment.assert_called_once_with(
                int(appointment.appointment_id),
                "cancellation_fee",
            )
        finally:
            screen.close()
            panel.close()

    def test_cash_and_qr_payments_clear_fee_and_reject_second_payment(self) -> None:
        for payment_method in ("Cash", "QR"):
            with self.subTest(payment_method=payment_method):
                appointment = self._create_fee_appointment()
                panel = AppointmentPanel(
                    self.appointment_manager, PricingCalculator(), self.admin
                )

                def accept_fee_dialog(dialog: PaymentDialog) -> QDialog.DialogCode:
                    method_input = dialog._cancellation_fee_payment_method
                    if not isinstance(method_input, QComboBox):
                        self.fail("Fee payment dialog did not offer payment methods")
                    self.assertEqual(
                        [
                            method_input.itemText(index)
                            for index in range(method_input.count())
                        ],
                        ["Cash", "QR"],
                    )
                    method_input.setCurrentText(payment_method)
                    self.assertEqual(
                        dialog.cancellation_fee_payment_method,
                        payment_method,
                    )
                    return QDialog.DialogCode.Accepted

                try:
                    with patch.object(PaymentDialog, "exec", accept_fee_dialog):
                        self.assertTrue(
                            panel.record_payment_for_appointment(
                                int(appointment.appointment_id),
                                "cancellation_fee",
                            )
                        )
                finally:
                    panel.close()

                payment = self.database._connection.execute(
                    """
                    SELECT amount, payment_method
                    FROM cancellation_fee_payments
                    WHERE appointment_id = ?
                    """,
                    (appointment.appointment_id,),
                ).fetchone()
                self.assertIsNotNone(payment)
                if payment is None:
                    self.fail("Cancellation fee payment was not recorded")
                self.assertEqual(payment["amount"], 450)
                self.assertEqual(payment["payment_method"], payment_method)
                self.assertEqual(
                    self.report_manager.pending_payments(self.admin)["appointments"],
                    [],
                )
                with self.assertRaisesRegex(ValueError, "already been paid"):
                    self.appointment_manager.record_cancellation_fee_payment(
                        int(appointment.appointment_id), payment_method, self.admin
                    )

    def test_waived_fee_is_not_pending(self) -> None:
        self._create_fee_appointment(fee=0)

        self.assertEqual(
            self.report_manager.pending_payments(self.admin)["appointments"], []
        )

    def test_staff_cannot_view_or_record_fee_payment(self) -> None:
        appointment = self._create_fee_appointment()

        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            self.report_manager.pending_payments(self.staff)
        staff_rows = self.report_manager.today_appointments(self.staff)
        self.assertEqual(len(staff_rows), 1)
        self.assertNotIn("cancellation_fee", staff_rows[0])
        self.assertNotIn("amount_paid", staff_rows[0])
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            self.appointment_manager.record_cancellation_fee_payment(
                int(appointment.appointment_id), "Cash", self.staff
            )

        panel = AppointmentPanel(
            self.appointment_manager, PricingCalculator(), self.staff
        )
        try:
            self.assertNotIn("cancellation_fee", panel._table_columns)
            self.assertTrue(panel._record_payment_button.isHidden())
            with patch("ui.appointment_panel.QMessageBox.warning"):
                self.assertFalse(
                    panel.record_payment_for_appointment(
                        int(appointment.appointment_id),
                        "cancellation_fee",
                    )
                )
        finally:
            panel.close()

    def test_reports_keep_fee_income_separate_from_service_revenue(self) -> None:
        appointment = self._create_fee_appointment(amount_paid=75)
        self.appointment_manager.record_cancellation_fee_payment(
            int(appointment.appointment_id), "QR", self.admin
        )
        today = date.today()

        self.assertEqual(self.report_manager.revenue(today, today, self.admin), 75)
        self.assertEqual(
            self.report_manager.status_counts(today, today, self.admin)[
                "cancellation_fee_income"
            ],
            450,
        )
        service_rows = self.report_manager.by_service(today, today, self.admin)
        fee_service = next(
            row for row in service_rows if row["service_name"] == "Fee service"
        )
        self.assertEqual(fee_service["revenue"], 75)

        self.assertEqual(
            self.database._connection.execute(
                "SELECT COUNT(*) FROM loyalty_monthly_stamps"
            ).fetchone()[0],
            0,
        )

    def test_older_database_migrates_fee_payment_table_without_data_loss(self) -> None:
        appointment = self._create_fee_appointment()
        appointment_id = appointment.appointment_id
        self.database._connection.execute("DROP TABLE cancellation_fee_payments")
        self.database.close()

        migrated = Database(self.database_path)
        try:
            migrated.initialize_schema()
            loaded_appointment = migrated.get_appointment(int(appointment_id))
            self.assertIsNotNone(loaded_appointment)
            if loaded_appointment is None:
                self.fail("Existing appointment was lost during migration")
            self.assertEqual(loaded_appointment.cancellation_fee, 450)
            columns = {
                row["name"]
                for row in migrated._connection.execute(
                    "PRAGMA table_info(cancellation_fee_payments)"
                ).fetchall()
            }
            self.assertEqual(
                columns,
                {"appointment_id", "amount", "payment_method", "paid_at"},
            )
            self.assertEqual(
                ReportManager(migrated).pending_payments(self.admin)[
                    "appointments"
                ][0]["service_name"],
                "Cancellation fee",
            )
        finally:
            migrated.close()


if __name__ == "__main__":
    unittest.main()
