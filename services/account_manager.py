from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from math import ceil

from database import Database
from models import AccountUser, User


class AuthenticationError(ValueError):
    def __init__(self, message: str, remaining_seconds: int = 0) -> None:
        super().__init__(message)
        self.remaining_seconds = remaining_seconds


class AccountManager:
    """Account persistence, password verification, and role authorization."""

    _USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,30}$")
    _PASSWORD_MINIMUM_LENGTH = 8
    _LOCKOUT_SECONDS = 60
    _MAX_ATTEMPTS = 5
    _DUMMY_SALT = b"account-authentication-dummy"
    _AUTH_ERROR = "Incorrect username or password"

    def __init__(self, database: Database) -> None:
        self._database = database
        self._failed_attempts: dict[str, tuple[int, float]] = {}

    def has_active_account(self, role: str) -> bool:
        normalized_role = self._normalize_role(role)
        return self._database.count_active_accounts(normalized_role) > 0

    def list_accounts(self, actor: User) -> list[dict[str, object]]:
        self._require_admin(actor)
        return self._database.list_accounts()

    def authenticate(self, username: str, password: str, view_role: str) -> AccountUser:
        normalized_username = username.strip().casefold() if isinstance(username, str) else ""
        now = time.monotonic()
        attempts, locked_until = self._failed_attempts.get(normalized_username, (0, 0.0))
        if locked_until > now:
            remaining = max(1, ceil(locked_until - now))
            raise AuthenticationError(
                f"{self._AUTH_ERROR}. Try again in {remaining} seconds.",
                remaining,
            )
        if locked_until:
            attempts = 0
        account = (
            self._database.get_account_auth(username.strip())
            if isinstance(username, str) and username.strip()
            else None
        )
        candidate = password if isinstance(password, str) else ""
        candidate_bytes = candidate.encode("utf-8")
        if account is None:
            expected_hash = hashlib.scrypt(
                candidate_bytes, salt=self._DUMMY_SALT, n=2**14, r=8, p=1, dklen=64
            ).hex()
            hmac.compare_digest(expected_hash, "0" * 128)
            valid = False
        else:
            expected_hash = str(account["password_hash"])
            actual_hash = hashlib.scrypt(
                candidate_bytes,
                salt=bytes.fromhex(str(account["salt"])),
                n=2**14,
                r=8,
                p=1,
                dklen=64,
            ).hex()
            valid = hmac.compare_digest(actual_hash, expected_hash)

        normalized_view = self._normalize_role(view_role)
        permitted_view = (
            normalized_view == "STAFF"
            or account is not None
            and account["role"] == "ADMIN"
            and normalized_view == "ADMIN"
        )
        if (
            account is None
            or not valid
            or not bool(account["active"])
            or not permitted_view
        ):
            attempts += 1
            locked_until = (
                now + self._LOCKOUT_SECONDS
                if attempts >= self._MAX_ATTEMPTS
                else 0.0
            )
            self._failed_attempts[normalized_username] = (attempts, locked_until)
            remaining = self._LOCKOUT_SECONDS if locked_until else 0
            suffix = (
                f". Try again in {remaining} seconds." if remaining else ""
            )
            raise AuthenticationError(f"{self._AUTH_ERROR}{suffix}", remaining)

        self._failed_attempts.pop(normalized_username, None)
        if normalized_view == "ADMIN" and account["role"] != "ADMIN":
            raise AuthenticationError(self._AUTH_ERROR)
        return AccountUser(
            int(account["id"]),
            str(account["username"]),
            str(account["display_name"]),
            str(account["role"]),
        )

    def create_first_admin(
        self,
        username: str,
        display_name: str,
        password: str,
        password_confirmation: str,
    ) -> AccountUser:
        normalized_username = self._validate_username(username)
        normalized_name = self._validate_display_name(display_name)
        self._validate_passwords(password, password_confirmation)
        salt = secrets.token_bytes(16)
        account_id = self._database.create_first_admin_account(
            normalized_username,
            normalized_name,
            self._hash_password(password, salt),
            salt.hex(),
        )
        return AccountUser(account_id, normalized_username, normalized_name, "ADMIN")

    def create_account(
        self,
        actor: User,
        username: str,
        display_name: str,
        role: str,
        password: str,
        password_confirmation: str,
    ) -> int:
        self._require_admin(actor)
        return self._create_account(
            username, display_name, self._normalize_role(role), password, password_confirmation
        )

    def update_account(
        self,
        actor: User,
        account_id: int,
        display_name: str,
        role: str,
        active: bool,
    ) -> None:
        self._require_admin(actor)
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("Display name is required")
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        self._database.update_account_profile(
            account_id,
            display_name.strip(),
            self._normalize_role(role),
            active,
        )

    def set_account_active(self, actor: User, account_id: int, active: bool) -> None:
        self._require_admin(actor)
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        account = self._database.get_account_auth_by_id(account_id)
        if account is None:
            raise KeyError("Account not found")
        self._database.update_account_profile(
            account_id,
            str(account["display_name"]),
            str(account["role"]),
            active,
        )

    def delete_account(self, actor: User, account_id: int) -> None:
        self._require_admin(actor)
        if account_id == getattr(actor, "account_id", None):
            raise PermissionError("An Admin cannot delete their own account")
        self._database.delete_account(account_id)

    def reset_password(
        self,
        actor: User,
        account_id: int,
        new_password: str,
        password_confirmation: str,
    ) -> None:
        self._require_admin(actor)
        if account_id == getattr(actor, "account_id", None):
            raise PermissionError("Use change-own-password for your own account")
        self._set_password(account_id, new_password, password_confirmation)

    def change_own_password(
        self,
        actor: User,
        current_password: str,
        new_password: str,
        password_confirmation: str,
    ) -> None:
        if not isinstance(actor, AccountUser):
            raise PermissionError("An authenticated account is required")
        account = self._database.get_account_auth_by_id(actor.account_id)
        if account is None or not bool(account["active"]):
            raise PermissionError("This account is not active")
        current_hash = hashlib.scrypt(
            current_password.encode("utf-8"),
            salt=bytes.fromhex(str(account["salt"])),
            n=2**14,
            r=8,
            p=1,
            dklen=64,
        ).hex()
        if not hmac.compare_digest(current_hash, str(account["password_hash"])):
            raise ValueError("Current password is incorrect")
        self._set_password(actor.account_id, new_password, password_confirmation)

    def recover_admin_password(
        self, username: str, new_password: str, password_confirmation: str
    ) -> None:
        account = self._database.get_account_auth(username.strip())
        if account is None or account["role"] != "ADMIN":
            raise ValueError("No matching Admin account was found")
        self._set_password(
            int(account["id"]), new_password, password_confirmation
        )

    def _create_account(
        self,
        username: str,
        display_name: str,
        role: str,
        password: str,
        password_confirmation: str,
    ) -> int:
        normalized_username = self._validate_username(username)
        normalized_name = self._validate_display_name(display_name)
        self._validate_passwords(password, password_confirmation)
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        return self._database.create_account(
            normalized_username,
            normalized_name,
            role,
            password_hash,
            salt.hex(),
        )

    def _set_password(
        self, account_id: int, password: str, password_confirmation: str
    ) -> None:
        self._validate_passwords(password, password_confirmation)
        salt = secrets.token_bytes(16)
        self._database.update_account_password(
            account_id, self._hash_password(password, salt), salt.hex()
        )

    @classmethod
    def _hash_password(cls, password: str, salt: bytes) -> str:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
        ).hex()

    @classmethod
    def _validate_username(cls, username: str) -> str:
        if not isinstance(username, str) or not cls._USERNAME_PATTERN.fullmatch(
            username.strip()
        ):
            raise ValueError(
                "Username must be 3 to 30 characters using letters, digits, or underscore"
            )
        return username.strip()

    @staticmethod
    def _validate_display_name(display_name: str) -> str:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("Display name is required")
        return display_name.strip()

    @classmethod
    def _validate_passwords(cls, password: str, confirmation: str) -> None:
        if not isinstance(password, str) or len(password) < cls._PASSWORD_MINIMUM_LENGTH:
            raise ValueError("Password must be at least 8 characters")
        if not isinstance(confirmation, str) or not hmac.compare_digest(
            password.encode("utf-8"), confirmation.encode("utf-8")
        ):
            raise ValueError("Passwords do not match")

    @staticmethod
    def _normalize_role(role: str) -> str:
        normalized = role.strip().upper() if isinstance(role, str) else ""
        if normalized not in {"ADMIN", "STAFF"}:
            raise ValueError("Role must be ADMIN or STAFF")
        return normalized

    @staticmethod
    def _require_admin(actor: User) -> None:
        if not isinstance(actor, User) or "view_payments" not in actor.get_permissions():
            raise PermissionError("Only an Admin can manage accounts")
