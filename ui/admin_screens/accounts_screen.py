import sqlite3

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from models import AccountUser
from services.account_manager import AccountManager
from ui.account_dialogs import AccountDetailsDialog, PasswordDialog
from ui.base_page import BasePage


class AccountsScreen(BasePage):
    """Admin account administration without exposing password data."""

    def __init__(
        self,
        account_manager: AccountManager,
        account_user: AccountUser,
        parent=None,
    ) -> None:
        self._account_manager = account_manager
        self._account_user = account_user
        super().__init__({"account_manager": account_manager}, parent)
        self.refresh()

    def build_ui(self) -> None:
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Username", "Display name", "Role", "Active", "Account ID"]
        )
        self._table.setColumnHidden(4, True)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._update_actions)

        self._add_button = QPushButton("Add account")
        self._add_button.setProperty("variant", "primary")
        self._edit_button = QPushButton("Edit")
        self._reset_button = QPushButton("Reset password")
        self._active_button = QPushButton("Deactivate")
        self._delete_button = QPushButton("Delete")
        self._delete_button.setProperty("variant", "destructive")
        self._change_password_button = QPushButton("Change my password")
        self._add_button.clicked.connect(self.add_account)
        self._edit_button.clicked.connect(self.edit_account)
        self._reset_button.clicked.connect(self.reset_password)
        self._active_button.clicked.connect(self.toggle_active)
        self._delete_button.clicked.connect(self.delete_account)
        self._change_password_button.clicked.connect(self.change_own_password)
        actions = QHBoxLayout()
        for button in (
            self._add_button,
            self._edit_button,
            self._reset_button,
            self._active_button,
            self._delete_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(actions)
        layout.addWidget(self._change_password_button)
        layout.addStretch()
        self._update_actions()

    def refresh(self) -> None:
        try:
            accounts = self._account_manager.list_accounts(self._account_user)
        except (PermissionError, sqlite3.Error) as error:
            QMessageBox.critical(self, "Could not load accounts", str(error))
            return
        self._table.setRowCount(0)
        for account in accounts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                str(account["username"]),
                str(account["display_name"]),
                str(account["role"]).title(),
                "Yes" if account["active"] else "No",
                str(account["id"]),
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(value))
        self._update_actions()

    def add_account(self) -> None:
        dialog = AccountDetailsDialog(include_credentials=True, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._account_manager.create_account(
                self._account_user,
                dialog.username.text(),
                dialog.display_name.text(),
                str(dialog.role.currentData()),
                dialog.password.text(),
                dialog.confirm_password.text(),
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError) as error:
            dialog.clear_passwords()
            QMessageBox.warning(self, "Could not add account", str(error))
            return
        dialog.clear_passwords()
        self.refresh()

    def edit_account(self) -> None:
        selected = self._selected_account()
        if selected is None:
            return
        account_id, display_name, role, _active = selected
        dialog = AccountDetailsDialog(
            role=role,
            display_name=display_name,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._account_manager.update_account(
                self._account_user,
                account_id,
                dialog.display_name.text(),
                str(dialog.role.currentData()),
                _active,
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not update account", str(error))
            return
        self.refresh()

    def reset_password(self) -> None:
        selected = self._selected_account()
        if selected is None:
            return
        account_id = selected[0]
        if account_id == self._account_user.account_id:
            QMessageBox.information(
                self, "Change your password", "Use Change my password instead."
            )
            return
        dialog = PasswordDialog(current_password_required=False, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._account_manager.reset_password(
                self._account_user,
                account_id,
                dialog.new_password.text(),
                dialog.confirm_password.text(),
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            dialog.clear_passwords()
            QMessageBox.warning(self, "Could not reset password", str(error))
            return
        dialog.clear_passwords()
        QMessageBox.information(self, "Password reset",
                                "The password was reset.")

    def toggle_active(self) -> None:
        selected = self._selected_account()
        if selected is None:
            return
        account_id, _display_name, _role, active = selected
        try:
            self._account_manager.set_account_active(
                self._account_user, account_id, not active
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not update account", str(error))
            return
        self.refresh()

    def delete_account(self) -> None:
        selected = self._selected_account()
        if selected is None:
            return
        account_id, _display_name, _role, _active = selected
        answer = QMessageBox.question(
            self,
            "Delete account",
            "Permanently delete this account?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._account_manager.delete_account(
                self._account_user, account_id)
        except (PermissionError, sqlite3.Error, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not delete account", str(error))
            return
        self.refresh()

    def change_own_password(self) -> None:
        dialog = PasswordDialog(current_password_required=True, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._account_manager.change_own_password(
                self._account_user,
                dialog.current_password.text(),
                dialog.new_password.text(),
                dialog.confirm_password.text(),
            )
        except (PermissionError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            dialog.clear_passwords()
            QMessageBox.warning(self, "Could not change password", str(error))
            return
        dialog.clear_passwords()
        QMessageBox.information(self, "Password changed",
                                "Your password was changed.")

    def _selected_account(self) -> tuple[int, str, str, bool] | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        account_id = self._table.item(row, 4)
        display_name = self._table.item(row, 1)
        role = self._table.item(row, 2)
        active = self._table.item(row, 3)
        if any(item is None for item in (account_id, display_name, role, active)):
            return None
        return (
            int(account_id.text()),
            display_name.text(),
            role.text().upper(),
            active.text() == "Yes",
        )

    def _update_actions(self) -> None:
        selected = self._selected_account()
        has_selection = selected is not None
        for button in (
            self._edit_button,
            self._reset_button,
            self._active_button,
            self._delete_button,
        ):
            button.setEnabled(has_selection)
        if selected is not None:
            self._active_button.setText(
                "Deactivate" if selected[3] else "Reactivate"
            )
