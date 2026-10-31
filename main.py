import sys
import traceback
from pathlib import Path
from types import TracebackType

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database import Database
from models import Admin, Staff
from services.client_manager import ClientManager
from services.gallery_manager import GalleryManager
from services.appointment_manager import AppointmentManager
from services.loyalty_manager import LoyaltyManager
from services.loyalty_web_server import LoyaltyWebServer
from services.notification_service import NotificationService
from services.pricing_calculator import PricingCalculator
from services.price_extra_manager import PriceExtraManager
from services.queue_manager import QueueManager
from services.service_manager import ServiceManager
from services.studio_settings_manager import StudioSettingsManager
from services.schedule_manager import ScheduleManager
from services.report_manager import ReportManager
from ui.admin_screens.appointment_calendar_screen import AppointmentCalendarScreen
from ui.admin_screens.client_management_screen import ClientManagementScreen
from ui.admin_screens.dashboard_screen import DashboardScreen
from ui.admin_screens.report_payments_screen import ReportPaymentsScreen
from ui.admin_screens.service_pricing_screen import ServicePricingScreen
from ui.admin_screens.studio_settings_screen import StudioSettingsScreen
from ui.admin_screens.schedule_screen import ScheduleScreen
from ui.base_window import BaseWindow
from ui.staff_screens.staff_appointment_screen import StaffAppointmentScreen
from ui.staff_screens.staff_queue_screen import StaffQueueScreen
from ui.staff_screens.staff_customer_screen import StaffCustomerScreen
from ui.customer_screens.queue_screen import QueueScreen
from ui.customer_screens.appointment_screen import CustomerAppointmentScreen
from ui.customer_screens.catalog_screen import CatalogScreen
from ui.customer_screens.map_screen import MapScreen, StudioInfo
from ui.admin_screens.loyalty_card_screen import LoyaltyCardScreen
from ui.admin_screens.map_screen import AdminMapScreen
from ui.admin_screens.nail_gallery_screen import NailGalleryScreen
from ui.customer_screens.gallery_screen import GalleryScreen
from ui.customer_screens.loyalty_screen import LoyaltyScreen
from ui.role_chooser import RoleChooser
from ui.branding import LOGO_PATH, brand_circular_pixmap
from ui.loyalty_scan_screen import LoyaltyScanScreen


ERROR_LOG_PATH = Path(__file__).resolve().parent / "data" / "application_errors.log"


def _handle_uncaught_exception(
    error_type: type[BaseException],
    error: BaseException,
    error_traceback: TracebackType | None,
) -> None:
    formatted_traceback = "".join(
        traceback.format_exception(error_type, error, error_traceback)
    )
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG_PATH.open("a", encoding="utf-8") as error_log:
            error_log.write(formatted_traceback)
            error_log.write("\n")
        log_notice = f"Details were saved to {ERROR_LOG_PATH}."
    except OSError as log_error:
        log_notice = f"Could not write the error log: {log_error}"

    from PyQt6.QtWidgets import QMessageBox

    QMessageBox.critical(
        None,
        "Unexpected error",
        f"An unexpected error occurred: {error}\n\n{log_notice}",
    )


def _size_desktop_window(window: QWidget) -> None:
    screen = QApplication.primaryScreen()
    if screen is None:
        window.setMinimumSize(1000, 600)
        window.resize(1000, 600)
        return
    available = screen.availableGeometry()
    width = min(1280, max(1, int(available.width() * 0.9)), available.width())
    height = min(720, max(1, int(available.height() * 0.9)), available.height())
    window.setMinimumSize(min(1000, width), min(600, height))
    window.setMaximumSize(available.width(), available.height())
    window.resize(max(window.minimumWidth(), width), max(window.minimumHeight(), height))
    window.move(
        available.x() + (available.width() - window.width()) // 2,
        available.y() + (available.height() - window.height()) // 2,
    )


def _navigation_and_stack(
    window: QMainWindow,
) -> tuple[QVBoxLayout, QWidget, QWidget]:
    central = window.centralWidget()
    layout = central.layout() if central is not None else None
    if not isinstance(layout, QVBoxLayout):
        raise RuntimeError("Window navigation layout is not initialized")
    navigation_item = layout.itemAt(0)
    stack_item = layout.itemAt(1)
    navigation = navigation_item.widget() if navigation_item else None
    screen_stack = stack_item.widget() if stack_item else None
    if navigation is None or screen_stack is None:
        raise RuntimeError("Window navigation and screen stack are not initialized")
    return layout, navigation, screen_stack


def _sidebar_logo() -> QLabel:
    logo = QLabel()
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setFixedSize(88, 88)
    pixmap = brand_circular_pixmap(88)
    if pixmap.isNull():
        logo.setText("P")
        logo.setStyleSheet(
            "background: #F4B4B8; color: #8A5A6A; border-radius: 44px; "
            "font-size: 30px; font-weight: 700;"
        )
    else:
        logo.setPixmap(pixmap)
    return logo


def _scrollable_sidebar(sidebar: QWidget) -> QScrollArea:
    sidebar.setFixedWidth(190)
    sidebar.setStyleSheet(
        "QPushButton { font-size: 12px; padding: 4px 6px; min-height: 22px; }"
        "QLabel#appTitle { font-size: 22px; }"
    )
    scroll_area = QScrollArea()
    scroll_area.setObjectName(f"{sidebar.objectName()}ScrollArea")
    scroll_area.setFixedWidth(190)
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    scroll_area.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    scroll_area.setWidget(sidebar)
    return scroll_area


class AdminWindow(BaseWindow):
    # Inheritance and polymorphism: each role window builds its own navigation.
    def __init__(
        self,
        service_manager: ServiceManager,
        pricing_calculator: PricingCalculator,
        client_manager: ClientManager,
        appointment_manager: AppointmentManager,
        queue_manager: QueueManager,
        loyalty_manager: LoyaltyManager,
        gallery_manager: GalleryManager,
        studio_settings_manager: StudioSettingsManager | None = None,
        schedule_manager: ScheduleManager | None = None,
        report_manager: ReportManager | None = None,
        price_extra_manager: PriceExtraManager | None = None,
        loyalty_web_server: LoyaltyWebServer | None = None,
    ) -> None:
        self._studio_settings_manager = studio_settings_manager
        self._loyalty_web_server = loyalty_web_server
        self._schedule_manager = schedule_manager
        self._has_report_manager = report_manager is not None
        super().__init__("Pearl's SigNAILture - Admin")
        self._admin_role = Admin("Pearl", "admin@pearls-signature.local")
        self._service_pricing_page = ServicePricingScreen(
            service_manager,
            pricing_calculator,
            price_extra_manager=price_extra_manager,
        )
        self._client_management_page = ClientManagementScreen(
            client_manager, self._admin_role
        )
        self._appointment_calendar_page = AppointmentCalendarScreen(
            appointment_manager,
            pricing_calculator,
            queue_manager,
            self._admin_role,
            studio_settings_manager=studio_settings_manager,
            loyalty_manager=loyalty_manager,
            loyalty_web_server=loyalty_web_server,
        )
        self._dashboard_page = (
            DashboardScreen(
                report_manager,
                self._appointment_calendar_page.appointment_panel,
                self._admin_role,
            )
            if report_manager is not None
            else None
        )
        self._report_payments_page = (
            ReportPaymentsScreen(
                report_manager,
                self._appointment_calendar_page.appointment_panel,
                self._admin_role,
            )
            if report_manager is not None
            else None
        )
        self._loyalty_page = LoyaltyCardScreen(
            loyalty_manager, loyalty_web_server=loyalty_web_server
        )
        self._loyalty_scan_page = LoyaltyScanScreen(
            loyalty_manager, admin_role=self._admin_role.get_role_name()
        )
        self._nail_gallery_page = NailGalleryScreen(gallery_manager)
        self._studio_settings_page = (
            StudioSettingsScreen(
                self._studio_settings_manager,
                loyalty_web_server=loyalty_web_server,
            )
            if self._studio_settings_manager is not None
            else None
        )
        self._map_page = (
            AdminMapScreen(self._studio_settings_manager, self._schedule_manager)
            if self._studio_settings_manager is not None
            else None
        )
        self._schedule_page = (
            ScheduleScreen(self._schedule_manager, self._admin_role)
            if self._schedule_manager is not None
            else None
        )
        if self._dashboard_page is not None:
            self.add_screen("Dashboard", self._dashboard_page, scrollable=True)
        self.add_screen("Service & Pricing", self._service_pricing_page, scrollable=True)
        self.add_screen("Client Management", self._client_management_page, scrollable=True)
        self.add_screen("Appointments", self._appointment_calendar_page, scrollable=True)
        self.add_screen("Digital Loyalty Card", self._loyalty_page, scrollable=True)
        self.add_screen("Scan Loyalty Card", self._loyalty_scan_page, scrollable=True)
        self.add_screen("Nail Gallery", self._nail_gallery_page, scrollable=True)
        if self._report_payments_page is not None:
            self.add_screen(
                "Reports & Payments", self._report_payments_page, scrollable=True
            )
        if self._studio_settings_page is not None:
            self.add_screen("Studio Settings", self._studio_settings_page, scrollable=True)
        if self._map_page is not None:
            self.add_screen("Map", self._map_page, scrollable=True)
        if self._schedule_page is not None:
            self.add_screen("Schedule", self._schedule_page, scrollable=True)

        # Arrange this role's navigation as a sidebar beside the shared screen stack.
        base_layout, navigation, screen_stack = _navigation_and_stack(self)
        base_layout.removeWidget(navigation)
        base_layout.removeWidget(screen_stack)
        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.addWidget(navigation)
        workspace_layout.addWidget(screen_stack, 1)
        self.setCentralWidget(workspace)
        _size_desktop_window(self)

    def build_navigation(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("adminSidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(_sidebar_logo(), alignment=Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("ADMIN")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        if self._has_report_manager:
            dashboard_button = QPushButton("Dashboard")
            dashboard_button.clicked.connect(lambda: self.show_screen("Dashboard"))
            layout.addWidget(dashboard_button)
        service_button = QPushButton("Service && Pricing")
        service_button.clicked.connect(
            lambda: self.show_screen("Service & Pricing")
        )
        layout.addWidget(service_button)
        client_button = QPushButton("Client Management")
        client_button.clicked.connect(
            lambda: self.show_screen("Client Management")
        )
        layout.addWidget(client_button)
        appointment_button = QPushButton("Appointments")
        appointment_button.clicked.connect(
            lambda: self.show_screen("Appointments")
        )
        layout.addWidget(appointment_button)
        loyalty_button = QPushButton("Digital Loyalty Card")
        loyalty_button.clicked.connect(
            lambda: self.show_screen("Digital Loyalty Card")
        )
        layout.addWidget(loyalty_button)
        loyalty_scan_button = QPushButton("Scan Loyalty Card")
        loyalty_scan_button.clicked.connect(
            lambda: self.show_screen("Scan Loyalty Card")
        )
        layout.addWidget(loyalty_scan_button)
        gallery_button = QPushButton("Nail Gallery")
        gallery_button.clicked.connect(lambda: self.show_screen("Nail Gallery"))
        layout.addWidget(gallery_button)
        if self._has_report_manager:
            reports_button = QPushButton("Reports && Payments")
            reports_button.clicked.connect(
                lambda: self.show_screen("Reports & Payments")
            )
            layout.addWidget(reports_button)
        if self._studio_settings_manager is not None:
            settings_button = QPushButton("Studio Settings")
            settings_button.clicked.connect(
                lambda: self.show_screen("Studio Settings")
            )
            layout.addWidget(settings_button)
            map_button = QPushButton("Map")
            map_button.clicked.connect(lambda: self.show_screen("Map"))
            layout.addWidget(map_button)
        if self._schedule_manager is not None:
            schedule_button = QPushButton("Schedule")
            schedule_button.clicked.connect(lambda: self.show_screen("Schedule"))
            layout.addWidget(schedule_button)
        layout.addStretch()
        return _scrollable_sidebar(sidebar)


class StaffWindow(BaseWindow):
    # Inheritance and polymorphism: navigation is overridden for the Staff role.
    def __init__(
        self,
        client_manager: ClientManager,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        queue_manager: QueueManager,
        report_manager: ReportManager | None = None,
        studio_settings_manager: StudioSettingsManager | None = None,
        loyalty_manager: LoyaltyManager | None = None,
    ) -> None:
        self._has_report_manager = report_manager is not None
        self._loyalty_manager = loyalty_manager
        super().__init__("Pearl's SigNAILture - Staff")
        self._staff_role = Staff("Pearl Staff", "staff@pearls-signature.local")
        self._customer_management_page = StaffCustomerScreen(
            client_manager, self._staff_role
        )
        self._appointment_page = StaffAppointmentScreen(
            appointment_manager,
            pricing_calculator,
            self._staff_role,
            studio_settings_manager=studio_settings_manager,
        )
        self._dashboard_page = (
            DashboardScreen(
                report_manager,
                self._appointment_page.appointment_panel,
                self._staff_role,
            )
            if report_manager is not None
            else None
        )
        self._queue_page = StaffQueueScreen(queue_manager)
        self._loyalty_scan_page = (
            LoyaltyScanScreen(
                loyalty_manager, admin_role=self._staff_role.get_role_name()
            )
            if loyalty_manager is not None
            else None
        )
        if self._dashboard_page is not None:
            self.add_screen("Dashboard", self._dashboard_page, scrollable=True)
        self.add_screen("Client Management", self._customer_management_page, scrollable=True)
        self.add_screen("Appointments", self._appointment_page, scrollable=True)
        self.add_screen("Queue", self._queue_page, scrollable=True)
        if self._loyalty_manager is not None:
            self.add_screen(
                "Scan Loyalty Card", self._loyalty_scan_page, scrollable=True
            )

        base_layout, navigation, screen_stack = _navigation_and_stack(self)
        base_layout.removeWidget(navigation)
        base_layout.removeWidget(screen_stack)
        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.addWidget(navigation)
        workspace_layout.addWidget(screen_stack, 1)
        self.setCentralWidget(workspace)
        _size_desktop_window(self)

    def build_navigation(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("staffSidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(_sidebar_logo(), alignment=Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("STAFF")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        if self._has_report_manager:
            dashboard_button = QPushButton("Dashboard")
            dashboard_button.clicked.connect(lambda: self.show_screen("Dashboard"))
            layout.addWidget(dashboard_button)
        clients_button = QPushButton("Client Management")
        clients_button.clicked.connect(
            lambda: self.show_screen("Client Management")
        )
        layout.addWidget(clients_button)
        appointments_button = QPushButton("Appointments")
        appointments_button.clicked.connect(
            lambda: self.show_screen("Appointments")
        )
        layout.addWidget(appointments_button)
        queue_button = QPushButton("Queue")
        queue_button.clicked.connect(lambda: self.show_screen("Queue"))
        layout.addWidget(queue_button)
        if self._loyalty_manager is not None:
            loyalty_scan_button = QPushButton("Scan Loyalty Card")
            loyalty_scan_button.clicked.connect(
                lambda: self.show_screen("Scan Loyalty Card")
            )
            layout.addWidget(loyalty_scan_button)
        layout.addStretch()
        return _scrollable_sidebar(sidebar)


class CustomerWindow(BaseWindow):
    # Inheritance and polymorphism: navigation is overridden for the Customer role.
    def __init__(
        self,
        queue_manager: QueueManager,
        loyalty_manager: LoyaltyManager,
        gallery_manager: GalleryManager,
        client_manager: ClientManager,
        service_manager: ServiceManager,
        appointment_manager: AppointmentManager,
        pricing_calculator: PricingCalculator,
        schedule_manager: ScheduleManager | None = None,
        studio_settings_manager: StudioSettingsManager | None = None,
    ) -> None:
        super().__init__("Pearl's SigNAILture - Customer")
        self._studio_info = StudioInfo(studio_settings_manager)
        self._appointment_page = CustomerAppointmentScreen(
            client_manager,
            service_manager,
            appointment_manager,
            pricing_calculator,
            self._studio_info,
        )
        self._catalog_page = CatalogScreen(service_manager)
        self._map_page = MapScreen(
            self._studio_info, schedule_manager, studio_settings_manager
        )
        self._queue_page = QueueScreen(queue_manager)
        self._loyalty_page = LoyaltyScreen(loyalty_manager)
        self._gallery_page = GalleryScreen(gallery_manager)
        self.add_screen("Appointment", self._appointment_page)
        self.add_screen("Catalog", self._catalog_page)
        self.add_screen("Loyalty", self._loyalty_page, scrollable=True)
        self.add_screen("Gallery", self._gallery_page)
        self.add_screen("Map", self._map_page, scrollable=True)
        self.add_screen("Queue", self._queue_page, scrollable=True)

        # Put the role-specific navigation after the screen stack as a bottom bar.
        base_layout, navigation, screen_stack = _navigation_and_stack(self)
        base_layout.removeWidget(navigation)
        base_layout.removeWidget(screen_stack)
        base_layout.addWidget(screen_stack, 1)
        base_layout.addWidget(navigation)
        self._nav_buttons["Appointment"].setChecked(True)
        self.show_screen("Appointment")
        self._size_customer_window()
        for area in self.findChildren(QScrollArea):
            area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            area.setWidgetResizable(True)

    def _size_customer_window(self) -> None:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width = min(390, available.width()) if available is not None else 390
        height = min(844, available.height()) if available is not None else 844
        self.setMinimumSize(min(390, width), min(600, height))
        self.setMaximumSize(width, height)
        self.resize(width, height)
        if available is not None:
            self.move(
                available.x() + (available.width() - self.width()) // 2,
                available.y() + (available.height() - self.height()) // 2,
            )

    def build_navigation(self) -> QWidget:
        navigation = QWidget()
        layout = QHBoxLayout(navigation)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)
        navigation.setFixedHeight(58)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._navigation_group = QButtonGroup(navigation)
        self._navigation_group.setExclusive(True)
        for screen_name in (
            "Appointment",
            "Catalog",
            "Loyalty",
            "Gallery",
            "Map",
            "Queue",
        ):
            button = QPushButton(screen_name)
            button.setCheckable(True)
            button.setMinimumHeight(48)
            self._navigation_group.addButton(button)
            button.setStyleSheet(
                "QPushButton { font-size: 9px; padding: 5px 2px; }"
                "QPushButton:checked { background-color: #c8799d; "
                "border-color: #ad6388; color: white; }"
            )
            button.clicked.connect(
                lambda _checked=False, name=screen_name: self._navigate_to(name)
            )
            self._nav_buttons[screen_name] = button
            layout.addWidget(button, 1)
        return navigation

    def _navigate_to(self, screen_name: str) -> None:
        self._nav_buttons[screen_name].setChecked(True)
        self.show_screen(screen_name)


def main() -> int:
    app = QApplication(sys.argv)
    sys.excepthook = _handle_uncaught_exception

    database = Database()
    database.initialize_schema()
    loyalty_manager = LoyaltyManager(database)
    studio_settings_manager = StudioSettingsManager(database)
    loyalty_web_server = LoyaltyWebServer(
        database.database_path,
        port=studio_settings_manager.get_loyalty_web_port(),
        logo_path=LOGO_PATH,
    )
    app.aboutToQuit.connect(loyalty_web_server.stop)
    app.aboutToQuit.connect(database.close)
    schedule_manager = ScheduleManager(database)
    report_manager = ReportManager(database)
    gallery_manager = GalleryManager(database)
    service_manager = ServiceManager(database)
    price_extra_manager = PriceExtraManager(database)
    pricing_calculator = PricingCalculator()
    client_manager = ClientManager(database)
    appointment_manager = AppointmentManager(
        database,
        pricing_calculator,
        NotificationService(),
        loyalty_manager,
        schedule_manager=schedule_manager,
    )
    queue_manager = QueueManager(database, appointment_manager)

    stylesheet_path = Path(__file__).resolve().parent / "styles" / "salon.qss"
    try:
        with stylesheet_path.open(encoding="utf-8") as stylesheet_file:
            app.setStyleSheet(stylesheet_file.read())
    except OSError as error:
        raise RuntimeError(f"Could not load stylesheet at {stylesheet_path}") from error

    chooser = RoleChooser(
        {
            "Customer": lambda: CustomerWindow(
                queue_manager,
                loyalty_manager,
                gallery_manager,
                client_manager,
                service_manager,
                appointment_manager,
                pricing_calculator,
                schedule_manager,
                studio_settings_manager,
            ),
            "Staff": lambda: StaffWindow(
                client_manager,
                appointment_manager,
                pricing_calculator,
                queue_manager,
                report_manager,
                studio_settings_manager=studio_settings_manager,
                loyalty_manager=loyalty_manager,
            ),
            "Admin": lambda: AdminWindow(
                service_manager,
                pricing_calculator,
                client_manager,
                appointment_manager,
                queue_manager,
                loyalty_manager,
                gallery_manager,
                studio_settings_manager,
                schedule_manager,
                report_manager,
                price_extra_manager,
                loyalty_web_server,
            ),
        }
    )
    chooser.setWindowTitle("Pearl's SigNAILture")
    chooser.resize(620, 240)
    chooser.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
