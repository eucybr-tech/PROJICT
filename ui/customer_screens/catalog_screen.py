import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models import Service, format_duration
from services.service_manager import ServiceManager
from ui.base_page import BasePage


class CatalogScreen(BasePage):
    """Read-only catalog of salon services and their price options."""

    # Inheritance and dependency injection: BasePage receives the service manager.
    def __init__(self, service_manager: ServiceManager, parent=None) -> None:
        self._service_manager = service_manager
        self._services: list[Service] = []
        super().__init__({"service_manager": service_manager}, parent)
        self.refresh()

    @property
    def service_manager(self) -> ServiceManager:
        return self._service_manager

    def build_ui(self) -> None:
        self._empty_message = QLabel("Our service catalog will be available soon.")
        self._empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_message.setWordWrap(True)

        self._cards = QWidget()
        self._cards_layout = QVBoxLayout(self._cards)
        self._cards_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_layout.setSpacing(12)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setWidget(self._cards)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self._empty_message, 1)
        self._content_layout.addWidget(self._scroll_area, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.addWidget(self._content)

    def refresh(self) -> None:
        try:
            self._services = self._service_manager.get_services()
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not load catalog", str(error))
            return
        self._clear_cards()
        has_services = bool(self._services)
        self._empty_message.setVisible(not has_services)
        self._scroll_area.setVisible(has_services)
        for service in self._services:
            self._cards_layout.addWidget(self._build_card(service))
        self._cards_layout.addStretch()

    def _build_card(self, service: Service) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)

        name = QLabel(service.name)
        name.setStyleSheet("color: #81566d; font-size: 18px; font-weight: 700;")
        description = QLabel(service.description or "A signature salon service.")
        description.setWordWrap(True)
        base_price = QLabel(f"Base price: ₱{service.base_price:,.2f}")
        base_price.setStyleSheet("font-weight: 600;")
        duration = QLabel(f"Duration: {format_duration(service.duration_minutes)}")

        length_lines = [
            f"{name}: ₱{price:,.2f}"
            for name, price in service.length_prices.items()
        ]
        add_on_lines = [
            f"{name}: ₱{price:,.2f}"
            for name, price in service.design_add_on_prices.items()
        ]
        lengths = QLabel(
            "Nail length prices:\n" + ("\n".join(length_lines) or "No options listed")
        )
        add_ons = QLabel(
            "Design add-ons:\n" + ("\n".join(add_on_lines) or "No add-ons listed")
        )
        lengths.setWordWrap(True)
        add_ons.setWordWrap(True)

        layout.addWidget(name)
        layout.addWidget(description)
        layout.addWidget(base_price)
        layout.addWidget(duration)
        layout.addWidget(lengths)
        layout.addWidget(add_ons)
        return card

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
