from PyQt6.QtWidgets import QVBoxLayout

from models import Admin
from services.client_manager import ClientManager
from ui.base_page import BasePage
from ui.client_panel import ClientPanel


class ClientManagementScreen(BasePage):
    def __init__(
        self,
        client_manager: ClientManager,
        role: Admin,
        parent=None,
    ) -> None:
        self._client_panel = ClientPanel(client_manager, role)
        super().__init__({"client_manager": client_manager}, parent)

    @property
    def client_panel(self) -> ClientPanel:
        return self._client_panel

    def build_ui(self) -> None:
        # Composition: admin screen embeds the shared client-management panel.
        layout = QVBoxLayout(self)
        layout.addWidget(self._client_panel)

    def refresh(self) -> None:
        self._client_panel.refresh()
