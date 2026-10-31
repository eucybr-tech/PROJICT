from ._validation import validate_nonempty_text, validate_optional_text


class GalleryItem:
    def __init__(
        self,
        title: str,
        photo_path: str,
        description: str | None = None,
        item_id: int | None = None,
    ) -> None:
        self._item_id = item_id
        self._title = validate_nonempty_text(title, "title")
        self._description = validate_optional_text(description, "description")
        self._photo_path = validate_nonempty_text(photo_path, "photo_path")

    @property
    def item_id(self) -> int | None:
        return self._item_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def photo_path(self) -> str:
        return self._photo_path

    def update_details(self, title: str, description: str | None, photo_path: str) -> None:
        self._title = validate_nonempty_text(title, "title")
        self._description = validate_optional_text(description, "description")
        self._photo_path = validate_nonempty_text(photo_path, "photo_path")
