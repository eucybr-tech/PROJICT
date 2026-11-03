import base64
import html
import mimetypes
import re
import socket
import sqlite3
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from database import Database


_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{22}\Z")
_STAMP_PATH_PATTERN = re.compile(r"/stamp/([^/]+)\Z")
_CARD_PATH_PATTERN = re.compile(r"/card/([^/]+)\Z")
_FALLBACK_LOGO = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    b'<circle cx="50" cy="50" r="48" fill="#f4b4b8"/>'
    b'<text x="50" y="66" text-anchor="middle" font-size="56" '
    b'font-family="sans-serif" fill="#8a5a6a">P</text></svg>'
)


class _ReadyHTTPServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
    ) -> None:
        self.ready = threading.Event()
        super().__init__(server_address, request_handler)

    def service_actions(self) -> None:
        self.ready.set()
        super().service_actions()


def get_lan_ip() -> str | None:
    """Return the outbound LAN interface address without sending a packet."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    if not address or address.startswith("127.") or address == "0.0.0.0":
        return None
    return address


class LoyaltyWebServer:
    """Small, private-card HTTP server hosted on the application's machine."""

    def __init__(
        self,
        database_path: str | Path,
        port: int = 8765,
        salon_name: str = "Pearl's SigNAILture",
        logo_path: str | Path | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._port = self._validate_port(port)
        self._salon_name = salon_name
        self._logo_path = Path(logo_path) if logo_path is not None else None
        self._httpd: _ReadyHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._database: Database | None = None
        self._rate_lock = threading.Lock()
        self._requests_by_ip: dict[str, deque[float]] = {}

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status_text(self) -> str:
        if not self.is_running:
            return "Stopped"
        address = get_lan_ip()
        if address is None:
            return "Running, but no network interface is available"
        return f"Running at http://{address}:{self._port}"

    def configure_port(self, port: int) -> None:
        if self.is_running:
            raise RuntimeError("Stop the loyalty web server before changing its port")
        self._port = self._validate_port(port)

    def build_url(self, path: str) -> str:
        address = get_lan_ip()
        if address is None:
            raise OSError("No network is available to create a phone link.")
        return f"http://{address}:{self._port}{path}"

    def start(self) -> None:
        if self.is_running:
            return
        database = Database(self._database_path, check_same_thread=False)
        try:
            database.initialize_schema()
            httpd = _ReadyHTTPServer(
                ("0.0.0.0", self._port), self._make_handler()
            )
        except (OSError, sqlite3.Error, RuntimeError):
            database.close()
            raise
        self._database = database
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="loyalty-web-server",
            daemon=True,
        )
        self._thread.start()
        if not httpd.ready.wait(timeout=5):
            self.stop()
            raise RuntimeError("The loyalty web server did not start in time")

    def stop(self) -> None:
        httpd = self._httpd
        thread = self._thread
        if httpd is not None and thread is not None and thread.is_alive():
            httpd.shutdown()
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("The loyalty web server did not stop in time")
        if httpd is not None:
            httpd.server_close()
        database = self._database
        if database is not None:
            database.close()
        self._database = None
        self._httpd = None
        self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class LoyaltyRequestHandler(BaseHTTPRequestHandler):
            server_version = "LoyaltyCard"
            sys_version = ""

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def handle_error(self, _request: object, _client_address: object) -> None:
                print("Loyalty web server request failed", file=sys.stderr)

            def do_GET(self) -> None:
                if not owner._allow_request(self.client_address[0]):
                    self._send(429, "text/plain; charset=utf-8", "Too many requests")
                    return
                path = urlsplit(self.path).path
                stamp_match = _STAMP_PATH_PATTERN.fullmatch(path)
                if stamp_match is not None:
                    self._serve_stamp(stamp_match.group(1))
                    return
                card_match = _CARD_PATH_PATTERN.fullmatch(path)
                if card_match is not None:
                    self._serve_card(card_match.group(1))
                    return
                self._send(404, "text/plain; charset=utf-8", "Not found")

            def _serve_stamp(self, token: str) -> None:
                if _CODE_PATTERN.fullmatch(token) is None:
                    self._serve_status_page("invalid", 200)
                    return
                database = owner._database
                if database is None:
                    self._send(503, "text/plain; charset=utf-8", "Service unavailable")
                    return
                try:
                    status, view_code = database.redeem_stamp_token(token)
                except (sqlite3.Error, RuntimeError):
                    self._serve_status_page("failure", 503)
                    return
                if status == "success" and view_code is not None:
                    if _CODE_PATTERN.fullmatch(view_code) is None:
                        self._serve_status_page("invalid", 200)
                        return
                    self.send_response(303)
                    self.send_header("Location", f"/card/{view_code}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._serve_status_page(status, 200)

            def _serve_card(self, view_code: str) -> None:
                if _CODE_PATTERN.fullmatch(view_code) is None:
                    self._send(404, "text/plain; charset=utf-8", "Not found")
                    return
                database = owner._database
                if database is None:
                    self._send(503, "text/plain; charset=utf-8", "Service unavailable")
                    return
                card = database.get_web_card(view_code)
                if card is None:
                    self._send(404, "text/plain; charset=utf-8", "Not found")
                    return
                html_page = owner._card_page(
                    *card,
                )
                self._send(200, "text/html; charset=utf-8", html_page)

            def _serve_status_page(self, status: str, code: int) -> None:
                messages = {
                    "used": "This stamp link was already used",
                    "expired": "This stamp link has expired",
                    "not_qualified": "This appointment does not qualify for a stamp.",
                    "invalid": "This stamp link is invalid",
                    "failure": (
                        "Stamp could not be recorded. No stamp was added. "
                        "Please retry scanning this QR."
                    ),
                }
                message = messages.get(status, messages["invalid"])
                page = (
                    "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                    "<title>Loyalty card</title><body><main><h1>"
                    + html.escape(message)
                    + "</h1><p>Please ask the salon for help.</p></main></body></html>"
                )
                self._send(code, "text/html; charset=utf-8", page)

            def _send(
                self, status: int, content_type: str, body: str
            ) -> None:
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

        return LoyaltyRequestHandler

    def _allow_request(self, ip_address: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        with self._rate_lock:
            requests = self._requests_by_ip.setdefault(ip_address, deque())
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= 30:
                return False
            requests.append(now)
            return True

    def _card_page(
        self,
        full_name: str,
        card_number: int,
        stamps: int,
        stamps_required: int,
        completed_cards: int,
        prize_draws: list[dict[str, object]] | None = None,
    ) -> str:
        first_name = html.escape(
            full_name.split(maxsplit=1)[0] if full_name else "Customer"
        )
        safe_salon_name = html.escape(self._salon_name)
        safe_logo_data = html.escape(self._logo_data_uri(), quote=True)
        filled = min(max(stamps, 0), stamps_required)
        circles: list[str] = []
        gift_icon = (
            '<svg class="gift" viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M3 10h18v3H3zM5 13h14v8H5zM4 7h16v3H4z" '
            'fill="currentColor"/><path d="M12 7v14M12 7H8.5a2.5 2.5 0 1 1 '
            '2.5-2.5V7Zm0 0h3.5a2.5 2.5 0 1 0-2.5-2.5V7Z" '
            'fill="none" stroke="currentColor" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'
        )
        for index in range(stamps_required):
            earned = index < filled
            reward_stamp = index + 1 in (5, 10)
            content = gift_icon if reward_stamp else ("✓" if earned else "")
            classes = "stamp earned" if earned else "stamp"
            if reward_stamp:
                classes += " gift-stamp"
            circles.append(
                f'<span class="{classes}" aria-label="'
                f'{"Earned" if earned else "Not yet earned"} stamp'
                f'{" and prize draw" if reward_stamp else ""}">{content}</span>'
            )
        reward_lines: list[str] = []
        for draw in prize_draws or []:
            if draw["status"] == "Pending":
                reward_lines.append(
                    '<p class="prize">You earned a prize draw!</p>'
                )
            elif draw["status"] in {"Drawn", "Given"} and draw["prize_name"]:
                reward_lines.append(
                    f'<p class="prize">You won: '
                    f'{html.escape(str(draw["prize_name"]))}!</p>'
                )
        reward_message = "".join(reward_lines)
        safe_count = html.escape(f"{filled} of {stamps_required} stamps")
        safe_card_number = html.escape(str(card_number))
        safe_completed_cards = html.escape(str(completed_cards))
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>{safe_salon_name} - Loyalty Card</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 16px; background: #fff7f8; color: #49343d; font-family: Arial, sans-serif; }}
main {{ width: 100%; max-width: 390px; margin: 0 auto; padding: 20px 16px; background: #fff; border-radius: 20px; box-shadow: 0 8px 30px #6c40521a; text-align: center; }}
img {{ width: 76px; height: 76px; object-fit: cover; border-radius: 50%; }}
h1 {{ margin: 10px 0 3px; font-size: 1.75rem; line-height: 1.15; font-weight: 700; }}
.grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px 6px; margin: 18px auto 12px; max-width: 330px; }}
.stamp {{ display: flex; align-items: center; justify-content: center; width: 46px; height: 46px; border: 3px dotted #d8c5cf; border-radius: 50%; margin: auto; color: #fff; font-size: 1.5rem; font-weight: 700; }}
.stamp.earned {{ background: #c8799d; border: 3px solid #c8799d; }}
.stamp.gift-stamp {{ color: #c9c9c9; }}
.stamp.gift-stamp.earned {{ color: #ffe28a; }}
.gift {{ width: 25px; height: 25px; }}
.count {{ margin: 8px 0; font-size: 1.25rem; font-weight: 700; }}
.prize {{ margin: 8px 0; color: #24754b; font-weight: 700; }}
.name, .card-number, .completed {{ margin: 12px 0 0; }}
.completed {{ color: #74636b; font-size: .85rem; }}
</style>
</head>
<body><main>
<img src="{safe_logo_data}" alt="{safe_salon_name} logo">
<h1>LOYALTY CARD</h1>
<p class="card-number">Card {safe_card_number}</p>
<div class="grid" aria-label="{stamps_required} loyalty stamps">{''.join(circles)}</div>
<p class="count">{safe_count}</p>
{reward_message}
<p class="name">{first_name}</p>
<p class="completed">Completed cards: {safe_completed_cards}</p>
</main></body></html>"""
        return page

    def _logo_data_uri(self) -> str:
        if self._logo_path is None:
            content = _FALLBACK_LOGO
            media_type = "image/svg+xml"
        else:
            try:
                content = self._logo_path.read_bytes()
            except OSError:
                content = _FALLBACK_LOGO
            media_type = mimetypes.guess_type(self._logo_path.name)[0] or "image/png"
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    @staticmethod
    def _validate_port(port: int) -> int:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Server port must be between 1 and 65535")
        return port
