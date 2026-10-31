from ._validation import (
    validate_nonempty_text,
    validate_nonnegative_number,
    validate_optional_text,
)


class Service:
    def __init__(
        self,
        name: str,
        base_price: int | float,
        description: str | None = None,
        length_prices: dict[str, int | float] | None = None,
        design_add_on_prices: dict[str, int | float] | None = None,
        service_id: int | None = None,
        duration_minutes: int = 120,
    ) -> None:
        self._service_id = service_id
        self._name = validate_nonempty_text(name, "name")
        self._description = validate_optional_text(description, "description")
        self._base_price = validate_nonnegative_number(base_price, "base_price")
        self._length_prices = self._validate_prices(length_prices or {}, "length_prices")
        self._design_add_on_prices = self._validate_prices(
            design_add_on_prices or {}, "design_add_on_prices"
        )
        self._duration_minutes = self._validate_duration_minutes(duration_minutes)

    @staticmethod
    def _validate_duration_minutes(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("duration_minutes must be a whole number")
        if not 5 <= value <= 240:
            raise ValueError("duration_minutes must be between 5 and 240")
        if value % 5:
            raise ValueError("duration_minutes must be a multiple of 5")
        return value

    @staticmethod
    def _validate_prices(values: dict[str, int | float], field_name: str) -> dict[str, float]:
        if not isinstance(values, dict):
            raise TypeError(f"{field_name} must be a dictionary")
        return {
            validate_nonempty_text(name, f"{field_name} key"):
            validate_nonnegative_number(price, f"{field_name}[{name!r}]")
            for name, price in values.items()
        }

    @property
    def service_id(self) -> int | None:
        return self._service_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def base_price(self) -> float:
        return self._base_price

    @property
    def length_prices(self) -> dict[str, float]:
        return self._length_prices.copy()

    @property
    def design_add_on_prices(self) -> dict[str, float]:
        return self._design_add_on_prices.copy()

    @property
    def duration_minutes(self) -> int:
        return self._duration_minutes

    def get_base_price(self) -> float:
        return self._base_price
