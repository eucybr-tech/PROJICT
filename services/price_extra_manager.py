from database import Database
from models import PriceExtra


class PriceExtraManager:
    """Business-logic boundary for the shared Extras price list."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_extras(self) -> list[PriceExtra]:
        return self._database.get_price_extras()

    def add_extra(self, extra: PriceExtra) -> PriceExtra:
        self._ensure_unique_name(extra.name)
        return self._database.add_price_extra(extra)

    def update_extra(self, extra: PriceExtra) -> None:
        if extra.extra_id is None:
            raise ValueError("An extra ID is required to edit an extra")
        self._ensure_unique_name(extra.name, exclude_extra_id=extra.extra_id)
        self._database.update_price_extra(extra)

    def delete_extra(self, extra_id: int) -> None:
        self._database.delete_price_extra(extra_id)

    def _ensure_unique_name(
        self, name: str, exclude_extra_id: int | None = None
    ) -> None:
        normalized_name = name.strip().casefold()
        for extra in self._database.get_price_extras():
            if extra.extra_id == exclude_extra_id:
                continue
            if extra.name.casefold() == normalized_name:
                raise ValueError(f"An extra named {extra.name!r} already exists")
