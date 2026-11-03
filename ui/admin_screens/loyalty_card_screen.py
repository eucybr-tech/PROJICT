import sqlite3

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models import Customer, User
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


class PrizeDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        prize: dict[str, object] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit prize" if prize else "Add prize")
        self.name_input = QLineEdit()
        self.milestone_input = QComboBox()
        self.milestone_input.addItem("5th stamp", "5")
        self.milestone_input.addItem("10th stamp", "10")
        self.milestone_input.addItem("Both", "both")
        self.active_input = QCheckBox("Active")
        self.active_input.setChecked(True)
        if prize is not None:
            self.name_input.setText(str(prize["name"]))
            self.milestone_input.setCurrentIndex(
                self.milestone_input.findData(prize["milestone"])
            )
            self.active_input.setChecked(bool(prize["active"]))
        form = QFormLayout()
        form.addRow("Prize name", self.name_input)
        form.addRow("Milestone", self.milestone_input)
        form.addRow(self.active_input)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)


class LoyaltyCardScreen(BasePage):
    """Admin controls for stamping and claiming in-person loyalty rewards."""

    # Dependency injection: the screen receives LoyaltyManager, never Database.
    def __init__(
        self,
        loyalty_manager: LoyaltyManager,
        role: User,
        parent=None,
        loyalty_web_server: LoyaltyWebServer | None = None,
    ) -> None:
        self._loyalty_manager = loyalty_manager
        self._role = role
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

        self._client_table = QTableWidget(0, 3)
        self._client_table.setHorizontalHeaderLabels(
            ["Name", "Email", "This month's stamps"]
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
        self._client_table.setColumnWidth(0, 150)
        self._client_table.setColumnWidth(1, 220)
        self._client_table.setStyleSheet(
            "QTableWidget::item:selected { "
            "background-color: #f8e5e3; color: #3f3437; }"
        )
        self._client_table.itemSelectionChanged.connect(self._update_selection)

        self._copy_card_link_button = QPushButton("Copy card link")
        self._copy_card_link_button.clicked.connect(self.copy_card_link)
        self._copy_card_link_button.setEnabled(False)
        self._reverse_stamp_button = QPushButton("Reverse stamp")
        self._reverse_stamp_button.clicked.connect(self.reverse_selected_stamp)
        self._reverse_stamp_button.setEnabled(False)

        action_row = QHBoxLayout()
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

        self._tabs = QTabWidget()
        cards_tab = QWidget()
        cards_layout = QVBoxLayout(cards_tab)
        cards_layout.addLayout(content, 1)
        cards_layout.addLayout(history_row, 1)
        self._tabs.addTab(cards_tab, "Cards")
        self._build_prizes_tab()
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        self._resize_client_table_columns()

    def _build_prizes_tab(self) -> None:
        self._prize_table = QTableWidget(0, 3)
        self._prize_table.setHorizontalHeaderLabels(
            ["Prize", "Milestone", "Active"]
        )
        self._prize_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._prize_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._prize_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._prize_table.itemSelectionChanged.connect(
            self._update_prize_actions
        )
        self._add_prize_button = QPushButton("Add")
        self._add_prize_button.clicked.connect(self.add_prize)
        self._edit_prize_button = QPushButton("Edit")
        self._edit_prize_button.clicked.connect(self.edit_prize)
        self._remove_prize_button = QPushButton("Remove")
        self._remove_prize_button.clicked.connect(self.remove_prize)
        self._edit_prize_button.setEnabled(False)
        self._remove_prize_button.setEnabled(False)
        prize_actions = QHBoxLayout()
        prize_actions.addWidget(self._add_prize_button)
        prize_actions.addWidget(self._edit_prize_button)
        prize_actions.addWidget(self._remove_prize_button)
        prize_actions.addStretch()

        self._draw_table = QTableWidget(0, 5)
        self._draw_table.setHorizontalHeaderLabels(
            ["Client", "Card month", "Milestone", "Prize", "Status"]
        )
        self._draw_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._draw_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._draw_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._draw_table.itemSelectionChanged.connect(self._update_draw_actions)
        self._draw_prize_button = QPushButton("Draw prize")
        self._draw_prize_button.clicked.connect(self.draw_prize)
        self._mark_given_button = QPushButton("Mark prize given")
        self._mark_given_button.clicked.connect(self.mark_prize_given)
        self._draw_prize_button.setEnabled(False)
        self._mark_given_button.setEnabled(False)
        draw_actions = QHBoxLayout()
        draw_actions.addWidget(self._draw_prize_button)
        draw_actions.addWidget(self._mark_given_button)
        draw_actions.addStretch()
        prizes_tab = QWidget()
        prizes_layout = QVBoxLayout(prizes_tab)
        prizes_layout.addWidget(QLabel("Prize list"))
        prizes_layout.addWidget(self._prize_table, 1)
        prizes_layout.addLayout(prize_actions)
        prizes_layout.addWidget(QLabel("Prize draw entries"))
        prizes_layout.addWidget(self._draw_table, 1)
        prizes_layout.addLayout(draw_actions)
        self._tabs.addTab(prizes_tab, "Prizes")

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
        )
        email_width = max(220, round(available * 0.38))
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
            prizes = self._loyalty_manager.get_prizes()
            draws = self._loyalty_manager.get_prize_draws()
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load loyalty cards", error)
            return
        self._populate_table(selected_email)
        self._populate_prizes(prizes)
        self._populate_draws(draws, prizes)

    def _populate_prizes(self, prizes: list[dict[str, object]]) -> None:
        self._prize_table.setRowCount(0)
        milestone_labels = {
            "5": "5th stamp",
            "10": "10th stamp",
            "both": "Both",
        }
        for prize in prizes:
            row = self._prize_table.rowCount()
            self._prize_table.insertRow(row)
            name_item = QTableWidgetItem(str(prize["name"]))
            name_item.setData(Qt.ItemDataRole.UserRole, prize["prize_id"])
            self._prize_table.setItem(row, 0, name_item)
            self._prize_table.setItem(
                row,
                1,
                QTableWidgetItem(milestone_labels[str(prize["milestone"])]),
            )
            self._prize_table.setItem(
                row, 2, QTableWidgetItem("Yes" if prize["active"] else "No")
            )
        self._update_prize_actions()

    def _populate_draws(
        self,
        draws: list[dict[str, object]],
        prizes: list[dict[str, object]],
    ) -> None:
        self._draw_table.setRowCount(0)
        for draw in draws:
            row = self._draw_table.rowCount()
            self._draw_table.insertRow(row)
            client_item = QTableWidgetItem(str(draw["client_name"]))
            client_item.setData(Qt.ItemDataRole.UserRole, draw["draw_id"])
            client_item.setToolTip(str(draw["client_email"]))
            self._draw_table.setItem(row, 0, client_item)
            self._draw_table.setItem(
                row, 1, QTableWidgetItem(str(draw["card_month"]))
            )
            self._draw_table.setItem(
                row, 2, QTableWidgetItem(f"{draw['milestone']}th stamp")
            )
            prize_name = str(draw["prize_name"])
            if draw["status"] == "Pending" and not any(
                prize["active"]
                and str(prize["milestone"]) in {
                    str(draw["milestone"]),
                    "both",
                }
                for prize in prizes
            ):
                prize_name = "No active prize for this milestone"
            self._draw_table.setItem(
                row, 3, QTableWidgetItem(prize_name)
            )
            self._draw_table.setItem(
                row, 4, QTableWidgetItem(str(draw["status"]))
            )
        self._update_draw_actions()

    def _selected_prize(self) -> tuple[int, dict[str, object]] | None:
        row = self._prize_table.currentRow()
        if row < 0:
            return None
        item = self._prize_table.item(row, 0)
        if item is None:
            return None
        prize_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(prize_id, int):
            return None
        prize = next(
            (
                item for item in self._loyalty_manager.get_prizes()
                if item["prize_id"] == prize_id
            ),
            None,
        )
        return (prize_id, prize) if prize is not None else None

    def _selected_draw_id(self) -> int | None:
        row = self._draw_table.currentRow()
        item = self._draw_table.item(row, 0) if row >= 0 else None
        draw_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return draw_id if isinstance(draw_id, int) else None

    def _update_prize_actions(self) -> None:
        selected = self._selected_prize()
        self._edit_prize_button.setEnabled(selected is not None)
        self._remove_prize_button.setEnabled(selected is not None)

    def _update_draw_actions(self) -> None:
        row = self._draw_table.currentRow()
        status_item = self._draw_table.item(row, 4) if row >= 0 else None
        status = status_item.text() if status_item is not None else ""
        self._draw_prize_button.setEnabled(status == "Pending")
        self._mark_given_button.setEnabled(status == "Drawn")

    def add_prize(self) -> None:
        dialog = PrizeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_prize(None, dialog)

    def edit_prize(self) -> None:
        selected = self._selected_prize()
        if selected is None:
            return
        dialog = PrizeDialog(self, selected[1])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_prize(selected[0], dialog)

    def _save_prize(self, prize_id: int | None, dialog: PrizeDialog) -> None:
        name = dialog.name_input.text()
        milestone = str(dialog.milestone_input.currentData())
        active = dialog.active_input.isChecked()
        try:
            if prize_id is None:
                self._loyalty_manager.add_prize(
                    name, milestone, active, self._role
                )
            else:
                self._loyalty_manager.update_prize(
                    prize_id, name, milestone, active, self._role
                )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            self._show_error("Could not save prize", error)
            return
        self.refresh()

    def remove_prize(self) -> None:
        selected = self._selected_prize()
        if selected is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove prize",
            f"Remove {selected[1]['name']} from the active prize list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._loyalty_manager.remove_prize(selected[0], self._role)
        except (PermissionError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not remove prize", error)
            return
        self.refresh()

    def draw_prize(self) -> None:
        draw_id = self._selected_draw_id()
        if draw_id is None:
            return
        try:
            draw = self._loyalty_manager.draw_prize(draw_id, self._role)
        except (PermissionError, sqlite3.Error, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not draw prize", str(error))
            return
        QMessageBox.information(
            self, "Prize drawn", f"Prize: {draw['prize_name']}"
        )
        self.refresh()

    def mark_prize_given(self) -> None:
        draw_id = self._selected_draw_id()
        if draw_id is None:
            return
        try:
            self._loyalty_manager.mark_prize_given(draw_id, self._role)
        except (PermissionError, sqlite3.Error, ValueError, KeyError) as error:
            self._show_error("Could not mark prize given", error)
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
                row, 2, QTableWidgetItem(f"{card.stamps} / 10")
            )
            if client.email == selected_email:
                self._client_table.selectRow(row)
                selected_found = True
        if not selected_found:
            self._qr_preview.setPixmap(QPixmap())
            self._qr_preview.setText("Select a client to preview their QR card.")
            self._copy_card_link_button.setEnabled(False)
            self._reverse_stamp_button.setEnabled(False)
            self._stamp_history.setRowCount(0)
            self._stamp_history_empty.show()
            self._claim_history.clear()
            self._claim_history_empty.show()

    def _update_selection(self) -> None:
        email = self._selected_email()
        if email is None:
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
