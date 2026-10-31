from PyQt6.QtWidgets import QTabWidget, QVBoxLayout

from models import Admin
from services.appointment_manager import AppointmentManager
from services.pricing_calculator import PricingCalculator
from services.queue_manager import QueueManager
from services.loyalty_manager import LoyaltyManager
from services.loyalty_web_server import LoyaltyWebServer
from services.studio_settings_manager import StudioSettingsManager
from ui.appointment_panel import AppointmentPanel
from ui.base_page import BasePage
from ui.queue_panel import QueuePanel


class AppointmentCalendarScreen(BasePage):
    def __init__(
        self,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        queue_manager: QueueManager,
        role: Admin,
        parent=None,
        studio_settings_manager: StudioSettingsManager | None = None,
        loyalty_manager: LoyaltyManager | None = None,
        loyalty_web_server: LoyaltyWebServer | None = None,
    ) -> None:
        self._role = role
        self._appointment_panel = AppointmentPanel(
            appointment_manager,
            pricing_calculator,
            role,
            studio_settings_manager=studio_settings_manager,
            loyalty_manager=loyalty_manager,
            loyalty_web_server=loyalty_web_server,
        )
        self._queue_panel = QueuePanel(queue_manager)
        super().__init__(
            {
                "appointment_manager": appointment_manager,
                "pricing_calculator": pricing_calculator,
                "queue_manager": queue_manager,
            },
            parent,
        )

    @property
    def appointment_panel(self) -> AppointmentPanel:
        return self._appointment_panel

    @property
    def queue_panel(self) -> QueuePanel:
        return self._queue_panel

    def build_ui(self) -> None:
        # Composition: Admin embeds the appointment panel and reusable queue panel.
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._appointment_panel, "Appointments")
        self._tabs.addTab(self._queue_panel, "Queue")
        layout.addWidget(self._tabs)

    def refresh(self) -> None:
        self._appointment_panel.refresh()
        self._queue_panel.refresh()
