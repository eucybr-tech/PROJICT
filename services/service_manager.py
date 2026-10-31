from models import Service

from database import Database


class ServiceManager:
    """Business-logic boundary between service screens and SQLite persistence."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_services(self) -> list[Service]:
        return self._database.get_services()

    def add_service(self, service: Service) -> Service:
        self._ensure_unique_name(service.name)
        return self._database.add_service(service)

    def update_service(self, service: Service) -> None:
        if service.service_id is None:
            raise ValueError("A service ID is required to edit a service")
        self._ensure_unique_name(service.name, exclude_service_id=service.service_id)
        self._database.update_service(service)

    def delete_service(self, service_id: int) -> None:
        self._database.delete_service(service_id)

    def _ensure_unique_name(self, name: str, exclude_service_id: int | None = None) -> None:
        normalized_name = name.strip().casefold()
        for service in self._database.get_services():
            if service.service_id == exclude_service_id:
                continue
            if service.name.casefold() == normalized_name:
                raise ValueError(f"A service named {service.name!r} already exists")
