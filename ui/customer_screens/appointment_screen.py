import re
import sqlite3
import calendar as month_calendar
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import QDate, QSize, Qt, pyqtSignal
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices, QColor, QTextCharFormat, QMouseEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QCalendarWidget,
)

from models import Customer, PriceExtra, Service, VisitType, format_duration
from services.appointment_manager import AppointmentManager
from services.client_manager import ClientManager
from services.pricing_calculator import PricingCalculator
from services.service_manager import ServiceManager
from ui.base_page import BasePage
from ui.navigation_icons import navigation_icon
from ui.branding import brand_circular_pixmap, circular_photo_pixmap
from ui.customer_screens.map_screen import StudioInfo


class ServiceRowFrame(QFrame):
    """Clickable service row; child labels stay transparent to row clicks."""

    selected = pyqtSignal()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
        super().mousePressEvent(a0)


class CustomerAppointmentScreen(BasePage):
    """Four-step customer appointment request flow."""

    _EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    _PHONE_PATTERN = re.compile(r"^(?:9\d{9}|09\d{9})$")

    # Inheritance and dependency injection: the page receives logic services, never SQL access.
    def __init__(
        self,
        client_manager: ClientManager,
        service_manager: ServiceManager,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        studio_info: StudioInfo | None = None,
        parent=None,
    ) -> None:
        self._client_manager = client_manager
        self._service_manager = service_manager
        self._appointment_manager = appointment_manager
        self._pricing_calculator = pricing_calculator
        self._studio_info = studio_info or StudioInfo()
        self._service_items: list[Service] = []
        self._price_extras: list[PriceExtra] = []
        self._selected_service_id: int | None = None
        self._selected_length = ""
        self._selected_add_ons: set[str] = set()
        self._selected_extras: set[str] = set()
        self._selected_slot: datetime | None = None
        self._visit_type = VisitType.STUDIO
        self._travel_fee = 0.0
        self._last_home_address = ""
        self._slot_buttons: list[QPushButton] = []
        self._welcome_dismissed = False
        self._confirmation_summary = ""
        super().__init__(
            {
                "client_manager": client_manager,
                "service_manager": service_manager,
                "appointment_manager": appointment_manager,
                "pricing_calculator": pricing_calculator,
                "studio_info": self._studio_info,
            },
            parent,
        )
        self.refresh()

    @property
    def client_manager(self) -> ClientManager:
        return self._client_manager

    @property
    def service_manager(self) -> ServiceManager:
        return self._service_manager

    @property
    def appointment_manager(self) -> AppointmentManager:
        return self._appointment_manager

    @property
    def pricing_calculator(self) -> PricingCalculator:
        return self._pricing_calculator

    @property
    def studio_info(self) -> StudioInfo:
        return self._studio_info

    def build_ui(self) -> None:
        self._step_stack = QStackedWidget()
        self._step_stack.addWidget(self._build_services_step())
        self._step_stack.addWidget(self._build_schedule_step())
        self._step_stack.addWidget(self._build_details_step())
        self._step_stack.addWidget(self._build_confirmation_step())

        self._total_label = QLabel("₱0.00")
        self._total_label.setStyleSheet(
            "font-size: 19px; font-weight: 700; color: #765f43;"
        )
        self._footer_description = QLabel("Choose a service")
        self._footer_description.setWordWrap(True)
        self._footer_button = QPushButton("Continue")
        self._footer_button.setProperty("variant", "primary")
        self._footer_button.clicked.connect(self._advance_step)
        self._footer = QFrame()
        self._footer.setStyleSheet(
            "QFrame { background: #fffaf3; border-top: 1px solid #eadfce; }"
        )
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_text = QVBoxLayout()
        self._footer_title = QLabel("Total to pay")
        footer_text.addWidget(self._footer_title)
        footer_text.addWidget(self._total_label)
        footer_text.addWidget(self._footer_description)
        footer_layout.addLayout(footer_text, 1)
        footer_layout.addWidget(self._footer_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._step_stack, 1)
        layout.addWidget(self._footer)
        self._show_step(0)

    def _build_services_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_header())

        self._welcome_card = QFrame()
        self._welcome_card.setStyleSheet(
            "QFrame { background: #fffaf3; border: 1px solid #eadfce; "
            "border-radius: 12px; }"
        )
        welcome_layout = QVBoxLayout(self._welcome_card)
        welcome_text = QLabel(self._studio_info.welcome_text)
        welcome_text.setWordWrap(True)
        welcome_text.setStyleSheet("border: none;")
        okay_button = QPushButton("Okay")
        okay_button.setProperty("variant", "primary")
        okay_button.clicked.connect(self._dismiss_welcome)
        welcome_layout.addWidget(welcome_text)
        welcome_layout.addWidget(
            okay_button, alignment=Qt.AlignmentFlag.AlignRight)

        self._service_list_widget = QWidget()
        self._service_list_layout = QVBoxLayout(self._service_list_widget)
        self._service_list_layout.setContentsMargins(0, 0, 0, 0)
        self._service_list_layout.setSpacing(7)
        self._services_scroll = QScrollArea()
        self._services_scroll.setWidgetResizable(True)
        self._services_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._services_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._services_scroll.setWidget(self._service_list_widget)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 4, 12, 8)
        body_layout.addWidget(self._welcome_card)
        body_layout.addWidget(QLabel("Services"))
        body_layout.addWidget(self._services_scroll, 1)
        layout.addWidget(body, 1)
        return page

    def _build_schedule_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_header(back=True))

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 0, 12, 4)
        schedule_title = QLabel("Choose a date and time")
        schedule_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._calendar = QCalendarWidget()
        self._calendar.setFirstDayOfWeek(Qt.DayOfWeek.Sunday)
        self._calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self._calendar.setGridVisible(True)
        self._calendar.setMaximumHeight(270)
        self._calendar.selectionChanged.connect(self._refresh_slots)
        self._calendar.currentPageChanged.connect(
            self._format_schedule_calendar)
        self._selected_date_label = QLabel()
        self._selected_date_label.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #765f43;"
        )
        self._slot_container = QWidget()
        self._slots_grid = QGridLayout(self._slot_container)
        self._slots_grid.setContentsMargins(0, 0, 0, 0)
        self._slots_grid.setSpacing(7)
        self._slots_scroll = QScrollArea()
        self._slots_scroll.setWidgetResizable(True)
        self._slots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._slots_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._slots_scroll.setWidget(self._slot_container)
        body_layout.addWidget(schedule_title)
        body_layout.addWidget(self._calendar)
        body_layout.addWidget(self._selected_date_label)
        body_layout.addWidget(self._slots_scroll, 1)
        layout.addWidget(body, 1)
        return page

    def _build_details_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_header(back=True))

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 2, 14, 12)
        form_layout.setSpacing(6)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Full name")
        self._phone_input = QLineEdit()
        self._phone_input.setPlaceholderText("9XXXXXXXXX")
        self._phone_prefix = QLabel("+63")
        phone_row = QHBoxLayout()
        phone_row.addWidget(self._phone_prefix)
        phone_row.addWidget(self._phone_input, 1)
        phone_widget = QWidget()
        phone_widget.setLayout(phone_row)
        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText("name@example.com")
        self._comments_input = QTextEdit()
        self._comments_input.setPlaceholderText("Comments (optional)")
        self._comments_input.setMaximumHeight(58)
        self._allergies_input = QLineEdit()
        self._allergies_input.setPlaceholderText(
            "Any allergies? (enter None if none)")
        self._address_label = QLabel(
            "Full address (house no., street, barangay) *"
        )
        self._street_address_input = QLineEdit()
        self._street_address_input.setPlaceholderText(
            "123 Rizal St., Brgy. Santa Clara Sur"
        )
        self._town_input = QLineEdit()
        self._town_input.setPlaceholderText("Town or municipality")
        self._landmark_input = QLineEdit()
        self._landmark_input.setPlaceholderText("Landmark (optional)")
        self._address_fields = QWidget()
        address_layout = QVBoxLayout(self._address_fields)
        address_layout.setContentsMargins(0, 0, 0, 0)
        address_layout.addWidget(
            QLabel("Full address (house no., street, barangay) *")
        )
        address_layout.addWidget(self._street_address_input)
        address_layout.addWidget(QLabel("Town or municipality *"))
        address_layout.addWidget(self._town_input)
        address_layout.addWidget(QLabel("Landmark (optional)"))
        address_layout.addWidget(self._landmark_input)
        self._address_label.hide()
        self._address_fields.hide()
        details_title = QLabel("Your details")
        details_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        form_layout.addWidget(details_title)
        form_layout.addWidget(QLabel("Full Name *"))
        form_layout.addWidget(self._name_input)
        form_layout.addWidget(QLabel("Phone *"))
        form_layout.addWidget(phone_widget)
        form_layout.addWidget(QLabel("Email *"))
        form_layout.addWidget(self._email_input)
        form_layout.addWidget(QLabel("Comments"))
        form_layout.addWidget(self._comments_input)
        form_layout.addWidget(QLabel("Any allergies? *"))
        form_layout.addWidget(self._allergies_input)
        form_layout.addWidget(self._address_label)
        form_layout.addWidget(self._address_fields)

        for heading, text in (
            ("Booking policy", self._studio_info.booking_policy),
            ("Cancellation policy", self._studio_info.cancellation_policy),
            ("Additional information", self._studio_info.additional_information),
        ):
            policy_card = QFrame()
            policy_card.setStyleSheet(
                "QFrame { background: #fffaf3; border: 1px solid #eadfce; "
                "border-radius: 9px; }"
            )
            policy_layout = QVBoxLayout(policy_card)
            policy_layout.setContentsMargins(9, 5, 9, 5)
            policy_title = QLabel(heading)
            policy_title.setStyleSheet("font-weight: 700; border: none;")
            policy_text = QLabel(text)
            policy_text.setWordWrap(True)
            policy_text.setStyleSheet("border: none;")
            policy_layout.addWidget(policy_title)
            policy_layout.addWidget(policy_text)
            form_layout.addWidget(policy_card)
        self._policy_agreement = QCheckBox(
            "I have read and agree to the booking policies."
        )
        form_layout.addWidget(self._policy_agreement)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(form)
        layout.addWidget(scroll, 1)
        return page

    def _build_confirmation_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_header(back=True))
        layout.addStretch()
        title = QLabel("Request sent! The salon will confirm by email.")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #765f43; font-size: 21px; font-weight: 700; padding: 16px;"
        )
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(self._summary_label)
        self._open_confirmation_address = QPushButton(
            "Open address in Google Maps"
        )
        self._open_confirmation_address.clicked.connect(
            self._open_confirmation_address_in_maps
        )
        self._open_confirmation_address.hide()
        layout.addWidget(
            self._open_confirmation_address,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        another_button = QPushButton("Book another")
        another_button.setProperty("variant", "primary")
        another_button.clicked.connect(self._start_new_request)
        layout.addWidget(
            another_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        return page

    def _build_header(self, back: bool = False) -> QWidget:
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(12, 6, 12, 4)
        top = QHBoxLayout()
        if back:
            back_button = QToolButton()
            back_button.setText("‹")
            back_button.setStyleSheet("font-size: 26px; border: none;")
            back_button.clicked.connect(lambda: self._show_step(
                self._step_stack.currentIndex() - 1))
            top.addWidget(back_button)
        logo = self._brand_image("logo.png", "P")
        top.addWidget(logo)
        name = QLabel(self._studio_info.studio_name)
        name.setWordWrap(True)
        name.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #765f43;")
        top.addWidget(name, 1)
        layout.addLayout(top)

        tech_card = QFrame()
        tech_card.setStyleSheet(
            "QFrame { background: #fffaf3; border: 1px solid #eadfce; "
            "border-radius: 11px; }"
        )
        tech_layout = QHBoxLayout(tech_card)
        tech_layout.setContentsMargins(8, 5, 8, 5)
        photo = self._brand_image("technician.png", "♡")
        tech_layout.addWidget(photo)
        tech_name = QLabel(
            f"{self._studio_info.technician_name}\n{self._studio_info.technician_title}"
        )
        tech_name.setStyleSheet("font-weight: 600; border: none;")
        tech_layout.addWidget(tech_name, 1)
        layout.addWidget(tech_card)
        return header

    def _brand_image(self, filename: str, placeholder: str) -> QLabel:
        image = QLabel()
        image.setFixedSize(42, 42)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = Path(__file__).resolve(
        ).parents[2] / "assets" / "branding" / filename
        pixmap = (
            brand_circular_pixmap(42)
            if filename == "logo.png"
            else circular_photo_pixmap(path, 42)
        )
        if not pixmap.isNull():
            image.setPixmap(
                pixmap.scaled(
                    42,
                    42,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            image.setText(placeholder)
            image.setStyleSheet(
                "background: #eadfce; color: #765f43; border-radius: 21px; "
                "font-size: 18px; font-weight: 700;"
            )
        return image

    def refresh(self) -> None:
        try:
            self._service_items = self._service_manager.get_services()
            self._price_extras = (
                self._appointment_manager.get_active_price_extras()
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not load services", str(error))
            return
        active_extra_names = {extra.name for extra in self._price_extras}
        self._selected_extras.intersection_update(active_extra_names)
        if self._selected_service_id not in {
            service.service_id for service in self._service_items
        }:
            self._selected_service_id = None
            self._selected_length = ""
            self._selected_add_ons.clear()
        self._rebuild_service_list()
        self._update_total()
        if self._step_stack.currentIndex() == 1:
            self._refresh_slots()

    def _rebuild_service_list(self) -> None:
        self._clear_layout(self._service_list_layout)
        if not self._service_items:
            self._service_list_layout.addWidget(
                QLabel("No services are available for booking yet.")
            )
            self._service_list_layout.addStretch()
            return
        selected_service = self._selected_service()
        for service in self._service_items:
            row = ServiceRowFrame()
            row.setStyleSheet(
                "QFrame { background: white; border: 1px solid #eadfce; "
                "border-radius: 10px; }"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 4, 5, 4)
            row_layout.setSpacing(4)
            image = QLabel()
            image.setFixedSize(38, 38)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setPixmap(navigation_icon("services").pixmap(QSize(20, 20)))
            image.setStyleSheet(
                "background: #F3F4F6; border-radius: 8px;"
            )
            info_widget = QWidget()
            info_widget.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            info_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            info = QVBoxLayout(info_widget)
            info.setContentsMargins(0, 0, 0, 0)
            info.setSpacing(1)
            name_label = QLabel(service.name)
            name_label.setWordWrap(True)
            name_label.setStyleSheet(
                "font-weight: 600; color: #5E3A56; border: none;"
            )
            details_line = QLabel(self._service_description(service))
            details_line.setWordWrap(True)
            details_line.setStyleSheet(
                "font-size: 11px; color: #374151; border: none;"
            )
            info.addWidget(name_label)
            info.addWidget(details_line)
            details = QPushButton("Details")
            details.setFixedWidth(72)
            details.setProperty("variant", "secondary")
            details.clicked.connect(
                lambda _checked=False, item=service: self._show_service_details(
                    item)
            )
            selected = service.service_id == self._selected_service_id
            selection_mark = QToolButton()
            selection_mark.setText("✓" if selected else "+")
            selection_mark.setFixedSize(34, 34)
            selection_mark.setProperty("serviceSelected", selected)
            selection_mark.clicked.connect(
                lambda _checked=False, item=service: self._select_service(item)
            )
            row_layout.addWidget(image)
            row_layout.addWidget(info_widget, 1)
            row_layout.addWidget(details)
            row_layout.addWidget(selection_mark)
            row.selected.connect(
                lambda item=service: self._select_service(item)
            )
            self._service_list_layout.addWidget(row)
            if selected_service is service:
                self._service_list_layout.addWidget(
                    self._build_customize_panel(service))
        self._service_list_layout.addStretch()

    def _service_description(self, service: Service) -> str:
        duration = format_duration(service.duration_minutes)
        length_prices = list(service.length_prices.values())
        if length_prices:
            minimum = service.base_price + min(length_prices)
            maximum = service.base_price + max(length_prices)
            return (
                f"{duration}  ·  from ₱{minimum:,.0f} "
                f"(₱{minimum:,.0f}–₱{maximum:,.0f})"
            )
        return f"{duration}  ·  from ₱{service.base_price:,.0f}"

    def _show_service_details(self, service: Service) -> None:
        lines = [service.description or "No description provided."]
        if service.length_prices:
            lines.extend(
                ["", "Nail lengths:"]
                + [
                    f"• {name}: +₱{price:,.2f}"
                    for name, price in service.length_prices.items()
                ]
            )
        if service.design_add_on_prices:
            lines.extend(
                ["", "Design add-ons:"]
                + [
                    f"• {name}: +₱{price:,.2f}"
                    for name, price in service.design_add_on_prices.items()
                ]
            )
        QMessageBox.information(self, service.name, "\n".join(lines))

    def _select_service(self, service: Service) -> None:
        if service.service_id != self._selected_service_id:
            self._selected_service_id = service.service_id
            self._selected_length = ""
            self._selected_add_ons.clear()
        self._rebuild_service_list()
        self._update_total()

    def _build_customize_panel(self, service: Service) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: #fffaf3; border: 1px solid #eadfce; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(9, 7, 9, 7)
        title = QLabel("Customize")
        title.setStyleSheet("font-weight: 700; border: none;")
        layout.addWidget(title)
        if service.length_prices:
            layout.addWidget(QLabel("Nail length"))
            length_row = QHBoxLayout()
            group = QButtonGroup(panel)
            group.setExclusive(True)
            for name, price in service.length_prices.items():
                chip = QToolButton()
                chip.setText(name)
                chip.setCheckable(True)
                chip.setChecked(name == self._selected_length)
                chip.setStyleSheet(self._chip_style())
                chip.clicked.connect(
                    lambda _checked=False, length=name: self._select_length(
                        length)
                )
                group.addButton(chip)
                length_row.addWidget(chip)
            layout.addLayout(length_row)
        if service.design_add_on_prices:
            layout.addWidget(QLabel("Design add-ons"))
            add_on_row = QGridLayout()
            for index, (name, price) in enumerate(
                service.design_add_on_prices.items()
            ):
                chip = QToolButton()
                chip.setText(f"{name} +₱{price:,.0f}")
                chip.setCheckable(True)
                chip.setChecked(name in self._selected_add_ons)
                chip.setStyleSheet(self._chip_style())
                chip.clicked.connect(
                    lambda checked, add_on=name: self._toggle_add_on(
                        add_on, checked)
                )
                add_on_row.addWidget(chip, index // 2, index % 2)
            layout.addLayout(add_on_row)
        if self._price_extras:
            layout.addWidget(QLabel("Extras"))
            extras_grid = QGridLayout()
            for index, extra in enumerate(self._price_extras):
                checkbox = QCheckBox(f"{extra.name} (+₱{extra.price:,.2f})")
                checkbox.setChecked(extra.name in self._selected_extras)
                checkbox.toggled.connect(
                    lambda checked, name=extra.name: self._toggle_extra(
                        name, checked
                    )
                )
                extras_grid.addWidget(checkbox, index // 2, index % 2)
            layout.addLayout(extras_grid)
        visit_label = QLabel("Visit type")
        visit_label.setStyleSheet("font-weight: 700; border: none;")
        layout.addWidget(visit_label)
        visit_buttons = QHBoxLayout()
        self._studio_visit_button = QRadioButton("Studio visit")
        self._home_visit_button = QRadioButton("Home service")
        visit_group = QButtonGroup(panel)
        visit_group.addButton(self._studio_visit_button)
        visit_group.addButton(self._home_visit_button)
        self._studio_visit_button.setChecked(
            self._visit_type is VisitType.STUDIO
        )
        self._home_visit_button.setChecked(
            self._visit_type is VisitType.HOME_SERVICE
        )
        self._studio_visit_button.toggled.connect(
            lambda checked: checked and self._set_visit_type(VisitType.STUDIO)
        )
        self._home_visit_button.toggled.connect(
            lambda checked: checked and self._set_visit_type(
                VisitType.HOME_SERVICE)
        )
        visit_buttons.addWidget(self._studio_visit_button)
        visit_buttons.addWidget(self._home_visit_button)
        layout.addLayout(visit_buttons)
        self._home_service_note = QLabel()
        self._home_service_note.setWordWrap(True)
        self._home_service_note.setStyleSheet("border: none; color: #765f43;")
        layout.addWidget(self._home_service_note)
        self._update_home_service_note()
        return panel

    @staticmethod
    def _chip_style() -> str:
        return (
            "QToolButton { background: white; border: 1px solid #d9c9b2; "
            "border-radius: 12px; padding: 5px 8px; }"
            "QToolButton:checked { background: #C8A97E; color: white; "
            "border-color: #C8A97E; }"
        )

    def _select_length(self, length: str) -> None:
        self._selected_length = length
        self._update_total()

    def _toggle_add_on(self, name: str, checked: bool) -> None:
        if checked:
            self._selected_add_ons.add(name)
        else:
            self._selected_add_ons.discard(name)
        self._update_total()

    def _toggle_extra(self, name: str, checked: bool) -> None:
        if checked:
            self._selected_extras.add(name)
        else:
            self._selected_extras.discard(name)
        self._update_total()

    def _selected_extra_prices(self) -> dict[str, float]:
        return {
            extra.name: extra.price
            for extra in self._price_extras
            if extra.name in self._selected_extras
        }

    def _update_total(self) -> None:
        self._footer_title.setText(
            "Estimated total (travel fee not included)"
            if self._visit_type is VisitType.HOME_SERVICE
            else "Total to pay"
        )
        service = self._selected_service()
        if service is None:
            self._total_label.setText("₱0.00")
            self._footer_description.setText("Choose a service")
            if hasattr(self, "_footer_button"):
                self._footer_button.setEnabled(False)
            return
        if service.length_prices and not self._selected_length:
            self._total_label.setText("Choose length")
            self._footer_description.setText(
                f"{service.name} - {format_duration(service.duration_minutes)}"
            )
            if self._step_stack.currentIndex() == 0:
                self._footer_button.setEnabled(False)
            return
        try:
            total = self._pricing_calculator.calculate_price(
                service,
                self._selected_length,
                self._selected_add_ons,
                self._selected_extra_prices(),
            )
        except (TypeError, ValueError):
            total = 0
        self._total_label.setText(f"₱{total:,.2f}")
        self._footer_description.setText(
            f"{service.name} - {format_duration(service.duration_minutes)}"
        )
        if self._step_stack.currentIndex() == 0:
            self._footer_button.setEnabled(
                not service.length_prices or bool(self._selected_length)
            )

    def _set_visit_type(self, visit_type: VisitType) -> None:
        self._visit_type = visit_type
        self._travel_fee = 0.0
        self._address_label.setVisible(visit_type is VisitType.HOME_SERVICE)
        self._address_fields.setVisible(
            visit_type is VisitType.HOME_SERVICE
        )
        self._update_home_service_note()
        self._update_total()
        self._refresh_slots()

    def _update_home_service_note(self) -> None:
        if not hasattr(self, "_home_service_note"):
            return
        if self._visit_type is VisitType.HOME_SERVICE:
            self._home_service_note.setText(
                "Travel fee depends on your location. The salon will confirm it."
            )
            self._home_service_note.show()
        else:
            self._home_service_note.clear()
            self._home_service_note.hide()

    def _advance_step(self) -> None:
        step = self._step_stack.currentIndex()
        if step == 0:
            service = self._selected_service()
            if service is None or (service.length_prices and not self._selected_length):
                return
            self._set_calendar_minimum()
            self._selected_slot = None
            self._step_stack.setCurrentIndex(1)
            self._refresh_slots()
        elif step == 1:
            if self._selected_slot is None:
                return
            self._step_stack.setCurrentIndex(2)
        elif step == 2:
            self.submit_request()
            return
        self._update_footer_for_step()

    def _show_step(self, index: int) -> None:
        self._step_stack.setCurrentIndex(
            max(0, min(index, self._step_stack.count() - 1)))
        self._update_footer_for_step()

    def _update_footer_for_step(self) -> None:
        step = self._step_stack.currentIndex()
        self._footer.setVisible(step < 3)
        if step == 0:
            self._footer_button.setText("Continue")
            service = self._selected_service()
            self._footer_button.setEnabled(
                service is not None
                and (not service.length_prices or bool(self._selected_length))
            )
        elif step == 1:
            self._footer_button.setText("Continue")
            self._footer_button.setEnabled(self._selected_slot is not None)
        elif step == 2:
            self._footer_button.setText("Confirm")
            self._footer_button.setEnabled(True)

    def _set_calendar_minimum(self) -> None:
        earliest = datetime.now() + timedelta(hours=24)
        minimum_date = QDate(earliest.year, earliest.month, earliest.day)
        self._calendar.setMinimumDate(minimum_date)
        current = self._calendar.selectedDate()
        if current < minimum_date:
            self._calendar.setSelectedDate(minimum_date)
        self._format_schedule_calendar()

    def _format_schedule_calendar(self, year: int | None = None, month: int | None = None) -> None:
        year = year or self._calendar.yearShown()
        month = month or self._calendar.monthShown()
        days = month_calendar.monthrange(year, month)[1]
        first = datetime(year, month, 1).date()
        last = datetime(year, month, days).date()
        manager = self._appointment_manager.schedule_manager
        try:
            closed_dates = manager.get_closed_dates(first, last)
            closure_dates = {
                selected_day
                for selected_day in closed_dates
                if manager.get_closures_for_date(selected_day)
            }
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Could not load schedule", str(error))
            return
        for day in range(1, days + 1):
            selected_day = first.replace(day=day)
            fmt = QTextCharFormat()
            if selected_day in closed_dates:
                fmt.setForeground(QColor("#a9a2a0"))
                if selected_day in closure_dates:
                    fmt.setBackground(QColor("#eadfce"))
            self._calendar.setDateTextFormat(
                QDate(selected_day.year, selected_day.month, selected_day.day),
                fmt,
            )

    def _refresh_slots(self) -> None:
        if not hasattr(self, "_calendar"):
            return
        self._selected_slot = None
        selected_date = self._calendar.selectedDate().toPyDate()
        self._selected_date_label.setText(selected_date.strftime("%A %d %B"))
        self._clear_layout(self._slots_grid)
        self._slot_buttons = []
        service = self._selected_service()
        if service is None:
            self._slots_grid.addWidget(
                QLabel("Choose a service first."), 0, 0, 1, 2)
            self._update_footer_for_step()
            return
        try:
            slots = self._appointment_manager.get_available_slots(
                selected_date,
                service.duration_minutes,
                self._visit_type,
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(
                self, "Could not load available times", str(error))
            slots = []
        if not slots:
            self._slots_grid.addWidget(
                QLabel("No times available on this day"), 0, 0, 1, 2
            )
        for index, slot in enumerate(slots):
            button = QPushButton(self._format_time(slot))
            button.setCheckable(True)
            button.setProperty("selectionChoice", True)
            button.clicked.connect(lambda _checked=False,
                                   value=slot: self._select_slot(value))
            self._slots_grid.addWidget(button, index // 2, index % 2)
            self._slot_buttons.append(button)
        self._slots_grid.setRowStretch((len(slots) + 1) // 2, 1)
        self._update_footer_for_step()

    def _select_slot(self, slot: datetime) -> None:
        self._selected_slot = slot
        for button in self._slot_buttons:
            button.setChecked(button.text() == self._format_time(slot))
        self._update_footer_for_step()

    def submit_request(self) -> None:
        name = self._name_input.text().strip()
        phone_digits = re.sub(r"\D", "", self._phone_input.text())
        email = self._email_input.text().strip().lower()
        allergies = self._allergies_input.text().strip()
        street_address = self._street_address_input.text().strip()
        town = self._town_input.text().strip()
        landmark = self._landmark_input.text().strip()
        service_address = self._format_service_address(
            street_address, town, landmark
        )
        service = self._selected_service()
        if not name:
            self._validation_error("Please enter your full name.")
            return
        if not self._PHONE_PATTERN.fullmatch(phone_digits):
            self._validation_error("Enter a valid Philippine mobile number.")
            return
        if not self._EMAIL_PATTERN.fullmatch(email):
            self._validation_error("Please enter a valid email address.")
            return
        if not allergies:
            self._validation_error("Please enter allergies or type None.")
            return
        if self._visit_type is VisitType.HOME_SERVICE:
            if len(street_address) < 10:
                self._validation_error(
                    "Please enter a complete address with at least 10 characters."
                )
                return
            if not town:
                self._validation_error(
                    "Please enter the town or municipality.")
                return
            if not self._appointment_manager.is_home_service_area_allowed(town):
                self._validation_error(
                    self._appointment_manager.get_home_service_area_message()
                )
                return
        if not self._policy_agreement.isChecked():
            self._validation_error("Please agree to the booking policies.")
            return
        if service is None or self._selected_slot is None:
            self._validation_error(
                "Please choose a service and available time.")
            return
        service_id = service.service_id
        requested_time = self._selected_slot
        if service_id is None:
            self._validation_error("The selected service is not available.")
            return
        if service.length_prices and not self._selected_length:
            self._validation_error("Please choose a nail length.")
            return
        formatted_phone = "+63" + (
            phone_digits[1:] if phone_digits.startswith("0") else phone_digits
        )
        try:
            existing_client = next(
                (
                    client
                    for client in self._client_manager.get_clients()
                    if client.email.casefold() == email.casefold()
                ),
                None,
            )
            if existing_client is None:
                self._client_manager.add_client(
                    Customer(name, email, formatted_phone)
                )
            appointment = self._appointment_manager.create_appointment(
                email,
                service_id,
                self._selected_length,
                sorted(self._selected_add_ons),
                requested_time,
                duration_minutes=service.duration_minutes,
                notes=self._comments_input.toPlainText().strip() or None,
                allergies=allergies,
                visit_type=self._visit_type,
                service_address=service_address,
                travel_fee=(
                    self._travel_fee
                    if self._visit_type is VisitType.HOME_SERVICE
                    else 0
                ),
                selected_extra_names=sorted(self._selected_extras),
            )
        except ValueError as error:
            if "overlaps an existing appointment" in str(error):
                self._selected_slot = None
                self._show_step(1)
                self._refresh_slots()
                self._show_unavailable_message()
                return
            self._validation_error(str(error))
            return
        except (sqlite3.Error, TypeError, KeyError) as error:
            QMessageBox.critical(self, "Could not submit request", str(error))
            return
        estimated_total_label = (
            "Estimated total (travel fee not included)"
            if self._visit_type is VisitType.HOME_SERVICE
            else "Estimated total"
        )
        self._confirmation_summary = (
            f"Service: {service.name}\n"
            f"Visit type: {self._visit_type.value.replace('_', ' ')}\n"
            + (
                f"Address: {service_address}\n"
                "Travel fee depends on your location. "
                "The salon will confirm it.\n"
                if self._visit_type is VisitType.HOME_SERVICE
                else ""
            )
            + (
                f"Nail length: {self._selected_length or '—'}\n"
                f"Add-ons: {', '.join(sorted(self._selected_add_ons)) or 'None'}\n"
                f"Extras: {', '.join(sorted(self._selected_extras)) or 'None'}\n"
                f"Date: {requested_time.strftime('%A %d %B %Y')}\n"
                f"Start time: {self._format_time(requested_time)}\n"
                f"{estimated_total_label}: "
                f"₱{appointment.total_price:,.2f}"
            )
        )
        self._summary_label.setText(self._confirmation_summary)
        self._last_home_address = (
            service_address if self._visit_type is VisitType.HOME_SERVICE else ""
        )
        if self._last_home_address:
            self._studio_info.set_customer_address(self._last_home_address)
        self._open_confirmation_address.setVisible(
            bool(self._last_home_address))
        self._show_step(3)

    def _selected_service(self) -> Service | None:
        return next(
            (
                service
                for service in self._service_items
                if service.service_id == self._selected_service_id
            ),
            None,
        )

    def _dismiss_welcome(self) -> None:
        self._welcome_dismissed = True
        self._welcome_card.hide()

    def _start_new_request(self) -> None:
        self._name_input.clear()
        self._phone_input.clear()
        self._email_input.clear()
        self._comments_input.clear()
        self._allergies_input.clear()
        self._street_address_input.clear()
        self._town_input.clear()
        self._landmark_input.clear()
        self._policy_agreement.setChecked(False)
        self._selected_service_id = None
        self._selected_length = ""
        self._selected_add_ons.clear()
        self._selected_slot = None
        self._visit_type = VisitType.STUDIO
        self._travel_fee = 0
        self._rebuild_service_list()
        self._update_total()
        self._show_step(0)

    def _open_confirmation_address_in_maps(self) -> None:
        if not self._last_home_address:
            return
        url = QUrl(
            "https://www.google.com/maps/search/?api=1&query="
            + quote(self._last_home_address, safe="")
        )
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Could not open map",
                "The address could not be opened in your browser.",
            )

    def _validation_error(self, message: str) -> None:
        QMessageBox.warning(self, "Appointment request", message)

    def _show_unavailable_message(self) -> None:
        QMessageBox.information(
            self,
            "Time unavailable",
            "That time is not available, please choose another.",
        )

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.strftime("%I:%M %p").lstrip("0")

    @staticmethod
    def _format_service_address(street: str, town: str, landmark: str) -> str:
        parts = [
            f"Street / house / barangay: {CustomerAppointmentScreen._single_line(street)}",
            f"Town or municipality: {CustomerAppointmentScreen._single_line(town)}",
        ]
        if landmark.strip():
            parts.append(
                f"Landmark: {CustomerAppointmentScreen._single_line(landmark)}"
            )
        return "; ".join(parts)

    @staticmethod
    def _single_line(value: str) -> str:
        return " ".join(value.replace("\r", " ").replace("\n", " ").split())

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                CustomerAppointmentScreen._clear_layout(item.layout())
