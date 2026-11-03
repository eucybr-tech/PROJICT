import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from database import Database
from database.database import StampNotQualifiedError
from models import (
    AccountUser,
    Admin,
    Appointment,
    AppointmentStatus,
    Customer,
    LoyaltySettings,
    Service,
    Staff,
)
from services.loyalty_manager import LoyaltyManager
from services.studio_settings_manager import StudioSettingsManager
from services.loyalty_web_server import LoyaltyWebServer
from ui.admin_screens.studio_settings_screen import StudioSettingsScreen
from ui.customer_screens.loyalty_screen import LoyaltyScreen


class LoyaltyCardPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _create_stamp_fixture(
        path: Path, minimum_spend: int | float = 500
    ) -> tuple[Database, LoyaltyManager, str, int]:
        database = Database(path)
        database.initialize_schema()
        email = "loyalty-client@example.test"
        database.add_client(Customer("Jordan Client", email))
        service = database.add_service(Service("Loyalty service", 530))
        if service.service_id is None:
            raise AssertionError("Loyalty test service was not saved")
        settings = database.get_studio_settings()
        admin_role = Admin("Test Admin", "test-admin@example.test")
        StudioSettingsManager(database).update_settings(
            settings.default_travel_fee,
            settings.travel_buffer_minutes,
            settings.service_area_note,
            minimum_spend_per_appointment=minimum_spend,
            role=admin_role,
        )
        return database, LoyaltyManager(database), email, service.service_id

    @staticmethod
    def _add_visit(
        database: Database,
        email: str,
        service_id: int,
        total_price: int | float,
        *,
        status: AppointmentStatus = AppointmentStatus.COMPLETED,
        travel_fee: int | float = 0,
        appointment_time: datetime | None = None,
    ) -> Appointment:
        return database.add_appointment(
            Appointment(
                email,
                service_id,
                appointment_time or datetime.combine(date.today(), datetime.min.time()),
                status=status,
                total_price=total_price,
                travel_fee=travel_fee,
            )
        )

    def test_phone_card_html_uses_temporary_database_and_hides_client_details(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_card_html_test_") as folder:
            root = Path(folder)
            database = Database(root / "test.sqlite")
            database.initialize_schema()
            client_email = "private-client@example.test"
            client_phone = "CLIENT_PHONE_SECRET"
            client_address = "CLIENT_ADDRESS_SECRET"
            database.add_client(
                Customer(
                    "Avery <script>alert(1)</script> Example",
                    client_email,
                    phone=client_phone,
                    address=client_address,
                )
            )
            card = database.get_or_create_loyalty_card(client_email)
            if card.view_code is None:
                self.fail("Temporary card did not receive a view code")
            server = LoyaltyWebServer(root / "test.sqlite")
            settings = database.get_studio_settings()
            current_month = date.today().strftime("%Y-%m")
            html_paths: list[Path] = []
            try:
                for stamps in (0, 3, 5, 10):
                    database._connection.execute(
                        "DELETE FROM loyalty_monthly_stamps WHERE client_email = ?",
                        (client_email,),
                    )
                    database._connection.execute(
                        "DELETE FROM loyalty_prize_draws WHERE client_email = ?",
                        (client_email,),
                    )
                    for appointment_id in range(1000, 1000 + stamps):
                        database._connection.execute(
                            """
                            INSERT INTO loyalty_monthly_stamps
                                (appointment_id, client_email, card_month, stamped_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                appointment_id,
                                client_email,
                                current_month,
                                datetime.now().isoformat(),
                            ),
                        )
                    if stamps >= 5:
                        for milestone in (5, 10):
                            if stamps >= milestone:
                                database._connection.execute(
                                    """
                                    INSERT INTO loyalty_prize_draws
                                        (client_email, card_month, milestone, status, created_at)
                                    VALUES (?, ?, ?, 'Pending', ?)
                                    """,
                                    (
                                        client_email,
                                        current_month,
                                        milestone,
                                        datetime.now().isoformat(),
                                    ),
                                )
                    card_data = database.get_web_card(card.view_code)
                    self.assertIsNotNone(card_data)
                    if card_data is None:
                        self.fail("Temporary web card could not be loaded")
                    page = server._card_page(*card_data, settings=settings)
                    path = root / f"card_{stamps}_stamps.html"
                    path.write_text(page, encoding="utf-8")
                    html_paths.append(path)
                    self.assertTrue(path.is_file())
                    self.assertIn(f"{stamps} of 10", page)
                    self.assertEqual(
                        "You earned a prize draw!" in page,
                        stamps >= 5,
                    )
                    self.assertNotIn("Terms &amp; Conditions", page)
                    for term in settings.loyalty_terms.splitlines():
                        self.assertNotIn(term, page)
                    self.assertNotIn(client_email, page)
                    self.assertNotIn(client_phone, page)
                    self.assertNotIn(client_address, page)
                    self.assertNotIn(settings.loyalty_phone, page)
                    self.assertIn('content="15"', page)
                    self.assertIn("LOYALTY CARD", page)
                    self.assertIn("Name:</strong> Avery", page)
                    self.assertNotIn("<script>", page)
                    self.assertNotIn("Example", page)
                    self.assertNotIn("CLIENT_", page)
                    self.assertEqual(page.count('class="stamp'), 10)

                previous_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
                database._connection.execute(
                    "DELETE FROM loyalty_monthly_stamps WHERE client_email = ?",
                    (client_email,),
                )
                database._connection.execute(
                    """
                    INSERT INTO loyalty_monthly_stamps
                        (appointment_id, client_email, card_month, stamped_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (2000, client_email, previous_month, datetime.now().isoformat()),
                )
                expired_data = database.get_web_card(card.view_code)
                if expired_data is None:
                    self.fail("Temporary web card could not be loaded")
                expired_page = server._card_page(
                    *expired_data, settings=database.get_studio_settings()
                )
                expired_path = root / "card_expired.html"
                expired_path.write_text(expired_page, encoding="utf-8")
                html_paths.append(expired_path)
                self.assertIn(">Expired</p>", expired_page)
                self.assertIn("expired", expired_page)
                self.assertNotIn("Valid until ", expired_page)
                for path in html_paths:
                    print(path)
            finally:
                database.close()

    def test_additive_settings_defaults_and_customer_terms_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_settings_test_") as folder:
            database = Database(Path(folder) / "settings.sqlite")
            database.initialize_schema()
            try:
                settings_manager = StudioSettingsManager(database)
                settings = settings_manager.get_settings()
                self.assertEqual(settings.loyalty_facebook, "@pearl's signailture")
                self.assertEqual(
                    settings.owner_provider_name,
                    "Nicole Pearl Millari Teodoro",
                )
                self.assertEqual(settings.review_url, "")
                self.assertEqual(settings.loyalty_phone, "09690811806")
                self.assertEqual(settings.minimum_spend_per_appointment, 500)
                self.assertEqual(len(settings.loyalty_terms.splitlines()), 5)

                database.update_loyalty_settings(LoyaltySettings(7))
                screen = LoyaltyScreen(
                    LoyaltyManager(database), settings_manager=settings_manager
                )
                screen.refresh()
                screen.show()
                self.application.processEvents()
                try:
                    self.assertIn("at least P500", screen._step_labels[0].text())
                    self.assertIn("5 and 10 stamps", screen._step_labels[3].text())
                    self.assertIn("Valid until", screen._valid_until_label.text())
                    terms = screen.findChildren(QLabel)
                    term_text = "\n".join(label.text() for label in terms)
                    self.assertIn("Terms & Conditions", term_text)
                    for term in settings.loyalty_terms.splitlines():
                        self.assertIn(term, term_text)
                    self.assertTrue(screen._terms_card.isVisible())
                finally:
                    screen.close()
                    self.application.processEvents()

                admin_screen = StudioSettingsScreen(
                    settings_manager,
                    role=Admin("Test Admin", "test-admin@example.test"),
                )
                admin_screen._loyalty_facebook.setText("@test & <handle>")
                admin_screen._owner_provider_name.setText("Provider Name")
                admin_screen._review_url.setText("https://reviews.example.test/")
                admin_screen._loyalty_phone.setText("09990001122")
                admin_screen._minimum_spend_per_appointment.setValue(625)
                admin_screen._loyalty_terms.setPlainText(
                    "First custom term\nSecond custom term"
                )
                with patch(
                    "ui.admin_screens.studio_settings_screen.QMessageBox.information"
                ):
                    admin_screen.save_settings()
                saved = settings_manager.get_settings()
                self.assertEqual(saved.loyalty_facebook, "@test & <handle>")
                self.assertEqual(saved.owner_provider_name, "Provider Name")
                self.assertEqual(saved.review_url, "https://reviews.example.test/")
                self.assertEqual(saved.loyalty_phone, "09990001122")
                self.assertEqual(saved.minimum_spend_per_appointment, 625)
                self.assertEqual(
                    saved.loyalty_terms,
                    "First custom term\nSecond custom term",
                )
                admin_screen.close()
                admin_screen.deleteLater()
                self.application.processEvents()
            finally:
                database.close()

    def test_existing_studio_settings_row_is_migrated_additively(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_migration_test_") as folder:
            path = Path(folder) / "legacy.sqlite"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE studio_settings (
                    setting_id INTEGER PRIMARY KEY,
                    default_travel_fee REAL NOT NULL DEFAULT 0,
                    travel_buffer_minutes INTEGER NOT NULL DEFAULT 30,
                    service_area_note TEXT NOT NULL DEFAULT 'Existing setting',
                    allowed_areas TEXT NOT NULL DEFAULT '["Pila"]',
                    cleaning_buffer_minutes INTEGER NOT NULL DEFAULT 0,
                    studio_address TEXT NOT NULL DEFAULT '',
                    maps_embed_url TEXT NOT NULL DEFAULT '',
                    map_latitude TEXT NOT NULL DEFAULT '',
                    map_longitude TEXT NOT NULL DEFAULT '',
                    map_image_path TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO studio_settings (setting_id, service_area_note)
                VALUES (1, 'Keep this setting');
                CREATE TABLE migration_sentinel (value TEXT NOT NULL);
                INSERT INTO migration_sentinel VALUES ('preserved');
                """
            )
            connection.close()

            database = Database(path)
            try:
                database.initialize_schema()
                settings = database.get_studio_settings()
                self.assertEqual(settings.service_area_note, "Keep this setting")
                self.assertEqual(settings.loyalty_facebook, "@pearl's signailture")
                self.assertEqual(settings.loyalty_phone, "09690811806")
                self.assertEqual(settings.minimum_spend_per_appointment, 500)
                self.assertEqual(len(settings.loyalty_terms.splitlines()), 5)
                sentinel = database._connection.execute(
                    "SELECT value FROM migration_sentinel"
                ).fetchone()
                self.assertIsNotNone(sentinel)
                self.assertEqual(sentinel["value"], "preserved")
            finally:
                database.close()

    def test_below_minimum_spend_is_role_specific_and_blocks_stamp_qr(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_minimum_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "minimum.sqlite"
            )
            try:
                visit = self._add_visit(database, email, service_id, 350)
                card = manager.get_or_create_card(email)
                with self.assertRaises(StampNotQualifiedError) as admin_error:
                    manager.add_stamp_for_card_code(card.card_code or "", "Admin")
                self.assertEqual(
                    str(admin_error.exception),
                    "This appointment totals P350, below the minimum spend of P500, "
                    "so no stamp is earned.",
                )
                with self.assertRaisesRegex(
                    ValueError, "This appointment does not qualify for a stamp."
                ):
                    manager.add_stamp_for_card_code(card.card_code or "", "Staff")
                with self.assertRaises(StampNotQualifiedError):
                    manager.create_stamp_token(self._appointment_id(visit))
                self.assertEqual(
                    database._connection.execute(
                        "SELECT COUNT(*) FROM loyalty_monthly_stamps"
                    ).fetchone()[0],
                    0,
                )
            finally:
                database.close()

    def test_450_appointment_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_450_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "450.sqlite"
            )
            try:
                self._add_visit(database, email, service_id, 450)
                card = manager.get_or_create_card(email)
                with self.assertRaises(StampNotQualifiedError) as error:
                    manager.add_stamp_for_card_code(card.card_code or "", "Admin")
                self.assertIn("P450", str(error.exception))
            finally:
                database.close()

    def test_completed_530_appointment_stamps_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_530_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "530.sqlite"
            )
            try:
                visit = self._add_visit(database, email, service_id, 530)
                card = manager.get_or_create_card(email)
                token = manager.create_stamp_token(self._appointment_id(visit))
                status, _view_code = database.redeem_stamp_token(token)
                self.assertEqual(status, "success")
                self.assertEqual(database.redeem_stamp_token(token), ("used", None))
                self.assertIsNone(
                    manager.add_stamp_for_card_code(card.card_code or "")
                )
                current_card = manager.get_card(email)
                self.assertIsNotNone(current_card)
                if current_card is None:
                    self.fail("Monthly loyalty card was not found")
                self.assertEqual(current_card.stamps, 1)
                self.assertEqual(
                    database._connection.execute(
                        "SELECT COUNT(*) FROM loyalty_monthly_stamps "
                        "WHERE appointment_id = ?",
                        (self._appointment_id(visit),),
                    ).fetchone()[0],
                    1,
                )
            finally:
                database.close()

    def test_travel_fee_does_not_count_toward_minimum_spend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_travel_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "travel.sqlite"
            )
            try:
                self._add_visit(
                    database,
                    email,
                    service_id,
                    450,
                    travel_fee=100,
                )
                card = manager.get_or_create_card(email)
                with self.assertRaises(StampNotQualifiedError) as error:
                    manager.add_stamp_for_card_code(card.card_code or "", "Admin")
                self.assertEqual(error.exception.total_price, 450)
            finally:
                database.close()

    def test_only_completed_appointments_can_earn_a_stamp(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_status_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "statuses.sqlite"
            )
            try:
                for status in (
                    AppointmentStatus.PENDING,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.CANCELLED,
                    AppointmentStatus.NO_SHOW,
                ):
                    visit = self._add_visit(
                        database, email, service_id, 530, status=status
                    )
                    with self.assertRaisesRegex(
                        ValueError, "only be created for a completed appointment"
                    ):
                        manager.create_stamp_token(self._appointment_id(visit))
                card = manager.get_or_create_card(email)
                self.assertIsNone(
                    manager.add_stamp_for_card_code(card.card_code or "")
                )
                self.assertEqual(
                    database._connection.execute(
                        "SELECT COUNT(*) FROM loyalty_monthly_stamps"
                    ).fetchone()[0],
                    0,
                )
            finally:
                database.close()

    def test_fifth_and_tenth_stamp_create_unique_pending_draws(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_milestone_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "milestones.sqlite"
            )
            try:
                card = manager.get_or_create_card(email)
                for _ in range(10):
                    self._add_visit(database, email, service_id, 530)
                    manager.add_stamp_for_card_code(card.card_code or "")
                draws = manager.get_prize_draws(email)
                self.assertEqual(
                    [(draw["milestone"], draw["status"]) for draw in draws],
                    [(5, "Pending"), (10, "Pending")],
                )
                self.assertIsNone(
                    manager.add_stamp_for_card_code(card.card_code or "")
                )
                self.assertEqual(len(manager.get_prize_draws(email)), 2)
            finally:
                database.close()

    def test_prize_drawing_uses_active_matching_prizes_and_admin_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_prize_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "prizes.sqlite"
            )
            try:
                card = manager.get_or_create_card(email)
                for _ in range(5):
                    self._add_visit(database, email, service_id, 530)
                    manager.add_stamp_for_card_code(card.card_code or "")
                draw = manager.get_prize_draws(email)[0]
                draw_id = int(draw["draw_id"])
                admin_role = Admin("Test Admin", "test-admin@example.test")
                staff_role = Staff("Test Staff", "test-staff@example.test")
                manager.add_prize("Inactive fifth", "5", False, admin_role)
                manager.add_prize("Tenth only", "10", True, admin_role)
                with self.assertRaisesRegex(ValueError, "No active prizes"):
                    manager.draw_prize(draw_id, admin_role)
                manager.add_prize("Active fifth", "5", True, admin_role)
                manager.add_prize("Both milestones", "both", True, admin_role)
                with self.assertRaises(PermissionError):
                    manager.draw_prize(draw_id, staff_role)
                result = manager.draw_prize(draw_id, admin_role)
                self.assertIn(
                    result["prize_name"],
                    {"Active fifth", "Both milestones"},
                )
                self.assertEqual(result["status"], "Drawn")
                view_code = manager.get_card(email).view_code
                phone_card = database.get_web_card(view_code or "")
                self.assertIsNotNone(phone_card)
                if phone_card is None:
                    self.fail("Prize card page data was not found")
                prize_page = LoyaltyWebServer(
                    Path(folder) / "prizes.sqlite"
                )._card_page(*phone_card)
                self.assertIn(str(result["prize_name"]), prize_page)
                manager.mark_prize_given(draw_id, admin_role)
                self.assertEqual(
                    manager.get_prize_draws(email)[0]["status"], "Given"
                )
            finally:
                database.close()

    def test_month_rollover_expires_old_card_and_preserves_stamp_history(self) -> None:
        fixed_today = date(2026, 1, 31)

        class FixedDate(date):
            @classmethod
            def today(cls) -> date:
                return fixed_today

        with tempfile.TemporaryDirectory(prefix="loyalty_rollover_test_") as folder:
            database, manager, email, service_id = self._create_stamp_fixture(
                Path(folder) / "rollover.sqlite"
            )
            try:
                card = manager.get_or_create_card(email)
                old_visit = self._add_visit(
                    database,
                    email,
                    service_id,
                    530,
                    appointment_time=datetime(2026, 1, 31, 12, 0),
                )
                manager.add_stamp_for_card_code(card.card_code or "")
                with (
                    patch("database.database.date", FixedDate),
                    patch("services.loyalty_web_server.date", FixedDate),
                ):
                    january_data = database.get_web_card(card.view_code or "")
                    self.assertIsNotNone(january_data)
                    if january_data is None:
                        self.fail("Monthly phone card was not found")
                    january_page = LoyaltyWebServer(
                        Path(folder) / "rollover.sqlite"
                    )._card_page(*january_data, settings=database.get_studio_settings())
                    self.assertIn("1 of 10", january_page)
                    self.assertIn("Valid until January 31, 2026", january_page)

                    february_data = database.get_web_card(
                        card.view_code or "", date(2026, 2, 1)
                    )
                    self.assertIsNotNone(february_data)
                    if february_data is None:
                        self.fail("Expired phone card was not found")
                    expired_page = LoyaltyWebServer(
                        Path(folder) / "rollover.sqlite"
                    )._card_page(
                        *february_data,
                        settings=database.get_studio_settings(),
                        today=date(2026, 2, 1),
                    )
                    self.assertIn(">Expired</p>", expired_page)
                    self.assertIn("0 of 10", expired_page)

                    february_visit = self._add_visit(
                        database,
                        email,
                        service_id,
                        530,
                        appointment_time=datetime(2026, 2, 1, 12, 0),
                    )
                    manager.add_stamp_for_card_code(card.card_code or "")
                    february_data = database.get_web_card(
                        card.view_code or "", date(2026, 2, 1)
                    )
                    self.assertIsNotNone(february_data)
                    if february_data is None:
                        self.fail("New monthly phone card was not found")
                    self.assertEqual(february_data[1], 1)
                    self.assertFalse(february_data[3])
                self.assertEqual(
                    database._connection.execute(
                        "SELECT COUNT(*) FROM loyalty_monthly_stamps "
                        "WHERE appointment_id IN (?, ?)",
                        (
                            self._appointment_id(old_visit),
                            self._appointment_id(february_visit),
                        ),
                    ).fetchone()[0],
                    2,
                )
            finally:
                database.close()

    def test_older_database_migrates_without_losing_stamp_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loyalty_old_db_test_") as folder:
            path = Path(folder) / "older.sqlite"
            database, manager, email, service_id = self._create_stamp_fixture(path)
            card = manager.get_or_create_card(email)
            visit = self._add_visit(database, email, service_id, 530)
            manager.add_stamp_for_card_code(card.card_code or "")
            appointment_id = self._appointment_id(visit)
            before_history = len(manager.get_stamp_history(email))
            database.close()

            old_connection = sqlite3.connect(path)
            old_connection.execute("DROP TABLE loyalty_prize_draws")
            old_connection.execute("DROP TABLE loyalty_prizes")
            old_connection.execute("DROP TABLE loyalty_monthly_stamps")
            old_connection.execute(
                "ALTER TABLE studio_settings "
                "DROP COLUMN minimum_spend_per_appointment"
            )
            old_connection.commit()
            old_connection.close()

            migrated = Database(path)
            try:
                migrated.initialize_schema()
                self.assertEqual(
                    migrated.get_studio_settings().minimum_spend_per_appointment,
                    500,
                )
                self.assertEqual(
                    migrated._connection.execute(
                        "SELECT COUNT(*) FROM loyalty_monthly_stamps "
                        "WHERE appointment_id = ?",
                        (appointment_id,),
                    ).fetchone()[0],
                    1,
                )
                history = migrated.get_loyalty_stamp_history(email)
                self.assertEqual(len(history), before_history)
            finally:
                migrated.close()

    @staticmethod
    def _appointment_id(appointment: Appointment) -> int:
        if appointment.appointment_id is None:
            raise AssertionError("Loyalty test appointment was not saved")
        return appointment.appointment_id

    def test_customer_staff_and_admin_windows_smoke_offscreen(self) -> None:
        from main import AdminWindow, CustomerWindow, StaffWindow
        from services.appointment_manager import AppointmentManager
        from services.client_manager import ClientManager
        from services.gallery_manager import GalleryManager
        from services.notification_service import NotificationService
        from services.price_extra_manager import PriceExtraManager
        from services.pricing_calculator import PricingCalculator
        from services.queue_manager import QueueManager
        from services.report_manager import ReportManager
        from services.schedule_manager import ScheduleManager
        from services.service_manager import ServiceManager

        with tempfile.TemporaryDirectory(prefix="loyalty_role_smoke_") as folder:
            root = Path(folder)
            database = Database(root / "roles.sqlite")
            database.initialize_schema()
            windows = []
            try:
                loyalty_manager = LoyaltyManager(
                    database, qr_codes_directory=root / "qr"
                )
                from services.account_manager import AccountManager

                account_manager = AccountManager(database)
                admin_user = account_manager.create_first_admin(
                    "test_admin",
                    "Test Admin",
                    "TemporaryTestPass123",
                    "TemporaryTestPass123",
                )
                staff_id = account_manager.create_account(
                    admin_user,
                    "test_staff",
                    "Test Staff",
                    "STAFF",
                    "TemporaryStaffPass123",
                    "TemporaryStaffPass123",
                )
                staff_user = AccountUser(
                    staff_id, "test_staff", "Test Staff", "STAFF"
                )
                settings_manager = StudioSettingsManager(database)
                schedule_manager = ScheduleManager(database)
                report_manager = ReportManager(database)
                gallery_manager = GalleryManager(
                    database, gallery_directory=root / "gallery"
                )
                service_manager = ServiceManager(database)
                price_extra_manager = PriceExtraManager(database)
                client_manager = ClientManager(database)
                pricing_calculator = PricingCalculator()
                appointment_manager = AppointmentManager(
                    database,
                    pricing_calculator,
                    NotificationService(),
                    loyalty_manager,
                    schedule_manager=schedule_manager,
                )
                queue_manager = QueueManager(database, appointment_manager)
                web_server = LoyaltyWebServer(database.database_path)

                admin_staff_window = StaffWindow(
                    client_manager,
                    appointment_manager,
                    pricing_calculator,
                    queue_manager,
                    report_manager,
                    settings_manager,
                    loyalty_manager,
                    account_user=admin_user,
                )
                windows = [
                    CustomerWindow(
                        queue_manager,
                        loyalty_manager,
                        gallery_manager,
                        client_manager,
                        service_manager,
                        appointment_manager,
                        pricing_calculator,
                        schedule_manager,
                        settings_manager,
                    ),
                    StaffWindow(
                        client_manager,
                        appointment_manager,
                        pricing_calculator,
                        queue_manager,
                        report_manager,
                        settings_manager,
                        loyalty_manager,
                        account_user=staff_user,
                    ),
                    admin_staff_window,
                    AdminWindow(
                        service_manager,
                        pricing_calculator,
                        client_manager,
                        appointment_manager,
                        queue_manager,
                        loyalty_manager,
                        gallery_manager,
                        settings_manager,
                        schedule_manager,
                        report_manager,
                        price_extra_manager,
                        web_server,
                        account_user=admin_user,
                        account_manager=account_manager,
                    ),
                ]
                for window in windows:
                    window.show()
                    self.application.processEvents()
                    self.assertTrue(window.isVisible())
                staff_window = windows[1]
                staff_button_labels = {
                    button.text()
                    for button in staff_window.findChildren(QPushButton)
                }
                self.assertNotIn("Back to Admin", staff_button_labels)
                self.assertFalse(
                    any(
                        label.text().startswith("Viewing as Staff")
                        for label in staff_window.findChildren(QLabel)
                    )
                )
                self.assertIn("Log out", staff_button_labels)

                panel = admin_staff_window._appointment_page.appointment_panel
                self.assertNotIn("total_price", panel._table_columns)
                self.assertNotIn("travel_fee", panel._table_columns)
                self.assertNotIn("cancellation_fee", panel._table_columns)
                client_panel = admin_staff_window._customer_management_page.client_panel
                client_headers = [
                    client_panel._client_table.horizontalHeaderItem(index).text()
                    for index in range(client_panel._client_table.columnCount())
                ]
                self.assertNotIn("Deposit", client_headers)
                self.assertTrue(client_panel._mark_deposit_paid_button.isHidden())
                admin_staff_buttons = {
                    button.text()
                    for button in admin_staff_window.findChildren(QPushButton)
                }
                self.assertIn("Back to Admin", admin_staff_buttons)
                self.assertIn("Log out", admin_staff_buttons)
                self.assertIn(
                    "Viewing as Staff (logged in as Test Admin)",
                    {
                        label.text()
                        for label in admin_staff_window.findChildren(QLabel)
                    },
                )
            finally:
                for window in windows:
                    window.close()
                    window.deleteLater()
                self.application.processEvents()
                database.close()


if __name__ == "__main__":
    unittest.main()
