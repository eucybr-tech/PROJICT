import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QCheckBox,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import Admin, Customer, Staff
from services.client_manager import ClientManager
from ui.scrollable_dialog import ScrollableDialog


class ClientDialog(ScrollableDialog):
    def __init__(
        self,
        client: Customer | None = None,
        can_edit_profile: bool = True,
        can_view_health_notes: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Client" if client else "Add Client")
        self._name_edit = QLineEdit(client.name if client else "")
        self._email_edit = QLineEdit(client.email if client else "")
        self._phone_edit = QLineEdit(client.phone or "" if client else "")
        self._notes_edit = QLineEdit(client.notes or "" if client else "")
        self._address_edit = QLineEdit(client.address if client else "")
        self._nail_condition_edit = QLineEdit(
            client.nail_condition if client else ""
        )
        self._health_notes_edit = QTextEdit(
            client.health_notes if client and can_view_health_notes else ""
        )
        self._health_notes_edit.setMaximumHeight(75)
        self._clear_profile_checks: dict[str, QCheckBox] = {}
        # Email is the client's primary key in the current persistence API.
        self._email_edit.setReadOnly(client is not None)

        form = QFormLayout()
        form.addRow("Name", self._name_edit)
        form.addRow("Email", self._email_edit)
        form.addRow("Phone", self._phone_edit)
        form.addRow("Notes", self._notes_edit)
        for field_name, label, editor in (
            ("address", "Address", self._address_edit),
            ("nail_condition", "Nail condition", self._nail_condition_edit),
            ("health_notes", "Health / service-safety notes", self._health_notes_edit),
        ):
            if field_name == "health_notes" and not can_view_health_notes:
                continue
            if not can_edit_profile:
                editor.setReadOnly(True)
            form.addRow(label, editor)
            if client is not None and getattr(client, field_name) and can_edit_profile:
                clear_check = QCheckBox("Clear saved value")
                clear_check.toggled.connect(editor.setDisabled)
                self._clear_profile_checks[field_name] = clear_check
                form.addRow("", clear_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    def get_client(self) -> Customer:
        return Customer(
            name=self._name_edit.text().strip(),
            email=self._email_edit.text().strip(),
            phone=self._phone_edit.text().strip() or None,
            notes=self._notes_edit.text().strip() or None,
            address=self._address_edit.text().strip(),
            nail_condition=self._nail_condition_edit.text().strip(),
            health_notes=self._health_notes_edit.toPlainText().strip(),
        )

    @property
    def clear_profile_fields(self) -> set[str]:
        return {
            field_name
            for field_name, checkbox in self._clear_profile_checks.items()
            if checkbox.isChecked()
        }


class ClientPanel(QWidget):
    """Reusable client list, editor, permissions, and booking-history panel."""

    # Dependency injection: this widget receives a manager, never a Database.
    # Polymorphism: authorization uses the injected User permission contract.
    def __init__(
        self,
        client_manager: ClientManager,
        role: Admin | Staff,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(role, (Admin, Staff)):
            raise TypeError("role must be an Admin or Staff user")
        permissions = role.get_permissions()
        if "manage_clients" not in permissions:
            raise PermissionError("This role cannot manage clients")

        self._client_manager = client_manager
        self._role = role
        self._can_delete = "delete_clients" in permissions
        self._can_view_health_notes = "view_health_notes" in permissions
        self._can_edit_profile = "edit_client_profile" in permissions
        self._can_mark_deposit_paid = "record_payments" in permissions
        self._can_view_payment_details = "view_payments" in permissions
        self._clients: list[Customer] = []
        self._build_ui()
        self.refresh()

    @property
    def client_manager(self) -> ClientManager:
        return self._client_manager

    @property
    def role(self) -> Admin | Staff:
        return self._role

    def _build_ui(self) -> None:
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search name, email, or phone")
        self._search_box.textChanged.connect(
            lambda text: self._filter_clients(text)
        )

        client_headers = ["Name", "Email", "Phone"]
        if self._can_view_payment_details:
            client_headers.append("Deposit")
        self._client_table = QTableWidget(0, len(client_headers))
        self._client_table.setHorizontalHeaderLabels(client_headers)
        self._client_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._client_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._client_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._client_table.horizontalHeader().setStretchLastSection(True)
        self._client_table.itemSelectionChanged.connect(self._show_booking_history)
        self._client_table.itemSelectionChanged.connect(self._show_client_details)
        self._client_table.itemSelectionChanged.connect(
            self._update_deposit_button
        )

        self._add_button = QPushButton("Add")
        self._edit_button = QPushButton("Edit")
        self._delete_button = QPushButton("Delete")
        self._mark_deposit_paid_button = QPushButton("Mark deposit paid")
        self._add_button.clicked.connect(self.add_client)
        self._edit_button.clicked.connect(self.edit_selected_client)
        self._delete_button.clicked.connect(self.delete_selected_client)
        self._mark_deposit_paid_button.clicked.connect(self.mark_selected_deposit_paid)

        # Polymorphism: this capability comes from the role's permission contract.
        self._delete_button.setVisible(self._can_delete)
        self._mark_deposit_paid_button.setVisible(self._can_mark_deposit_paid)

        controls = QHBoxLayout()
        controls.addWidget(self._add_button)
        controls.addWidget(self._edit_button)
        controls.addWidget(self._delete_button)
        controls.addWidget(self._mark_deposit_paid_button)
        controls.addStretch()

        client_box = QGroupBox("Clients")
        client_layout = QVBoxLayout(client_box)
        client_layout.addWidget(self._search_box)
        client_layout.addWidget(self._client_table)
        client_layout.addLayout(controls)

        self._history_empty_label = QLabel("Select a client to view booking history.")
        self._history_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        history_headers = ["Date", "Service", "Status"]
        if self._can_view_payment_details:
            history_headers.append("Total price")
        self._history_table = QTableWidget(0, len(history_headers))
        self._history_table.setHorizontalHeaderLabels(history_headers)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.hide()

        history_box = QGroupBox("Booking History")
        history_layout = QVBoxLayout(history_box)
        history_layout.addWidget(self._history_empty_label)
        history_layout.addWidget(self._history_table)

        self._profile_address = QLineEdit()
        self._profile_address.setReadOnly(True)
        self._profile_nail_condition = QLineEdit()
        self._profile_nail_condition.setReadOnly(True)
        self._profile_health_notes = QTextEdit()
        self._profile_health_notes.setReadOnly(True)
        self._profile_health_notes.setMaximumHeight(65)
        profile_form = QFormLayout()
        profile_form.addRow("Address", self._profile_address)
        profile_form.addRow("Nail condition", self._profile_nail_condition)
        if not self._can_view_health_notes:
            self._profile_health_notes.hide()
        else:
            profile_form.addRow(
                "Health / service-safety notes", self._profile_health_notes
            )
        self._profile_box = QGroupBox("Client Profile")
        self._profile_box.setLayout(profile_form)
        self._profile_box.hide()

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(client_box)
        splitter.addWidget(history_box)
        splitter.addWidget(self._profile_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def refresh(self) -> None:
        selected_client = self._selected_client()
        selected_email = selected_client.email if selected_client is not None else None
        try:
            self._clients = self._client_manager.get_clients()
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load clients", error)
            return
        self._populate_client_table(selected_email)

    def add_client(self) -> None:
        dialog = ClientDialog(
            can_edit_profile=self._can_edit_profile,
            can_view_health_notes=self._can_view_health_notes,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            client = dialog.get_client()
            self._client_manager.add_client(client)
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not add client", error)
            return
        self.refresh()
        self._select_email(client.email)

    def edit_selected_client(self) -> None:
        client = self._selected_client()
        if client is None:
            QMessageBox.information(self, "Select a client", "Choose a client to edit.")
            return
        dialog = ClientDialog(
            client,
            can_edit_profile=self._can_edit_profile,
            can_view_health_notes=self._can_view_health_notes,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._client_manager.update_client(
                client.email,
                dialog.get_client(),
                clear_fields=dialog.clear_profile_fields,
            )
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not update client", error)
            return
        self.refresh()
        self._select_email(client.email)

    def delete_selected_client(self) -> None:
        if not self._can_delete:
            return
        client = self._selected_client()
        if client is None:
            QMessageBox.information(self, "Select a client", "Choose a client to delete.")
            return
        answer = QMessageBox.question(
            self,
            "Delete client",
            f"Delete {client.name} ({client.email})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._client_manager.delete_client(client.email)
        except (ValueError, TypeError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not delete client", error)
            return
        self.refresh()
        self._show_empty_history("Select a client to view booking history.")

    def mark_selected_deposit_paid(self) -> None:
        if not self._can_mark_deposit_paid:
            return
        client = self._selected_client()
        if client is None:
            QMessageBox.information(
                self, "Select a client", "Choose a client to update their deposit."
            )
            return
        if client.deposit_paid:
            return
        try:
            self._client_manager.mark_deposit_paid(client.email)
        except (ValueError, TypeError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not update deposit status", error)
            return
        self.refresh()
        self._select_email(client.email)

    def _populate_client_table(self, selected_email: str | None = None) -> None:
        query = self._search_box.text().strip().casefold()
        visible_clients = [
            client
            for client in self._clients
            if not query
            or query in client.name.casefold()
            or query in client.email.casefold()
            or query in (client.phone or "").casefold()
        ]
        self._client_table.setRowCount(0)
        selected_row_found = False
        for client in visible_clients:
            row = self._client_table.rowCount()
            self._client_table.insertRow(row)
            name_item = QTableWidgetItem(client.name)
            name_item.setData(Qt.ItemDataRole.UserRole, client.email)
            self._client_table.setItem(row, 0, name_item)
            self._client_table.setItem(row, 1, QTableWidgetItem(client.email))
            self._client_table.setItem(row, 2, QTableWidgetItem(client.phone or ""))
            if self._can_view_payment_details:
                self._client_table.setItem(
                    row,
                    3,
                    QTableWidgetItem(
                        (
                            f"Paid on {client.deposit_paid_on.isoformat()}"
                            if client.deposit_paid and client.deposit_paid_on
                            else "Paid"
                            if client.deposit_paid
                            else "Not paid"
                        )
                    ),
                )
            if client.email == selected_email:
                self._client_table.selectRow(row)
                selected_row_found = True
        if not selected_row_found:
            self._show_empty_history("Select a client to view booking history.")
        self._update_deposit_button()

    def _filter_clients(self, _text: str) -> None:
        del _text
        selected = self._selected_client()
        self._populate_client_table(selected.email if selected else None)

    def _selected_client(self) -> Customer | None:
        row = self._client_table.currentRow()
        if row < 0:
            return None
        item = self._client_table.item(row, 0)
        email = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((client for client in self._clients if client.email == email), None)

    def _select_email(self, email: str) -> None:
        for row in range(self._client_table.rowCount()):
            item = self._client_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == email:
                self._client_table.selectRow(row)
                return

    def _show_booking_history(self) -> None:
        client = self._selected_client()
        if client is None:
            self._show_empty_history("Select a client to view booking history.")
            return
        try:
            history = self._client_manager.get_booking_history(client.email)
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load booking history", error)
            return

        if not history:
            self._show_empty_history("No booking history for this client yet.")
            return
        self._history_empty_label.hide()
        self._history_table.show()
        self._history_table.setRowCount(len(history))
        for row, record in enumerate(history):
            self._history_table.setItem(row, 0, QTableWidgetItem(record["date"]))
            self._history_table.setItem(row, 1, QTableWidgetItem(record["service"]))
            self._history_table.setItem(row, 2, QTableWidgetItem(record["status"]))
            if self._can_view_payment_details:
                self._history_table.setItem(
                    row, 3, QTableWidgetItem(f"₱ {record['total_price']:,.2f}")
                )

    def _show_empty_history(self, message: str) -> None:
        self._history_table.setRowCount(0)
        self._history_table.hide()
        self._history_empty_label.setText(message)
        self._history_empty_label.show()

    def _show_client_details(self) -> None:
        client = self._selected_client()
        if client is None:
            self._profile_address.clear()
            self._profile_nail_condition.clear()
            self._profile_health_notes.clear()
            self._profile_box.hide()
            return
        self._profile_address.setText(client.address)
        self._profile_nail_condition.setText(client.nail_condition)
        if self._can_view_health_notes:
            self._profile_health_notes.setPlainText(client.health_notes)
        self._profile_box.show()

    def _update_deposit_button(self) -> None:
        if not self._can_mark_deposit_paid:
            self._mark_deposit_paid_button.setEnabled(False)
            return
        client = self._selected_client()
        self._mark_deposit_paid_button.setEnabled(
            client is not None and not client.deposit_paid
        )

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
