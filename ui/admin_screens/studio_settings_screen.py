import sqlite3
import shutil
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from services.studio_settings_manager import StudioSettingsManager
from services.loyalty_web_server import LoyaltyWebServer
from models import User
from ui.base_page import BasePage


class StudioSettingsScreen(BasePage):
    """Admin editor for validated home-service settings."""

    def __init__(
        self,
        settings_manager: StudioSettingsManager,
        parent=None,
        loyalty_web_server: LoyaltyWebServer | None = None,
        role: User | None = None,
    ) -> None:
        self._settings_manager = settings_manager
        self._loyalty_web_server = loyalty_web_server
        self._role = role
        super().__init__({"studio_settings_manager": settings_manager}, parent)
        self.refresh()
        self._server_status_timer = QTimer(self)
        self._server_status_timer.timeout.connect(self._refresh_server_status)
        self._server_status_timer.start(2000)

    @property
    def settings_manager(self) -> StudioSettingsManager:
        return self._settings_manager

    def build_ui(self) -> None:
        self._travel_fee = QDoubleSpinBox()
        self._travel_fee.setRange(0, 1_000_000)
        self._travel_fee.setDecimals(2)
        self._travel_fee.setPrefix("₱ ")
        self._travel_buffer = QSpinBox()
        self._travel_buffer.setRange(0, 600)
        self._travel_buffer.setSingleStep(5)
        self._travel_buffer.setSuffix(" minutes")
        self._cleaning_buffer = QSpinBox()
        self._cleaning_buffer.setRange(0, 600)
        self._cleaning_buffer.setSingleStep(5)
        self._cleaning_buffer.setSuffix(" minutes")
        self._service_area_note = QTextEdit()
        self._service_area_note.setMaximumHeight(110)
        self._allowed_areas = QLineEdit()
        self._allowed_areas.setPlaceholderText("Pila, Santa Cruz")
        self._studio_address = QLineEdit()
        self._maps_embed_url = QLineEdit()
        self._maps_embed_url.setPlaceholderText("Paste Google Maps embed URL")
        self._map_latitude = QLineEdit()
        self._map_longitude = QLineEdit()
        self._map_image_path = ""
        choose_map_picture = QPushButton("Choose map picture")
        choose_map_picture.clicked.connect(self.choose_map_picture)
        self._map_image_preview = QLabel("No map picture selected")
        self._map_image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._map_image_preview.setMinimumHeight(120)
        self._loyalty_web_port = QSpinBox()
        self._loyalty_web_port.setRange(1, 65535)
        self._loyalty_web_port.setValue(8765)
        self._loyalty_web_toggle = QCheckBox("Run loyalty card web server")
        self._loyalty_web_toggle.toggled.connect(self._set_web_server_running)
        self._loyalty_web_status = QLabel("Stopped")
        self._loyalty_web_status.setWordWrap(True)
        self._loyalty_facebook = QLineEdit()
        self._loyalty_phone = QLineEdit()
        self._owner_provider_name = QLineEdit()
        self._review_url = QLineEdit()
        self._online_booking_url = QLineEdit()
        self._map_link_url = QLineEdit()
        self._minimum_spend_per_appointment = QDoubleSpinBox()
        self._minimum_spend_per_appointment.setRange(0, 1_000_000)
        self._minimum_spend_per_appointment.setDecimals(2)
        self._minimum_spend_per_appointment.setPrefix("P ")
        self._loyalty_terms = QTextEdit()
        self._loyalty_terms.setMaximumHeight(150)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_settings)

        form = QFormLayout()
        form.addRow(
            "Default travel fee (0 = the owner sets it per booking)",
            self._travel_fee,
        )
        form.addRow("Travel buffer before and after", self._travel_buffer)
        form.addRow("Cleaning buffer after appointments", self._cleaning_buffer)
        form.addRow("Service area note", self._service_area_note)
        form.addRow("Allowed towns / municipalities", self._allowed_areas)
        form.addRow("Studio address", self._studio_address)
        form.addRow("Google Maps embed URL", self._maps_embed_url)
        form.addRow("Map latitude", self._map_latitude)
        form.addRow("Map longitude", self._map_longitude)
        form.addRow(choose_map_picture, self._map_image_preview)
        form.addRow("Loyalty web server port", self._loyalty_web_port)
        form.addRow("Loyalty web server", self._loyalty_web_toggle)
        form.addRow("Server status", self._loyalty_web_status)
        form.addRow("Loyalty Facebook handle", self._loyalty_facebook)
        form.addRow("Owner / provider name", self._owner_provider_name)
        form.addRow("Review URL (optional)", self._review_url)
        form.addRow("Online booking link (URL)", self._online_booking_url)
        form.addRow("Map link (URL)", self._map_link_url)
        form.addRow(
            "Minimum spend per appointment",
            self._minimum_spend_per_appointment,
        )
        form.addRow("Loyalty contact phone", self._loyalty_phone)
        form.addRow("Loyalty terms (one per line)", self._loyalty_terms)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Studio Settings"))
        layout.addLayout(form)
        layout.addWidget(save_button)
        layout.addStretch()

    def refresh(self) -> None:
        try:
            settings = self._settings_manager.get_settings()
            loyalty_web_port = self._settings_manager.get_loyalty_web_port()
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not load studio settings", str(error))
            return
        self._travel_fee.setValue(settings.default_travel_fee)
        self._travel_buffer.setValue(settings.travel_buffer_minutes)
        self._cleaning_buffer.setValue(settings.cleaning_buffer_minutes)
        self._service_area_note.setPlainText(settings.service_area_note)
        self._allowed_areas.setText(", ".join(settings.allowed_areas))
        self._studio_address.setText(settings.studio_address)
        self._maps_embed_url.setText(settings.maps_embed_url)
        self._map_latitude.setText(settings.map_latitude)
        self._map_longitude.setText(settings.map_longitude)
        self._map_image_path = settings.map_image_path
        self._show_map_image(self._resolve_map_image_path(self._map_image_path))
        self._loyalty_web_port.setValue(loyalty_web_port)
        self._loyalty_facebook.setText(settings.loyalty_facebook)
        self._owner_provider_name.setText(settings.owner_provider_name)
        self._review_url.setText(settings.review_url)
        self._online_booking_url.setText(settings.online_booking_url)
        self._map_link_url.setText(settings.map_link_url)
        self._minimum_spend_per_appointment.setValue(
            settings.minimum_spend_per_appointment
        )
        self._loyalty_phone.setText(settings.loyalty_phone)
        self._loyalty_terms.setPlainText(settings.loyalty_terms)
        self._refresh_server_status()

    def save_settings(self) -> None:
        maps_embed_url = self._maps_embed_url.text().strip()
        if maps_embed_url and not maps_embed_url.startswith(
            "https://www.google.com/maps/embed"
        ):
            QMessageBox.warning(
                self,
                "Invalid Google Maps embed URL",
                "The embed URL must start with https://www.google.com/maps/embed.",
            )
            return
        try:
            port = self._loyalty_web_port.value()
            self._settings_manager.set_loyalty_web_port(port, self._role)
            if (
                self._loyalty_web_server is not None
                and not self._loyalty_web_server.is_running
            ):
                self._loyalty_web_server.configure_port(port)
            self._settings_manager.update_settings(
                self._travel_fee.value(),
                self._travel_buffer.value(),
                self._service_area_note.toPlainText(),
                [
                    area.strip()
                    for area in self._allowed_areas.text().split(",")
                    if area.strip()
                ],
                self._cleaning_buffer.value(),
                self._studio_address.text(),
                maps_embed_url,
                self._map_latitude.text(),
                self._map_longitude.text(),
                self._map_image_path,
                self._loyalty_facebook.text(),
                self._loyalty_phone.text(),
                self._loyalty_terms.toPlainText(),
                self._owner_provider_name.text(),
                self._review_url.text(),
                self._online_booking_url.text(),
                self._minimum_spend_per_appointment.value(),
                self._map_link_url.text(),
                role=self._role,
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid studio settings", str(error))
            return
        QMessageBox.information(self, "Studio settings", "Settings saved.")

    def choose_map_picture(self) -> None:
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose map picture",
            "",
            "Map pictures (*.png *.jpg *.jpeg)",
        )
        if not selected_path:
            return
        source = Path(selected_path)
        if source.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            QMessageBox.warning(
                self, "Invalid map picture", "Choose a PNG or JPG image."
            )
            return
        try:
            if source.stat().st_size > 5 * 1024 * 1024:
                QMessageBox.warning(
                    self,
                    "Map picture too large",
                    "The map picture must be 5 MB or smaller.",
                )
                return
        except OSError as error:
            QMessageBox.warning(self, "Could not read map picture", str(error))
            return
        pixmap = QPixmap(str(source))
        if pixmap.isNull():
            QMessageBox.warning(
                self, "Invalid map picture", "The selected image could not be loaded."
            )
            return

        project_root = Path(__file__).resolve().parents[2]
        map_directory = project_root / "assets" / "map"
        destination = map_directory / source.name
        try:
            map_directory.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)
        except OSError as error:
            QMessageBox.warning(self, "Could not copy map picture", str(error))
            return
        self._map_image_path = str(destination.relative_to(project_root))
        self._show_map_image(destination, pixmap)

    def _set_web_server_running(self, should_run: bool) -> None:
        server = self._loyalty_web_server
        if server is None:
            return
        try:
            if should_run:
                port = self._loyalty_web_port.value()
                self._settings_manager.set_loyalty_web_port(port, self._role)
                server.configure_port(port)
                server.start()
            else:
                server.stop()
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
            QMessageBox.warning(
                self, "Loyalty web server", f"Could not update the server: {error}"
            )
            with QSignalBlocker(self._loyalty_web_toggle):
                self._loyalty_web_toggle.setChecked(server.is_running)
        self._refresh_server_status()

    def _refresh_server_status(self) -> None:
        server = self._loyalty_web_server
        if server is None:
            self._loyalty_web_status.setText("Stopped")
            self._loyalty_web_toggle.setEnabled(False)
            self._loyalty_web_port.setEnabled(False)
            return
        self._loyalty_web_status.setText(server.status_text)
        running = server.is_running
        with QSignalBlocker(self._loyalty_web_toggle):
            self._loyalty_web_toggle.setChecked(running)
        self._loyalty_web_port.setEnabled(not running)

    @staticmethod
    def _resolve_map_image_path(image_path: str) -> Path | None:
        if not image_path:
            return None
        path = Path(image_path)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    def _show_map_image(
        self, image_path: Path | None, pixmap: QPixmap | None = None
    ) -> None:
        if pixmap is None:
            image = QPixmap(str(image_path)) if image_path else QPixmap()
        else:
            image = pixmap
        if image.isNull():
            self._map_image_preview.setPixmap(QPixmap())
            self._map_image_preview.setText("No map picture selected")
            return
        self._map_image_preview.setText("")
        self._map_image_preview.setPixmap(
            image.scaled(
                360,
                220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
