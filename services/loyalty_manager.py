from pathlib import Path

from database import Database
from database.database import StampNotQualifiedError
from models import LoyaltyCard, LoyaltySettings, User


class LoyaltyManager:
    """Loyalty-card operations isolated from the UI and SQL."""

    def __init__(
        self,
        database: Database,
        qr_codes_directory: str | Path | None = None,
    ) -> None:
        self._database = database
        self._qr_codes_directory = (
            Path(qr_codes_directory)
            if qr_codes_directory is not None
            else Path(__file__).resolve().parent.parent / "assets" / "qr_codes"
        )

    @property
    def qr_codes_directory(self) -> Path:
        return self._qr_codes_directory

    def get_or_create_card(self, email: str) -> LoyaltyCard:
        normalized_email = self._normalize_email(email)
        if self._database.get_client(normalized_email) is None:
            raise ValueError(f"No existing client found with email {normalized_email!r}")
        return self._database.get_or_create_loyalty_card(normalized_email)

    def get_card(self, email: str) -> LoyaltyCard | None:
        normalized_email = self._normalize_email(email)
        if self._database.get_client(normalized_email) is None:
            raise ValueError(f"No existing client found with email {normalized_email!r}")
        return self._database.get_loyalty_card(normalized_email)

    def get_cards(self) -> list[LoyaltyCard]:
        return self._database.get_loyalty_cards()

    def get_scan_details(
        self, card_code: str
    ) -> tuple[str, int, int, int] | None:
        if not isinstance(card_code, str) or not card_code.strip():
            return None
        card = self._database.get_loyalty_card_by_code(card_code.strip())
        if card is None:
            return None
        client = self._database.get_client(card.client_email)
        if client is None:
            return None
        return (
            client.name,
            card.stamps,
            self.get_stamps_required(),
            self._database.count_unstamped_completed_visits(card.client_email),
        )

    def add_stamp_for_card_code(
        self, card_code: str, admin_role: str = "Staff"
    ) -> LoyaltyCard | None:
        if not isinstance(card_code, str) or not card_code.strip():
            return None
        try:
            return self._database.award_next_unstamped_completed_visit(
                card_code.strip(), admin_role
            )
        except StampNotQualifiedError as error:
            if admin_role == "Admin":
                raise
            raise ValueError(
                "This appointment does not qualify for a stamp."
            ) from error

    def get_clients(self):
        return self._database.get_clients()

    def create_stamp_token(
        self, appointment_id: int, admin_role: str = "Admin"
    ) -> str:
        if isinstance(appointment_id, bool) or not isinstance(appointment_id, int):
            raise TypeError("appointment_id must be an integer")
        try:
            return self._database.create_stamp_token(appointment_id)
        except StampNotQualifiedError as error:
            if admin_role == "Admin":
                raise
            raise ValueError(
                "This appointment does not qualify for a stamp."
            ) from error

    def has_stamp_for_appointment(self, appointment_id: int) -> bool:
        return self._database.has_loyalty_stamp_for_appointment(appointment_id)

    def has_active_stamp_for_appointment(self, appointment_id: int) -> bool:
        return self._database.has_active_loyalty_stamp_for_appointment(
            appointment_id
        )

    def claim_reward(
        self, email: str, admin_role: str = "Admin"
    ) -> LoyaltyCard:
        card = self.get_or_create_card(email)
        return self._database.claim_loyalty_reward(card.client_email, admin_role)

    def reverse_stamp(
        self,
        appointment_id: int,
        reason: str,
        admin_role: str,
        allow_restamp: bool,
    ) -> LoyaltyCard:
        return self._database.reverse_loyalty_stamp(
            appointment_id, reason, admin_role, allow_restamp
        )

    def get_stamp_history(self, email: str) -> list[dict[str, object]]:
        normalized_email = self._normalize_email(email)
        return self._database.get_loyalty_stamp_history(normalized_email)

    def get_reward_claim_history(self, email: str) -> list[dict[str, str]]:
        normalized_email = self._normalize_email(email)
        return self._database.get_reward_claim_history(normalized_email)

    def generate_qr_code(self, email: str) -> str:
        card = self.get_or_create_card(email)
        try:
            import qrcode
        except ImportError as error:
            raise RuntimeError("The qrcode package is required to generate loyalty cards") from error

        self._qr_codes_directory.mkdir(parents=True, exist_ok=True)
        if not card.card_code:
            raise RuntimeError("Loyalty card has no scan code")
        path = self._qr_codes_directory / f"{card.card_code}.png"
        image = qrcode.make(card.card_code)
        image.save(path)
        card_with_qr = LoyaltyCard(
            card.client_email, card.stamps, str(path), card.card_code, card.view_code
        )
        self._database.update_loyalty_card(card_with_qr)
        return str(path)

    def get_stamps_required(self) -> int:
        return 10

    def set_stamps_required(self, value: int) -> None:
        settings = LoyaltySettings(value)
        self._database.update_loyalty_settings(settings)

    def is_reward_ready(self, email: str) -> bool:
        card = self.get_card(email)
        return card is not None and card.is_reward_ready(self.get_stamps_required())

    def get_minimum_spend_per_appointment(self) -> float:
        return self._database.get_minimum_spend_per_appointment()

    def get_prizes(self) -> list[dict[str, object]]:
        return self._database.get_loyalty_prizes()

    def add_prize(
        self, name: str, milestone: str, active: bool, role: User
    ) -> int:
        self._require_admin(role, "manage prizes")
        return self._database.add_loyalty_prize(
            name, milestone, active, role.get_role_name()
        )

    def update_prize(
        self,
        prize_id: int,
        name: str,
        milestone: str,
        active: bool,
        role: User,
    ) -> None:
        self._require_admin(role, "manage prizes")
        self._database.update_loyalty_prize(
            prize_id, name, milestone, active, role.get_role_name()
        )

    def remove_prize(self, prize_id: int, role: User) -> None:
        self._require_admin(role, "manage prizes")
        self._database.delete_loyalty_prize(prize_id, role.get_role_name())

    def get_prize_draws(
        self,
        email: str | None = None,
        card_month: str | None = None,
    ) -> list[dict[str, object]]:
        return self._database.get_loyalty_prize_draws(email, card_month)

    def draw_prize(self, draw_id: int, role: User) -> dict[str, object]:
        self._require_admin(role, "draw a prize")
        return self._database.draw_loyalty_prize(
            draw_id, role.get_role_name()
        )

    def mark_prize_given(self, draw_id: int, role: User) -> None:
        self._require_admin(role, "mark a prize given")
        self._database.mark_loyalty_prize_given(
            draw_id, role.get_role_name()
        )

    @staticmethod
    def _require_admin(role: User, action: str) -> None:
        if not isinstance(role, User) or "view_payments" not in role.get_permissions():
            raise PermissionError(f"Only an Admin can {action}")

    @staticmethod
    def _normalize_email(email: str) -> str:
        if not isinstance(email, str) or not email.strip():
            raise ValueError("Client email is required")
        return email.strip().lower()
