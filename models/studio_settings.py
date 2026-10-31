import math

from ._validation import validate_nonempty_text, validate_nonnegative_number


class StudioSettings:
    """Validated settings that control home-service travel charges and buffers."""

    _DEFAULT_TRAVEL_FEE = 0.0
    _DEFAULT_TRAVEL_BUFFER_MINUTES = 30
    _DEFAULT_SERVICE_AREA_NOTE = (
        "Home service is available around the Pila area. A travel fee applies."
    )
    _DEFAULT_ALLOWED_AREAS = ("Pila",)
    _DEFAULT_CLEANING_BUFFER_MINUTES = 0

    def __init__(
        self,
        default_travel_fee: int | float = _DEFAULT_TRAVEL_FEE,
        travel_buffer_minutes: int = _DEFAULT_TRAVEL_BUFFER_MINUTES,
        service_area_note: str = _DEFAULT_SERVICE_AREA_NOTE,
        allowed_areas: list[str] | tuple[str, ...] = _DEFAULT_ALLOWED_AREAS,
        cleaning_buffer_minutes: int = _DEFAULT_CLEANING_BUFFER_MINUTES,
        studio_address: str = "",
        maps_embed_url: str = "",
        map_latitude: str | int | float = "",
        map_longitude: str | int | float = "",
        map_image_path: str = "",
    ) -> None:
        self._default_travel_fee = validate_nonnegative_number(
            default_travel_fee, "default_travel_fee"
        )
        self._travel_buffer_minutes = self._validate_buffer(travel_buffer_minutes)
        self._service_area_note = validate_nonempty_text(
            service_area_note, "service_area_note"
        )
        self._allowed_areas = self._validate_allowed_areas(allowed_areas)
        self._cleaning_buffer_minutes = self._validate_buffer(
            cleaning_buffer_minutes, "cleaning_buffer_minutes"
        )
        self._studio_address = self._validate_map_text(
            studio_address, "studio_address"
        )
        self._maps_embed_url = self._validate_map_text(
            maps_embed_url, "maps_embed_url"
        )
        if self._maps_embed_url and not self._maps_embed_url.startswith(
            "https://www.google.com/maps/embed"
        ):
            raise ValueError(
                "Google Maps embed link must start with "
                "https://www.google.com/maps/embed"
            )
        self._map_latitude = self._validate_coordinate(
            map_latitude, "map_latitude", -90, 90
        )
        self._map_longitude = self._validate_coordinate(
            map_longitude, "map_longitude", -180, 180
        )
        if bool(self._map_latitude) != bool(self._map_longitude):
            raise ValueError("Latitude and longitude must both be provided.")
        self._map_image_path = self._validate_map_text(
            map_image_path, "map_image_path"
        )

    @staticmethod
    def _validate_map_text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        return value.strip()

    @classmethod
    def _validate_coordinate(
        cls,
        value: str | int | float,
        field_name: str,
        minimum: int,
        maximum: int,
    ) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise TypeError(f"{field_name} must be a number or an empty string")
        text = str(value).strip()
        if not text:
            return ""
        try:
            number = float(text)
        except ValueError as error:
            raise ValueError(f"{field_name} must be a valid number") from error
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(
                f"{field_name} must be between {minimum} and {maximum}"
            )
        return text

    @staticmethod
    def _validate_allowed_areas(value: list[str] | tuple[str, ...]) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise TypeError("allowed_areas must be a list of town names")
        areas: list[str] = []
        seen: set[str] = set()
        for area in value:
            name = validate_nonempty_text(area, "allowed area")
            key = name.casefold()
            if key not in seen:
                areas.append(name)
                seen.add(key)
        if not areas:
            raise ValueError("At least one allowed service area is required")
        return areas

    @staticmethod
    def _validate_buffer(value: int, field_name: str = "travel_buffer_minutes") -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be a whole number")
        if value < 0 or value % 5:
            raise ValueError(
                f"{field_name} must be non-negative and a multiple of 5"
            )
        return value

    @property
    def default_travel_fee(self) -> float:
        return self._default_travel_fee

    @property
    def travel_buffer_minutes(self) -> int:
        return self._travel_buffer_minutes

    @property
    def service_area_note(self) -> str:
        return self._service_area_note

    @property
    def allowed_areas(self) -> list[str]:
        return self._allowed_areas.copy()

    @property
    def cleaning_buffer_minutes(self) -> int:
        return self._cleaning_buffer_minutes

    @property
    def studio_address(self) -> str:
        return self._studio_address

    @property
    def maps_embed_url(self) -> str:
        return self._maps_embed_url

    @property
    def map_latitude(self) -> str:
        return self._map_latitude

    @property
    def map_longitude(self) -> str:
        return self._map_longitude

    @property
    def map_image_path(self) -> str:
        return self._map_image_path
