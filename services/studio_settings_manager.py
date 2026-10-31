from database import Database
from models import StudioSettings


class StudioSettingsManager:
    """Business-logic boundary for studio-wide service settings."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_settings(self) -> StudioSettings:
        return self._database.get_studio_settings()

    def get_loyalty_web_port(self) -> int:
        return self._database.get_loyalty_web_port()

    def set_loyalty_web_port(self, port: int) -> None:
        self._database.set_loyalty_web_port(port)

    def update_settings(
        self,
        default_travel_fee: int | float,
        travel_buffer_minutes: int,
        service_area_note: str,
        allowed_areas: list[str] | None = None,
        cleaning_buffer_minutes: int | None = None,
        studio_address: str | None = None,
        maps_embed_url: str | None = None,
        map_latitude: str | int | float | None = None,
        map_longitude: str | int | float | None = None,
        map_image_path: str | None = None,
    ) -> StudioSettings:
        current = self.get_settings()
        settings = StudioSettings(
            default_travel_fee,
            travel_buffer_minutes,
            service_area_note,
            current.allowed_areas if allowed_areas is None else allowed_areas,
            (
                current.cleaning_buffer_minutes
                if cleaning_buffer_minutes is None
                else cleaning_buffer_minutes
            ),
            current.studio_address if studio_address is None else studio_address,
            current.maps_embed_url if maps_embed_url is None else maps_embed_url,
            current.map_latitude if map_latitude is None else map_latitude,
            current.map_longitude if map_longitude is None else map_longitude,
            current.map_image_path if map_image_path is None else map_image_path,
        )
        self._database.update_studio_settings(settings)
        return settings
