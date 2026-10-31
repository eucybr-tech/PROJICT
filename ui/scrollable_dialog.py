from PyQt6.QtCore import QChildEvent, QEvent, QObject, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ScrollableDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dialog_layout = QVBoxLayout(self)
        self._dialog_layout.setContentsMargins(12, 12, 12, 12)
        self._dialog_layout.setSpacing(8)
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setMinimumSize(0, 0)
        self._dialog_layout.addWidget(self._scroll_area, 1)
        self._footer: QWidget | None = None

    @property
    def footer(self) -> QWidget | None:
        return self._footer

    @property
    def scroll_area(self) -> QScrollArea:
        return self._scroll_area

    def set_dialog_layout(
        self, content_layout: QLayout, footer_layout: QLayout
    ) -> None:
        content = QWidget()
        content.setLayout(content_layout)
        content.setMinimumSize(0, 0)
        self._scroll_area.setWidget(content)

        footer = QWidget()
        footer.setLayout(footer_layout)
        self._footer = footer
        self._dialog_layout.addWidget(footer)

        for widget in (content, *content.findChildren(QWidget)):
            widget.installEventFilter(self)
        self._fit_to_available_screen()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QChildEvent):
            child = event.child()
            if isinstance(child, QWidget):
                child.installEventFilter(self)
            return super().eventFilter(watched, event)
        if not isinstance(event, QWheelEvent):
            return super().eventFilter(watched, event)

        if isinstance(watched, (QComboBox, QAbstractSpinBox)):
            if watched.hasFocus():
                return super().eventFilter(watched, event)
            event.accept()
            return True

        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta:
            scroll_bar = self._scroll_area.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.value() - delta)
        event.accept()
        return True

    def _available_geometry(self) -> QRect | None:
        screen = self.screen()
        if screen is None and self.parentWidget() is not None:
            screen = self.parentWidget().screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _fit_to_available_screen(self) -> None:
        available = self._available_geometry()
        if available is None:
            return

        maximum_width = max(1, available.width() - 80)
        maximum_height = max(1, available.height() - 80)
        self.setMaximumSize(maximum_width, maximum_height)
        self.adjustSize()
        width = min(max(self.minimumWidth(), self.sizeHint().width()), maximum_width)
        height = min(max(self.minimumHeight(), self.sizeHint().height()), maximum_height)
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )
