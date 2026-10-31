from ._validation import validate_nonempty_text, validate_positive_integer


class LoyaltyCard:
    def __init__(
        self,
        client_email: str,
        stamps: int = 0,
        qr_code_path: str | None = None,
        card_code: str | None = None,
        view_code: str | None = None,
    ) -> None:
        self._client_email = validate_nonempty_text(client_email, "client_email").lower()
        self._stamps = self._validate_stamps(stamps)
        if qr_code_path is not None and not isinstance(qr_code_path, str):
            raise TypeError("qr_code_path must be a string or None")
        self._qr_code_path = qr_code_path
        if card_code is not None and (
            not isinstance(card_code, str) or not card_code.strip()
        ):
            raise ValueError("card_code must be a non-empty string or None")
        self._card_code = card_code
        if view_code is not None and (
            not isinstance(view_code, str) or not view_code.strip()
        ):
            raise ValueError("view_code must be a non-empty string or None")
        self._view_code = view_code

    @staticmethod
    def _validate_stamps(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("stamps must be a non-negative integer")
        if value < 0:
            raise ValueError("stamps must be a non-negative integer")
        return value

    @property
    def client_email(self) -> str:
        return self._client_email

    @property
    def stamps(self) -> int:
        return self._stamps

    @property
    def qr_code_path(self) -> str | None:
        return self._qr_code_path

    @property
    def card_code(self) -> str | None:
        return self._card_code

    @property
    def view_code(self) -> str | None:
        return self._view_code

    def claim_reward(self, stamps_required: int) -> int:
        validate_positive_integer(stamps_required, "stamps_required")
        if self._stamps < stamps_required:
            raise ValueError("This loyalty card does not have enough stamps to claim a reward")
        self._stamps -= stamps_required
        return self._stamps

    def is_reward_ready(self, stamps_required: int) -> bool:
        validate_positive_integer(stamps_required, "stamps_required")
        return self._stamps >= stamps_required


class LoyaltySettings:
    def __init__(self, stamps_required: int = 10) -> None:
        self._stamps_required = 10
        self.set_stamps_required(stamps_required)

    def get_stamps_required(self) -> int:
        return self._stamps_required

    def set_stamps_required(self, value: int) -> None:
        self._stamps_required = validate_positive_integer(value, "stamps_required")
