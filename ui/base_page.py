from collections.abc import Mapping

from PyQt6.QtWidgets import QWidget


class BasePage(QWidget):
    """Base widget for screens, with service dependencies injected by the owner."""

    def __init__(
        self,
        services: Mapping[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Dependency injection: pages receive logic services, never a raw Database.
        self._services = dict(services or {})
        self.build_ui()

    def get_service(self, name: str) -> object:
        try:
            return self._services[name]
        except KeyError as error:
            raise KeyError(f"No service named {name!r} was injected into this page") from error

    def build_ui(self) -> None:
        """Build screen-specific controls in subclasses."""

    def refresh(self) -> None:
        """Refresh screen-specific data in subclasses."""
