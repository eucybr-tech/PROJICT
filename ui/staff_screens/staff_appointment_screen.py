from PyQt6.QtWidgets import QVBoxLayout

from models import Staff
from services.appointment_manager import AppointmentManager
from services.pricing_calculator import PricingCalculator
from services.studio_settings_manager import StudioSettingsManager
from ui.appointment_panel import AppointmentPanel
from ui.base_page import BasePage


class StaffAppointmentScreen(BasePage):
    def __init__(
        self,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        role: Staff,
        parent=None,
        studio_settings_manager: StudioSettingsManager | None = None,
    ) -> None:
        self._role = role
        self._appointment_panel = AppointmentPanel(
            appointment_manager,
            pricing_calculator,
            role,
            studio_settings_manager=studio_settings_manager,
        )
        super().__init__(
            {
                "appointment_manager": appointment_manager,
                "pricing_calculator": pricing_calculator,
            },
            parent,
        )

    @property
    def appointment_panel(self) -> AppointmentPanel:
        return self._appointment_panel

    def build_ui(self) -> None:
        # Composition: Staff embeds the same panel, without queue controls.
        layout = QVBoxLayout(self)
        layout.addWidget(self._appointment_panel)

    def refresh(self) -> None:
        self._appointment_panel.refresh()
