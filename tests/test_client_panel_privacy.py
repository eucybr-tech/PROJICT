import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTableWidget

from database import Database
from models import Admin, Appointment, AppointmentStatus, Customer, Service, Staff
from services.client_manager import ClientManager
from ui.client_panel import ClientPanel
from ui.staff_screens.staff_customer_screen import StaffCustomerScreen


class ClientPanelPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="client_panel_privacy_"
        )
        self.database = Database(
            Path(self.temporary_directory.name) / "privacy.sqlite"
        )
        self.database.initialize_schema()
        self.email = "client-panel@example.test"
        self.database.add_client(
            Customer("Panel Client", self.email, deposit_paid=True)
        )
        service = self.database.add_service(Service("Panel Service", 1234))
        if service.service_id is None:
            self.fail("The test service was not persisted")
        self.database.add_appointment(
            Appointment(
                self.email,
                service.service_id,
                datetime(2026, 11, 1, 10, 0),
                status=AppointmentStatus.COMPLETED,
                total_price=1234,
            )
        )
        self.client_manager = ClientManager(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def _select_first_client(self, table: QTableWidget) -> None:
        self.assertEqual(table.rowCount(), 1)
        table.selectRow(0)
        self.application.processEvents()

    def _table_text(self, table: QTableWidget) -> list[str]:
        return [
            item.text()
            for row in range(table.rowCount())
            for column in range(table.columnCount())
            if (item := table.item(row, column)) is not None
        ]

    def test_staff_client_panel_omits_payment_fields_from_widgets(self) -> None:
        screen = StaffCustomerScreen(
            self.client_manager,
            Staff("Panel Staff", "staff@example.test"),
        )
        panel = screen.client_panel
        self._select_first_client(panel._client_table)

        client_headers = [
            panel._client_table.horizontalHeaderItem(index).text()
            for index in range(panel._client_table.columnCount())
        ]
        history_headers = [
            panel._history_table.horizontalHeaderItem(index).text()
            for index in range(panel._history_table.columnCount())
        ]

        self.assertNotIn("Deposit", client_headers)
        self.assertNotIn("Total price", history_headers)
        self.assertEqual(history_headers, ["Date", "Service", "Status"])
        self.assertNotIn("₱", " ".join(self._table_text(panel._client_table)))
        self.assertNotIn("₱", " ".join(self._table_text(panel._history_table)))
        self.assertNotIn("1234", " ".join(self._table_text(panel._client_table)))
        self.assertNotIn("1234", " ".join(self._table_text(panel._history_table)))

        screen.close()

    def test_admin_client_panel_keeps_payment_fields(self) -> None:
        panel = ClientPanel(
            self.client_manager,
            Admin("Panel Admin", "admin@example.test"),
        )
        self._select_first_client(panel._client_table)

        client_headers = [
            panel._client_table.horizontalHeaderItem(index).text()
            for index in range(panel._client_table.columnCount())
        ]
        history_headers = [
            panel._history_table.horizontalHeaderItem(index).text()
            for index in range(panel._history_table.columnCount())
        ]

        self.assertIn("Deposit", client_headers)
        self.assertIn("Total price", history_headers)
        self.assertIn("Paid", " ".join(self._table_text(panel._client_table)))
        self.assertIn("₱ 1,234.00", " ".join(self._table_text(panel._history_table)))
        panel.close()


if __name__ == "__main__":
    unittest.main()
