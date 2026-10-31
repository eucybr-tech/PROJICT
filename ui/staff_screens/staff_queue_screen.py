from PyQt6.QtWidgets import QVBoxLayout

from services.queue_manager import QueueManager
from ui.base_page import BasePage
from ui.queue_panel import QueuePanel


class StaffQueueScreen(BasePage):
    def __init__(self, queue_manager: QueueManager, parent=None) -> None:
        self._queue_panel = QueuePanel(queue_manager)
        super().__init__({"queue_manager": queue_manager}, parent)

    @property
    def queue_panel(self) -> QueuePanel:
        return self._queue_panel

    def build_ui(self) -> None:
        # Composition: staff screen owns the reusable queue panel.
        layout = QVBoxLayout(self)
        layout.addWidget(self._queue_panel)

    def refresh(self) -> None:
        self._queue_panel.refresh()
