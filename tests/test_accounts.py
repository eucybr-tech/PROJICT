import os
import secrets
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow

from database import Database
from models import Appointment, AppointmentStatus, Customer, Service
from services.account_manager import AccountManager, AuthenticationError
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.pricing_calculator import PricingCalculator
from services.report_manager import ReportManager
from services.studio_settings_manager import StudioSettingsManager
from ui.account_dialogs import FirstAdminDialog
from ui.role_chooser import RoleChooser


class AccountAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="account_test_")
        self.path = Path(self.temp.name) / "accounts.sqlite"
        self.database = Database(self.path)
        self.database.initialize_schema()
        self.manager = AccountManager(self.database)
        self.admin_password = secrets.token_urlsafe(16)
        self.admin = self.manager.create_first_admin(
            "owner_" + secrets.token_hex(4),
            "Studio Owner",
            self.admin_password,
            self.admin_password,
        )
        self.staff_password = secrets.token_urlsafe(16)
        self.staff_id = self.manager.create_account(
            self.admin,
            "staff_" + secrets.token_hex(4),
            "Studio Staff",
            "STAFF",
            self.staff_password,
            self.staff_password,
        )
        staff_record = self.database.get_account_auth_by_id(self.staff_id)
        if staff_record is None:
            self.fail("Staff account was not created")
        self.staff_username = str(staff_record["username"])

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_password_is_salted_and_never_stored_as_plain_text(self) -> None:
        raw_password = "PrivateTestPassword_981"
        account_id = self.manager.create_account(
            self.admin,
            "hash_check",
            "Hash Check",
            "STAFF",
            raw_password,
            raw_password,
        )
        second_id = self.manager.create_account(
            self.admin,
            "hash_check_second",
            "Hash Check Second",
            "STAFF",
            raw_password,
            raw_password,
        )
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT password_hash, salt FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        if row is None:
            self.fail("Password storage row was not created")
        self.assertNotEqual(row[0], raw_password)
        self.assertNotIn(raw_password, repr(row))
        self.assertNotEqual(row[1], "")
        second_record = self.database.get_account_auth_by_id(second_id)
        self.assertIsNotNone(second_record)
        self.assertNotEqual(row[1], second_record["salt"])
        self.assertNotIn(
            "password_hash",
            self.manager.list_accounts(self.admin)[0],
        )

    def test_correct_login_and_generic_wrong_credentials_message(self) -> None:
        admin_record = self.database.get_account_auth_by_id(self.admin.account_id)
        if admin_record is None:
            self.fail("Admin account was not created")
        user = self.manager.authenticate(
            str(admin_record["username"]).upper(), self.admin_password, "Admin"
        )
        self.assertEqual(user.get_role_name(), "Admin")
        self.assertEqual(user.name, "Studio Owner")

        with self.assertRaises(AuthenticationError) as wrong_password:
            self.manager.authenticate(
                str(admin_record["username"]), "wrong-password", "Admin"
            )
        with self.assertRaises(AuthenticationError) as wrong_username:
            self.manager.authenticate("nobody_exists", "wrong-password", "Admin")
        self.assertEqual(str(wrong_password.exception), "Incorrect username or password")
        self.assertEqual(
            str(wrong_username.exception), str(wrong_password.exception)
        )

    def test_lockout_starts_after_five_failures(self) -> None:
        for attempt in range(5):
            with self.assertRaises(AuthenticationError) as error:
                self.manager.authenticate(
                    self.staff_username, "incorrect-password", "Staff"
                )
            if attempt == 4:
                self.assertEqual(error.exception.remaining_seconds, 60)
                self.assertIn("60 seconds", str(error.exception))
        with self.assertRaises(AuthenticationError) as locked:
            self.manager.authenticate(
                self.staff_username, self.staff_password, "Staff"
            )
        self.assertGreater(locked.exception.remaining_seconds, 0)

    def test_first_admin_creation_dialog_creates_initial_admin(self) -> None:
        fresh_path = Path(self.temp.name) / "first-run.sqlite"
        database = Database(fresh_path)
        database.initialize_schema()
        manager = AccountManager(database)
        self.assertFalse(manager.has_active_account("ADMIN"))
        try:
            dialog = FirstAdminDialog(manager)
            password = secrets.token_urlsafe(16)
            dialog.username.setText("first_admin")
            dialog.display_name.setText("First Admin")
            dialog.password.setText(password)
            dialog.confirm_password.setText(password)
            dialog.create_account()
            self.assertIsNotNone(dialog.account_user)
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            self.assertTrue(manager.has_active_account("ADMIN"))
            self.assertTrue(manager.authenticate("first_admin", password, "Admin"))
        finally:
            database.close()

    def test_staff_view_access_and_admin_view_rejection(self) -> None:
        user = self.manager.authenticate(
            self.staff_username, self.staff_password, "Staff"
        )
        self.assertEqual(user.get_role_name(), "Staff")
        with self.assertRaises(AuthenticationError) as denied:
            self.manager.authenticate(
                self.staff_username, self.staff_password, "Admin"
            )
        self.assertEqual(str(denied.exception), "Incorrect username or password")
        admin_user = self.manager.authenticate(
            self.admin.username, self.admin_password, "Staff"
        )
        self.assertEqual(admin_user.get_role_name(), "Admin")

    def test_inactive_accounts_cannot_log_in(self) -> None:
        self.manager.set_account_active(self.admin, self.staff_id, False)
        with self.assertRaises(AuthenticationError) as error:
            self.manager.authenticate(
                self.staff_username, self.staff_password, "Staff"
            )
        self.assertEqual(str(error.exception), "Incorrect username or password")

    def test_last_active_admin_cannot_be_deleted_deactivated_or_demoted(self) -> None:
        with self.assertRaisesRegex(ValueError, "last active Admin"):
            self.manager.set_account_active(
                self.admin, self.admin.account_id, False
            )
        with self.assertRaisesRegex(ValueError, "last active Admin"):
            self.manager.update_account(
                self.admin,
                self.admin.account_id,
                self.admin.name,
                "STAFF",
                True,
            )
        with self.assertRaisesRegex(PermissionError, "cannot delete their own"):
            self.manager.delete_account(self.admin, self.admin.account_id)
        with self.assertRaisesRegex(ValueError, "last active Admin"):
            self.database.delete_account(self.admin.account_id)
        self.assertEqual(self.database.count_active_accounts("ADMIN"), 1)

    def test_own_password_change_requires_current_password(self) -> None:
        replacement = secrets.token_urlsafe(16)
        with self.assertRaisesRegex(ValueError, "Current password is incorrect"):
            self.manager.change_own_password(
                self.admin,
                "not-the-current-password",
                replacement,
                replacement,
            )
        self.manager.change_own_password(
            self.admin, self.admin_password, replacement, replacement
        )
        with self.assertRaises(AuthenticationError):
            self.manager.authenticate(
                self.admin.username, self.admin_password, "Admin"
            )
        self.assertTrue(
            self.manager.authenticate(self.admin.username, replacement, "Admin")
        )

    def test_manager_permissions_cover_fees_prizes_settings_and_accounts(self) -> None:
        appointment_manager = AppointmentManager(
            self.database,
            PricingCalculator(),
            Mock(),
            LoyaltyManager(self.database),
        )
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            appointment_manager.update_status(
                999,
                AppointmentStatus.CANCELLED,
                lambda _success, _error: None,
                late_confirmation=True,
                waive_fee=True,
                role=self._account_user_for_staff(),
            )
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            appointment_manager.reschedule(
                999,
                datetime.now() + timedelta(days=1),
                lambda _success, _error: None,
                waive_fee=True,
                role=self._account_user_for_staff(),
            )
        email = "fee-client@example.test"
        self.database.add_client(Customer("Fee Client", email, deposit_paid=True))
        service = self.database.add_service(Service("Fee test service", 100))
        if service.service_id is None:
            self.fail("Fee test service was not persisted")
        now = datetime.now()
        cancellation = self.database.add_appointment(
            Appointment(
                email,
                service.service_id,
                now + timedelta(hours=1),
                status=AppointmentStatus.CONFIRMED,
                total_price=100,
                duration_minutes=60,
            )
        )
        cancellation_result = appointment_manager.update_status(
            cancellation.appointment_id,
            AppointmentStatus.CANCELLED,
            lambda _success, _error: None,
            late_confirmation=True,
            waive_fee=True,
            role=self.admin,
        )
        self.assertEqual(cancellation_result.cancellation_fee, 0)
        reschedule = self.database.add_appointment(
            Appointment(
                email,
                service.service_id,
                now + timedelta(hours=3),
                status=AppointmentStatus.CONFIRMED,
                total_price=100,
                duration_minutes=60,
            )
        )
        rescheduled_result = appointment_manager.reschedule(
            reschedule.appointment_id,
            now + timedelta(days=2),
            lambda _success, _error: None,
            late_confirmation=True,
            waive_fee=True,
            allow_outside_schedule=True,
            role=self.admin,
        )
        self.assertEqual(rescheduled_result.cancellation_fee, 0)

        prizes = _PrizeDatabase()
        loyalty_manager = LoyaltyManager(prizes)
        staff_user = self._account_user_for_staff()
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            loyalty_manager.draw_prize(1, staff_user)
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            loyalty_manager.mark_prize_given(1, staff_user)
        self.assertEqual(
            loyalty_manager.draw_prize(1, self.admin)["status"], "Drawn"
        )
        loyalty_manager.mark_prize_given(1, self.admin)
        self.assertEqual(prizes.last_role, "Admin")

        settings_manager = StudioSettingsManager(self.database)
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            settings_manager.update_settings(0, 30, "test", role=staff_user)
        settings_manager.update_settings(
            12, 35, "Updated by Admin", role=self.admin
        )
        self.assertEqual(
            settings_manager.get_settings().service_area_note, "Updated by Admin"
        )
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            self.manager.list_accounts(staff_user)
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            self.manager.create_account(
                staff_user,
                "unauthorized",
                "Unauthorized",
                "STAFF",
                "LongEnoughPassword",
                "LongEnoughPassword",
            )
        created_id = self.manager.create_account(
            self.admin,
            "created_by_admin",
            "Created by Admin",
            "STAFF",
            "LongEnoughPassword",
            "LongEnoughPassword",
        )
        self.assertTrue(
            any(
                account["id"] == created_id
                for account in self.manager.list_accounts(self.admin)
            )
        )

    def test_staff_report_data_excludes_prices_and_payments(self) -> None:
        email = "report-client@example.test"
        self.database.add_client(Customer("Report Client", email))
        service = self.database.add_service(Service("Report service", 321))
        if service.service_id is None:
            self.fail("Report service was not persisted")
        self.database.add_appointment(
            Appointment(
                email,
                service.service_id,
                datetime.now() + timedelta(hours=2),
                status=AppointmentStatus.CONFIRMED,
                total_price=321,
                amount_paid=100,
            )
        )
        report_manager = ReportManager(self.database)
        staff_rows = report_manager.today_appointments(self._account_user_for_staff())
        self.assertTrue(staff_rows)
        self.assertFalse(
            {
                "total_price",
                "travel_fee",
                "discount",
                "amount_paid",
                "cancellation_fee",
            }
            & staff_rows[0].keys()
        )
        with self.assertRaisesRegex(PermissionError, "Only an Admin"):
            report_manager.pending_payments(self._account_user_for_staff())

    def test_old_database_migrates_without_changing_existing_records(self) -> None:
        legacy_path = Path(self.temp.name) / "legacy.sqlite"
        legacy = Database(legacy_path)
        legacy.initialize_schema()
        email = "legacy-client@example.test"
        legacy.add_client(Customer("Legacy Client", email))
        service = legacy.add_service(Service("Legacy service", 222))
        if service.service_id is None:
            self.fail("Legacy service was not persisted")
        legacy.close()
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute("DROP TABLE accounts")
        finally:
            connection.close()

        migrated = Database(legacy_path)
        migrated.initialize_schema()
        self.assertEqual(migrated.get_client(email).name, "Legacy Client")
        self.assertEqual(migrated.get_service(service.service_id).name, "Legacy service")
        self.assertEqual(migrated.count_active_accounts("ADMIN"), 0)
        migrated.close()

    def test_staff_chooser_without_staff_account_shows_notice(self) -> None:
        self.manager.set_account_active(self.admin, self.staff_id, False)
        from ui.account_dialogs import LoginDialog

        dialog = LoginDialog(self.manager, "Staff")
        dialog.username.setText(self.admin.username)
        dialog.password.setText("incorrect password")
        dialog.login()
        self.assertEqual(
            dialog.error_label.text(),
            "No Staff account yet. Ask the Admin to create one.",
        )
        dialog.close()

    def test_admin_can_choose_staff_without_staff_account_and_return_to_admin(self) -> None:
        self.manager.set_account_active(self.admin, self.staff_id, False)

        class ViewWindow(QMainWindow):
            def __init__(self, account_user):
                super().__init__()
                self.account_user = account_user
                self.logout_callback = None
                self.back_callback = None

            def set_logout_callback(self, callback):
                self.logout_callback = callback

            def set_back_to_admin_callback(self, callback):
                self.back_callback = callback

            def go_back(self):
                self.back_callback()

        admin_user = self.admin

        class LoginStub:
            DialogCode = QDialog.DialogCode

            def __init__(self, _manager, _role, _parent):
                self.account_user = admin_user

            def exec(self):
                return self.DialogCode.Accepted

        windows: dict[str, ViewWindow] = {}

        def make_window(role):
            def factory(account_user):
                windows[role] = ViewWindow(account_user)
                return windows[role]

            return factory

        chooser = RoleChooser(
            {
                "Customer": lambda: QMainWindow(),
                "Staff": make_window("Staff"),
                "Admin": make_window("Admin"),
            },
            self.manager,
        )
        with patch("ui.role_chooser.LoginDialog", LoginStub):
            staff_window = chooser.open_role("Staff")
        self.assertIsNotNone(staff_window)
        self.assertEqual(windows["Staff"].account_user.get_role_name(), "Admin")
        self.assertFalse(self.manager.has_active_account("STAFF"))
        windows["Staff"].go_back()
        self.assertTrue(windows["Admin"].isVisible())
        self.assertFalse(windows["Staff"].isVisible())
        chooser.close()
        for window in windows.values():
            window.close()

    def test_wrong_password_login_dialog_keeps_generic_message(self) -> None:
        from ui.account_dialogs import LoginDialog

        dialog = LoginDialog(self.manager, "Staff")
        dialog.username.setText(self.staff_username)
        dialog.password.setText("not-the-password")
        dialog.login()
        self.assertEqual(
            dialog.error_label.text(), "Incorrect username or password"
        )
        dialog.close()

    def _account_user_for_staff(self):
        record = self.database.get_account_auth_by_id(self.staff_id)
        if record is None:
            self.fail("Staff account was not found")
        from models import AccountUser

        return AccountUser(
            self.staff_id,
            str(record["username"]),
            str(record["display_name"]),
            str(record["role"]),
        )


class _PrizeDatabase:
    def __init__(self) -> None:
        self.last_role = ""

    def draw_loyalty_prize(self, draw_id: int, role: str) -> dict[str, object]:
        self.last_role = role
        return {"draw_id": draw_id, "status": "Drawn"}

    def mark_loyalty_prize_given(self, draw_id: int, role: str) -> None:
        self.last_role = role


if __name__ == "__main__":
    unittest.main()
