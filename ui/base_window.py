from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.branding import brand_icon


class BaseWindow(QMainWindow):
    """Shared window shell and screen-switching behavior for each role."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(brand_icon())
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
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setWidget(screen)
            stacked_widget = area
        self._screen_containers[name] = stacked_widget
        self._stack.addWidget(stacked_widget)

    def show_screen(self, screen_name: str) -> None:
        try:
            screen = self._screens[screen_name]
        except KeyError as error:
            raise KeyError(f"No screen named {screen_name!r} is registered") from error
        self._stack.setCurrentWidget(self._screen_containers[screen_name])
        refresh = getattr(screen, "refresh", None)
        if callable(refresh):
            refresh()
