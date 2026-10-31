from urllib.parse import quote

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.schedule_manager import ScheduleManager
from services.studio_settings_manager import StudioSettingsManager
from ui.base_page import BasePage
from ui.studio_map_widget import StudioMapWidget


class StudioInfo:
    """Customer-facing studio information and booking policies."""

    _STUDIO_NAME = "Pearl's SigNAILture"
    _TECHNICIAN_NAME = "Pearl"
    _TECHNICIAN_TITLE = "Nail Technician"
    _WELCOME_TEXT = (
        "Hello, Gorgeous! Welcome to my booking page. Please take a quick peek at "
        "the policies on my highlights, then feel free to book your preferred "
        "schedule. Can't wait to see you!"
    )
    _BOOKING_POLICY = (
        "New clients pay a one-time lifetime deposit of 100 pesos. It is not "
        "deductible from the service price and is kept on file for future bookings."
    )
    _CANCELLATION_POLICY = (
        "Cancelling or rescheduling needs at least 48 hours notice, and a "
        "cancellation costs 50 pesos."
    )
    _ADDITIONAL_INFORMATION = (
        "Please arrive 5 to 10 minutes early. There is a 3-day warranty on lifting "
        "not caused by force."
    )

    def __init__(
        self, settings_manager: StudioSettingsManager | None = None
    ) -> None:
        self._settings_manager = settings_manager
        self._customer_address = ""

    @property
    def settings_manager(self) -> StudioSettingsManager | None:
        return self._settings_manager

    @property
    def studio_name(self) -> str:
        return self._STUDIO_NAME

    @property
    def technician_name(self) -> str:
        return self._TECHNICIAN_NAME

    @property
    def technician_title(self) -> str:
        return self._TECHNICIAN_TITLE

    @property
    def welcome_text(self) -> str:
        return self._WELCOME_TEXT

    @property
    def booking_policy(self) -> str:
        return self._BOOKING_POLICY

    @property
    def cancellation_policy(self) -> str:
        return self._CANCELLATION_POLICY

    @property
    def additional_information(self) -> str:
        return self._ADDITIONAL_INFORMATION

    @property
    def address(self) -> str:
        return (
            self._settings_manager.get_settings().studio_address
            if self._settings_manager is not None
            else ""
        )

    @property
    def customer_address(self) -> str:
        return self._customer_address

    def set_customer_address(self, address: str) -> None:
        if not isinstance(address, str):
            raise TypeError("address must be a string")
        self._customer_address = address.strip()


class MapScreen(BasePage):
    """Customer map and address search screen."""

    def __init__(
        self,
        studio_info: StudioInfo | None = None,
        schedule_manager: ScheduleManager | None = None,
        settings_manager: StudioSettingsManager | None = None,
        parent=None,
    ) -> None:
        self._studio_info = studio_info or StudioInfo(settings_manager)
        self._schedule_manager = schedule_manager
        self._settings_manager = settings_manager or self._studio_info.settings_manager
        super().__init__(
            {
                "studio_info": self._studio_info,
                "schedule_manager": schedule_manager,
                "studio_settings_manager": self._settings_manager,
            },
            parent,
        )
        self.refresh()

    @property
    def studio_info(self) -> StudioInfo:
        return self._studio_info

    @property
    def schedule_manager(self) -> ScheduleManager | None:
        return self._schedule_manager

    @property
    def map_widget(self) -> StudioMapWidget:
        return self._map_widget

    def build_ui(self) -> None:
        self._map_widget = StudioMapWidget(
            self._settings_manager, self._schedule_manager
        )
        self._customer_address_input = QLineEdit()
        self._customer_address_input.setPlaceholderText("Enter your address")
        self._customer_address_input.setText(self._studio_info.customer_address)
        self._customer_address_input.textChanged.connect(
            self._studio_info.set_customer_address
        )
        self._customer_address_button = QPushButton(
            "Open your address in Google Maps"
        )
        self._customer_address_button.clicked.connect(self._open_customer_address)
        self._open_studio_map_button = QPushButton("Open in Google Maps")
        self._open_studio_map_button.clicked.connect(self._open_studio_map)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self._map_widget, 1)
        layout.addWidget(self._open_studio_map_button)
        layout.addWidget(QLabel("Your address"))
        layout.addWidget(self._customer_address_input)
        layout.addWidget(self._customer_address_button)

    def refresh(self) -> None:
        self._map_widget.refresh()
        if self._customer_address_input.text() != self._studio_info.customer_address:
            self._customer_address_input.setText(self._studio_info.customer_address)
        address = self._map_widget.studio_address
        self._open_studio_map_button.setEnabled(bool(address))

    def _open_studio_map(self) -> None:
        address = self._map_widget.studio_address
        if not address:
            QMessageBox.information(
                self, "Address unavailable", "The studio address has not been set."
            )
            return
        url = QUrl(
            "https://www.google.com/maps/search/?api=1&query="
            + quote(address, safe="")
        )
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Could not open map",
                "The studio address could not be opened in your browser.",
            )

    def _open_customer_address(self) -> None:
        address = self._customer_address_input.text().strip()
        if not address:
            QMessageBox.information(
                self, "Address required", "Enter an address to open it in Google Maps."
            )
            return
        url = QUrl(
            "https://www.google.com/maps/search/?api=1&query="
            + quote(address, safe="")
        )
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Could not open map",
                "The address could not be opened in your browser.",
            )
