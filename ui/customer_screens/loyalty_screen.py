import calendar
from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.loyalty_manager import LoyaltyManager
from services.studio_settings_manager import StudioSettingsManager
from ui.base_page import BasePage
from ui.branding import brand_circular_pixmap


class LoyaltyScreen(BasePage):
    """Explain the phone-based loyalty card to customers."""

    def __init__(
        self,
        loyalty_manager: LoyaltyManager,
        parent=None,
        settings_manager: StudioSettingsManager | None = None,
    ) -> None:
        self._loyalty_manager = loyalty_manager
        self._settings_manager = settings_manager
        super().__init__(
            {
                "loyalty_manager": loyalty_manager,
                "studio_settings_manager": settings_manager,
            },
            parent,
        )

    @property
    def loyalty_manager(self) -> LoyaltyManager:
        return self._loyalty_manager

    def build_ui(self) -> None:
        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 18, 16, 18)
        card_layout.setSpacing(14)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(76, 76)
        logo.setPixmap(brand_circular_pixmap(72))

        title = QLabel("Your loyalty card")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #8A5A6A; font-size: 20px; font-weight: 700;"
        )

        self._steps_layout = QVBoxLayout()
        self._steps_layout.setSpacing(12)
        self._step_labels: list[QLabel] = []

        card_layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)
        card_layout.addWidget(title)
        card_layout.addLayout(self._steps_layout)

        self._terms_card = QFrame()
        self._terms_card.setProperty("card", True)
        terms_layout = QVBoxLayout(self._terms_card)
        terms_layout.setContentsMargins(16, 16, 16, 16)
        terms_layout.setSpacing(8)
        terms_title = QLabel("Terms & Conditions")
        terms_title.setStyleSheet(
            "color: #8A5A6A; font-size: 16px; font-weight: 700;"
        )
        terms_layout.addWidget(terms_title)
        self._terms_items_layout = QVBoxLayout()
        self._terms_items_layout.setSpacing(6)
        terms_layout.addLayout(self._terms_items_layout)
        self._valid_until_label = QLabel()
        self._valid_until_label.setWordWrap(True)
        terms_layout.addWidget(self._valid_until_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._terms_card, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

    def refresh(self) -> None:
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._step_labels.clear()

        minimum_spend = self._loyalty_manager.get_minimum_spend_per_appointment()
        instructions = (
            (
                f"Earn one stamp for each completed appointment with a total "
                f"of at least P{minimum_spend:g} (travel fees do not count)."
            ),
            "Your nail technician will show you a QR code. Scan it with your phone camera to get your stamp.",
            "Your card page opens while your phone is connected to the studio's Wi-Fi.",
            "At 5 and 10 stamps, you earn a prize draw entry. The card resets each month.",
        )
        for index, instruction in enumerate(instructions, start=1):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            number = QLabel(str(index))
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFixedSize(28, 28)
            number.setStyleSheet(
                "background-color: #f8e5e3; color: #8A5A6A; "
                "border-radius: 14px; font-weight: 700;"
            )
            text = QLabel(instruction)
            text.setWordWrap(True)
            text.setMinimumWidth(0)
            text.setStyleSheet("color: #3f3437;")
            row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            self._steps_layout.addWidget(row_widget)
            self._step_labels.append(text)

        settings = (
            self._settings_manager.get_settings()
            if self._settings_manager is not None
            else None
        )
        while self._terms_items_layout.count():
            item = self._terms_items_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if settings is None:
            self._terms_card.setVisible(False)
            return

        self._terms_card.setVisible(True)
        for term in settings.loyalty_terms.splitlines():
            if not term.strip():
                continue
            bullet = QLabel(f"• {term.strip()}")
            bullet.setTextFormat(Qt.TextFormat.PlainText)
            bullet.setWordWrap(True)
            bullet.setMinimumWidth(0)
            bullet.setStyleSheet("color: #3f3437;")
            self._terms_items_layout.addWidget(bullet)
        current_date = date.today()
        last_day = calendar.monthrange(current_date.year, current_date.month)[1]
        self._valid_until_label.setText(
            f"Valid until "
            f"{date(current_date.year, current_date.month, last_day):%B %d, %Y}."
        )
