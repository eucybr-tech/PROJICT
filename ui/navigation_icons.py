from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


_ICON_DIRECTORY = Path(__file__).resolve().parent.parent / "assets" / "icons"
_ICON_SIZE = QSize(20, 20)
_NEUTRAL = "#6B7280"
_ACCENT = "#A96879"


def _render_icon(svg: str, color: str) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(
        svg.replace(_NEUTRAL, color).encode("utf-8")))
    pixmap = QPixmap(_ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


@lru_cache(maxsize=None)
def navigation_icon(name: str) -> QIcon:
    svg_path = _ICON_DIRECTORY / f"{name}.svg"
    svg = svg_path.read_text(encoding="utf-8")
    neutral = _render_icon(svg, _NEUTRAL)
    accent = _render_icon(svg, _ACCENT)
    icon = QIcon()
    icon.addPixmap(neutral, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(accent, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(accent, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(accent, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(accent, QIcon.Mode.Active, QIcon.State.On)
    icon.addPixmap(accent, QIcon.Mode.Selected, QIcon.State.On)
    return icon
