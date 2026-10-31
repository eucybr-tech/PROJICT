import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox, QPushButton

from models import (
    Admin,
    Appointment,
    Customer,
    GalleryItem,
    PriceExtra,
    Service,
    StudioPolicy,
)
from services.pricing_calculator import PricingCalculator
from ui.admin_screens.loyalty_card_screen import StampReversalDialog
from ui.admin_screens.nail_gallery_screen import GalleryItemDialog
from ui.admin_screens.schedule_screen import BreakDialog, ClosureDialog
from ui.admin_screens.service_pricing_screen import PriceExtraDialog, ServiceDialog
from ui.appointment_panel import (
    AppointmentDetailsDialog,
    EditDurationDialog,
    HomeServiceMapDialog,
    LatePolicyDialog,
    NewAppointmentDialog,
    PaymentDialog,
    RescheduleDialog,
    StampQrDialog,
    TravelFeeDialog,
)
from ui.client_panel import ClientDialog
from ui.customer_screens.gallery_screen import GalleryDetailDialog
from ui.scrollable_dialog import ScrollableDialog


class ScrollableDialogScreenChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_all_dialog_footers_fit_1366_by_768(self) -> None:
        available = QRect(0, 0, 1366, 768)
        service = Service(
            "Screen test service",
            100,
            service_id=1,
        )
        client = Customer("Screen Test", "screen-test@example.test")
        appointment = Appointment(
            client.email,
            1,
            datetime.now(),
            total_price=100,
            travel_fee=20,
            appointment_id=1,
        )

        class AppointmentManagerStub:
            studio_policy = StudioPolicy()
            schedule_manager = None

            def get_clients(self):
                return [client]

            def get_services(self):
                return [service]

            def get_active_price_extras(self):
                return []

        dialog_factories = (
            lambda: HomeServiceMapDialog(appointment, None, True),
            lambda: NewAppointmentDialog(
                AppointmentManagerStub(),
                PricingCalculator(),
                datetime.now().date(),
                Admin("Screen Test", "admin@example.test"),
            ),
            lambda: RescheduleDialog(datetime.now()),
            lambda: EditDurationDialog(120, StudioPolicy()),
            lambda: LatePolicyDialog("Cancellation", 50, True),
            lambda: PaymentDialog(appointment),
            lambda: TravelFeeDialog(20),
            lambda: ClientDialog(),
            lambda: ServiceDialog(),
            lambda: PriceExtraDialog(PriceExtra("Screen test", 20)),
            lambda: BreakDialog(),
            lambda: ClosureDialog(),
            lambda: GalleryItemDialog(),
            lambda: GalleryDetailDialog(
                GalleryItem("Screen test", "missing.jpg"),
                Path("missing.jpg"),
            ),
            lambda: AppointmentDetailsDialog("Appointment details " * 80),
            lambda: StampQrDialog(),
            lambda: StampReversalDialog(),
        )

        for create_dialog in dialog_factories:
            with patch.object(
                ScrollableDialog,
                "_available_geometry",
                return_value=available,
            ):
                dialog = create_dialog()
            with self.subTest(dialog=type(dialog).__name__):
                dialog.show()
                self.application.processEvents()
                try:
                    self.assertIsNotNone(dialog.footer)
                    self.assertLessEqual(dialog.height(), available.height() - 80)
                    self.assertTrue(dialog.scroll_area.widgetResizable())
                    self.assertFalse(
                        dialog.scroll_area.widget().isAncestorOf(dialog.footer)
                    )
                    self.assertEqual(
                        dialog.scroll_area.horizontalScrollBarPolicy(),
                        Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                    )
                    footer_rect = QRect(
                        dialog.footer.mapToGlobal(dialog.footer.rect().topLeft()),
                        dialog.footer.size(),
                    )
                    self.assertTrue(available.contains(footer_rect))
                    if isinstance(dialog, RescheduleDialog):
                        self.assertLess(dialog.height(), available.height() - 80)
                    if isinstance(dialog, NewAppointmentDialog):
                        self.assertTrue(dialog.footer.isAncestorOf(dialog._total))
                    buttons = [
                        button
                        for button in dialog.footer.findChildren(QPushButton)
                        if button.isVisible()
                    ]
                    self.assertTrue(buttons)
                    for button in buttons:
                        button_rect = QRect(
                            button.mapToGlobal(button.rect().topLeft()),
                            button.size(),
                        )
                        self.assertTrue(available.contains(button_rect))
                finally:
                    dialog.close()
                    self.application.processEvents()

    def test_wheel_over_unfocused_combo_and_spin_does_not_change_values(self) -> None:
        services = [
            Service("First service", 100, service_id=1),
            Service("Second service", 200, service_id=2),
        ]

        class AppointmentManagerStub:
            studio_policy = StudioPolicy()

            def get_clients(self):
                return []

            def get_services(self):
                return services

            def get_active_price_extras(self):
                return []

        dialog = NewAppointmentDialog(
            AppointmentManagerStub(),
            PricingCalculator(),
            datetime.now().date(),
            Admin("Screen Test", "admin@example.test"),
        )
        dialog.show()
        self.application.processEvents()
        try:
            dialog._date.setFocus()
            self.application.processEvents()
            initial_service = dialog._service.currentIndex()
            initial_duration = dialog._duration.value()
            wheel = QWheelEvent(
                QPointF(1, 1),
                QPointF(1, 1),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            self.application.sendEvent(dialog._service, wheel)
            self.assertEqual(dialog._service.currentIndex(), initial_service)

            wheel = QWheelEvent(
                QPointF(1, 1),
                QPointF(1, 1),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            self.application.sendEvent(dialog._duration, wheel)
            self.assertEqual(dialog._duration.value(), initial_duration)
        finally:
            dialog.close()
            self.application.processEvents()

    def test_wheel_guard_applies_to_dynamically_added_spin_boxes(self) -> None:
        dialog = ServiceDialog()
        dialog._has_length_options.setChecked(True)
        row = dialog._length_editor._table.rowCount()
        dialog._length_editor.add_option("New option", 10)
        price_input = dialog._length_editor._table.cellWidget(row, 1)
        self.assertIsInstance(price_input, QDoubleSpinBox)
        if not isinstance(price_input, QDoubleSpinBox):
            self.fail("The new price input was not created")
        dialog.show()
        self.application.processEvents()
        try:
            price_input.clearFocus()
            initial_price = price_input.value()
            wheel = QWheelEvent(
                QPointF(1, 1),
                QPointF(1, 1),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            self.application.sendEvent(price_input, wheel)
            self.assertEqual(price_input.value(), initial_price)
        finally:
            dialog.close()
            self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
