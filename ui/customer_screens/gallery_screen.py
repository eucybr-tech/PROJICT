import sqlite3
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QPixmapCache
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models import GalleryItem
from services.gallery_manager import GalleryManager
from ui.base_page import BasePage
from ui.scrollable_dialog import ScrollableDialog


def _thumbnail(photo_path: Path, key: str) -> QPixmap:
    cached = QPixmapCache.find(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(str(photo_path))
    if not pixmap.isNull():
        pixmap = pixmap.scaled(
            300,
            300,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        QPixmapCache.insert(key, pixmap)
    return pixmap


class GalleryDetailDialog(ScrollableDialog):
    def __init__(self, item: GalleryItem, photo_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._item = item
        self._photo_path = photo_path
        self.setWindowTitle(item.title)
        self.resize(680, 620)
        self._photo = QLabel()
        self._photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo.setMinimumSize(500, 420)
        self._title = QLabel(item.title)
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._description = QLabel(item.description or "")
        self._description.setWordWrap(True)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close_button)
        content = QVBoxLayout()
        content.addWidget(self._photo, 1)
        content.addWidget(self._title)
        content.addWidget(self._description)
        self.set_dialog_layout(content, footer)
        self._load_photo()

    @property
    def item(self) -> GalleryItem:
        return self._item

    def _load_photo(self) -> None:
        if not self._photo_path.is_file():
            self._photo.setText("Photo is missing on disk.")
            return
        pixmap = QPixmap(str(self._photo_path))
        if pixmap.isNull():
            self._photo.setText("Photo could not be loaded.")
            return
        self._photo.setPixmap(
            pixmap.scaled(
                640,
                480,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

class GalleryScreen(BasePage):
    """Customer gallery presented as a narrow, scrollable two-column view."""

    # Inheritance: this mobile screen reuses the shared BasePage widget lifecycle.
    # Dependency injection and encapsulation: the page uses its injected manager.
    def __init__(self, gallery_manager: GalleryManager, parent=None) -> None:
        self._gallery_manager = gallery_manager
        self._items: list[GalleryItem] = []
        super().__init__({"gallery_manager": gallery_manager}, parent)
        self.refresh()

    @property
    def gallery_manager(self) -> GalleryManager:
        return self._gallery_manager

    def build_ui(self) -> None:
        self._empty_message = QLabel("No photos yet. Check back soon!")
        self._empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_message.setWordWrap(True)
        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(12)
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setWidget(self._content)

        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._stack_layout.addWidget(self._empty_message, 1)
        self._stack_layout.addWidget(self._scroll_area, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.addWidget(self._stack)

    def refresh(self) -> None:
        try:
            self._items = self._gallery_manager.get_gallery_items()
        except (sqlite3.Error, TypeError, ValueError) as error:
            self._empty_message.setText(f"Could not load gallery: {error}")
            self._empty_message.show()
            self._scroll_area.hide()
            return
        self._clear_grid()
        if not self._items:
            self._empty_message.setText("No photos yet. Check back soon!")
            self._empty_message.show()
            self._scroll_area.hide()
            return
        self._empty_message.hide()
        self._scroll_area.show()
        for index, item in enumerate(self._items):
            self._grid.addWidget(self._build_card(item), index // 2, index % 2)

    def _build_card(self, item: GalleryItem) -> QWidget:
        card = QPushButton()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(165)
        card.setStyleSheet(
            "QPushButton { background: #ffffff; border: 1px solid #eddce5; "
            "border-radius: 12px; padding: 6px; text-align: center; }"
            "QPushButton:hover { background: #fff1f7; }"
        )
        card_layout = QVBoxLayout(card)
        photo = QLabel()
        photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        photo.setMinimumHeight(115)
        photo.setMaximumHeight(130)
        path = self._gallery_manager.resolve_photo_path(item.photo_path)
        if not path.is_file():
            photo.setText("Photo unavailable")
        else:
            pixmap = _thumbnail(path, self._cache_key(path))
            if pixmap.isNull():
                photo.setText("Photo unavailable")
            else:
                photo.setPixmap(
                    pixmap.scaled(
                        160,
                        120,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        title = QLabel(item.title)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(photo, 1)
        card_layout.addWidget(title)
        card.clicked.connect(lambda _checked=False, entry=item: self._open_detail(entry))
        return card

    def _open_detail(self, item: GalleryItem) -> None:
        dialog = GalleryDetailDialog(
            item,
            self._gallery_manager.resolve_photo_path(item.photo_path),
            self,
        )
        dialog.exec()

    def _clear_grid(self) -> None:
        while self._grid.count():
            layout_item = self._grid.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _cache_key(path: Path) -> str:
        try:
            return f"gallery:{path.resolve()}:{path.stat().st_mtime_ns}"
        except OSError:
            return f"gallery:{path}"
