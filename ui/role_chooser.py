from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from ui.branding import brand_circular_pixmap, brand_icon


class RoleChooser(QWidget):
    def __init__(
        self,
        window_factories: dict[str, Callable[[], QMainWindow]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        required_roles = {"Customer", "Staff", "Admin"}
        if set(window_factories) != required_roles:
            raise ValueError("Provide exactly one window factory for Customer, Staff, and Admin")

        self._window_factories = window_factories.copy()
        self._open_windows: dict[str, QMainWindow] = {}
        self.setWindowIcon(brand_icon())
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pixmap = brand_circular_pixmap(120)
        if not logo_pixmap.isNull():
            logo.setPixmap(logo_pixmap)
        else:
            logo.setText("P")
            logo.setFixedSize(120, 120)
            logo.setStyleSheet(
                "background: #F4B4B8; color: #8A5A6A; border-radius: 60px; "
                "font-size: 44px; font-weight: 700;"
            )
        layout.addWidget(logo)

        title = QLabel("Pearl's SigNAILture")
        title.setObjectName("appTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Choose a view to continue")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        buttons = QHBoxLayout()
        for role in ("Customer", "Staff", "Admin"):
            button = QPushButton(role)
            button.setMinimumHeight(56)
            button.clicked.connect(
                lambda checked=False, selected_role=role: self.open_role(selected_role)
            )
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch()

    def open_customer(self) -> QMainWindow:
        return self.open_role("Customer")

    def open_staff(self) -> QMainWindow:
        return self.open_role("Staff")

    def open_admin(self) -> QMainWindow:
        return self.open_role("Admin")

    def open_role(self, role: str) -> QMainWindow:
        if role not in self._window_factories:
            raise ValueError(f"Unknown role: {role}")
        window = self._open_windows.get(role)
        if window is None:
            window = self._window_factories[role]()
            self._open_windows[role] = window
        window.show()
        window.raise_()
        window.activateWindow()
        return window
