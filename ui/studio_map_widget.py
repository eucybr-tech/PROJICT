import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from models import StudioSettings
from services.schedule_manager import ScheduleManager
from services.studio_settings_manager import StudioSettingsManager

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


class StudioMapWidget(QWidget):
    """Read-only studio map, address, and weekly hours shared across roles."""

    def __init__(
        self,
        settings_manager: StudioSettingsManager | None,
        schedule_manager: ScheduleManager | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._schedule_manager = schedule_manager
        self._display_mode = "text"
        self._settings = StudioSettings()

        self._name_label = QLabel("Pearl's SigNAILture")
        self._name_label.setStyleSheet(
            "color: #81566d; font-size: 21px; font-weight: 700;"
        )
        self._name_label.setWordWrap(True)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._map_stack = QStackedWidget()
        self._fallback_label = QLabel("Studio map will be available soon")
        self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback_label.setMinimumHeight(260)
        self._fallback_label.setStyleSheet(
            "background: #ffffff; border: 1px solid #eddce5; border-radius: 12px;"
        )
        self._map_stack.addWidget(self._fallback_label)
        self._web_view = None

        self._address_label = QLabel()
        self._address_label.setWordWrap(True)
        self._hours_label = QLabel()
        self._hours_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._name_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._map_stack, 1)
        layout.addWidget(self._address_label)
        layout.addWidget(self._hours_label)
        self.refresh()

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def studio_address(self) -> str:
        return self._settings.studio_address

    def refresh(self) -> None:
        settings_error = ""
        try:
            settings = (
                self._settings_manager.get_settings()
                if self._settings_manager is not None
                else StudioSettings()
            )
        except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
            settings = StudioSettings()
            settings_error = f"Studio map settings could not be loaded: {error}"
        self._settings = settings
        self._status_label.setText(settings_error)
        self._address_label.setText(
            f"Address: {settings.studio_address or 'Not provided'}"
        )
        self._hours_label.setText(self._opening_hours())

        if settings.maps_embed_url and QWebEngineView is not None:
            self._load_web_map(settings.maps_embed_url, "google_embed")
            return
        if (
            settings.map_latitude
            and settings.map_longitude
            and QWebEngineView is not None
        ):
            self._load_web_map(self._open_street_map_url(settings), "openstreetmap")
            return
        self._show_static_fallback(settings, settings_error)

    def _opening_hours(self) -> str:
        if self._schedule_manager is None:
            return "Opening hours are managed by the studio."
        try:
            hours = []
            for entry in self._schedule_manager.get_weekly_hours():
                weekday = self._schedule_manager.WEEKDAYS[int(entry["weekday"])][:3]
                if entry["is_open"]:
                    hours.append(
                        f"{weekday} {entry['open_time']}–{entry['close_time']}"
                    )
                else:
                    hours.append(f"{weekday} closed")
        except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
            return f"Opening hours could not be loaded: {error}"
        return "Opening hours: " + " · ".join(hours)

    @staticmethod
    def _open_street_map_url(settings: StudioSettings) -> str:
        latitude = float(settings.map_latitude)
        longitude = float(settings.map_longitude)
        west = max(-180.0, longitude - 0.01)
        east = min(180.0, longitude + 0.01)
        south = max(-90.0, latitude - 0.01)
        north = min(90.0, latitude + 0.01)
        return "https://www.openstreetmap.org/export/embed.html?" + urlencode(
            {
                "bbox": f"{west},{south},{east},{north}",
                "layer": "mapnik",
                "marker": f"{latitude},{longitude}",
            }
        )

    def _load_web_map(self, url: str, mode: str) -> None:
        if QWebEngineView is None:
            self._show_static_fallback(self._settings, "")
            return
        if self._web_view is None:
            try:
                self._web_view = QWebEngineView()
                self._web_view.loadFinished.connect(self._web_load_finished)
                self._map_stack.addWidget(self._web_view)
            except (ImportError, RuntimeError):
                self._show_static_fallback(
                    self._settings, "Map needs an internet connection"
                )
                return
        self._display_mode = mode
        self._map_stack.setCurrentWidget(self._fallback_label)
        try:
            self._web_view.setUrl(QUrl(url))
        except RuntimeError:
            self._show_static_fallback(
                self._settings, "Map needs an internet connection"
            )

    def _web_load_finished(self, succeeded: bool) -> None:
        if succeeded:
            self._map_stack.setCurrentWidget(self._web_view)
            return
        self._show_static_fallback(
            self._settings, "Map needs an internet connection"
        )

    def _show_static_fallback(self, settings: StudioSettings, message: str) -> None:
        self._status_label.setText(message)
        image_path = Path(settings.map_image_path) if settings.map_image_path else None
        if image_path is not None and not image_path.is_absolute():
            project_root = Path(__file__).resolve().parents[1]
            image_path = project_root / image_path
        pixmap = QPixmap(str(image_path)) if image_path is not None else QPixmap()
        if not pixmap.isNull():
            self._fallback_label.setText("")
            self._fallback_label.setPixmap(
                pixmap.scaled(
                    640,
                    400,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._display_mode = "picture"
        else:
            self._fallback_label.setPixmap(QPixmap())
            self._fallback_label.setText("Studio map will be available soon")
            self._display_mode = "text"
        self._map_stack.setCurrentWidget(self._fallback_label)
