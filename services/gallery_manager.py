import shutil
import uuid
from pathlib import Path

from PyQt6.QtGui import QImageReader

from database import Database
from models import GalleryItem


class GalleryManager:
    """Gallery operations with image files managed outside the database."""

    _ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
    _MAX_IMAGE_SIZE = 10 * 1024 * 1024

    # Dependency injection: persistence is supplied by the application owner.
    def __init__(
        self,
        database: Database,
        gallery_directory: str | Path | None = None,
    ) -> None:
        self._database = database
        self._project_directory = Path(__file__).resolve().parent.parent
        self._gallery_directory = (
            Path(gallery_directory)
            if gallery_directory is not None
            else self._project_directory / "assets" / "gallery_photos"
        )

    @property
    def gallery_directory(self) -> Path:
        return self._gallery_directory

    def get_gallery_items(self) -> list[GalleryItem]:
        return self._database.get_gallery_items()

    def add_gallery_item(
        self,
        title: str,
        description: str | None,
        source_image_path: str | Path,
    ) -> GalleryItem:
        normalized_title = self._validate_title(title)
        source_path = self._validate_image(source_image_path)
        relative_path, copied_path = self._copy_image(source_path)
        try:
            item = GalleryItem(normalized_title, relative_path, description)
            return self._database.add_gallery_item(item)
        except Exception:
            copied_path.unlink(missing_ok=True)
            raise

    def update_gallery_item(
        self,
        item_id: int,
        title: str,
        description: str | None,
        new_image_path: str | Path | None = None,
    ) -> GalleryItem:
        item = self._database.get_gallery_item(item_id)
        if item is None:
            raise KeyError(f"No gallery item found with ID {item_id}")
        normalized_title = self._validate_title(title)
        old_photo_path = item.photo_path
        copied_path: Path | None = None
        new_photo_path = old_photo_path
        if new_image_path is not None:
            source_path = self._validate_image(new_image_path)
            new_photo_path, copied_path = self._copy_image(source_path)
        try:
            item.update_details(normalized_title, description, new_photo_path)
            self._database.update_gallery_item(item)
        except Exception:
            if copied_path is not None:
                copied_path.unlink(missing_ok=True)
            raise
        if copied_path is not None:
            self._remove_managed_photo(old_photo_path)
        return item

    def remove_gallery_item(self, item_id: int) -> None:
        item = self._database.get_gallery_item(item_id)
        if item is None:
            raise KeyError(f"No gallery item found with ID {item_id}")
        self._database.delete_gallery_item(item_id)
        self._remove_managed_photo(item.photo_path)

    def resolve_photo_path(self, photo_path: str) -> Path:
        path = Path(photo_path)
        if path.is_absolute():
            return path
        managed_prefix = Path("assets") / "gallery_photos"
        if path.parts[:2] == managed_prefix.parts:
            return self._gallery_directory / path.name
        return self._project_directory / path

    @classmethod
    def _validate_title(cls, title: str) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Photo title is required")
        return title.strip()

    @classmethod
    def _validate_image(cls, source_image_path: str | Path) -> Path:
        if not isinstance(source_image_path, (str, Path)) or not str(source_image_path).strip():
            raise ValueError("Choose a photo file")
        path = Path(source_image_path)
        if path.suffix.lower() not in cls._ALLOWED_SUFFIXES:
            raise ValueError("Choose a PNG, JPG, JPEG, or WEBP image")
        try:
            file_size = path.stat().st_size
        except OSError as error:
            raise ValueError(f"Could not read the selected photo: {error}") from error
        if file_size > cls._MAX_IMAGE_SIZE:
            raise ValueError("Photo files must be 10 MB or smaller")
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if reader.read().isNull():
            reason = reader.errorString()
            raise ValueError(f"The selected file is not a readable image: {reason}")
        return path

    def _copy_image(self, source_path: Path) -> tuple[str, Path]:
        self._gallery_directory.mkdir(parents=True, exist_ok=True)
        destination = self._gallery_directory / (
            f"{uuid.uuid4().hex}{source_path.suffix.lower()}"
        )
        shutil.copy2(source_path, destination)
        relative_path = Path("assets") / "gallery_photos" / destination.name
        return relative_path.as_posix(), destination

    def _remove_managed_photo(self, photo_path: str) -> None:
        path = self.resolve_photo_path(photo_path)
        try:
            path.resolve().relative_to(self._gallery_directory.resolve())
        except ValueError:
            return
        path.unlink(missing_ok=True)
