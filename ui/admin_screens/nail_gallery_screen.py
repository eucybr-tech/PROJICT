import sqlite3
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPixmap, QPixmapCache
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
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


class GalleryItemDialog(ScrollableDialog):
    """Dialog for creating or editing a gallery item."""

    def __init__(
        self,
        item: GalleryItem | None = None,
        current_photo: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._image_path: str | None = None
        self.setWindowTitle("Edit Gallery Photo" if item else "Add Gallery Photo")
        self.setMinimumWidth(420)

        self._title_input = QLineEdit(item.title if item else "")
        self._description_input = QTextEdit(item.description if item else "")
        self._description_input.setMaximumHeight(100)
        self._photo_preview = QLabel("Choose a photo" if item is None else "Current photo")
        self._photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo_preview.setMinimumSize(240, 180)
        self._photo_preview.setMaximumSize(360, 240)
        self._photo_preview.setStyleSheet(
            "border: 1px dashed #d8afc3; border-radius: 10px; padding: 8px;"
        )
        if current_photo is not None and current_photo.is_file():
            pixmap = _thumbnail(current_photo, self._cache_key(current_photo))
            if not pixmap.isNull():
                self._set_preview(pixmap)

        choose_button = QPushButton("Choose photo...")
        choose_button.clicked.connect(self._choose_photo)
        form = QFormLayout()
        form.addRow("Title", self._title_input)
        form.addRow("Description", self._description_input)
        form.addRow(choose_button)
        form.addRow(self._photo_preview)

        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        save_button.clicked.connect(self._accept_if_valid)
        cancel_button.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)
        self.set_dialog_layout(form, footer)

    @property
    def title(self) -> str:
        return self._title_input.text().strip()

    @property
    def description(self) -> str:
        return self._description_input.toPlainText().strip()

    @property
    def image_path(self) -> str | None:
        return self._image_path

    def _choose_photo(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose gallery photo",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            QMessageBox.warning(
                self, "Unsupported photo", "Choose a PNG, JPG, JPEG, or WEBP image."
            )
            return
        try:
            if path.stat().st_size > 10 * 1024 * 1024:
                QMessageBox.warning(
                    self, "Photo is too large", "Photo files must be 10 MB or smaller."
                )
                return
        except OSError as error:
            QMessageBox.warning(self, "Could not read photo", str(error))
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            QMessageBox.warning(
                self, "Invalid photo", "Qt could not load the selected image."
            )
            return
        self._image_path = str(path)
        self._set_preview(
            pixmap.scaled(
                300,
                300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _accept_if_valid(self) -> None:
        if not self.title:
            QMessageBox.warning(self, "Title required", "Photo title is required.")
            return
        if self._item is None and self._image_path is None:
            QMessageBox.warning(
                self, "Photo required", "Choose a photo before adding the gallery item."
            )
            return
        self.accept()

    def _set_preview(self, pixmap: QPixmap) -> None:
        self._photo_preview.setText("")
        self._photo_preview.setPixmap(
            pixmap.scaled(
                self._photo_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @staticmethod
    def _cache_key(path: Path) -> str:
        try:
            return f"gallery:{path.resolve()}:{path.stat().st_mtime_ns}"
        except OSError:
            return f"gallery:{path}"


class NailGalleryScreen(BasePage):
    """Admin gallery management screen."""

    # Inheritance: this screen reuses the shared BasePage widget lifecycle.
    # Dependency injection: gallery persistence and file handling stay in GalleryManager.
    def __init__(self, gallery_manager: GalleryManager, parent=None) -> None:
        self._gallery_manager = gallery_manager
        self._items: list[GalleryItem] = []
        self._items_by_id: dict[int, GalleryItem] = {}
        super().__init__({"gallery_manager": gallery_manager}, parent)
        self.refresh()

    @property
    def gallery_manager(self) -> GalleryManager:
        return self._gallery_manager

    def build_ui(self) -> None:
        self._item_list = QListWidget()
        self._item_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._item_list.setIconSize(QSize(130, 130))
        self._item_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._item_list.setMovement(QListWidget.Movement.Static)
        self._item_list.setMinimumWidth(300)
        self._item_list.itemSelectionChanged.connect(self._update_detail)

        self._add_button = QPushButton("Add")
        self._edit_button = QPushButton("Edit")
        self._delete_button = QPushButton("Delete")
        self._edit_button.setEnabled(False)
        self._delete_button.setEnabled(False)
        self._add_button.clicked.connect(self.add_item)
        self._edit_button.clicked.connect(self.edit_item)
        self._delete_button.clicked.connect(self.delete_item)
        buttons = QHBoxLayout()
        buttons.addWidget(self._add_button)
        buttons.addWidget(self._edit_button)
        buttons.addWidget(self._delete_button)
        buttons.addStretch()

        self._detail_photo = QLabel("Select a photo")
        self._detail_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_photo.setMinimumSize(320, 280)
        self._detail_photo.setStyleSheet(
            "background: #ffffff; border: 1px solid #eddce5; border-radius: 12px;"
        )
        self._detail_title = QLabel()
        self._detail_title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self._detail_description = QLabel()
        self._detail_description.setWordWrap(True)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(self._detail_photo, 1)
        detail_layout.addWidget(self._detail_title)
        detail_layout.addWidget(self._detail_description)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._item_list)
        splitter.addWidget(detail)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        selected_id = self._selected_item_id()
        try:
            self._items = self._gallery_manager.get_gallery_items()
        except (sqlite3.Error, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not load gallery", str(error))
            return
        self._items_by_id = {
            item.item_id: item
            for item in self._items
            if item.item_id is not None
        }
        self._item_list.clear()
        selected_row = -1
        for index, item in enumerate(self._items):
            widget_item = QListWidgetItem(item.title)
            widget_item.setData(Qt.ItemDataRole.UserRole, item.item_id)
            photo_path = self._gallery_manager.resolve_photo_path(item.photo_path)
            if photo_path.is_file():
                pixmap = _thumbnail(photo_path, self._cache_key(photo_path))
                if not pixmap.isNull():
                    widget_item.setIcon(QIcon(pixmap))
            else:
                widget_item.setText(f"{item.title}\n(Photo missing)")
            self._item_list.addItem(widget_item)
            if item.item_id == selected_id:
                selected_row = index
        if selected_row >= 0:
            self._item_list.setCurrentRow(selected_row)
        else:
            self._clear_detail()
        enabled = self._selected_item_id() is not None
        self._edit_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)

    def add_item(self) -> None:
        dialog = GalleryItemDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._gallery_manager.add_gallery_item(
                dialog.title, dialog.description, dialog.image_path or ""
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            self._show_error("Could not add gallery photo", error)
            return
        self.refresh()

    def edit_item(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        current_photo = self._gallery_manager.resolve_photo_path(item.photo_path)
        dialog = GalleryItemDialog(item, current_photo, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._gallery_manager.update_gallery_item(
                item.item_id,
                dialog.title,
                dialog.description,
                dialog.image_path,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
            self._show_error("Could not update gallery photo", error)
            return
        self.refresh()
        self._select_item(item.item_id)

    def delete_item(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete photo",
            f"Delete '{item.title}' from the gallery?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._gallery_manager.remove_gallery_item(item.item_id)
        except (OSError, sqlite3.Error, KeyError) as error:
            self._show_error("Could not delete gallery photo", error)
            return
        self.refresh()

    def _update_detail(self) -> None:
        item = self._selected_item()
        enabled = item is not None
        self._edit_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)
        if item is None:
            self._clear_detail()
            return
        self._detail_title.setText(item.title)
        self._detail_description.setText(item.description or "")
        path = self._gallery_manager.resolve_photo_path(item.photo_path)
        if not path.is_file():
            self._detail_photo.setPixmap(QPixmap())
            self._detail_photo.setText("Photo is missing on disk.")
            return
        pixmap = _thumbnail(path, self._cache_key(path))
        if pixmap.isNull():
            self._detail_photo.setPixmap(QPixmap())
            self._detail_photo.setText("Photo could not be loaded.")
            return
        self._detail_photo.setText("")
        self._detail_photo.setPixmap(
            pixmap.scaled(
                self._detail_photo.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _selected_item(self) -> GalleryItem | None:
        item_id = self._selected_item_id()
        return self._items_by_id.get(item_id) if item_id is not None else None

    def _selected_item_id(self) -> int | None:
        selected = self._item_list.selectedItems() if hasattr(self, "_item_list") else []
        return selected[0].data(Qt.ItemDataRole.UserRole) if selected else None

    def _select_item(self, item_id: int) -> None:
        for row in range(self._item_list.count()):
            if self._item_list.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                self._item_list.setCurrentRow(row)
                return

    def _clear_detail(self) -> None:
        self._detail_photo.setPixmap(QPixmap())
        self._detail_photo.setText("Select a photo")
        self._detail_title.clear()
        self._detail_description.clear()

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))

    @staticmethod
    def _cache_key(path: Path) -> str:
        try:
            return f"gallery:{path.resolve()}:{path.stat().st_mtime_ns}"
        except OSError:
            return f"gallery:{path}"
