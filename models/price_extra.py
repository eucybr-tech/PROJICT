from ._validation import (
    validate_nonempty_text,
    validate_nonnegative_number,
)


class PriceExtra:
    def __init__(
        self,
        name: str,
        price: int | float,
        category: str = "design",
        active: bool = True,
        extra_id: int | None = None,
    ) -> None:
        if extra_id is not None and (
            isinstance(extra_id, bool) or not isinstance(extra_id, int) or extra_id <= 0
        ):
            raise ValueError("extra_id must be a positive integer or None")
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        self._extra_id = extra_id
        self._name = validate_nonempty_text(name, "name")
        self._category = validate_nonempty_text(category, "category")
        self._price = validate_nonnegative_number(price, "price")
        self._active = active

    @property
    def extra_id(self) -> int | None:
        return self._extra_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> str:
        return self._category

    @property
    def price(self) -> float:
        return self._price

    @property
    def active(self) -> bool:
        return self._active
