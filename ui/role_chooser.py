from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from ui.branding import brand_circular_pixmap, brand_icon
from ui.navigation_icons import navigation_icon
from services.account_manager import AccountManager
from ui.account_dialogs import FirstAdminDialog, LoginDialog


class RoleChooser(QWidget):
    def __init__(
        self,
        window_factories: dict[str, Callable[..., QMainWindow]],
        account_manager: AccountManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("roleChooser")
        required_roles = {"Customer", "Staff", "Admin"}
        if set(window_factories) != required_roles:
            raise ValueError(
                "Provide exactly one window factory for Customer, Staff, and Admin")

        self._window_factories = window_factories.copy()
        self._account_manager = account_manager
        self._open_windows: dict[str, QMainWindow] = {}
        self.setWindowIcon(brand_icon())
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 36)
        layout.setSpacing(18)

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
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        buttons = QHBoxLayout()
        role_icons = {
            "Customer": "customer",
            "Staff": "staff",
            "Admin": "admin",
        }
        for role in ("Customer", "Staff", "Admin"):
            button = QPushButton(role)
            button.setProperty("navigation", True)
            button.setIcon(navigation_icon(role_icons[role]))
            button.setIconSize(QSize(18, 18))
            button.setMinimumSize(180, 68)
            button.clicked.connect(
                lambda checked=False, selected_role=role: self.open_role(
                    selected_role)
            )
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch()

    def open_customer(self) -> QMainWindow:
        return self.open_role("Customer")

    def open_staff(self) -> QMainWindow | None:
        return self.open_role("Staff")

    def open_admin(self) -> QMainWindow | None:
        return self.open_role("Admin")

    def open_role(self, role: str) -> QMainWindow | None:
        if role not in self._window_factories:
            raise ValueError(f"Unknown role: {role}")
        if role == "Customer":
            window = self._open_windows.get(role)
            if window is None:
                window = self._window_factories[role]()
                self._open_windows[role] = window
        else:
            if role == "Admin" and not self._account_manager.has_active_account(
                "ADMIN"
            ):
                dialog = FirstAdminDialog(self._account_manager, self)
                if dialog.exec() != dialog.DialogCode.Accepted:
                    return None
                account_user = dialog.account_user
            else:
                dialog = LoginDialog(self._account_manager, role, self)
                if dialog.exec() != dialog.DialogCode.Accepted:
                    return None
                account_user = dialog.account_user
            if account_user is None:
                return None
            previous_window = self._open_windows.pop(role, None)
            if previous_window is not None:
                previous_window.hide()
                previous_window.deleteLater()
            if role == "Staff" and account_user.get_role_name() == "Admin":
                admin_window = self._open_windows.get("Admin")
                if admin_window is None:
                    admin_window = self._window_factories["Admin"](
                        account_user)
                    set_logout_callback = getattr(
                        admin_window, "set_logout_callback", None
                    )
                    if callable(set_logout_callback):
                        set_logout_callback(
                            lambda: self._return_to_chooser("Admin")
                        )
                    self._open_windows["Admin"] = admin_window
                admin_window.hide()
            window = self._window_factories[role](account_user)
            set_logout_callback = getattr(window, "set_logout_callback", None)
            if callable(set_logout_callback):
                set_logout_callback(
                    lambda: self._return_to_chooser(
                        role, close_admin=(
                            role == "Staff" and account_user.get_role_name() == "Admin")
                    )
                )
            if role == "Staff" and account_user.get_role_name() == "Admin":
                set_back_callback = getattr(
                    window, "set_back_to_admin_callback", None)
                if callable(set_back_callback):
                    set_back_callback(self._return_to_admin)
            self._open_windows[role] = window
        window.show()
        window.raise_()
        window.activateWindow()
        if role != "Customer":
            self.hide()
        return window

    def _return_to_chooser(self, role: str, close_admin: bool = False) -> None:
        roles_to_close = (role, "Admin") if close_admin else (role,)
        for selected_role in roles_to_close:
            window = self._open_windows.pop(selected_role, None)
            if window is not None:
                window.hide()
                window.deleteLater()
        self.show()
        self.raise_()
        self.activateWindow()

    def _return_to_admin(self) -> None:
        staff_window = self._open_windows.pop("Staff", None)
        if staff_window is not None:
            staff_window.hide()
            staff_window.deleteLater()
        admin_window = self._open_windows.get("Admin")
        if admin_window is None:
            raise RuntimeError("The Admin window is unavailable")
        admin_window.show()
        admin_window.raise_()
        admin_window.activateWindow()
