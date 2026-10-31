import os
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr
from typing import Callable


EmailCallback = Callable[[bool, str | None], None]


class NotificationService:
    """Sends appointment and queue emails using SMTP settings from the environment."""

    def send_appointment_status(self, email: str, appointment_summary: str) -> None:
        self._send_message(
            email,
            "Pearl's SigNAILture appointment update",
            "Your appointment has been updated.\n\n"
            f"{appointment_summary}\n\n"
            "Pearl's SigNAILture",
        )

    def send_queue_called(self, email: str) -> None:
        self._send_message(
            email,
            "You are next at Pearl's SigNAILture",
            "You are next at Pearl's SigNAILture",
        )

    def send_queue_called_async(
        self,
        email: str,
        callback: EmailCallback,
    ) -> threading.Thread:
        def send() -> None:
            try:
                self.send_queue_called(email)
            except Exception as error:
                callback(False, str(error))
            else:
                callback(True, None)

        thread = threading.Thread(
            target=send,
            name="queue-called-email",
            daemon=True,
        )
        thread.start()
        return thread

    @staticmethod
    def _send_message(email: str, subject: str, content: str) -> None:
        host = os.environ.get("SMTP_HOST", "").strip()
        port_text = os.environ.get("SMTP_PORT", "").strip()
        username = os.environ.get("SMTP_USER", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        sender_name = os.environ.get("SENDER_NAME", "").strip()
        if not all((host, port_text, username, password, sender_name)):
            raise RuntimeError("SMTP email settings are incomplete")

        try:
            port = int(port_text)
        except ValueError as error:
            raise RuntimeError("SMTP_PORT must be a valid port number") from error
        if not 1 <= port <= 65535:
            raise RuntimeError("SMTP_PORT must be between 1 and 65535")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((sender_name, username))
        message["To"] = email
        message.set_content(content)

        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(host, port, timeout=20) as smtp:
            if port != 465:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)

    def send_appointment_status_async(
        self,
        email: str,
        appointment_summary: str,
        callback: EmailCallback,
    ) -> threading.Thread:
        def send() -> None:
            try:
                self.send_appointment_status(email, appointment_summary)
            except Exception as error:
                callback(False, str(error))
            else:
                callback(True, None)

        thread = threading.Thread(
            target=send,
            name="appointment-email",
            daemon=True,
        )
        thread.start()
        return thread
