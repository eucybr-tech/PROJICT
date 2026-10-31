import sqlite3
from io import BytesIO
from datetime import date, datetime, timedelta
from typing import Callable
from urllib.parse import quote

from PyQt6.QtCore import (
    QDate,
    QObject,
    QRect,
    QSize,
    QTime,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPixmap, QTextCharFormat, QDesktopServices
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QLayoutItem,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from models import (
    Appointment,
    AppointmentStatus,
    Service,
    StudioPolicy,
    User,
    VisitType,
    format_duration,
)
from services.appointment_manager import AppointmentManager
from services.pricing_calculator import PricingCalculator
from services.studio_settings_manager import StudioSettingsManager
from services.loyalty_manager import LoyaltyManager
from services.loyalty_web_server import LoyaltyWebServer, get_lan_ip
from ui.scrollable_dialog import ScrollableDialog

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


class HomeServiceMapDialog(ScrollableDialog):
    """Read-only appointment location with role-aware fee visibility."""

    def __init__(
        self,
        appointment: Appointment,
        studio_settings_manager: StudioSettingsManager | None,
        show_travel_fee: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Home-service location")
        self.resize(760, 620)
        self._appointment = appointment
        self._show_travel_fee = show_travel_fee
        self._address, self._town = self._parse_service_address(
            appointment.service_address
        )
        self._studio_address = ""
        self._settings_error = ""
        if studio_settings_manager is not None:
            try:
                self._studio_address = (
                    studio_settings_manager.get_settings().studio_address.strip()
                )
            except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
                self._studio_address = ""
                self._settings_error = f"Studio address could not be loaded: {error}"

        self._address_label = QLabel(
            self._address or "No service address was provided."
        )
        self._address_label.setWordWrap(True)
        self._town_label = QLabel(f"Town: {self._town or 'Not provided'}")
        self._town_label.setWordWrap(True)
        self._travel_fee_label = (
            QLabel(f"Travel fee: ₱ {appointment.travel_fee:,.2f}")
            if show_travel_fee
            else None
        )
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._map_stack = QStackedWidget()
        self._fallback_label = QLabel("Map needs an internet connection")
        self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback_label.setWordWrap(True)
        self._map_stack.addWidget(self._fallback_label)
        self._web_view = None
        self._embed_url = self.build_embed_url(
            appointment.service_address, self._town
        )
        if self._address and QWebEngineView is not None:
            try:
                self._web_view = QWebEngineView()
                self._web_view.loadFinished.connect(self._web_load_finished)
                self._map_stack.addWidget(self._web_view)
                self._web_view.setUrl(QUrl.fromEncoded(self._embed_url.encode("utf-8")))
            except (ImportError, RuntimeError):
                self._web_view = None
                self._status_label.setText(self._connection_status())
        elif self._address:
            self._status_label.setText(self._connection_status())
        else:
            self._status_label.setText(self._connection_status())

        self._directions_button = QPushButton("Get directions")
        self._directions_button.clicked.connect(self._open_directions)
        self._open_map_button = QPushButton("Open in Google Maps")
        self._open_map_button.clicked.connect(self._open_google_maps)
        self._map_stack.setMinimumHeight(320)
        footer = QHBoxLayout()
        footer.addWidget(self._directions_button)
        footer.addWidget(self._open_map_button)
        footer.addStretch()
        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button.rejected.connect(self.reject)
        footer.addWidget(close_button)
        content = QVBoxLayout()
        content.addWidget(self._address_label)
        content.addWidget(self._town_label)
        if self._travel_fee_label is not None:
            content.addWidget(self._travel_fee_label)
        content.addWidget(self._status_label)
        content.addWidget(self._map_stack, 1)
        self.set_dialog_layout(content, footer)

    @staticmethod
    def _parse_service_address(service_address: str) -> tuple[str, str]:
        if not service_address.strip():
            return "", ""
        address = ""
        town = ""
        landmark = ""
        for component in service_address.split(";"):
            key, separator, value = component.partition(":")
            if not separator:
                continue
            normalized_key = key.strip().casefold()
            if normalized_key == "street / house / barangay":
                address = value.strip()
            elif normalized_key == "town or municipality":
                town = value.strip()
            elif normalized_key == "landmark":
                landmark = value.strip()
        if address and len(address) < 10:
            address = ""
        if address and landmark:
            address = f"{address}, {landmark}"
        if not address and not town:
            raw_address = service_address.strip()
            return (raw_address, "") if len(raw_address) >= 10 else ("", "")
        return address, town

    @classmethod
    def build_embed_url(cls, service_address: str, town: str = "") -> str:
        address, parsed_town = cls._parse_service_address(service_address)
        town = town.strip() or parsed_town
        if not address:
            return ""
        query = ", ".join(
            part
            for part in (address, town, "Laguna, Philippines")
            if part
        )
        return (
            "https://www.google.com/maps?q="
            + quote(query, safe="")
            + "&output=embed"
        )

    @classmethod
    def build_directions_url(
        cls, studio_address: str, customer_address: str
    ) -> str:
        destination = customer_address.strip()
        if not destination:
            return ""
        url = "https://www.google.com/maps/dir/?api=1&"
        if studio_address.strip():
            url += "origin=" + quote(studio_address.strip(), safe="") + "&"
        return url + "destination=" + quote(destination, safe="")

    def _web_load_finished(self, succeeded: bool) -> None:
        if succeeded:
            self._map_stack.setCurrentWidget(self._web_view)
            self._status_label.clear()
            return
        self._map_stack.setCurrentWidget(self._fallback_label)
        self._status_label.setText(self._connection_status())

    def _connection_status(self) -> str:
        if self._settings_error:
            return f"{self._settings_error} Map needs an internet connection"
        return "Map needs an internet connection"

    def _open_directions(self) -> None:
        if not self._address:
            QMessageBox.information(
                self, "Address unavailable", "No service address was provided."
            )
            return
        destination = ", ".join(
            part for part in (self._address, self._town) if part
        )
        url_text = self.build_directions_url(self._studio_address, destination)
        if not self._studio_address and not self._settings_error:
            QMessageBox.information(
                self,
                "Studio address not set",
                "The studio address is not set. Opening directions to the customer only.",
            )
        elif self._settings_error:
            QMessageBox.warning(
                self, "Studio address unavailable", self._settings_error
            )
        self._open_url(url_text, "Could not open directions")

    def _open_google_maps(self) -> None:
        if not self._address:
            QMessageBox.information(
                self, "Address unavailable", "No service address was provided."
            )
            return
        destination = ", ".join(
            part for part in (self._address, self._town) if part
        )
        query = ", ".join(
            part for part in (destination, "Laguna, Philippines") if part
        )
        url = (
            "https://www.google.com/maps/search/?api=1&query="
            + quote(query, safe="")
        )
        self._open_url(url, "Could not open Google Maps")

    @staticmethod
    def _open_url(url: str, error_title: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(
                None, error_title, "The map could not be opened in your browser."
            )


class AppointmentDetailsDialog(ScrollableDialog):
    def __init__(
        self,
        details: str,
        open_address: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appointment details")
        label = QLabel(details)
        label.setWordWrap(True)
        content = QVBoxLayout()
        content.addWidget(label)

        footer = QHBoxLayout()
        if open_address is not None:
            open_button = QPushButton("Open address in Google Maps")
            open_button.clicked.connect(open_address)
            footer.addWidget(open_button)
        footer.addStretch()
        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_button.accepted.connect(self.accept)
        footer.addWidget(close_button)
        self.set_dialog_layout(content, footer)


class StampQrDialog(ScrollableDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Show stamp QR")
        self.setMinimumWidth(400)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link_label = QLabel()
        self.link_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.link_label.setWordWrap(True)
        self.note_label = QLabel(
            "Customer scans with their phone camera. Phone must be on the same Wi-Fi."
        )
        self.note_label.setWordWrap(True)
        self.countdown_label = QLabel()
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generate_button = QPushButton("Generate new QR")
        self.generate_button.hide()
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)

        content = QVBoxLayout()
        content.addWidget(self.image_label)
        content.addWidget(self.link_label)
        content.addWidget(self.countdown_label)
        content.addWidget(self.note_label)
        footer = QHBoxLayout()
        footer.addWidget(self.generate_button)
        footer.addStretch()
        footer.addWidget(self.close_buttons)
        self.set_dialog_layout(content, footer)


class EmailResultSignals(QObject):
    completed = pyqtSignal(bool, str)


class NewAppointmentDialog(ScrollableDialog):
    # Dependency injection: appointment and price logic are supplied by the caller.
    def __init__(
        self,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        selected_date: date,
        role: User,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Appointment")
        self.setMinimumWidth(460)
        self._appointment_manager = appointment_manager
        self._pricing_calculator = pricing_calculator
        self._can_record_payments = "record_payments" in role.get_permissions()
        self._clients = appointment_manager.get_clients()
        self._services = appointment_manager.get_services()
        self._extras = appointment_manager.get_active_price_extras()

        self._client_email = QComboBox()
        self._client_email.setEditable(True)
        self._client_email.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._client_email.setCurrentText("")
        self._client_email.setPlaceholderText("Search or enter client email")
        for client in self._clients:
            self._client_email.addItem(client.email, client.email)

        self._service = QComboBox()
        for service in self._services:
            self._service.addItem(service.name, service.service_id)
        self._nail_length = QComboBox()
        self._design_add_ons = QListWidget()
        self._design_add_ons.setMaximumHeight(115)
        self._extras_list = QListWidget()
        self._extras_list.setMaximumHeight(115)
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setDate(selected_date)
        self._time = QTimeEdit()
        self._time.setDisplayFormat("HH:mm")
        policy = appointment_manager.studio_policy
        self._duration = QSpinBox()
        self._duration.setRange(policy.min_minutes, policy.max_minutes)
        self._duration.setSingleStep(5)
        self._duration.setSuffix(" minutes")
        self._duration.setValue(120)
        self._visit_type = QComboBox()
        self._visit_type.addItem("Studio visit", VisitType.STUDIO)
        self._visit_type.addItem("Home service", VisitType.HOME_SERVICE)
        self._street_address = QLineEdit()
        self._street_address.setPlaceholderText("Street / house / barangay")
        self._town = QLineEdit()
        self._town.setPlaceholderText("Town or municipality")
        self._landmark = QLineEdit()
        self._landmark.setPlaceholderText("Landmark (optional)")
        self._address_fields = QWidget()
        address_layout = QVBoxLayout(self._address_fields)
        address_layout.setContentsMargins(0, 0, 0, 0)
        address_layout.addWidget(QLabel("Street / house / barangay *"))
        address_layout.addWidget(self._street_address)
        address_layout.addWidget(QLabel("Town or municipality *"))
        address_layout.addWidget(self._town)
        address_layout.addWidget(QLabel("Landmark (optional)"))
        address_layout.addWidget(self._landmark)
        self._travel_fee = QDoubleSpinBox()
        self._travel_fee.setRange(0, 1_000_000)
        self._travel_fee.setDecimals(2)
        self._travel_fee.setPrefix("₱ ")
        self._allow_outside_schedule = False
        self._address_fields.hide()
        self._travel_fee.hide()
        self._end_time = QLabel()
        self._total = QLabel("Total: ₱ 0.00")
        self._total.setObjectName("appTitle")

        form = QFormLayout()
        form.addRow("Client email", self._client_email)
        form.addRow("Service", self._service)
        form.addRow("Nail length", self._nail_length)
        form.addRow("Design add-ons", self._design_add_ons)
        form.addRow("Extras", self._extras_list)
        form.addRow("Visit type", self._visit_type)
        form.addRow("Service address", self._address_fields)
        if self._can_record_payments:
            form.addRow("Travel fee", self._travel_fee)
        form.addRow("Date", self._date)
        form.addRow("Time", self._time)
        form.addRow("Duration", self._duration)
        form.addRow("End time", self._end_time)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        footer = QHBoxLayout()
        if self._can_record_payments:
            footer.addWidget(self._total)
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

        self._service.currentIndexChanged.connect(self._update_service_options)
        self._nail_length.currentIndexChanged.connect(self._update_total)
        self._design_add_ons.itemChanged.connect(self._update_total)
        self._extras_list.itemChanged.connect(self._update_total)
        self._date.dateChanged.connect(self._update_end_time)
        self._time.timeChanged.connect(self._update_end_time)
        self._duration.valueChanged.connect(self._update_end_time)
        self._visit_type.currentIndexChanged.connect(self._update_visit_type)
        self._update_service_options()
        self._update_end_time()

    def get_appointment_values(
        self,
    ) -> tuple[
        str, int, str, list[str], list[str], datetime, int, VisitType, str, float
    ]:
        email = self._client_email.currentText().strip()
        if not email:
            raise ValueError("Client email is required")
        service_id = self._service.currentData()
        if not isinstance(service_id, int):
            raise ValueError("Choose a service")
        service = self._current_service()
        nail_length = self._nail_length.currentText()
        if service is not None and service.length_prices and not nail_length:
            raise ValueError("Choose a nail length")
        selected_add_ons = []
        for row in range(self._design_add_ons.count()):
            item = self._design_add_ons.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected_add_ons.append(item.text())
        selected_date = self._date.date().toPyDate()
        selected_time = self._time.time().toPyTime()
        appointment_time = datetime.combine(selected_date, selected_time)
        visit_type = self._visit_type.currentData()
        if not isinstance(visit_type, VisitType):
            raise ValueError("Choose a visit type")
        service_address = ""
        if visit_type is VisitType.HOME_SERVICE:
            street = self._single_line(self._street_address.text())
            town = self._single_line(self._town.text())
            landmark = self._single_line(self._landmark.text())
            if not street:
                raise ValueError("Street, house, or barangay is required")
            if not town:
                raise ValueError("Town or municipality is required")
            service_address = self._format_service_address(
                street, town, landmark
            )
        return (
            email,
            service_id,
            nail_length,
            selected_add_ons,
            sorted(self._checked_extras()),
            appointment_time,
            self._duration.value(),
            visit_type,
            service_address,
            (
                self._travel_fee.value()
                if visit_type is VisitType.HOME_SERVICE
                and self._can_record_payments
                else 0
            ),
        )

    def _update_visit_type(self, *_signal_args: object) -> None:
        visit_type = self._visit_type.currentData()
        is_home_service = visit_type is VisitType.HOME_SERVICE
        self._address_fields.setVisible(is_home_service)
        self._travel_fee.setVisible(is_home_service and self._can_record_payments)
        if is_home_service and self._can_record_payments:
            settings = self._appointment_manager.get_studio_settings()
            self._travel_fee.setValue(settings.default_travel_fee)

    def _validate_and_accept(self) -> None:
        self._allow_outside_schedule = False
        try:
            (
                _email,
                _service_id,
                _nail_length,
                _design_add_ons,
                _selected_extras,
                appointment_start,
                duration_minutes,
                visit_type,
                _service_address,
                _travel_fee,
            ) = self.get_appointment_values()
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Appointment details", str(error))
            return
        if (
            self._visit_type.currentData() is VisitType.HOME_SERVICE
            and not self._appointment_manager.is_home_service_area_allowed(
                self._town.text()
            )
        ):
            QMessageBox.warning(
                self,
                "Outside the service area",
                self._appointment_manager.get_home_service_area_message(),
            )
            answer = QMessageBox.question(
                self,
                "Outside the service area",
                "Outside the service area. Book anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if appointment_start and duration_minutes:
            issue = self._appointment_manager.schedule_manager.get_schedule_issue(
                appointment_start, duration_minutes, visit_type
            )
            if issue is not None:
                answer = QMessageBox.question(
                    self,
                    "Outside working hours",
                    "Outside working hours. Book anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self._allow_outside_schedule = True
        self.accept()

    @property
    def allow_outside_schedule(self) -> bool:
        return self._allow_outside_schedule

    @staticmethod
    def _single_line(value: str) -> str:
        return " ".join(value.replace("\r", " ").replace("\n", " ").split())

    @classmethod
    def _format_service_address(
        cls, street: str, town: str, landmark: str
    ) -> str:
        parts = [
            f"Street / house / barangay: {cls._single_line(street)}",
            f"Town or municipality: {cls._single_line(town)}",
        ]
        if landmark:
            parts.append(f"Landmark: {cls._single_line(landmark)}")
        return "; ".join(parts)

    def _update_end_time(self, *signal_args: object) -> None:
        del signal_args
        start = datetime.combine(
            self._date.date().toPyDate(),
            self._time.time().toPyTime(),
        )
        end = start + timedelta(minutes=self._duration.value())
        self._end_time.setText(end.strftime("%Y-%m-%d %H:%M"))

    def _current_service(self) -> Service | None:
        service_id = self._service.currentData()
        return next(
            (service for service in self._services if service.service_id == service_id),
            None,
        )

    def _update_service_options(self, *signal_args: object) -> None:
        del signal_args
        service = self._current_service()
        previous_length = self._nail_length.currentText()
        selected_add_ons = self._checked_add_ons()
        selected_extras = self._checked_extras()
        if service is not None:
            self._duration.setValue(service.duration_minutes)

        self._nail_length.blockSignals(True)
        self._nail_length.clear()
        if service:
            self._nail_length.addItems(service.length_prices.keys())
        index = self._nail_length.findText(previous_length)
        if index >= 0:
            self._nail_length.setCurrentIndex(index)
        self._nail_length.blockSignals(False)

        self._design_add_ons.blockSignals(True)
        self._design_add_ons.clear()
        if service:
            for name in service.design_add_on_prices:
                item = QListWidgetItem(name, self._design_add_ons)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if name in selected_add_ons
                    else Qt.CheckState.Unchecked
                )
        self._design_add_ons.blockSignals(False)
        self._extras_list.blockSignals(True)
        self._extras_list.clear()
        for extra in self._extras:
            label = (
                f"{extra.name} (+₱{extra.price:,.2f})"
                if self._can_record_payments
                else extra.name
            )
            item = QListWidgetItem(label, self._extras_list)
            item.setData(Qt.ItemDataRole.UserRole, extra.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if extra.name in selected_extras
                else Qt.CheckState.Unchecked
            )
        self._extras_list.blockSignals(False)
        self._update_total()

    def _checked_add_ons(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self._design_add_ons.count()):
            item = self._design_add_ons.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                checked.add(item.text())
        return checked

    def _checked_extras(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self._extras_list.count()):
            item = self._extras_list.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                name = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(name, str):
                    checked.add(name)
        return checked

    def _update_total(self, *signal_args: object) -> None:
        del signal_args
        service = self._current_service()
        length = self._nail_length.currentText()
        if service is None:
            self._total.setText("Total: ₱ 0.00")
            return
        try:
            total = self._pricing_calculator.calculate_price(
                service,
                length,
                self._checked_add_ons(),
                {
                    extra.name: extra.price
                    for extra in self._extras
                    if extra.name in self._checked_extras()
                },
            )
        except (ValueError, TypeError) as error:
            self._total.setText("Total: —")
            QMessageBox.warning(self, "Could not calculate price", str(error))
            return
        self._total.setText(f"Total: ₱ {total:,.2f}")


class RescheduleDialog(ScrollableDialog):
    def __init__(self, appointment_time: datetime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reschedule Appointment")
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setDate(appointment_time.date())
        self._time = QTimeEdit()
        self._time.setDisplayFormat("HH:mm")
        self._time.setTime(
            QTime(appointment_time.hour, appointment_time.minute, appointment_time.second)
        )
        form = QFormLayout()
        form.addRow("New date", self._date)
        form.addRow("New time", self._time)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    def get_datetime(self) -> datetime:
        return datetime.combine(self._date.date().toPyDate(), self._time.time().toPyTime())


class EditDurationDialog(ScrollableDialog):
    def __init__(
        self,
        duration_minutes: int,
        policy: StudioPolicy,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Appointment Duration")
        self._duration = QSpinBox()
        self._duration.setRange(policy.min_minutes, policy.max_minutes)
        self._duration.setSingleStep(5)
        self._duration.setSuffix(" minutes")
        self._duration.setValue(duration_minutes)
        form = QFormLayout()
        form.addRow("Duration", self._duration)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    @property
    def duration_minutes(self) -> int:
        return self._duration.value()


class LatePolicyDialog(ScrollableDialog):
    def __init__(
        self,
        action: str,
        fee_amount: int,
        can_waive_fee: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Late {action}")
        self._waive_fee = QCheckBox("Waive fee")
        self._waive_fee.setVisible(can_waive_fee)
        message = QLabel(
            f"This {action.lower()} is within the {StudioPolicy().notice_hours}-hour "
            "notice period."
        )
        message.setWordWrap(True)
        fee_message = QLabel(
            f"The fee is ₱ {fee_amount:.2f} unless waived."
        )
        fee_message.setVisible(can_waive_fee)
        fee_message.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel
        )
        yes_button = buttons.button(QDialogButtonBox.StandardButton.Yes)
        if yes_button is None:
            raise RuntimeError("Confirmation button was not created")
        yes_button.setText(f"Confirm {action.lower()}")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        content = QVBoxLayout()
        content.addWidget(message)
        content.addWidget(fee_message)
        content.addWidget(self._waive_fee)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(content, footer)

    @property
    def waive_fee(self) -> bool:
        return self._waive_fee.isChecked()


class PaymentDialog(ScrollableDialog):
    """Edit the recorded payment totals and preview their computed balance."""

    def __init__(self, appointment: Appointment, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record payment")
        self._appointment = appointment
        self._amount_paid = self._create_money_input(appointment.amount_paid)
        self._discount = self._create_money_input(appointment.discount)
        self._travel_fee = self._create_money_input(appointment.travel_fee)
        self._payment_note = QTextEdit(appointment.payment_note)
        self._payment_note.setMaximumHeight(80)
        self._final_price_label = QLabel()
        self._balance_label = QLabel()

        form = QFormLayout()
        form.addRow("Service price", QLabel(f"₱ {appointment.total_price:,.2f}"))
        form.addRow("Amount paid to date", self._amount_paid)
        form.addRow("Discount", self._discount)
        form.addRow("Travel fee", self._travel_fee)
        form.addRow("Payment note", self._payment_note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Final price:"))
        footer.addWidget(self._final_price_label)
        footer.addSpacing(12)
        footer.addWidget(QLabel("Balance:"))
        footer.addWidget(self._balance_label)
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)
        for input_widget in (self._amount_paid, self._discount, self._travel_fee):
            input_widget.valueChanged.connect(self._update_preview)
        self._update_preview()

    @staticmethod
    def _create_money_input(value: float) -> QDoubleSpinBox:
        input_widget = QDoubleSpinBox()
        input_widget.setRange(0, 1_000_000_000)
        input_widget.setDecimals(2)
        input_widget.setSingleStep(50)
        input_widget.setPrefix("₱ ")
        input_widget.setValue(value)
        return input_widget

    def get_payment_values(self) -> tuple[float, float, float, str]:
        return (
            self._amount_paid.value(),
            self._discount.value(),
            self._travel_fee.value(),
            self._payment_note.toPlainText().strip(),
        )

    def _update_preview(self, *_signal_args: object) -> None:
        final_price = (
            self._appointment.total_price
            + self._travel_fee.value()
            - self._discount.value()
        )
        balance = final_price - self._amount_paid.value()
        self._final_price_label.setText(f"₱ {final_price:,.2f}")
        self._balance_label.setText(f"₱ {balance:,.2f}")


class TravelFeeDialog(ScrollableDialog):
    def __init__(self, current_fee: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit home-service travel fee")
        self._fee = QDoubleSpinBox()
        self._fee.setRange(0, 1_000_000)
        self._fee.setDecimals(2)
        self._fee.setPrefix("₱ ")
        self._fee.setValue(current_fee)
        form = QFormLayout()
        form.addRow("Travel fee", self._fee)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    @property
    def travel_fee(self) -> float:
        return self._fee.value()


class _FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        rect = self.contentsRect()
        margins = self.contentsMargins()
        rect.setWidth(max(0, width - margins.left() - margins.right()))
        return self._layout_items(rect, True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout_items(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _layout_items(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        row_height = 0
        spacing = self.spacing()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if row_height and next_x - spacing > rect.right() + 1:
                x = rect.x()
                y += row_height + spacing
                next_x = x + hint.width() + spacing
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = next_x
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


class AppointmentPanel(QWidget):
    """Shared calendar and appointment actions for Admin and Staff."""

    # Encapsulation and dependency injection: collaborators and widget state are private.
    def __init__(
        self,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        role: User,
        parent: QWidget | None = None,
        studio_settings_manager: StudioSettingsManager | None = None,
        loyalty_manager: LoyaltyManager | None = None,
        loyalty_web_server: LoyaltyWebServer | None = None,
    ) -> None:
        super().__init__(parent)
        self._appointment_manager = appointment_manager
        self._pricing_calculator = pricing_calculator
        self._role = role
        self._studio_settings_manager = studio_settings_manager
        self._loyalty_manager = loyalty_manager
        self._loyalty_web_server = loyalty_web_server
        self._can_show_stamp_qr = (
            loyalty_manager is not None and loyalty_web_server is not None
        )
        self._can_record_payments = "record_payments" in role.get_permissions()
        self._appointments: list[Appointment] = []
        self._highlighted_dates: set[date] = set()
        self._email_signals = EmailResultSignals(self)
        self._email_signals.completed.connect(self._show_email_result)
        self._build_ui()
        self.refresh()

    @property
    def appointment_manager(self) -> AppointmentManager:
        return self._appointment_manager

    @property
    def pricing_calculator(self) -> PricingCalculator:
        return self._pricing_calculator

    def _build_ui(self) -> None:
        self._calendar = QCalendarWidget()
        self._calendar.selectionChanged.connect(self._refresh_selected_day)
        self._calendar.currentPageChanged.connect(self._format_schedule_calendar)

        self._status_filter = QComboBox()
        self._status_filter.addItems(
            ["All", "Pending", "Confirmed", "Completed", "Cancelled", "No-show"]
        )
        self._status_filter.currentIndexChanged.connect(self._refresh_selected_day)
        self._view_mode = QComboBox()
        self._view_mode.addItems(["Day", "Week"])
        self._view_mode.currentIndexChanged.connect(self._refresh_selected_day)

        common_columns = [
            ("day", "Day"),
            ("start_time", "Start time"),
            ("end_time", "End time"),
            ("duration", "Duration"),
            ("client", "Client"),
            ("service", "Service"),
            ("nail_length", "Nail length"),
            ("add_ons", "Add-ons"),
            ("extras", "Extras"),
        ]
        if self._can_record_payments:
            common_columns.extend(
                [
                    ("total_price", "Total price"),
                    ("travel_fee", "Travel fee"),
                    ("cancellation_fee", "Cancellation fee"),
                ]
            )
        common_columns.extend(
            [
                ("status", "Status"),
                ("allergies", "Allergies"),
                ("visit_type", "Visit type"),
            ]
        )
        if self._can_record_payments:
            common_columns.extend(
                [
                    ("final_price", "Final price"),
                    ("paid", "Paid"),
                    ("balance", "Balance"),
                ]
            )
        self._table_columns = [key for key, _header in common_columns]
        self._appointment_table = QTableWidget(0, len(common_columns))
        self._appointment_table.setHorizontalHeaderLabels(
            [header for _key, header in common_columns]
        )
        self._appointment_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._appointment_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._appointment_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._appointment_table.setWordWrap(True)
        header = self._appointment_table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(False)
            for key in (
                "day",
                "start_time",
                "end_time",
                "duration",
                "nail_length",
                "total_price",
                "travel_fee",
                "cancellation_fee",
                "status",
                "visit_type",
                "final_price",
                "paid",
                "balance",
            ):
                if key not in self._table_columns:
                    continue
                column = self._table_columns.index(key)
                header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.ResizeToContents
                )
            for key, width in (
                ("client", 130),
                ("service", 150),
                ("add_ons", 140),
                ("allergies", 120),
            ):
                if key not in self._table_columns:
                    continue
                column = self._table_columns.index(key)
                header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.Interactive
                )
                self._appointment_table.setColumnWidth(column, width)
        vertical_header = self._appointment_table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )

        self._new_button = QPushButton("New Appointment")
        self._confirm_button = QPushButton("Confirm")
        self._complete_button = QPushButton("Complete")
        self._cancel_button = QPushButton("Cancel")
        self._reschedule_button = QPushButton("Reschedule")
        self._edit_duration_button = QPushButton("Edit duration")
        self._no_show_button = QPushButton("No-show")
        self._view_on_map_button = QPushButton("View on map")
        self._record_payment_button = QPushButton("Record payment")
        self._edit_travel_fee_button = QPushButton("Edit travel fee")
        self._show_stamp_qr_button = QPushButton("Show stamp QR")
        self._record_payment_button.setVisible(self._can_record_payments)
        self._edit_travel_fee_button.setVisible(self._can_record_payments)
        self._show_stamp_qr_button.setVisible(self._can_show_stamp_qr)
        self._new_button.clicked.connect(self.new_appointment)
        self._confirm_button.clicked.connect(self.confirm_selected)
        self._complete_button.clicked.connect(self.complete_selected)
        self._cancel_button.clicked.connect(self.cancel_selected)
        self._reschedule_button.clicked.connect(self.reschedule_selected)
        self._edit_duration_button.clicked.connect(self.edit_duration_selected)
        self._no_show_button.clicked.connect(self.mark_no_show_selected)
        self._view_on_map_button.clicked.connect(self.view_selected_on_map)
        self._record_payment_button.clicked.connect(self.record_payment_selected)
        self._edit_travel_fee_button.clicked.connect(self.edit_travel_fee_selected)
        self._show_stamp_qr_button.clicked.connect(self.show_stamp_qr_selected)
        self._appointment_table.itemSelectionChanged.connect(self._update_action_buttons)
        self._appointment_table.cellDoubleClicked.connect(
            self._show_appointment_details
        )

        actions = _FlowLayout()
        actions.addWidget(self._new_button)
        actions.addWidget(self._confirm_button)
        actions.addWidget(self._complete_button)
        actions.addWidget(self._cancel_button)
        actions.addWidget(self._reschedule_button)
        actions.addWidget(self._edit_duration_button)
        actions.addWidget(self._no_show_button)
        actions.addWidget(self._view_on_map_button)
        actions.addWidget(self._record_payment_button)
        actions.addWidget(self._edit_travel_fee_button)
        actions.addWidget(self._show_stamp_qr_button)
        self._actions_layout = actions

        right_layout = QVBoxLayout()
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Status"))
        filter_row.addWidget(self._status_filter)
        filter_row.addWidget(QLabel("View"))
        filter_row.addWidget(self._view_mode)
        filter_row.addStretch()
        right_layout.addLayout(filter_row)
        right_layout.addWidget(self._appointment_table, 1)
        right_layout.addLayout(actions)

        right_panel = QWidget()
        right_panel.setLayout(right_layout)
        content = QHBoxLayout()
        content.addWidget(self._calendar, 1)
        content.addWidget(right_panel, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(content)

    def refresh(self) -> None:
        try:
            self._appointments = self._appointment_manager.get_appointments()
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load appointments", error)
            return
        self._highlight_appointment_dates()
        self._refresh_selected_day()

    def new_appointment(self) -> None:
        try:
            dialog = NewAppointmentDialog(
                self._appointment_manager,
                self._pricing_calculator,
                self._calendar.selectedDate().toPyDate(),
                self._role,
                self,
            )
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not open appointment form", error)
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            (
                email,
                service_id,
                nail_length,
                add_ons,
                selected_extras,
                appointment_time,
                duration_minutes,
                visit_type,
                service_address,
                travel_fee,
            ) = dialog.get_appointment_values()
            appointment = self._appointment_manager.create_appointment(
                email,
                service_id,
                nail_length,
                add_ons,
                appointment_time,
                duration_minutes,
                visit_type=visit_type,
                service_address=service_address,
                travel_fee=travel_fee,
                allow_outside_schedule=dialog.allow_outside_schedule,
                selected_extra_names=selected_extras,
            )
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not create appointment", error)
            return
        self._calendar.setSelectedDate(
            QDate.fromString(appointment_time.date().isoformat(), "yyyy-MM-dd")
        )
        self.refresh()
        self._select_appointment(appointment.appointment_id)

    def confirm_selected(self) -> None:
        self._change_status(AppointmentStatus.CONFIRMED)

    def complete_selected(self) -> None:
        self._change_status(AppointmentStatus.COMPLETED)

    def mark_no_show_selected(self) -> None:
        appointment = self._selected_appointment()
        if appointment is None or appointment.status is not AppointmentStatus.CONFIRMED:
            return
        answer = QMessageBox.question(
            self,
            "Mark as No-show",
            f"Mark {appointment.client_email}'s appointment as No-show?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._change_status(AppointmentStatus.NO_SHOW)

    def record_payment_selected(self) -> None:
        appointment = self._selected_appointment()
        if appointment is None or appointment.appointment_id is None:
            QMessageBox.information(
                self, "Select an appointment", "Choose an appointment first."
            )
            return
        self.record_payment_for_appointment(appointment.appointment_id)

    def record_payment_for_appointment(self, appointment_id: int) -> bool:
        if not self._can_record_payments:
            QMessageBox.warning(
                self, "Permission denied", "Only an Admin can record payments."
            )
            return False
        try:
            appointment = self._appointment_manager.get_appointment(appointment_id)
        except (KeyError, sqlite3.Error) as error:
            self._show_error("Could not load appointment", error)
            return False
        saved_appointment_id = appointment.appointment_id
        if saved_appointment_id is None:
            self._show_error(
                "Could not record payment",
                ValueError("The appointment has not been saved"),
            )
            return False
        if appointment.status not in (
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.COMPLETED,
        ):
            QMessageBox.information(
                self, "Payment unavailable", "Only confirmed or completed appointments can be paid."
            )
            return False
        dialog = PaymentDialog(appointment, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self._appointment_manager.record_payment(
                saved_appointment_id,
                *dialog.get_payment_values(),
                role=self._role,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            PermissionError,
            sqlite3.Error,
        ) as error:
            self._show_error("Could not record payment", error)
            return False
        self.refresh()
        self._select_appointment(saved_appointment_id)
        return True

    def edit_travel_fee_selected(self) -> None:
        if not self._can_record_payments:
            QMessageBox.warning(
                self, "Permission denied", "Only an Admin can edit travel fees."
            )
            return
        appointment = self._selected_appointment()
        if appointment is None or appointment.appointment_id is None:
            return
        dialog = TravelFeeDialog(appointment.travel_fee, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._appointment_manager.set_home_service_travel_fee(
                appointment.appointment_id, dialog.travel_fee, self._role
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            PermissionError,
            sqlite3.Error,
        ) as error:
            self._show_error("Could not update travel fee", error)
            return
        self.refresh()
        self._select_appointment(appointment.appointment_id)

    def cancel_selected(self) -> None:
        appointment = self._selected_appointment()
        if appointment is None or appointment.appointment_id is None:
            QMessageBox.information(
                self, "Select an appointment", "Choose an appointment first."
            )
            return
        is_late = self._appointment_manager.requires_late_notice_confirmation(
            self._as_datetime(appointment.appointment_time)
        )
        waive_fee = False
        if is_late:
            dialog = LatePolicyDialog(
                "Cancellation",
                self._appointment_manager.studio_policy.cancellation_fee,
                self._can_record_payments,
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            waive_fee = dialog.waive_fee
        self._change_status(
            AppointmentStatus.CANCELLED,
            late_confirmation=is_late,
            waive_fee=waive_fee,
        )

    def reschedule_selected(self) -> None:
        appointment = self._selected_appointment()
        if appointment is None:
            QMessageBox.information(
                self, "Select an appointment", "Choose an appointment to reschedule."
            )
            return
        appointment_time = self._as_datetime(appointment.appointment_time)
        appointment_id = appointment.appointment_id
        if appointment_id is None:
            self._show_error(
                "Could not reschedule appointment",
                ValueError("The appointment has not been saved"),
            )
            return
        dialog = RescheduleDialog(appointment_time, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        is_late = self._appointment_manager.requires_late_notice_confirmation(
            appointment_time
        )
        waive_fee = False
        if is_late:
            warning = LatePolicyDialog(
                "Reschedule",
                self._appointment_manager.studio_policy.cancellation_fee,
                self._can_record_payments,
                self,
            )
            if warning.exec() != QDialog.DialogCode.Accepted:
                return
            waive_fee = warning.waive_fee
        allow_outside_schedule = False
        schedule_issue = self._appointment_manager.schedule_manager.get_schedule_issue(
            dialog.get_datetime(),
            appointment.duration_minutes,
            appointment.visit_type,
        )
        if schedule_issue is not None:
            answer = QMessageBox.question(
                self,
                "Outside working hours",
                "Outside working hours. Book anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            allow_outside_schedule = True
        try:
            updated = self._appointment_manager.reschedule(
                appointment_id,
                dialog.get_datetime(),
                self._email_callback,
                late_confirmation=is_late,
                waive_fee=waive_fee,
                allow_outside_schedule=allow_outside_schedule,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            PermissionError,
            sqlite3.Error,
        ) as error:
            self._show_error("Could not reschedule appointment", error)
            return
        self._calendar.setSelectedDate(
            QDate.fromString(
                self._as_datetime(updated.appointment_time).date().isoformat(),
                "yyyy-MM-dd",
            )
        )
        self.refresh()
        self._select_appointment(updated.appointment_id)

    def edit_duration_selected(self) -> None:
        appointment = self._selected_appointment()
        if (
            appointment is None
            or appointment.appointment_id is None
            or appointment.status
            not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        ):
            return
        dialog = EditDurationDialog(
            appointment.duration_minutes,
            self._appointment_manager.studio_policy,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        duration_minutes = dialog.duration_minutes
        if duration_minutes == appointment.duration_minutes:
            return

        allow_outside_schedule = False
        schedule_issue = self._appointment_manager.schedule_manager.get_schedule_issue(
            self._as_datetime(appointment.appointment_time),
            duration_minutes,
            appointment.visit_type,
        )
        if schedule_issue is not None:
            answer = QMessageBox.question(
                self,
                "Outside working hours",
                "Outside working hours. Save anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            allow_outside_schedule = True
        try:
            updated = self._appointment_manager.update_duration(
                appointment.appointment_id,
                duration_minutes,
                allow_outside_schedule=allow_outside_schedule,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            PermissionError,
            sqlite3.Error,
        ) as error:
            self._show_error("Could not update appointment duration", error)
            return
        self.refresh()
        self._select_appointment(updated.appointment_id)

    def _change_status(
        self,
        status: AppointmentStatus,
        late_confirmation: bool = False,
        waive_fee: bool = False,
    ) -> None:
        appointment = self._selected_appointment()
        if appointment is None or appointment.appointment_id is None:
            QMessageBox.information(
                self, "Select an appointment", "Choose an appointment first."
            )
            return
        try:
            self._appointment_manager.update_status(
                appointment.appointment_id,
                status,
                self._email_callback,
                late_confirmation=late_confirmation,
                waive_fee=waive_fee,
                role=self._role,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            PermissionError,
            sqlite3.Error,
        ) as error:
            self._show_error("Could not update appointment", error)
            return
        selected_id = appointment.appointment_id
        self.refresh()
        self._select_appointment(selected_id)

    def _email_callback(self, success: bool, error: str | None) -> None:
        self._email_signals.completed.emit(success, error or "")

    def _show_email_result(self, success: bool, error: str) -> None:
        if not success:
            QMessageBox.warning(
                self,
                "Email notification",
                "Saved, but the email could not be sent"
                + (f": {error}" if error else ""),
            )

    def _highlight_appointment_dates(self) -> None:
        for old_date in self._highlighted_dates:
            self._calendar.setDateTextFormat(
                QDate.fromString(old_date.isoformat(), "yyyy-MM-dd"),
                QTextCharFormat(),
            )
        self._highlighted_dates.clear()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#f1c5d8"))
        fmt.setForeground(QColor("#553d4b"))
        for appointment in self._appointments:
            appointment_date = self._as_datetime(appointment.appointment_time).date()
            self._highlighted_dates.add(appointment_date)
        for appointment_date in self._highlighted_dates:
            qt_date = QDate.fromString(appointment_date.isoformat(), "yyyy-MM-dd")
            self._calendar.setDateTextFormat(qt_date, fmt)
        self._format_schedule_calendar()

    def _format_schedule_calendar(
        self, year: int | None = None, month: int | None = None
    ) -> None:
        year = year or self._calendar.yearShown()
        month = month or self._calendar.monthShown()
        from calendar import monthrange

        from datetime import date

        days = monthrange(year, month)[1]
        first = date(year, month, 1)
        last = date(year, month, days)
        schedule = self._appointment_manager.schedule_manager
        try:
            closed_dates = schedule.get_closed_dates(first, last)
            closure_dates = {
                selected_day
                for selected_day in closed_dates
                if schedule.get_closures_for_date(selected_day)
            }
        except (sqlite3.Error, TypeError, ValueError) as error:
            self._show_error("Could not load schedule calendar", error)
            return
        for day in range(1, days + 1):
            selected_day = first.replace(day=day)
            fmt = QTextCharFormat()
            if selected_day in closed_dates:
                fmt.setForeground(QColor("#a9a2a0"))
                if selected_day in closure_dates:
                    fmt.setBackground(QColor("#eadfce"))
            elif selected_day in self._highlighted_dates:
                fmt.setBackground(QColor("#f1c5d8"))
                fmt.setForeground(QColor("#553d4b"))
            self._calendar.setDateTextFormat(
                QDate(year, month, day), fmt
            )

    def _refresh_selected_day(self, *signal_args: object) -> None:
        del signal_args
        selected_date = self._calendar.selectedDate().toPyDate()
        if self._view_mode.currentText() == "Week":
            week_start = selected_date - timedelta(
                days=(selected_date.weekday() + 1) % 7
            )
            week_end = week_start + timedelta(days=6)
        else:
            week_start = week_end = selected_date
        status_text = self._status_filter.currentText().upper()
        status_value = "NO_SHOW" if status_text == "NO-SHOW" else status_text
        day_appointments = [
            appointment
            for appointment in self._appointments
            if week_start
            <= self._as_datetime(appointment.appointment_time).date()
            <= week_end
            and (
                status_value == "ALL"
                or appointment.status.value == status_value
            )
        ]
        self._appointment_table.setRowCount(0)
        for appointment in day_appointments:
            row = self._appointment_table.rowCount()
            self._appointment_table.insertRow(row)
            appointment_time = self._as_datetime(appointment.appointment_time)
            end_time = appointment.get_end_time()
            try:
                client_name = self._appointment_manager.get_client_name(
                    appointment.client_email
                )
                service_name = self._appointment_manager.get_service_name(
                    appointment.service_id
                )
            except (KeyError, sqlite3.Error) as error:
                self._show_error("Could not load appointment details", error)
                return
            values = {
                "day": appointment_time.strftime("%a"),
                "start_time": appointment_time.strftime("%H:%M"),
                "end_time": end_time.strftime("%H:%M"),
                "duration": format_duration(appointment.duration_minutes),
                "client": client_name,
                "service": service_name,
                "nail_length": appointment.nail_length,
                "add_ons": ", ".join(appointment.design_add_ons),
                "extras": ", ".join(appointment.selected_extras),
                "total_price": f"₱ {appointment.total_price:,.2f}",
                "travel_fee": f"₱ {appointment.travel_fee:,.2f}",
                "cancellation_fee": f"₱ {appointment.cancellation_fee:,.2f}",
                "status": appointment.status.value,
                "allergies": appointment.allergies,
                "visit_type": appointment.visit_type.value.replace("_", " "),
                "final_price": f"₱ {appointment.final_price:,.2f}",
                "paid": f"₱ {appointment.amount_paid:,.2f}",
                "balance": f"₱ {appointment.balance:,.2f}",
            }
            for column, key in enumerate(self._table_columns):
                value = values[key]
                item = QTableWidgetItem(value)
                if key == "allergies":
                    item.setToolTip(value or "None reported")
                if key == "balance" and appointment.balance > 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if key == "start_time":
                    item.setData(Qt.ItemDataRole.UserRole, appointment.appointment_id)
                self._appointment_table.setItem(row, column, item)
        self._update_action_buttons()

    def _show_appointment_details(self, row: int, _column: int) -> None:
        item = self._appointment_table.item(row, 1)
        appointment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(appointment_id, int):
            return
        self.show_appointment_details(appointment_id)

    def show_appointment_details(self, appointment_id: int) -> None:
        try:
            appointment = self._appointment_manager.get_appointment(appointment_id)
        except (KeyError, sqlite3.Error) as error:
            self._show_error("Could not load appointment details", error)
            return
        details = (
            f"Client: {appointment.client_email}\n"
            f"Notes: {appointment.notes or 'None'}\n"
            f"Allergies: {appointment.allergies or 'None reported'}\n"
            f"Visit type: {appointment.visit_type.value.replace('_', ' ')}\n"
        )
        if self._can_record_payments:
            extras_text = ", ".join(
                f"{name} (₱ {price:,.2f})"
                for name, price in appointment.selected_extras.items()
            )
        else:
            extras_text = ", ".join(appointment.selected_extras)
        details += f"Extras: {extras_text or 'None'}\n"
        open_address_callback = None
        if appointment.visit_type is VisitType.HOME_SERVICE:
            service_address, town = HomeServiceMapDialog._parse_service_address(
                appointment.service_address
            )
            address_text = service_address or "No service address was provided."
            details += f"Address: {address_text}\n"
            if town:
                details += f"Town: {town}\n"
            if self._can_record_payments:
                details += f"Travel fee: ₱ {appointment.travel_fee:,.2f}\n"
            open_address_callback = lambda: self._open_address(
                appointment.service_address
            )
        if self._can_record_payments:
            details += (
                f"Total price: ₱ {appointment.total_price:,.2f}\n"
                f"Cancellation fee: ₱ {appointment.cancellation_fee:,.2f}\n"
                f"Final price: ₱ {appointment.final_price:,.2f}\n"
                f"Paid: ₱ {appointment.amount_paid:,.2f}\n"
                f"Balance: ₱ {appointment.balance:,.2f}\n"
                f"Payment note: {appointment.payment_note or 'None'}"
            )
        details_dialog = AppointmentDetailsDialog(
            details, open_address_callback, self
        )
        details_dialog.exec()

    def view_selected_on_map(self) -> None:
        appointment = self._selected_appointment()
        if appointment is None or appointment.visit_type is not VisitType.HOME_SERVICE:
            return
        HomeServiceMapDialog(
            appointment,
            self._studio_settings_manager,
            self._can_record_payments,
            self,
        ).exec()

    def show_stamp_qr_selected(self) -> None:
        try:
            self._show_stamp_qr_dialog()
        except Exception as error:
            QMessageBox.critical(
                self,
                "Could not show stamp QR",
                f"Could not show the stamp QR: {error}",
            )

    def _show_stamp_qr_dialog(self) -> None:
        appointment = self._selected_appointment()
        loyalty_manager = self._loyalty_manager
        server = self._loyalty_web_server
        if (
            appointment is None
            or appointment.appointment_id is None
            or appointment.status is not AppointmentStatus.COMPLETED
            or loyalty_manager is None
            or server is None
        ):
            return
        try:
            if get_lan_ip() is None:
                QMessageBox.warning(
                    self,
                    "Network unavailable",
                    "No network is available. Connect this computer to Wi-Fi "
                    "before creating a stamp QR.",
                )
                return
            if not server.is_running:
                QMessageBox.information(
                    self,
                    "Loyalty server is stopped",
                    "Start the loyalty web server in Studio Settings before "
                    "showing a stamp QR.",
                )
                return
        except Exception as error:
            QMessageBox.critical(
                self,
                "Could not show stamp QR",
                f"Could not show the stamp QR: {error}",
            )
            return

        dialog = StampQrDialog(self)
        image_label = dialog.image_label
        link_label = dialog.link_label
        countdown = dialog.countdown_label
        generate_button = dialog.generate_button
        countdown_timer = QTimer(dialog)
        remaining_seconds = 120

        def show_error(error: Exception) -> None:
            countdown_timer.stop()
            QMessageBox.critical(
                self,
                "Could not show stamp QR",
                f"Could not show the stamp QR: {error}",
            )

        def show_countdown() -> bool:
            try:
                minutes, seconds = divmod(remaining_seconds, 60)
                countdown.setText(f"QR expires in {minutes}:{seconds:02d}")
            except Exception as error:
                show_error(error)
                return False
            return True

        def update_countdown() -> None:
            nonlocal remaining_seconds
            try:
                remaining_seconds -= 1
                if remaining_seconds <= 0:
                    countdown_timer.stop()
                    countdown.setText("QR expired")
                    image_label.clear()
                    link_label.clear()
                    generate_button.show()
                    return
                if not show_countdown():
                    return
            except Exception as error:
                show_error(error)

        def generate_qr() -> bool:
            nonlocal remaining_seconds
            try:
                if loyalty_manager.has_stamp_for_appointment(
                    appointment.appointment_id
                ):
                    raise ValueError(
                        "This appointment has already earned a stamp."
                    )
                token = loyalty_manager.create_stamp_token(
                    appointment.appointment_id
                )
                link = server.build_url(f"/stamp/{token}")
                import qrcode

                image = qrcode.make(link)
                image_bytes = BytesIO()
                image.save(image_bytes, format="PNG")
                qr_pixmap = QPixmap()
                if not qr_pixmap.loadFromData(image_bytes.getvalue(), "PNG"):
                    raise RuntimeError("Could not render the stamp QR code")
            except Exception as error:
                show_error(error)
                return False
            try:
                image_label.setPixmap(
                    qr_pixmap.scaled(
                        340,
                        340,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                link_label.setText(link)
                remaining_seconds = 120
                if not show_countdown():
                    return False
                generate_button.hide()
                countdown_timer.start(1000)
            except Exception as error:
                show_error(error)
                return False
            return True

        generate_button.clicked.connect(generate_qr)
        countdown_timer.timeout.connect(update_countdown)
        if generate_qr():
            dialog.exec()

    @staticmethod
    def _open_address(address: str) -> None:
        url = QUrl(
            "https://www.google.com/maps/search/?api=1&query="
            + quote(address, safe="")
        )
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                None, "Could not open map", "The address could not be opened."
            )

    def _selected_appointment(self) -> Appointment | None:
        row = self._appointment_table.currentRow()
        if row < 0:
            return None
        item = self._appointment_table.item(row, 1)
        appointment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next(
            (
                appointment
                for appointment in self._appointments
                if appointment.appointment_id == appointment_id
            ),
            None,
        )

    def _update_action_buttons(self) -> None:
        appointment = self._selected_appointment()
        pending = appointment is not None and appointment.status is AppointmentStatus.PENDING
        confirmed = appointment is not None and appointment.status is AppointmentStatus.CONFIRMED
        active = pending or confirmed
        self._confirm_button.setEnabled(pending)
        self._complete_button.setEnabled(confirmed)
        self._cancel_button.setEnabled(active)
        self._reschedule_button.setEnabled(active)
        self._edit_duration_button.setEnabled(active)
        self._no_show_button.setEnabled(confirmed)
        is_home_service = (
            appointment is not None
            and appointment.visit_type is VisitType.HOME_SERVICE
        )
        self._view_on_map_button.setVisible(is_home_service)
        self._view_on_map_button.setEnabled(is_home_service)
        if self._can_record_payments:
            self._record_payment_button.setEnabled(
                appointment is not None
                and appointment.status
                in (AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED)
            )
            self._edit_travel_fee_button.setEnabled(
                appointment is not None
                and appointment.status is AppointmentStatus.PENDING
                and appointment.visit_type is VisitType.HOME_SERVICE
            )
        if self._can_show_stamp_qr:
            can_issue = (
                appointment is not None
                and appointment.status is AppointmentStatus.COMPLETED
                and appointment.appointment_id is not None
            )
            if can_issue and self._loyalty_manager is not None:
                try:
                    can_issue = not self._loyalty_manager.has_stamp_for_appointment(
                        appointment.appointment_id
                    )
                except sqlite3.Error as error:
                    can_issue = False
                    self._show_error("Could not check loyalty stamp", error)
            self._show_stamp_qr_button.setEnabled(can_issue)

    def _select_appointment(self, appointment_id: int | None) -> None:
        if appointment_id is None:
            return
        for row in range(self._appointment_table.rowCount()):
            item = self._appointment_table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == appointment_id:
                self._appointment_table.selectRow(row)
                return

    @staticmethod
    def _as_datetime(value: datetime | str) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
