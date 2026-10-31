from PyQt6.QtWidgets import QVBoxLayout

from services.schedule_manager import ScheduleManager
from services.studio_settings_manager import StudioSettingsManager
from ui.base_page import BasePage
from ui.studio_map_widget import StudioMapWidget


class AdminMapScreen(BasePage):
    """Read-only map and location details for Admin."""

    def __init__(
        self,
        settings_manager: StudioSettingsManager,
        schedule_manager: ScheduleManager | None = None,
        parent=None,
    ) -> None:
        self._settings_manager = settings_manager
        self._schedule_manager = schedule_manager
        super().__init__(
            {
                "studio_settings_manager": settings_manager,
                "schedule_manager": schedule_manager,
            },
            parent,
        )

    @property
    def map_widget(self) -> StudioMapWidget:
        return self._map_widget

    def build_ui(self) -> None:
        self._map_widget = StudioMapWidget(
            self._settings_manager, self._schedule_manager
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self._map_widget)

    def refresh(self) -> None:
        self._map_widget.refresh()
