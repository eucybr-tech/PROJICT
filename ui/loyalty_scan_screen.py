import sqlite3

try:
    import cv2
except (ImportError, OSError):
    cv2 = None

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.loyalty_manager import LoyaltyManager
from ui.base_page import BasePage


class LoyaltyScanScreen(BasePage):
    """Staff and Admin lookup of loyalty cards by their QR card code."""

    def __init__(
        self, loyalty_manager: LoyaltyManager, parent=None, admin_role: str = "Staff"
    ) -> None:
        self._loyalty_manager = loyalty_manager
        self._admin_role = admin_role
        self._camera = None
        self._detector = None
        self._stamp_added_for_lookup = False
        self._camera_available = False
        self._camera_timer = QTimer()
        self._camera_timer.setInterval(100)
        self._camera_timer.timeout.connect(self._read_camera_frame)
        super().__init__({"loyalty_manager": loyalty_manager}, parent)

    def build_ui(self) -> None:
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("Scan or type card code")
        self._code_input.setAccessibleName("Scan or type card code")
        self._code_input.returnPressed.connect(self.lookup_code)
        self._lookup_button = QPushButton("Find card")
        self._lookup_button.clicked.connect(self.lookup_code)
        lookup_row = QHBoxLayout()
        lookup_row.addWidget(self._code_input, 1)
        lookup_row.addWidget(self._lookup_button)

        self._camera_button = QPushButton("Scan with camera")
        self._camera_button.clicked.connect(self._toggle_camera_scan)
        self._camera_status = QLabel()
        self._camera_status.setWordWrap(True)
        self._camera_available = self._is_camera_available()
        self._camera_button.setVisible(self._camera_available)
        self._camera_status.setVisible(not self._camera_available)
        if not self._camera_available:
            self._camera_status.setText("Camera scan is unavailable.")

        self._client_name = QLabel("No card selected.")
        self._stamp_status = QLabel()
        self._card_status = QLabel()
        self._reward_status = QLabel()
        self._waiting_status = QLabel()
        for label in (
            self._client_name,
            self._card_status,
            self._stamp_status,
            self._reward_status,
            self._waiting_status,
        ):
            label.setWordWrap(True)

        details = QGroupBox("Loyalty card")
        details_form = QFormLayout(details)
        details_form.addRow("Client", self._client_name)
        details_form.addRow("Card", self._card_status)
        details_form.addRow("Stamps", self._stamp_status)
        details_form.addRow("Reward", self._reward_status)
        details_form.addRow("Visit", self._waiting_status)

        self._add_stamp_button = QPushButton("Add stamp")
        self._add_stamp_button.setEnabled(False)
        self._add_stamp_button.clicked.connect(self.add_stamp)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(lookup_row)
        camera_row = QHBoxLayout()
        camera_row.addWidget(self._camera_button)
        camera_row.addWidget(self._camera_status, 1)
        camera_row.addStretch()
        layout.addLayout(camera_row)
        layout.addWidget(details)
        layout.addWidget(self._add_stamp_button)
        layout.addStretch()

    def _is_camera_available(self) -> bool:
        if cv2 is None or not hasattr(cv2, "QRCodeDetector"):
            return False
        camera = None
        try:
            camera = cv2.VideoCapture(0)
            available = bool(camera.isOpened())
        except (OSError, RuntimeError, TypeError, AttributeError):
            available = False
        finally:
            if camera is not None:
                camera.release()
        return available

    def _toggle_camera_scan(self) -> None:
        if self._camera_timer.isActive():
            self._stop_camera_scan()
            return
        if cv2 is None:
            self._set_camera_unavailable()
            return
        try:
            camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                camera.release()
                self._set_camera_unavailable()
                return
            self._camera = camera
            self._detector = cv2.QRCodeDetector()
        except (OSError, RuntimeError, TypeError, AttributeError):
            if self._camera is not None:
                self._camera.release()
            self._camera = None
            self._set_camera_unavailable()
            return
        self._camera_button.setText("Stop camera scan")
        self._camera_timer.start()

    def _read_camera_frame(self) -> None:
        if self._camera is None or self._detector is None:
            self._stop_camera_scan()
            return
        try:
            success, frame = self._camera.read()
            if not success:
                self._stop_camera_scan()
                self._camera_status.setText(
                    "Could not read from the camera. Type the card code instead."
                )
                self._camera_status.setVisible(True)
                return
            code, _points, _straight_qr = self._detector.detectAndDecode(frame)
        except (OSError, RuntimeError, TypeError, AttributeError):
            self._stop_camera_scan()
            self._camera_status.setText(
                "Camera scan failed. Type the card code instead."
            )
            self._camera_status.setVisible(True)
            return
        if code:
            self._stop_camera_scan()
            self._code_input.setText(code.strip())
            self.lookup_code()

    def _stop_camera_scan(self) -> None:
        self._camera_timer.stop()
        if self._camera is not None:
            self._camera.release()
        self._camera = None
        self._detector = None
        if self._camera_available:
            self._camera_button.setText("Scan with camera")

    def _set_camera_unavailable(self) -> None:
        self._camera_available = False
        self._camera_button.hide()
        self._camera_status.setText("Camera scan is unavailable.")
        self._camera_status.show()

    def lookup_code(self) -> None:
        self._stop_camera_scan()
        code = self._code_input.text().strip()
        self._stamp_added_for_lookup = False
        self._add_stamp_button.setEnabled(False)
        if not code:
            self._show_unknown_card()
            self._client_name.setText("Enter a card code to search.")
            return
        try:
            details = self._loyalty_manager.get_scan_details(code)
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not find loyalty card", error)
            return
        if details is None:
            self._show_unknown_card()
            return
        self._show_details(details)

    def _show_unknown_card(self) -> None:
        self._client_name.setText("No loyalty card found for that code.")
        self._card_status.clear()
        self._stamp_status.clear()
        self._reward_status.clear()
        self._waiting_status.clear()

    def _show_details(self, details: tuple[str, int, int, int, int]) -> None:
        name, stamps, card_number, required, waiting_count = details
        self._client_name.setText(name)
        self._card_status.setText(f"Card {card_number}")
        self._stamp_status.setText(f"{stamps} of {required}")
        self._reward_status.setText(
            "Reward ready" if stamps >= required else "Not ready"
        )
        self._waiting_status.setText(
            "Completed visit waiting for a stamp"
            if waiting_count
            else "No completed visit waiting for a stamp"
        )
        self._add_stamp_button.setEnabled(
            waiting_count > 0 and not self._stamp_added_for_lookup
        )

    def add_stamp(self) -> None:
        code = self._code_input.text().strip()
        if not code or self._stamp_added_for_lookup:
            self._add_stamp_button.setEnabled(False)
            return
        self._stamp_added_for_lookup = True
        self._add_stamp_button.setEnabled(False)
        try:
            card = self._loyalty_manager.add_stamp_for_card_code(
                code, self._admin_role
            )
            details = self._loyalty_manager.get_scan_details(code)
        except (sqlite3.Error, ValueError, TypeError) as error:
            self._show_error("Could not add loyalty stamp", error)
            return
        if card is None or details is None:
            self._show_unknown_card()
            return
        self._show_details(details)
        self._add_stamp_button.setEnabled(False)
        self._stamp_status.setText(f"{card.stamps} of {details[3]}")
        if details[4]:
            self._waiting_status.setText(
                "Stamp added. Another completed visit is waiting; scan this card "
                "again to add its stamp."
            )
        else:
            self._waiting_status.setText("Stamp added. No completed visit waiting for a stamp.")

    def _show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))
