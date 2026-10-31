from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from services.loyalty_manager import LoyaltyManager
from ui.base_page import BasePage
from ui.branding import brand_circular_pixmap


class LoyaltyScreen(BasePage):
    """Explain the phone-based loyalty card to customers."""

    def __init__(self, loyalty_manager: LoyaltyManager, parent=None) -> None:
        self._loyalty_manager = loyalty_manager
        super().__init__({"loyalty_manager": loyalty_manager}, parent)

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

    def refresh(self) -> None:
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._step_labels.clear()

        stamps_required = self._loyalty_manager.get_stamps_required()
        instructions = (
            "Earn a stamp after each completed visit.",
            "Your nail technician will show you a QR code. Scan it with your phone camera to get your stamp.",
            "Your card page opens while your phone is connected to the studio's Wi-Fi.",
            (
                f"Collect {stamps_required} stamps to earn your reward. "
                "You receive your reward at the studio."
            ),
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
