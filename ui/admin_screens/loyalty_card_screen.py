import sqlite3

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import Customer
from services.loyalty_manager import LoyaltyManager
from services.loyalty_web_server import LoyaltyWebServer
from ui.base_page import BasePage
from ui.scrollable_dialog import ScrollableDialog


class StampReversalDialog(ScrollableDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reverse stamp")
        self.reason_input = QLineEdit()
        self.reason_input.setMaxLength(500)
        self.reason_input.setPlaceholderText("Reason (at least 5 characters)")
        self.allow_restamp = QCheckBox(
            "Allow this appointment to be stamped again"
        )
        form = QFormLayout()
        form.addRow("Reason", self.reason_input)
        form.addRow(self.allow_restamp)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)


class LoyaltyCardScreen(BasePage):
    """Admin controls for stamping and claiming in-person loyalty rewards."""

    # Dependency injection: the screen receives LoyaltyManager, never Database.
    def __init__(
        self,
        loyalty_manager: LoyaltyManager,
        parent=None,
        loyalty_web_server: LoyaltyWebServer | None = None,
    ) -> None:
        self._loyalty_manager = loyalty_manager
        self._loyalty_web_server = loyalty_web_server
        self._clients: list[Customer] = []
        super().__init__({"loyalty_manager": loyalty_manager}, parent)
        self.refresh()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(10_000)

    @property
    def loyalty_manager(self) -> LoyaltyManager:
        return self._loyalty_manager

    def build_ui(self) -> None:
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search name or email")
        self._search_box.textChanged.connect(lambda _text: self._populate_table())

        self._client_table = QTableWidget(0, 4)
        self._client_table.setHorizontalHeaderLabels(
            ["Name", "Email", "Stamps", "Reward"]
        )
        self._client_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._client_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._client_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        client_header = self._client_table.horizontalHeader()
        client_header.setStretchLastSection(False)
        client_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        client_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        client_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        client_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._client_table.setColumnWidth(0, 150)
        self._client_table.setColumnWidth(1, 220)
        self._client_table.setColumnWidth(3, 140)
        self._client_table.setStyleSheet(
            "QTableWidget::item:selected { "
            "background-color: #f8e5e3; color: #3f3437; }"
        )
        self._client_table.itemSelectionChanged.connect(self._update_selection)

        self._claim_button = QPushButton("Mark reward claimed")
        self._claim_button.clicked.connect(self.mark_reward_claimed)
        self._claim_button.setEnabled(False)
        self._copy_card_link_button = QPushButton("Copy card link")
        self._copy_card_link_button.clicked.connect(self.copy_card_link)
        self._copy_card_link_button.setEnabled(False)
        self._reverse_stamp_button = QPushButton("Reverse stamp")
        self._reverse_stamp_button.clicked.connect(self.reverse_selected_stamp)
        self._reverse_stamp_button.setEnabled(False)

        action_row = QHBoxLayout()
        action_row.addWidget(self._claim_button)
        action_row.addWidget(self._copy_card_link_button)
        action_row.addWidget(self._reverse_stamp_button)
        action_row.addStretch()

        clients_box = QGroupBox("Client Loyalty Cards")
        clients_layout = QVBoxLayout(clients_box)
        clients_layout.addWidget(self._search_box)
        clients_layout.addWidget(self._client_table)
        clients_layout.addLayout(action_row)

        self._qr_preview = QLabel("Select a client to preview their QR card.")
        self._qr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_preview.setMinimumSize(180, 180)
        self._qr_preview.setMaximumSize(240, 240)
        self._qr_preview.setScaledContents(False)
        qr_box = QGroupBox("QR Card Preview")
        qr_layout = QVBoxLayout(qr_box)
        qr_layout.addWidget(self._qr_preview)

        self._stamps_required = QSpinBox()
        self._stamps_required.setRange(1, 1_000_000)
        save_settings = QPushButton("Save")
        save_settings.clicked.connect(self.save_settings)
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Stamps needed for a reward"))
        settings_row.addWidget(self._stamps_required)
        settings_row.addWidget(save_settings)
        settings_row.addStretch()

        content = QHBoxLayout()
        content.addWidget(clients_box, 3)
        content.addWidget(qr_box, 1)

        self._stamp_history = QTableWidget(0, 3)
        self._stamp_history.setHorizontalHeaderLabels(["Date", "Type", "Reason"])
        self._stamp_history.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._stamp_history.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._stamp_history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        history_header = self._stamp_history.horizontalHeader()
        history_header.setStretchLastSection(False)
        history_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        history_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._stamp_history.setColumnWidth(0, 150)
        self._stamp_history.setColumnWidth(1, 90)
        self._stamp_history.itemSelectionChanged.connect(
            self._update_reverse_button
        )
        self._stamp_history_empty = QLabel("No stamp history yet")
        self._stamp_history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._claim_history = QListWidget()
        self._claim_history_empty = QLabel("No claims yet")
        self._claim_history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stamp_history_box = QGroupBox("Stamp transaction history")
        stamp_history_layout = QVBoxLayout(stamp_history_box)
        stamp_history_layout.addWidget(self._stamp_history)
        stamp_history_layout.addWidget(self._stamp_history_empty)
        claim_history_box = QGroupBox("Reward claim history")
        claim_history_layout = QVBoxLayout(claim_history_box)
        claim_history_layout.addWidget(self._claim_history)
        claim_history_layout.addWidget(self._claim_history_empty)
        history_row = QHBoxLayout()
        history_row.addWidget(stamp_history_box, 2)
        history_row.addWidget(claim_history_box, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(content, 1)
        layout.addLayout(history_row, 1)
        layout.addLayout(settings_row)
        self._resize_client_table_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_client_table_columns()

    def _resize_client_table_columns(self) -> None:
        table = getattr(self, "_client_table", None)
        if table is None:
            return
        header = table.horizontalHeader()
        available = (
            table.viewport().width()
            - header.sectionSize(2)
            - header.sectionSize(3)
        )
        email_width = max(220, round(available * 220 / 370))
        name_width = max(150, available - email_width)
        table.setColumnWidth(0, name_width)
        table.setColumnWidth(1, email_width)

    def refresh(self) -> None:
        selected_email = self._selected_email()
        try:
            self._clients = self._loyalty_manager.get_clients()
            cards_by_email = {
                card.client_email: card for card in self._loyalty_manager.get_cards()
            }
            for client in self._clients:
                if client.email not in cards_by_email:
                    cards_by_email[client.email] = self._loyalty_manager.get_or_create_card(
                        client.email
                    )
            self._cards_by_email = cards_by_email
            required = self._loyalty_manager.get_stamps_required()
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load loyalty cards", error)
            return
        self._stamps_required.setValue(required)
        self._populate_table(selected_email)

    def mark_reward_claimed(self) -> None:
        email = self._selected_email()
        if email is None:
            return
        try:
            ready = self._loyalty_manager.is_reward_ready(email)
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not check reward status", error)
            return
        if not ready:
            QMessageBox.information(
                self, "Reward not ready", "This client has not earned a reward yet."
            )
            return
        answer = QMessageBox.question(
            self,
            "Mark reward claimed",
            "Confirm that this client claimed their reward at the salon?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._loyalty_manager.claim_reward(email, "Admin")
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not claim reward", error)
            return
        self.refresh()
        self._select_email(email)

    def save_settings(self) -> None:
        try:
            self._loyalty_manager.set_stamps_required(self._stamps_required.value())
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not save loyalty settings", error)
            return
        self.refresh()

    def copy_card_link(self) -> None:
        email = self._selected_email()
        server = self._loyalty_web_server
        if email is None or server is None:
            return
        try:
            card = self._loyalty_manager.get_card(email)
            if card is None or card.view_code is None:
                raise RuntimeError("This client does not have a private card link")
            link = server.build_url(f"/card/{card.view_code}")
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Could not copy card link", str(error))
            return
        QApplication.clipboard().setText(link)
        QMessageBox.information(
            self, "Card link copied", "The private card link was copied."
        )

    def reverse_selected_stamp(self) -> None:
        row = self._stamp_history.currentRow()
        email = self._selected_email()
        if row < 0 or email is None:
            return
        date_item = self._stamp_history.item(row, 0)
        appointment_id = (
            date_item.data(Qt.ItemDataRole.UserRole) if date_item is not None else None
        )
        if not isinstance(appointment_id, int):
            return
        dialog = StampReversalDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reason = dialog.reason_input.text().strip()
        if len(reason) < 5:
            QMessageBox.warning(
                self,
                "Reason required",
                "Enter a reversal reason with at least 5 characters.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Confirm stamp reversal",
            "Reverse this stamp? The reward claim history will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._loyalty_manager.reverse_stamp(
                appointment_id,
                reason,
                "Admin",
                dialog.allow_restamp.isChecked(),
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not reverse stamp", str(error))
            return
        self.refresh()
        self._select_email(email)

    def _populate_table(self, selected_email: str | None = None) -> None:
        query = self._search_box.text().strip().casefold()
        clients = [
            client
            for client in self._clients
            if not query
            or query in client.name.casefold()
            or query in client.email.casefold()
        ]
        required = self._loyalty_manager.get_stamps_required()
        self._client_table.setRowCount(0)
        selected_found = False
        for client in clients:
            card = self._cards_by_email[client.email]
            row = self._client_table.rowCount()
            self._client_table.insertRow(row)
            name_item = QTableWidgetItem(client.name)
            name_item.setData(Qt.ItemDataRole.UserRole, client.email)
            name_item.setToolTip(client.name)
            self._client_table.setItem(row, 0, name_item)
            email_item = QTableWidgetItem(client.email)
            email_item.setToolTip(client.email)
            self._client_table.setItem(row, 1, email_item)
            self._client_table.setItem(
                row, 2, QTableWidgetItem(f"{card.stamps} / {required}")
            )
            self._client_table.setItem(
                row,
                3,
                QTableWidgetItem(
                    "Reward ready"
                    if card.is_reward_ready(required)
                    else ""
                ),
            )
            if client.email == selected_email:
                self._client_table.selectRow(row)
                selected_found = True
        if not selected_found:
            self._qr_preview.setPixmap(QPixmap())
            self._qr_preview.setText("Select a client to preview their QR card.")
            self._claim_button.setEnabled(False)
            self._copy_card_link_button.setEnabled(False)
            self._reverse_stamp_button.setEnabled(False)
            self._stamp_history.setRowCount(0)
            self._stamp_history_empty.show()
            self._claim_history.clear()
            self._claim_history_empty.show()

    def _update_selection(self) -> None:
        email = self._selected_email()
        if email is None:
            self._claim_button.setEnabled(False)
            self._copy_card_link_button.setEnabled(False)
            self._reverse_stamp_button.setEnabled(False)
            self._stamp_history.setRowCount(0)
            self._stamp_history_empty.show()
            self._claim_history.clear()
            self._claim_history_empty.show()
            self._qr_preview.setPixmap(QPixmap())
            self._qr_preview.setText("Select a client to preview their QR card.")
            return
        self._copy_card_link_button.setEnabled(False)
        try:
            card = self._loyalty_manager.get_card(email)
            ready = self._loyalty_manager.is_reward_ready(email)
            stamp_history = self._loyalty_manager.get_stamp_history(email)
            claim_history = self._loyalty_manager.get_reward_claim_history(email)
            if card is None:
                self._qr_preview.setText("QR preview is unavailable.")
                return
            self._copy_card_link_button.setEnabled(card.view_code is not None)
            path = self._loyalty_manager.generate_qr_code(email)
            pixmap = QPixmap(path)
        except (ValueError, TypeError, sqlite3.Error, RuntimeError) as error:
            self._show_error("Could not load QR card", error)
            return
        self._claim_button.setEnabled(ready)
        self._populate_history(stamp_history, claim_history)
        self._update_reverse_button()
        if pixmap.isNull():
            self._qr_preview.setText("QR preview is unavailable.")
        else:
            self._qr_preview.setText("")
            self._qr_preview.setPixmap(
                pixmap.scaled(
                    self._qr_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _selected_email(self) -> str | None:
        row = self._client_table.currentRow()
        if row < 0:
            return None
        item = self._client_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_email(self, email: str) -> None:
        for row in range(self._client_table.rowCount()):
            item = self._client_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == email:
                self._client_table.selectRow(row)
                return

    def _populate_history(
        self,
        stamp_history: list[dict[str, object]],
        claim_history: list[dict[str, str]],
    ) -> None:
        self._stamp_history.setRowCount(0)
        for transaction in stamp_history:
            row = self._stamp_history.rowCount()
            self._stamp_history.insertRow(row)
            date_item = QTableWidgetItem(str(transaction["created_at"]))
            date_item.setData(
                Qt.ItemDataRole.UserRole, transaction["appointment_id"]
            )
            self._stamp_history.setItem(row, 0, date_item)
            self._stamp_history.setItem(
                row, 1, QTableWidgetItem(str(transaction["type"]))
            )
            self._stamp_history.setItem(
                row, 2, QTableWidgetItem(str(transaction["reason"]))
            )
        has_stamp_history = bool(stamp_history)
        self._stamp_history.setVisible(has_stamp_history)
        self._stamp_history_empty.setVisible(not has_stamp_history)
        self._claim_history.clear()
        for claim in claim_history:
            self._claim_history.addItem(
                f"{claim['claimed_at']} - {claim['admin_role']}"
            )
        has_claim_history = bool(claim_history)
        self._claim_history.setVisible(has_claim_history)
        self._claim_history_empty.setVisible(not has_claim_history)

    def _update_reverse_button(self) -> None:
        row = self._stamp_history.currentRow()
        if row < 0:
            self._reverse_stamp_button.setEnabled(False)
            return
        item = self._stamp_history.item(row, 0)
        appointment_id = (
            item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        )
        if not isinstance(appointment_id, int):
            self._reverse_stamp_button.setEnabled(False)
            return
        try:
            self._reverse_stamp_button.setEnabled(
                self._loyalty_manager.has_active_stamp_for_appointment(
                    appointment_id
                )
            )
        except sqlite3.Error as error:
            self._reverse_stamp_button.setEnabled(False)
            self._show_error("Could not check stamp status", error)

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
