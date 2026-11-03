from database import Database
from models import StudioSettings, User


class StudioSettingsManager:
    """Business-logic boundary for studio-wide service settings."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_settings(self) -> StudioSettings:
        return self._database.get_studio_settings()

    def get_loyalty_web_port(self) -> int:
        return self._database.get_loyalty_web_port()

    def set_loyalty_web_port(self, port: int, role: User) -> None:
        self._require_admin(role)
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
        loyalty_facebook: str | None = None,
        loyalty_phone: str | None = None,
        loyalty_valid_until: str | None = None,
        loyalty_terms: str | None = None,
        owner_provider_name: str | None = None,
        review_url: str | None = None,
        online_booking_url: str | None = None,
        minimum_spend_per_appointment: int | float | None = None,
        map_link_url: str | None = None,
        role: User | None = None,
    ) -> StudioSettings:
        self._require_admin(role)
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
            (
                current.loyalty_facebook
                if loyalty_facebook is None
                else loyalty_facebook
            ),
            current.loyalty_phone if loyalty_phone is None else loyalty_phone,
            (
                current.loyalty_valid_until
                if loyalty_valid_until is None
                else loyalty_valid_until
            ),
            current.loyalty_terms if loyalty_terms is None else loyalty_terms,
            (
                current.owner_provider_name
                if owner_provider_name is None
                else owner_provider_name
            ),
            current.review_url if review_url is None else review_url,
            (
                current.online_booking_url
                if online_booking_url is None
                else online_booking_url
            ),
            (
                current.minimum_spend_per_appointment
                if minimum_spend_per_appointment is None
                else minimum_spend_per_appointment
            ),
            current.map_link_url if map_link_url is None else map_link_url,
        )
        self._database.update_studio_settings(settings)
        return settings

    @staticmethod
    def _require_admin(role: User | None) -> None:
        if not isinstance(role, User) or "view_payments" not in role.get_permissions():
            raise PermissionError("Only an Admin can save Studio Settings")
