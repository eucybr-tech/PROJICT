import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from database import Database
from models import Customer, LoyaltySettings, StudioSettings
from services.loyalty_manager import LoyaltyManager
from services.studio_settings_manager import StudioSettingsManager
from services.loyalty_web_server import LoyaltyWebServer
from ui.admin_screens.studio_settings_screen import StudioSettingsScreen
from ui.customer_screens.loyalty_screen import LoyaltyScreen


class LoyaltyCardPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

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
            html_paths: list[Path] = []
            try:
                for stamps in (0, 3, 5, 10):
                    database._connection.execute(
                        "UPDATE loyalty_cards SET stamps = ? WHERE client_email = ?",
                        (stamps, client_email),
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
                        "Prize draw earned!" in page,
                        stamps >= 5,
                    )
                    self.assertNotIn("Terms &amp; Conditions", page)
                    for term in settings.loyalty_terms.splitlines():
                        self.assertNotIn(term, page)
                    self.assertNotIn(client_email, page)
                    self.assertNotIn(client_phone, page)
                    self.assertNotIn(client_address, page)
                    self.assertIn(settings.loyalty_phone, page)
                    self.assertIn('content="15"', page)
                    self.assertIn("LOYALTY CARD", page)
                    self.assertIn("Name:</strong> Avery", page)
                    self.assertNotIn("<script>", page)
                    self.assertNotIn("Example", page)
                    self.assertNotIn("CLIENT_", page)
                    self.assertEqual(page.count('class="stamp'), 10)

                expired_settings = StudioSettings(
                    loyalty_valid_until=(date.today() - timedelta(days=1)).isoformat()
                )
                database.update_studio_settings(expired_settings)
                expired_data = database.get_web_card(card.view_code)
                if expired_data is None:
                    self.fail("Temporary web card could not be loaded")
                expired_page = server._card_page(
                    *expired_data, settings=database.get_studio_settings()
                )
                expired_path = root / "card_expired.html"
                expired_path.write_text(expired_page, encoding="utf-8")
                html_paths.append(expired_path)
                self.assertIn("Card expired", expired_page)
                self.assertIn("expired", expired_page)
                self.assertNotIn("Valid until:", expired_page)
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
                self.assertEqual(settings.loyalty_phone, "09690811806")
                self.assertEqual(settings.loyalty_valid_until, "")
                self.assertEqual(len(settings.loyalty_terms.splitlines()), 5)

                database.update_loyalty_settings(LoyaltySettings(7))
                screen = LoyaltyScreen(
                    LoyaltyManager(database), settings_manager=settings_manager
                )
                screen.refresh()
                screen.show()
                self.application.processEvents()
                try:
                    self.assertIn("Collect 7 stamps", screen._step_labels[3].text())
                    terms = screen.findChildren(QLabel)
                    term_text = "\n".join(label.text() for label in terms)
                    self.assertIn("Terms & Conditions", term_text)
                    for term in settings.loyalty_terms.splitlines():
                        self.assertIn(term, term_text)
                    self.assertTrue(screen._terms_card.isVisible())
                finally:
                    screen.close()
                    self.application.processEvents()

                admin_screen = StudioSettingsScreen(settings_manager)
                admin_screen._loyalty_facebook.setText("@test & <handle>")
                admin_screen._loyalty_phone.setText("09990001122")
                admin_screen._loyalty_valid_until.setText("2030-12-31")
                admin_screen._loyalty_terms.setPlainText(
                    "First custom term\nSecond custom term"
                )
                with patch(
                    "ui.admin_screens.studio_settings_screen.QMessageBox.information"
                ):
                    admin_screen.save_settings()
                saved = settings_manager.get_settings()
                self.assertEqual(saved.loyalty_facebook, "@test & <handle>")
                self.assertEqual(saved.loyalty_phone, "09990001122")
                self.assertEqual(saved.loyalty_valid_until, "2030-12-31")
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
                self.assertEqual(settings.loyalty_valid_until, "")
                self.assertEqual(len(settings.loyalty_terms.splitlines()), 5)
                sentinel = database._connection.execute(
                    "SELECT value FROM migration_sentinel"
                ).fetchone()
                self.assertIsNotNone(sentinel)
                self.assertEqual(sentinel["value"], "preserved")
            finally:
                database.close()

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
                    ),
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
                    ),
                ]
                for window in windows:
                    window.show()
                    self.application.processEvents()
                    self.assertTrue(window.isVisible())
            finally:
                for window in windows:
                    window.close()
                    window.deleteLater()
                self.application.processEvents()
                database.close()


if __name__ == "__main__":
    unittest.main()
