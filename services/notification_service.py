import html
import logging
import os
import smtplib
import threading
from datetime import datetime, timedelta, timezone as dt_timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Callable
from urllib.parse import quote


EmailCallback = Callable[[bool, str | None], None]
_LOGGER = logging.getLogger(__name__)


class NotificationService:
    """Sends appointment and queue emails using SMTP settings from the environment."""

    _STUDIO_NAME = "Pearl's SigNAILture"
    _LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "branding" / "logo.png"
    _APPOINTMENT_STATES = {
        "confirmed": (
            "Appointment confirmed - Pearl's SigNAILture",
            "Your appointment is confirmed",
            "Your appointment is confirmed. We look forward to seeing you.",
        ),
        "cancelled": (
            "Appointment cancelled - Pearl's SigNAILture",
            "Appointment cancelled",
            "Your appointment has been cancelled.",
        ),
        "rescheduled": (
            "Appointment rescheduled - Pearl's SigNAILture",
            "Appointment rescheduled",
            "Your appointment has been rescheduled.",
        ),
    }

    def send_booking_received(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int = 0,
        studio_address: str = "",
        studio_phone: str = "",
        provider_name: str = "",
        facebook_page: str = "",
        review_url: str = "",
        duration_minutes: int = 120,
        online_booking_url: str = "",
        map_link_url: str = "",
        full_name: str = "",
    ) -> None:
        self._send_appointment_email(
            email,
            "Booking received - Pearl's SigNAILture",
            "Your appointment is booked",
            "We received your booking request and will be in touch with any updates.",
            first_name,
            service_name,
            appointment_time,
            appointment_id,
            studio_address,
            studio_phone,
            provider_name,
            facebook_page,
            review_url,
            duration_minutes,
            online_booking_url,
            map_link_url=map_link_url,
            full_name=full_name,
        )

    def send_appointment_reminder(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int = 0,
        studio_address: str = "",
        studio_phone: str = "",
        provider_name: str = "",
        facebook_page: str = "",
        review_url: str = "",
        duration_minutes: int = 120,
        online_booking_url: str = "",
        calendar_sequence: int = 0,
        map_link_url: str = "",
        full_name: str = "",
    ) -> None:
        self._send_appointment_email(
            email,
            "Appointment reminder - Pearl's SigNAILture",
            "Reminder: your appointment is tomorrow",
            "We are looking forward to seeing you tomorrow.",
            first_name,
            service_name,
            appointment_time,
            appointment_id,
            studio_address,
            studio_phone,
            provider_name,
            facebook_page,
            review_url,
            duration_minutes,
            online_booking_url,
            include_calendar=True,
            calendar_sequence=calendar_sequence,
            map_link_url=map_link_url,
            full_name=full_name,
        )

    def send_appointment_thank_you(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int = 0,
        studio_address: str = "",
        studio_phone: str = "",
        provider_name: str = "",
        facebook_page: str = "",
        review_url: str = "",
        duration_minutes: int = 120,
        online_booking_url: str = "",
        map_link_url: str = "",
        full_name: str = "",
    ) -> None:
        self._send_appointment_email(
            email,
            "Thank you for visiting - Pearl's SigNAILture",
            "Thank you",
            "Thank you for visiting us. We hope you enjoyed your appointment.",
            first_name,
            service_name,
            appointment_time,
            appointment_id,
            studio_address,
            studio_phone,
            provider_name,
            facebook_page,
            review_url,
            duration_minutes,
            online_booking_url,
            map_link_url=map_link_url,
            full_name=full_name,
        )

    def send_appointment_status(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int,
        status: str,
        studio_address: str = "",
        studio_phone: str = "",
        provider_name: str = "",
        facebook_page: str = "",
        review_url: str = "",
        duration_minutes: int = 120,
        online_booking_url: str = "",
        map_link_url: str = "",
        full_name: str = "",
    ) -> None:
        try:
            subject, heading, body = self._APPOINTMENT_STATES[status]
        except KeyError as error:
            raise ValueError(f"Unsupported appointment email status: {status}") from error
        self._send_appointment_email(
            email,
            subject,
            heading,
            body,
            first_name,
            service_name,
            appointment_time,
            appointment_id,
            studio_address,
            studio_phone,
            provider_name,
            facebook_page,
            review_url,
            duration_minutes,
            online_booking_url,
            include_calendar=status == "confirmed",
            map_link_url=map_link_url,
            full_name=full_name,
        )

    def _send_appointment_email(
        self,
        email: str,
        subject: str,
        heading: str,
        message: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int,
        studio_address: str,
        studio_phone: str,
        provider_name: str,
        facebook_page: str,
        review_url: str,
        duration_minutes: int,
        online_booking_url: str,
        include_calendar: bool = False,
        calendar_sequence: int = 0,
        map_link_url: str = "",
        full_name: str = "",
    ) -> None:
        when = appointment_time.strftime("%A, %B %d, %Y at %I:%M %p")
        reference = f"PS-{appointment_id:06d}"
        address_directions_url = (
            "https://www.google.com/maps/search/?api=1&query="
            f"{quote(studio_address, safe='')}"
            if studio_address.strip()
            else ""
        )
        directions_url = (
            self._validated_http_url(map_link_url) or address_directions_url
        )
        logo_content = self._read_logo()
        calendar_content = (
            self._calendar_invite(
                service_name,
                appointment_time,
                duration_minutes,
                studio_address,
                appointment_id,
                calendar_sequence,
            )
            if include_calendar
            else None
        )
        text_content = self._appointment_text(
            heading,
            message,
            full_name,
            first_name,
            when,
            service_name,
            reference,
            studio_address,
            studio_phone,
            directions_url,
            provider_name,
            facebook_page,
            review_url,
        )
        html_content = self._appointment_html(
            heading,
            message,
            first_name,
            when,
            service_name,
            reference,
            studio_address,
            studio_phone,
            directions_url,
            logo_content is not None,
            provider_name,
            facebook_page,
            review_url,
            online_booking_url,
            full_name,
        )
        self._send_message(
            email,
            subject,
            text_content,
            html_content,
            logo_content,
            calendar_content,
        )

    @classmethod
    def _appointment_text(
        cls,
        heading: str,
        message: str,
        full_name: str,
        first_name: str,
        when: str,
        service_name: str,
        reference: str,
        studio_address: str,
        studio_phone: str,
        directions_url: str,
        provider_name: str,
        facebook_page: str,
        review_url: str,
    ) -> str:
        lines = [
            heading,
            "",
            f"Hi {cls._greeting_name(full_name, first_name)},",
            "",
            message,
            "",
            "Appointment details",
            f"When: {when}",
            f"Service: {service_name}",
            f"Booking ID: {reference}",
            "",
            cls._STUDIO_NAME,
        ]
        if studio_address.strip():
            lines.append(studio_address)
        if directions_url:
            lines.append(f"Get Directions: {directions_url}")
        if studio_phone.strip():
            lines.append(f"Phone: {studio_phone}")
        if facebook_page.strip():
            lines.append(f"Visit our Facebook page: {facebook_page}")
        if review_url.strip():
            lines.append(f"Write a Review: {review_url}")
        if provider_name.strip():
            lines.extend(("", "Thanks,", provider_name))
        return "\n".join(lines)

    @classmethod
    def _appointment_html(
        cls,
        heading: str,
        message: str,
        first_name: str,
        when: str,
        service_name: str,
        reference: str,
        studio_address: str,
        studio_phone: str,
        directions_url: str,
        has_logo: bool,
        provider_name: str,
        facebook_page: str,
        review_url: str,
        online_booking_url: str,
        full_name: str = "",
    ) -> str:
        escape = lambda value: html.escape(value, quote=True)
        logo = (
            '<img src="cid:studio-logo" alt="Pearl\'s SigNAILture" '
            'width="120" style="display:block;width:120px;height:auto;'
            'margin:0 auto 18px;">'
            if has_logo
            else ""
        )
        address = (
            f'<p style="margin:0 0 12px;color:#62545a;">{escape(studio_address)}</p>'
            if studio_address.strip()
            else ""
        )
        directions = (
            f'<p style="margin:0 0 16px;"><a href="{escape(directions_url)}" '
            'style="color:#a94f78;text-decoration:underline;">Get Directions</a></p>'
            if directions_url
            else ""
        )
        phone = (
            f'<p style="margin:0;color:#62545a;">Phone: '
            f'<a href="tel:{escape(quote(studio_phone, safe="+-"))}" '
            f'style="color:#a94f78;">{escape(studio_phone)}</a></p>'
            if studio_phone.strip()
            else ""
        )
        provider = (
            f'<tr><td style="padding:7px 14px;color:#796a70;">Provider</td>'
            f'<td style="padding:7px 14px;color:#44383d;">{escape(provider_name)}</td></tr>'
            if provider_name.strip()
            else ""
        )
        booking_link = cls._validated_http_url(online_booking_url)
        facebook_link = cls._validated_http_url(facebook_page)
        side_panel_link = (
            f'<p style="margin:0 0 12px;"><a href="{escape(booking_link)}" '
            'style="color:#a94f78;text-decoration:underline;">'
            "Book again</a></p>"
            if booking_link
            else (
                f'<p style="margin:0 0 12px;"><a href="{escape(facebook_link)}" '
                'style="color:#a94f78;text-decoration:underline;">'
                "Visit our Facebook page</a></p>"
                if facebook_link
                else ""
            )
        )
        review = (
            f'<p style="margin:0 0 12px;"><a href="{escape(review_url)}" '
            'style="color:#a94f78;text-decoration:underline;">'
            "Write a Review</a></p>"
            if review_url.strip()
            else ""
        )
        sign_off = (
            f'<p style="margin:22px 0 0;color:#62545a;">Thanks,<br>'
            f'{escape(provider_name)}</p>'
            if provider_name.strip()
            else ""
        )
        greeting_name = cls._greeting_name(full_name, first_name)
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@media only screen and (max-width: 600px) {{
  .email-card {{ width:100% !important; }}
  .email-column {{ display:block !important; width:100% !important; box-sizing:border-box; }}
  .studio-column {{ border-left:0 !important; border-top:1px solid #f0dce5 !important; }}
}}
</style>
</head>
<body style="margin:0;padding:24px 10px;background-color:#f8edf1;
font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#44383d;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="border-collapse:collapse;background-color:#f8edf1;">
<tr><td align="center" style="padding:12px;">
<table role="presentation" class="email-card" width="600" cellspacing="0"
cellpadding="0" style="width:100%;max-width:600px;border-collapse:collapse;
background-color:#ffffff;border:1px solid #f0dce5;border-radius:12px;">
<tr>
<td class="email-column" width="62%" valign="top"
style="width:62%;padding:32px 28px;">
<h1 style="margin:0 0 22px;color:#a94f78;font-size:24px;line-height:1.3;">
{escape(heading)}</h1>
<p style="margin:0 0 14px;font-size:15px;">Hi {escape(greeting_name)},</p>
<p style="margin:0 0 22px;color:#62545a;font-size:15px;line-height:1.6;">{escape(message)}</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="border-collapse:collapse;background-color:#fff7fa;border:1px solid #f0dce5;font-size:14px;">
<tr><td colspan="2" style="padding:14px 14px 8px;color:#a94f78;
font-size:16px;font-weight:bold;">Appointment details</td></tr>
<tr><td style="padding:7px 14px;color:#796a70;font-size:14px;">When</td>
<td style="padding:7px 14px;color:#44383d;font-size:14px;">{escape(when)}</td></tr>
<tr><td style="padding:7px 14px;color:#796a70;font-size:14px;">Service</td>
<td style="padding:7px 14px;color:#44383d;font-size:14px;">{escape(service_name)}</td></tr>
{provider}
<tr><td style="padding:7px 14px 14px;color:#796a70;font-size:14px;">Booking ID</td>
<td style="padding:7px 14px 14px;color:#44383d;font-size:14px;">{escape(reference)}</td></tr>
</table>
{sign_off}
</td>
<td class="email-column studio-column" width="38%" valign="top" align="center"
style="width:38%;padding:32px 22px;border-left:1px solid #f0dce5;
background-color:#fffafd;text-align:center;">
{logo}
<h2 style="margin:0 0 14px;color:#a94f78;font-size:18px;">
{escape(cls._STUDIO_NAME)}</h2>
{address}
{directions}
{phone}
{side_panel_link}
{review}
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    @staticmethod
    def _ics_escape_text(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\n", "\\n")
            .replace(",", "\\,")
            .replace(";", "\\;")
        )

    @staticmethod
    def _validated_http_url(value: str) -> str:
        candidate = value.strip()
        return (
            candidate
            if candidate.startswith(("http://", "https://"))
            else ""
        )

    @staticmethod
    def _greeting_name(full_name: str, first_name: str) -> str:
        return full_name.strip() or first_name.strip() or "there"

    @classmethod
    def _calendar_invite(
        cls,
        service_name: str,
        appointment_time: datetime,
        duration_minutes: int,
        studio_address: str,
        appointment_id: int,
        sequence: int = 0,
    ) -> str:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("calendar sequence must be a non-negative integer")
        timezone = dt_timezone(timedelta(hours=8), "Asia/Manila")
        start = (
            appointment_time.replace(tzinfo=timezone)
            if appointment_time.tzinfo is None
            else appointment_time.astimezone(timezone)
        )
        end = start + timedelta(minutes=duration_minutes)
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Pearl's SigNAILture//Appointment//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VTIMEZONE",
            "TZID:Asia/Manila",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            "TZOFFSETFROM:+0800",
            "TZOFFSETTO:+0800",
            "TZNAME:PHT",
            "END:STANDARD",
            "END:VTIMEZONE",
            "BEGIN:VEVENT",
            f"UID:PS-{appointment_id:06d}@pearls-signailture",
            f"SEQUENCE:{sequence}",
            f"DTSTAMP:{datetime.now(dt_timezone.utc):%Y%m%dT%H%M%SZ}",
            f"DTSTART;TZID=Asia/Manila:{start:%Y%m%dT%H%M%S}",
            f"DTEND;TZID=Asia/Manila:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{cls._ics_escape_text(service_name)}",
        ]
        if studio_address.strip():
            lines.append(f"LOCATION:{cls._ics_escape_text(studio_address)}")
        lines.extend(("END:VEVENT", "END:VCALENDAR", ""))
        return "\r\n".join(lines)

    @classmethod
    def _read_logo(cls) -> bytes | None:
        try:
            return cls._LOGO_PATH.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            _LOGGER.warning("Could not read studio logo at %s", cls._LOGO_PATH, exc_info=True)
            return None

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
    def _send_message(
        email: str,
        subject: str,
        content: str,
        html_content: str | None = None,
        logo_content: bytes | None = None,
        calendar_content: str | None = None,
    ) -> None:
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
        if html_content is not None:
            message.add_alternative(html_content, subtype="html")
            if logo_content is not None:
                message.get_payload()[-1].add_related(
                    logo_content,
                    maintype="image",
                    subtype="png",
                    cid="<studio-logo>",
                )
        if calendar_content is not None:
            message.add_attachment(
                calendar_content,
                subtype="calendar",
                params={"method": "PUBLISH"},
                filename="appointment.ics",
            )

        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(host, port, timeout=20) as smtp:
            if port != 465:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)

    def send_appointment_status_async(
        self,
        email: str,
        first_name: str,
        service_name: str,
        appointment_time: datetime,
        appointment_id: int,
        status: str,
        studio_address: str,
        studio_phone: str,
        callback: EmailCallback,
        provider_name: str = "",
        facebook_page: str = "",
        review_url: str = "",
        duration_minutes: int = 120,
        online_booking_url: str = "",
        map_link_url: str = "",
        full_name: str = "",
    ) -> threading.Thread:
        def send() -> None:
            try:
                self.send_appointment_status(
                    email,
                    first_name,
                    service_name,
                    appointment_time,
                    appointment_id,
                    status,
                    studio_address,
                    studio_phone,
                    provider_name,
                    facebook_page,
                    review_url,
                    duration_minutes,
                    online_booking_url,
                    map_link_url=map_link_url,
                    full_name=full_name,
                )
            except Exception as error:
                _LOGGER.exception(
                    "Could not send %s appointment email for appointment %s",
                    status,
                    appointment_id,
                )
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
