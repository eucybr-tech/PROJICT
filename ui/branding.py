from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap


LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "branding" / "logo.png"


def brand_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 256):
        icon.addPixmap(brand_circular_pixmap(size))
    return icon


def brand_circular_pixmap(size: int, ring: bool = True) -> QPixmap:
    if size <= 0:
        raise ValueError("size must be positive")
    source = QPixmap(str(LOGO_PATH)) if LOGO_PATH.is_file() else QPixmap()
    scale = 2
    canvas_size = size * scale
    padding = round(canvas_size * 0.06)
    diameter = canvas_size - (padding * 2)
    result = QPixmap(canvas_size, canvas_size)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    circle = QPainterPath()
    circle.addEllipse(padding, padding, diameter, diameter)
    painter.setClipPath(circle)
    if not source.isNull():
        side = min(source.width(), source.height())
        square = source.copy(
            (source.width() - side) // 2,
            (source.height() - side) // 2,
            side,
            side,
        )
        artwork = square.scaled(
            diameter,
            diameter,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(padding, padding, artwork)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F4B4B8"))
        painter.drawEllipse(padding, padding, diameter, diameter)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(round(diameter * 0.52))
        painter.setFont(font)
        painter.setPen(QColor("#8A5A6A"))
        painter.drawText(
            result.rect(),
            Qt.AlignmentFlag.AlignCenter,
            "P",
        )
    painter.setClipping(False)
    if ring:
        pen = painter.pen()
        pen.setColor(QColor("#F4B4B8"))
        pen.setWidth(4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = padding + 2
        painter.drawEllipse(
            inset,
            inset,
            canvas_size - (inset * 2),
            canvas_size - (inset * 2),
        )
    painter.end()
    return result.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def circular_photo_pixmap(photo_path: Path, size: int) -> QPixmap:
    if size <= 0:
        raise ValueError("size must be positive")

    source = QPixmap()
    try:
        if photo_path.is_file() and photo_path.stat().st_size > 0:
            source = QPixmap(str(photo_path))
    except (OSError, RuntimeError):
        return QPixmap()
    if source.isNull():
        return QPixmap()

    canvas_size = size * 2
    result = QPixmap(canvas_size, canvas_size)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    circle = QPainterPath()
    circle.addEllipse(0, 0, canvas_size, canvas_size)
    painter.setClipPath(circle)
    side = min(source.width(), source.height())
    square = source.copy(
        (source.width() - side) // 2,
        (source.height() - side) // 2,
        side,
        side,
    )
    artwork = square.scaled(
        canvas_size,
        canvas_size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawPixmap(0, 0, artwork)
    painter.end()
    return result.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def brand_pixmap(size: int, circular: bool = False) -> QPixmap:
    if circular:
        return brand_circular_pixmap(size)
    source = QPixmap(str(LOGO_PATH)) if LOGO_PATH.is_file() else QPixmap()
    if source.isNull():
        return QPixmap()
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return scaled
