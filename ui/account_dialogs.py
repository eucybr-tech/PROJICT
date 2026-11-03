import sqlite3

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from models import AccountUser
from services.account_manager import AccountManager, AuthenticationError


class FirstAdminDialog(QDialog):
    def __init__(
        self, account_manager: AccountManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create the first Admin account")
        self._account_manager = account_manager
        self.account_user: AccountUser | None = None
        self.username = QLineEdit()
        self.username.setMaxLength(30)
        self.display_name = QLineEdit()
        self.password = self._password_input()
        self.confirm_password = self._password_input()
        self.password.setMaxLength(1024)
        self.confirm_password.setMaxLength(1024)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Display name", self.display_name)
        form.addRow("Password", self.password)
        form.addRow("Password again", self.confirm_password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        create_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if create_button is None:
            raise RuntimeError("Create button was not created")
        create_button.setText("Create")
        buttons.accepted.connect(self.create_account)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Create the first Admin account"))
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    @staticmethod
    def _password_input() -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        return field

    def create_account(self) -> None:
        try:
            self.account_user = self._account_manager.create_first_admin(
                self.username.text(),
                self.display_name.text(),
                self.password.text(),
                self.confirm_password.text(),
            )
        except (ValueError, TypeError) as error:
            self.error_label.setText(str(error))
            return
        except sqlite3.Error:
            self.error_label.setText("That username is already in use.")
            return
        self._clear_passwords()
        self.accept()

    def _clear_passwords(self) -> None:
        self.password.clear()
        self.confirm_password.clear()

    def reject(self) -> None:
        self._clear_passwords()
        super().reject()


class LoginDialog(QDialog):
    def __init__(
        self,
        account_manager: AccountManager,
        view_role: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{view_role} login")
        self._account_manager = account_manager
        self._view_role = view_role
        self.account_user: AccountUser | None = None
        self.username = QLineEdit()
        self.username.setMaxLength(30)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(1024)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.login)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    def login(self) -> None:
        try:
            self.account_user = self._account_manager.authenticate(
                self.username.text(), self.password.text(), self._view_role
            )
        except AuthenticationError as error:
            if (
                self._view_role == "Staff"
                and not self._account_manager.has_active_account("STAFF")
            ):
                self.error_label.setText(
                    "No Staff account yet. Ask the Admin to create one."
                )
            else:
                self.error_label.setText(str(error))
            self.password.clear()
            return
        self.password.clear()
        self.accept()

    def reject(self) -> None:
        self.password.clear()
        super().reject()


class AccountDetailsDialog(QDialog):
    def __init__(
        self,
        *,
        role: str = "STAFF",
        display_name: str = "",
        include_credentials: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add account" if include_credentials else "Edit account")
        self.username = QLineEdit()
        self.username.setMaxLength(30)
        self.display_name = QLineEdit(display_name)
        self.role = QComboBox()
        self.role.addItem("Admin", "ADMIN")
        self.role.addItem("Staff", "STAFF")
        index = self.role.findData(role)
        if index >= 0:
            self.role.setCurrentIndex(index)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(1024)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setMaxLength(1024)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        form = QFormLayout()
        if include_credentials:
            form.addRow("Username", self.username)
        form.addRow("Display name", self.display_name)
        form.addRow("Role", self.role)
        if include_credentials:
            form.addRow("Password", self.password)
            form.addRow("Password again", self.confirm_password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self._include_credentials = include_credentials

    def clear_passwords(self) -> None:
        self.password.clear()
        self.confirm_password.clear()

    def reject(self) -> None:
        self.clear_passwords()
        super().reject()

class PasswordDialog(QDialog):
    def __init__(
        self, *, current_password_required: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change password" if current_password_required else "Reset password")
        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_password.setMaxLength(1024)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password.setMaxLength(1024)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setMaxLength(1024)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        form = QFormLayout()
        if current_password_required:
            form.addRow("Current password", self.current_password)
        form.addRow("New password", self.new_password)
        form.addRow("New password again", self.confirm_password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    def clear_passwords(self) -> None:
        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()

    def reject(self) -> None:
        self.clear_passwords()
        super().reject()
