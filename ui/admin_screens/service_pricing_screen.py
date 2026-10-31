import sqlite3
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QButtonGroup,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from models import PriceExtra, Service, format_duration
from services.price_extra_manager import PriceExtraManager
from services.pricing_calculator import PricingCalculator
from services.service_manager import ServiceManager
from ui.base_page import BasePage
from ui.scrollable_dialog import ScrollableDialog


class PriceOptionsEditor(QWidget):
    """Editable name/price rows reused for lengths and design add-ons."""

    def __init__(
        self, title: str, options: dict[str, float] | None = None
    ) -> None:
        super().__init__()
        self._title = title
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Name", "Price (₱)"])
        self._table.verticalHeader().setDefaultSectionSize(40)
        self._table.verticalHeader().setMinimumSectionSize(40)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        add_button = QPushButton("Add")
        remove_button = QPushButton("Remove")
        for button in (add_button, remove_button):
            button.setMinimumHeight(34)
            button.setStyleSheet("padding: 5px 12px;")
        add_button.clicked.connect(self.add_option)
        remove_button.clicked.connect(self.remove_selected)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)
        for name, price in (options or {}).items():
            self.add_option(name, price)

    def add_option(self, name: str = "", price: float = 0.0) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name))
        price_widget = QDoubleSpinBox()
        price_widget.setRange(0, 1_000_000_000)
        price_widget.setDecimals(2)
        price_widget.setPrefix("₱ ")
        price_widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        price_widget.setMinimumHeight(32)
        price_widget.setValue(price)
        self._table.setCellWidget(row, 1, price_widget)
        self._table.setRowHeight(row, 40)

    def remove_selected(self) -> None:
        selection_model = self._table.selectionModel()
        if selection_model is None:
            raise RuntimeError("Price option selection model is unavailable")
        for row in sorted(
            {index.row() for index in selection_model.selectedRows()},
            reverse=True,
        ):
            self._table.removeRow(row)

    def get_options(self) -> dict[str, float]:
        options: dict[str, float] = {}
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            name = item.text().strip() if item else ""
            if not name:
                raise ValueError(f"Every {self._title.lower()} option needs a name")
            if any(existing.casefold() == name.casefold() for existing in options):
                raise ValueError(f"Duplicate {self._title.lower()} option: {name}")
            price_widget = self._table.cellWidget(row, 1)
            if not isinstance(price_widget, QDoubleSpinBox):
                raise ValueError("Option price control is missing")
            options[name] = price_widget.value()
        return options


class ServicePricingTable(QTableWidget):
    _MINIMUM_NAME_WIDTH = 240

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_name_column()

    def _resize_name_column(self) -> None:
        if self.columnCount() < 2 or self.viewport().width() <= 0:
            return
        reserved = sum(
            self.columnWidth(column)
            for column in range(self.columnCount())
            if column != 1 and not self.isColumnHidden(column)
        )
        self.setColumnWidth(
            1,
            max(
                self._MINIMUM_NAME_WIDTH,
                self.viewport().width() - reserved,
            ),
        )


class ServiceDialog(ScrollableDialog):
    _STANDARD_LENGTHS = ("Short", "Medium", "Long", "Extra Long")

    def __init__(
        self, service: Service | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Service" if service else "Add Service")
        self.setMinimumSize(760, 420)
        self.resize(900, 540)

        self._name_edit = QLineEdit(service.name if service else "")
        self._description_edit = QLineEdit(
            (service.description or "") if service else ""
        )
        self._base_price = QDoubleSpinBox()
        self._base_price.setRange(0, 1_000_000_000)
        self._base_price.setDecimals(2)
        self._base_price.setPrefix("₱ ")
        self._base_price.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._base_price.setMinimumHeight(32)
        if service:
            self._base_price.setValue(service.base_price)
        self._duration_minutes = QSpinBox()
        self._duration_minutes.setRange(5, 240)
        self._duration_minutes.setSingleStep(5)
        self._duration_minutes.setSuffix(" minutes")
        self._duration_minutes.setValue(service.duration_minutes if service else 120)
        self._has_length_options = QCheckBox("Has length options")
        self._has_length_options.setChecked(bool(service and service.length_prices))
        length_prices = service.length_prices if service else {}
        if not service:
            length_prices = {name: 0.0 for name in self._STANDARD_LENGTHS}
        self._length_editor = PriceOptionsEditor("Length", length_prices)
        self._length_box = QGroupBox("Length add-on prices")
        length_layout = QVBoxLayout(self._length_box)
        length_layout.addWidget(self._length_editor)
        self._length_box.setVisible(self._has_length_options.isChecked())
        self._has_length_options.toggled.connect(self._length_box.setVisible)
        self._add_on_editor = PriceOptionsEditor(
            "Design add-on", service.design_add_on_prices if service else None
        )
        self._add_on_box = QGroupBox("Per-service design add-ons")
        add_on_layout = QVBoxLayout(self._add_on_box)
        add_on_layout.addWidget(self._add_on_editor)
        self._add_on_box.setVisible(
            bool(service and service.design_add_on_prices)
        )

        details_box = QGroupBox("Service details")
        details_form = QFormLayout(details_box)
        details_form.addRow("Service name", self._name_edit)
        details_form.addRow("Description", self._description_edit)
        details_form.addRow("Base price", self._base_price)
        details_form.addRow("Duration", self._duration_minutes)
        details_form.addRow("", self._has_length_options)

        columns = QGridLayout()
        columns.addWidget(details_box, 0, 0)
        columns.addWidget(self._length_box, 0, 1)
        columns.addWidget(self._add_on_box, 1, 0, 1, 2)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)
        columns.setRowStretch(1, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        for button in buttons.buttons():
            button.setMinimumHeight(34)
            button.setStyleSheet("padding: 5px 14px;")
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(columns, footer)

    def get_service_values(
        self,
    ) -> tuple[str, str, float, dict[str, float], dict[str, float], int]:
        name = self._name_edit.text().strip()
        if not name:
            raise ValueError("Service name is required")
        length_prices = (
            self._length_editor.get_options()
            if self._has_length_options.isChecked()
            else {}
        )
        if self._has_length_options.isChecked() and not length_prices:
            raise ValueError("Add at least one length option or clear Has length options")
        return (
            name,
            self._description_edit.text().strip(),
            self._base_price.value(),
            length_prices,
            self._add_on_editor.get_options(),
            self._duration_minutes.value(),
        )


class PriceExtraDialog(ScrollableDialog):
    def __init__(
        self, extra: PriceExtra | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Design" if extra else "Add Design")
        self._name = QLineEdit(extra.name if extra else "")
        self._category = QLineEdit(extra.category if extra else "design")
        self._price = QDoubleSpinBox()
        self._price.setRange(0, 1_000_000_000)
        self._price.setDecimals(2)
        self._price.setPrefix("₱ ")
        if extra:
            self._price.setValue(extra.price)
        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Category", self._category)
        form.addRow("Price", self._price)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(buttons)
        self.set_dialog_layout(form, footer)

    def get_extra(self, extra_id: int | None = None, active: bool = True) -> PriceExtra:
        name = self._name.text().strip()
        if not name:
            raise ValueError("Design name is required")
        return PriceExtra(
            name=name,
            category=self._category.text().strip() or "design",
            price=self._price.value(),
            active=active,
            extra_id=extra_id,
        )


class ServicePricingScreen(BasePage):
    """Desktop Admin service/design editor and price preview."""

    _CATEGORY_ALL = "All"
    _CATEGORY_SERVICES = "Services"
    _CATEGORY_DESIGNS = "Designs"
    _ENTITY_ROLE = Qt.ItemDataRole.UserRole
    _ID_ROLE = Qt.ItemDataRole.UserRole + 1
    _CATEGORY_LABELS = (
        _CATEGORY_ALL,
        _CATEGORY_SERVICES,
        _CATEGORY_DESIGNS,
    )

    def __init__(
        self,
        service_manager: ServiceManager,
        pricing_calculator: PricingCalculator,
        parent: QWidget | None = None,
        price_extra_manager: PriceExtraManager | None = None,
    ) -> None:
        self._service_manager = service_manager
        self._pricing_calculator = pricing_calculator
        self._price_extra_manager = price_extra_manager
        self._service_records: list[Service] = []
        self._price_extra_records: list[PriceExtra] = []
        self._category = self._CATEGORY_ALL
        super().__init__(
            {
                "service_manager": service_manager,
                "pricing_calculator": pricing_calculator,
            },
            parent,
        )
        self.refresh()

    @property
    def service_manager(self) -> ServiceManager:
        return self._service_manager

    @property
    def pricing_calculator(self) -> PricingCalculator:
        return self._pricing_calculator

    def build_ui(self) -> None:
        self.setObjectName("servicePricingScreen")
        self.setStyleSheet(
            """
            QWidget#servicePricingScreen QPushButton#servicePricingCategory {
                background-color: #ffffff;
                border: 1px solid #ead9d6;
                border-radius: 8px;
                color: #8A5A6A;
                padding: 8px 16px;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingCategory:checked {
                background-color: #F4B4B8;
                border-color: #d9979d;
                color: #3f3437;
            }
            QWidget#servicePricingScreen QTableWidget#servicePricingTable::item:selected {
                background-color: #f8e5e3;
                color: #3f3437;
            }
            QWidget#servicePricingScreen QTableWidget#servicePricingTable {
                font-size: 11px;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingAdd {
                background-color: #F4B4B8;
                border: 1px solid #d9979d;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingEdit {
                background-color: #ffffff;
                border: 1px solid #d9979d;
                color: #8A5A6A;
                border-radius: 6px;
                padding: 4px 9px;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingDelete {
                background-color: #ffffff;
                border: 1px solid #b5545d;
                color: #a3424d;
                border-radius: 6px;
                padding: 4px 9px;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingStatus[active="true"] {
                background-color: #e3f0e5;
                border: 1px solid #b8d4bd;
                color: #3f6848;
                border-radius: 12px;
                padding: 3px 8px;
            }
            QWidget#servicePricingScreen QPushButton#servicePricingStatus[active="false"] {
                background-color: #eeeae9;
                border: 1px solid #d7d0ce;
                color: #625b59;
                border-radius: 12px;
                padding: 3px 8px;
            }
            QWidget#servicePricingScreen QComboBox#servicePricingPreviewCombo {
                padding: 5px 26px 5px 8px;
            }
            QWidget#servicePricingScreen QComboBox#servicePricingPreviewCombo::drop-down {
                width: 22px;
                border: none;
                background: transparent;
            }
            """
        )
        self._category_group = QButtonGroup(self)
        self._category_group.setExclusive(True)
        self._category_buttons: dict[str, QPushButton] = {}
        category_row = QHBoxLayout()
        category_row.setContentsMargins(0, 0, 0, 0)
        category_row.setSpacing(6)
        for category in self._CATEGORY_LABELS:
            button = QPushButton()
            button.setObjectName("servicePricingCategory")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            self._category_group.addButton(button)
            self._category_buttons[category] = button
            button.clicked.connect(
                lambda _checked=False, selected=category: self._set_category(
                    selected
                )
            )
            category_row.addWidget(button)
        category_row.addStretch(1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search services and designs")
        self._search.textChanged.connect(self._filter_table)
        self._add_button = QPushButton("Add")
        self._add_button.setObjectName("servicePricingAdd")
        self._add_button.setMaximumWidth(76)
        self._add_button.clicked.connect(self.add_selected_kind)
        table_toolbar = QHBoxLayout()
        table_toolbar.addWidget(self._search, 1)
        table_toolbar.addWidget(self._add_button)

        self._service_table = ServicePricingTable(0, 6)
        self._service_table.setObjectName("servicePricingTable")
        self._headers = ["Picture", "Name", "Duration", "Price", "Status", "Actions"]
        self._sort_column = 1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._service_table.setHorizontalHeaderLabels(self._headers)
        self._service_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._service_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._service_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._service_table.setSortingEnabled(False)
        self._service_table.setWordWrap(True)
        self._service_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._service_table.verticalHeader().setVisible(False)
        self._service_table.verticalHeader().setDefaultSectionSize(60)
        self._service_table.verticalHeader().setMinimumSectionSize(56)
        header = self._service_table.horizontalHeader()
        if header is not None:
            header.setMinimumSectionSize(56)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
            header.setSortIndicatorShown(False)
            header.setSectionsClickable(True)
            header.sectionClicked.connect(self._sort_table_column)
        self._service_table.setColumnWidth(0, 56)
        self._service_table.setColumnWidth(1, 220)
        self._service_table.setColumnWidth(2, 110)
        self._service_table.setColumnWidth(4, 84)
        self._service_table.setColumnWidth(5, 120)
        self._service_table._resize_name_column()
        self._service_table.setMinimumWidth(720)
        self._update_sort_headers()
        self._service_table.itemSelectionChanged.connect(
            self._select_preview_service_from_table
        )

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(6, 0, 6, 0)
        center_layout.addLayout(table_toolbar)
        center_layout.addWidget(self._service_table, 1)

        self._preview_service = QComboBox()
        self._preview_service.setMinimumWidth(180)
        self._configure_preview_combo(self._preview_service)
        self._preview_length = QComboBox()
        self._configure_preview_combo(self._preview_length)
        self._preview_length_label = QLabel("Nail length")
        self._preview_add_ons = QListWidget()
        self._preview_add_ons.setMinimumHeight(150)
        self._preview_add_ons.setSelectionMode(
            QListWidget.SelectionMode.NoSelection
        )
        self._preview_add_ons.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_breakdown = QTableWidget(0, 2)
        self._preview_breakdown.setObjectName("servicePricingBreakdown")
        self._preview_breakdown.horizontalHeader().hide()
        self._preview_breakdown.verticalHeader().hide()
        self._preview_breakdown.setShowGrid(False)
        self._preview_breakdown.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self._preview_breakdown.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_breakdown.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._preview_breakdown.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._preview_breakdown.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._preview_breakdown.setMaximumHeight(160)
        self._preview_total = QLabel("Total: ₱ 0.00")
        self._preview_total.setStyleSheet(
            "color: #8A5A6A; font-size: 20px; font-weight: 700;"
        )
        self._preview_service.currentIndexChanged.connect(
            self._update_preview_options
        )
        self._preview_length.currentIndexChanged.connect(
            self._update_preview_total
        )
        self._preview_add_ons.itemChanged.connect(self._update_preview_total)
        preview_form = QVBoxLayout()
        preview_form.setContentsMargins(0, 0, 0, 0)
        preview_form.setSpacing(4)
        preview_form.addWidget(QLabel("Service"))
        preview_form.addWidget(self._preview_service)
        preview_form.addWidget(self._preview_length_label)
        preview_form.addWidget(self._preview_length)
        preview_form.addWidget(QLabel("Designs"))
        preview_form.addWidget(self._preview_add_ons)
        self._preview_box = QGroupBox("Price preview")
        preview_layout = QVBoxLayout(self._preview_box)
        preview_layout.addLayout(preview_form)
        preview_layout.addWidget(self._preview_breakdown)
        preview_layout.addWidget(self._preview_total)
        preview_panel = QWidget()
        preview_panel.setMinimumWidth(320)
        preview_panel_layout = QVBoxLayout(preview_panel)
        preview_panel_layout.setContentsMargins(6, 0, 0, 0)
        preview_panel_layout.addWidget(self._preview_box)
        preview_panel_layout.addStretch()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(center)
        splitter.addWidget(preview_panel)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([750, 320])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(category_row)
        layout.addWidget(splitter)

    def _set_category_counts(self) -> None:
        service_count = len(getattr(self, "_service_records", []))
        design_count = len(getattr(self, "_price_extra_records", []))
        counts = {
            self._CATEGORY_ALL: service_count + design_count,
            self._CATEGORY_SERVICES: service_count,
            self._CATEGORY_DESIGNS: design_count,
        }
        for category, button in self._category_buttons.items():
            button.setText(f"{category} ({counts[category]})")
            button.setChecked(category == self._category)
        self._service_table.setColumnHidden(
            4, self._category == self._CATEGORY_SERVICES
        )
        self._service_table._resize_name_column()

    @staticmethod
    def _configure_preview_combo(combo: QComboBox) -> None:
        combo.setObjectName("servicePricingPreviewCombo")
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setMinimumContentsLength(16)
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setToolTip(combo.currentText())
        combo.currentTextChanged.connect(combo.setToolTip)

    def _sort_table_column(self, column: int) -> None:
        if column not in (1, 2, 3):
            return
        header = self._service_table.horizontalHeader()
        if header is None:
            return
        if self._sort_column == column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder
        self._service_table.sortItems(column, self._sort_order)
        self._update_sort_headers()

    def _update_sort_headers(self) -> None:
        if not hasattr(self, "_headers"):
            return
        direction = (
            "▲"
            if self._sort_order == Qt.SortOrder.AscendingOrder
            else "▼"
        )
        for column, label in enumerate(self._headers):
            if column == self._sort_column:
                label = f"{label} {direction}"
            self._service_table.setHorizontalHeaderItem(
                column, QTableWidgetItem(label)
            )

    def _set_category(self, category: str) -> None:
        self._category = category
        self._category_buttons[category].setChecked(True)
        self._service_table.setColumnHidden(
            4, category == self._CATEGORY_SERVICES
        )
        self._filter_table()

    def refresh(self) -> None:
        try:
            self._service_records = self._service_manager.get_services()
            self._price_extra_records = (
                self._price_extra_manager.get_extras()
                if self._price_extra_manager is not None
                else []
            )
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not load services and designs", error)
            return
        self._set_category_counts()
        self._populate_table()
        self._refresh_preview_services()

    def _populate_table(self) -> None:
        self._service_table.setRowCount(0)
        for service in self._service_records:
            self._insert_service_row(service)
        for extra in self._price_extra_records:
            self._insert_design_row(extra)
        self._service_table._resize_name_column()
        self._service_table.sortItems(self._sort_column, self._sort_order)
        self._filter_table()

    def _insert_service_row(self, service: Service) -> None:
        row = self._service_table.rowCount()
        self._service_table.insertRow(row)
        self._service_table.setRowHeight(row, 60)
        self._set_thumbnail(row, "S", "service", service.service_id)
        name = self._create_entity_item(service.name, "service", service.service_id)
        name.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._service_table.setItem(row, 1, name)
        self._service_table.setItem(
            row, 2, QTableWidgetItem(format_duration(service.duration_minutes))
        )
        price = (
            min(service.length_prices.values()) + service.base_price
            if service.length_prices
            else service.base_price
        )
        price_text = (
            f"from ₱{price:,.0f}"
            if service.length_prices and price.is_integer()
            else f"from ₱{price:,.2f}"
            if service.length_prices
            else f"₱{price:,.0f}"
            if price.is_integer()
            else f"₱{price:,.2f}"
        )
        self._service_table.setItem(row, 3, QTableWidgetItem(price_text))
        self._service_table.setItem(row, 4, QTableWidgetItem("—"))
        self._set_row_actions(row, "service", service.service_id)

    def _insert_design_row(self, extra: PriceExtra) -> None:
        row = self._service_table.rowCount()
        self._service_table.insertRow(row)
        self._service_table.setRowHeight(row, 60)
        self._set_thumbnail(row, "D", "design", extra.extra_id)
        name = self._create_entity_item(extra.name, "design", extra.extra_id)
        name.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._service_table.setItem(row, 1, name)
        self._service_table.setItem(row, 2, QTableWidgetItem("—"))
        price_text = (
            f"₱{extra.price:,.0f}"
            if extra.price.is_integer()
            else f"₱{extra.price:,.2f}"
        )
        self._service_table.setItem(row, 3, QTableWidgetItem(price_text))
        status_button = QPushButton("Active" if extra.active else "Inactive")
        status_button.setObjectName("servicePricingStatus")
        status_button.setProperty("active", extra.active)
        status_button.setFixedSize(82, 28)
        status_button.setToolTip("Toggle design availability")
        status_button.clicked.connect(
            lambda _checked=False, extra_id=extra.extra_id: self._toggle_design(
                extra_id
            )
        )
        self._service_table.setCellWidget(row, 4, status_button)
        self._set_row_actions(row, "design", extra.extra_id)

    def _set_thumbnail(
        self,
        row: int,
        label: str,
        entity_type: str,
        entity_id: int | None,
    ) -> None:
        thumbnail = QLabel()
        thumbnail.setFixedSize(48, 48)
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_path = self._thumbnail_path(entity_type, entity_id)
        thumbnail.setPixmap(self._thumbnail_pixmap(image_path, label))
        thumbnail.setToolTip(
            str(image_path) if image_path is not None else "No picture available"
        )
        self._service_table.setCellWidget(row, 0, thumbnail)

    @staticmethod
    def _thumbnail_path(entity_type: str, entity_id: int | None) -> Path | None:
        if entity_id is None:
            return None
        directory = Path(__file__).resolve().parents[2] / "assets" / "services"
        for extension in (".png", ".jpg", ".jpeg"):
            image_path = directory / f"{entity_type}_{entity_id}{extension}"
            if image_path.is_file():
                return image_path
        return None

    @classmethod
    def _thumbnail_pixmap(cls, image_path: Path | None, label: str) -> QPixmap:
        if image_path is not None:
            try:
                pixmap = QPixmap(str(image_path))
            except (OSError, RuntimeError):
                pixmap = QPixmap()
            if not pixmap.isNull():
                return pixmap.scaled(
                    48,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        return cls._placeholder_pixmap(label)

    @staticmethod
    def _placeholder_pixmap(label: str) -> QPixmap:
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QWidget().palette().alternateBase())
        painter.drawRoundedRect(0, 0, 48, 48, 6, 6)
        painter.setPen(QWidget().palette().text().color())
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return pixmap

    @classmethod
    def _create_entity_item(
        cls, name: str, entity_type: str, entity_id: int | None
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(name)
        item.setToolTip(name)
        item.setData(cls._ENTITY_ROLE, entity_type)
        item.setData(cls._ID_ROLE, entity_id)
        return item

    def _set_row_actions(
        self, row: int, entity_type: str, entity_id: int | None
    ) -> None:
        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(2, 1, 2, 1)
        action_layout.setSpacing(4)
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        edit_button.setObjectName("servicePricingEdit")
        delete_button.setObjectName("servicePricingDelete")
        for button in (edit_button, delete_button):
            button.setFixedHeight(30)
            action_layout.addWidget(button)
        edit_button.setFixedWidth(54)
        delete_button.setFixedWidth(64)
        if entity_type == "service":
            edit_button.clicked.connect(
                lambda _checked=False, selected_id=entity_id: self._edit_service(
                    selected_id
                )
            )
            delete_button.clicked.connect(
                lambda _checked=False, selected_id=entity_id: self._delete_service(
                    selected_id
                )
            )
        else:
            edit_button.clicked.connect(
                lambda _checked=False, selected_id=entity_id: self._edit_design(
                    selected_id
                )
            )
            delete_button.clicked.connect(
                lambda _checked=False, selected_id=entity_id: self._delete_design(
                    selected_id
                )
            )
        self._service_table.setCellWidget(row, 5, actions)

    def _filter_table(self, *_args: object) -> None:
        query = self._search.text().strip().casefold()
        for row in range(self._service_table.rowCount()):
            item = self._service_table.item(row, 1)
            if item is None:
                self._service_table.setRowHidden(row, True)
                continue
            entity_type = item.data(self._ENTITY_ROLE)
            matches_category = (
                self._category == self._CATEGORY_ALL
                or self._category == self._CATEGORY_SERVICES
                and entity_type == "service"
                or self._category == self._CATEGORY_DESIGNS
                and entity_type == "design"
            )
            self._service_table.setRowHidden(
                row, not matches_category or query not in item.text().casefold()
            )

    def add_selected_kind(self) -> None:
        if self._category == self._CATEGORY_DESIGNS:
            self.add_extra()
        else:
            self.add_service()

    def _selected_entity(self) -> tuple[str, int] | None:
        row = self._service_table.currentRow()
        item = self._service_table.item(row, 1) if row >= 0 else None
        if item is None:
            return None
        entity_id = item.data(self._ID_ROLE)
        entity_type = item.data(self._ENTITY_ROLE)
        return (entity_type, entity_id) if entity_id is not None else None

    def _select_preview_service_from_table(self) -> None:
        selected = self._selected_entity()
        if selected is None or selected[0] != "service":
            return
        index = self._preview_service.findData(selected[1])
        if index >= 0:
            self._preview_service.setCurrentIndex(index)

    def _selected_service(self) -> Service | None:
        selected = self._selected_entity()
        if selected is None or selected[0] != "service":
            return None
        return next(
            (
                service
                for service in self._service_records
                if service.service_id == selected[1]
            ),
            None,
        )

    def _selected_extra(self) -> PriceExtra | None:
        selected = self._selected_entity()
        if selected is None or selected[0] != "design":
            return None
        return next(
            (
                extra
                for extra in self._price_extra_records
                if extra.extra_id == selected[1]
            ),
            None,
        )

    def add_extra(self) -> None:
        if self._price_extra_manager is None:
            QMessageBox.information(
                self, "Designs unavailable", "Design editing is not configured."
            )
            return
        dialog = PriceExtraDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._price_extra_manager.add_extra(dialog.get_extra())
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not add design", error)
            return
        self.refresh()

    def add_service(self) -> None:
        dialog = ServiceDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._service_manager.add_service(self._service_from_dialog(dialog))
        except (ValueError, TypeError, sqlite3.Error) as error:
            self._show_error("Could not add service", error)
            return
        self.refresh()

    def _edit_service(self, service_id: int | None) -> None:
        service = self._service_by_id(service_id)
        if service is None:
            QMessageBox.information(self, "Select a service", "Choose a service to edit.")
            return
        dialog = ServiceDialog(service, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._service_manager.update_service(
                self._service_from_dialog(dialog, service.service_id)
            )
        except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
            self._show_error("Could not update service", error)
            return
        self.refresh()

    def edit_selected_service(self) -> None:
        selected = self._selected_entity()
        if selected is None or selected[0] != "service":
            QMessageBox.information(self, "Select a service", "Choose a service to edit.")
            return
        self._edit_service(selected[1])

    def delete_selected_service(self) -> None:
        selected = self._selected_entity()
        if selected is None or selected[0] != "service":
            QMessageBox.information(self, "Select a service", "Choose a service to delete.")
            return
        self._delete_service(selected[1])

    def _delete_service(self, service_id: int | None) -> None:
        service = self._service_by_id(service_id)
        if service is None or service.service_id is None:
            QMessageBox.information(self, "Select a service", "Choose a service to delete.")
            return
        answer = QMessageBox.question(
            self,
            "Delete service",
            f"Delete {service.name!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service_manager.delete_service(service.service_id)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                "Service is in use",
                f"{service.name} cannot be deleted because it is used by an appointment.",
            )
            return
        except (ValueError, KeyError, sqlite3.Error) as error:
            self._show_error("Could not delete service", error)
            return
        self.refresh()

    def _edit_design(self, extra_id: int | None) -> None:
        extra = self._extra_by_id(extra_id)
        if extra is None or self._price_extra_manager is None:
            QMessageBox.information(self, "Select a design", "Choose a design to edit.")
            return
        dialog = PriceExtraDialog(extra, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._price_extra_manager.update_extra(
                dialog.get_extra(extra.extra_id, extra.active)
            )
        except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
            self._show_error("Could not update design", error)
            return
        self.refresh()

    def edit_selected_extra(self) -> None:
        selected = self._selected_entity()
        if selected is not None and selected[0] == "design":
            self._edit_design(selected[1])

    def _toggle_design(self, extra_id: int | None) -> None:
        extra = self._extra_by_id(extra_id)
        if extra is None or self._price_extra_manager is None:
            return
        try:
            self._price_extra_manager.update_extra(
                PriceExtra(
                    extra.name,
                    extra.price,
                    extra.category,
                    not extra.active,
                    extra.extra_id,
                )
            )
        except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
            self._show_error("Could not update design status", error)
            return
        self.refresh()

    def toggle_selected_extra(self) -> None:
        extra = self._selected_extra()
        if extra is None:
            QMessageBox.information(self, "Select a design", "Choose a design first.")
            return
        self._toggle_design(extra.extra_id)

    def _delete_design(self, extra_id: int | None) -> None:
        extra = self._extra_by_id(extra_id)
        if extra is None or extra.extra_id is None or self._price_extra_manager is None:
            QMessageBox.information(self, "Select a design", "Choose a design to delete.")
            return
        answer = QMessageBox.question(
            self,
            "Delete design",
            f"Delete {extra.name!r}? Existing appointments retain their saved design "
            "names and prices.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._price_extra_manager.delete_extra(extra.extra_id)
        except (ValueError, KeyError, sqlite3.Error) as error:
            self._show_error("Could not delete design", error)
            return
        self.refresh()

    def delete_selected_extra(self) -> None:
        selected = self._selected_entity()
        if selected is not None and selected[0] == "design":
            self._delete_design(selected[1])

    def _service_by_id(self, service_id: int | None) -> Service | None:
        return next(
            (service for service in self._service_records if service.service_id == service_id),
            None,
        )

    def _extra_by_id(self, extra_id: int | None) -> PriceExtra | None:
        return next(
            (extra for extra in self._price_extra_records if extra.extra_id == extra_id),
            None,
        )

    @staticmethod
    def _service_from_dialog(
        dialog: ServiceDialog, service_id: int | None = None
    ) -> Service:
        (
            name,
            description,
            base_price,
            length_prices,
            add_on_prices,
            duration_minutes,
        ) = dialog.get_service_values()
        return Service(
            name=name,
            description=description,
            base_price=base_price,
            length_prices=length_prices,
            design_add_on_prices=add_on_prices,
            service_id=service_id,
            duration_minutes=duration_minutes,
        )

    def _refresh_preview_services(self) -> None:
        current_id = self._preview_service.currentData()
        self._preview_service.blockSignals(True)
        self._preview_service.clear()
        for service in self._service_records:
            self._preview_service.addItem(service.name, service.service_id)
            self._preview_service.setItemData(
                self._preview_service.count() - 1,
                service.name,
                Qt.ItemDataRole.ToolTipRole,
            )
        selected_index = self._preview_service.findData(current_id)
        if selected_index < 0 and self._preview_service.count():
            selected_index = 0
        if selected_index >= 0:
            self._preview_service.setCurrentIndex(selected_index)
        self._preview_service.blockSignals(False)
        self._preview_service.setToolTip(self._preview_service.currentText())
        self._update_preview_options()

    def _update_preview_options(self, *_signal_args: object) -> None:
        service = self._preview_service_service()
        selected_length = self._preview_length.currentText()
        self._preview_length.blockSignals(True)
        self._preview_length.clear()
        if service:
            self._preview_length.addItems(service.length_prices.keys())
        index = self._preview_length.findText(selected_length)
        if index >= 0:
            self._preview_length.setCurrentIndex(index)
        self._preview_length.blockSignals(False)
        self._preview_length_label.setVisible(
            bool(service and service.length_prices)
        )
        self._preview_length.setVisible(bool(service and service.length_prices))

        selected_add_ons = self._checked_add_ons()
        self._preview_add_ons.blockSignals(True)
        self._preview_add_ons.clear()
        available_designs: dict[str, str] = {}
        if service:
            for name in service.design_add_on_prices:
                available_designs.setdefault(name.casefold(), name)
        for extra in self._price_extra_records:
            if extra.active:
                available_designs.setdefault(extra.name.casefold(), extra.name)
        self._preview_design_records = {
            extra.name.casefold(): extra for extra in self._price_extra_records
        }
        for name in available_designs.values():
            item = QListWidgetItem(name, self._preview_add_ons)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if name.casefold() in {value.casefold() for value in selected_add_ons}
                else Qt.CheckState.Unchecked
            )
        self._preview_add_ons.blockSignals(False)
        self._preview_add_ons.setCurrentRow(-1)
        self._update_preview_total()

    def _preview_service_service(self) -> Service | None:
        return self._service_by_id(self._preview_service.currentData())

    def _checked_add_ons(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self._preview_add_ons.count()):
            item = self._preview_add_ons.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                checked.add(item.text())
        return checked

    def _update_preview_total(self, *_signal_args: object) -> None:
        service = self._preview_service_service()
        if service is None:
            self._clear_preview_breakdown()
            self._preview_total.setText("Total: ₱ 0.00")
            return
        selected_names = self._checked_add_ons()
        selected_extra_prices = {
            extra.name: extra.price
            for extra in self._price_extra_records
            if extra.active
            and any(name.casefold() == extra.name.casefold() for name in selected_names)
        }
        service_add_ons = {
            name
            for name in selected_names
            if name in service.design_add_on_prices
        }
        try:
            total = self._pricing_calculator.calculate_price(
                service,
                self._preview_length.currentText(),
                service_add_ons,
                selected_extra_prices,
            )
        except (ValueError, TypeError) as error:
            self._clear_preview_breakdown()
            self._preview_total.setText("Total: —")
            self._show_error("Could not calculate price", error)
            return
        self._show_preview_breakdown(
            service, selected_names, selected_extra_prices
        )
        self._preview_total.setText(f"Total: ₱ {total:,.2f}")

    def _clear_preview_breakdown(self) -> None:
        self._preview_breakdown.clearContents()
        self._preview_breakdown.setRowCount(0)

    def _show_preview_breakdown(
        self,
        service: Service,
        selected_names: set[str],
        selected_extra_prices: dict[str, int | float],
    ) -> None:
        rows: list[tuple[str, int | float]] = [("Base", service.base_price)]
        length_name = self._preview_length.currentText()
        length_price = service.length_prices.get(length_name, 0)
        length_label = f"Length ({length_name})" if length_name else "Length"
        rows.append((length_label, length_price))

        global_extra_names = {
            name.casefold() for name in selected_extra_prices
        }
        service_add_ons = {
            name for name in selected_names if name in service.design_add_on_prices
        }
        for name in sorted(service_add_ons):
            if name.casefold() not in global_extra_names:
                rows.append((name, service.design_add_on_prices[name]))
        for name, price in selected_extra_prices.items():
            rows.append((name, price))

        self._clear_preview_breakdown()
        self._preview_breakdown.setRowCount(len(rows))
        header = self._preview_breakdown.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for row_index, (label_text, amount) in enumerate(rows):
            label = QTableWidgetItem(label_text)
            amount_item = QTableWidgetItem(f"₱ {amount:,.2f}")
            amount_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._preview_breakdown.setItem(row_index, 0, label)
            self._preview_breakdown.setItem(row_index, 1, amount_item)
            self._preview_breakdown.setRowHeight(row_index, 22)

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
