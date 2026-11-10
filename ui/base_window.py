from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.branding import brand_icon
from ui.navigation_icons import navigation_icon
from models import User


class BaseWindow(QMainWindow):
    """Shared window shell and screen-switching behavior for each role."""

    def __init__(
        self,
        title: str,
        authenticated_user: User | None = None,
        logout_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(brand_icon())
        self._authenticated_user = authenticated_user
        self._logout_callback = logout_callback
        self._screens: dict[str, QWidget] = {}
        self._screen_containers: dict[str, QWidget] = {}
        self._stack = QStackedWidget()

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.build_navigation())
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(content)

    def build_navigation(self) -> QWidget:
        """Overridden by role windows to provide role-specific navigation."""
        return QWidget(self)

    def add_account_controls(self, layout: QVBoxLayout) -> None:
        if self._authenticated_user is None:
            return
        identity = QLabel(
            f"{self._authenticated_user.name} "
            f"({self._authenticated_user.get_role_name()})"
        )
        identity.setWordWrap(True)
        layout.addWidget(identity)
        logout_button = QPushButton("Log out")
        logout_button.setProperty("navigation", True)
        logout_button.setIcon(navigation_icon("logout"))
        logout_button.setIconSize(QSize(18, 18))
        logout_button.clicked.connect(self._logout)
        layout.addWidget(logout_button)

    def set_logout_callback(self, callback: Callable[[], None]) -> None:
        self._logout_callback = callback

    def _logout(self) -> None:
        if self._logout_callback is not None:
            self._logout_callback()
        else:
            self.hide()

    def add_screen(
        self, name: str, screen: QWidget, scrollable: bool = False
    ) -> None:
        if not name.strip():
            raise ValueError("Screen name must not be empty")
        if name in self._screens:
            raise ValueError(f"A screen named {name!r} is already registered")
        self._screens[name] = screen
        stacked_widget = screen
        if scrollable:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setWidget(screen)
            stacked_widget = area
        self._screen_containers[name] = stacked_widget
        self._stack.addWidget(stacked_widget)

    def show_screen(self, screen_name: str) -> None:
        try:
            screen = self._screens[screen_name]
        except KeyError as error:
            raise KeyError(
                f"No screen named {screen_name!r} is registered") from error
        self._stack.setCurrentWidget(self._screen_containers[screen_name])
        refresh = getattr(screen, "refresh", None)
        if callable(refresh):
            refresh()
