import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from models import (
    Appointment,
    AppointmentStatus,
    Customer,
    GalleryItem,
    LoyaltyCard,
    LoyaltySettings,
    PriceExtra,
    QueueEntry,
    QueueEntryType,
    QueueStatus,
    Service,
    StudioSettings,
    VisitType,
)


class StampNotQualifiedError(ValueError):
    def __init__(self, total_price: float, minimum_spend: float) -> None:
        self.total_price = total_price
        self.minimum_spend = minimum_spend
        super().__init__(
            f"This appointment totals P{total_price:g}, below the minimum spend "
            f"of P{minimum_spend:g}, so no stamp is earned."
        )


class Database:
    """SQLite persistence boundary. All SQL statements are kept in this class."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        check_same_thread: bool = True,
    ) -> None:
        default_path = Path(__file__).resolve().parent.parent / "data" / "pearls_signature.sqlite"
        self._database_path = Path(database_path) if database_path is not None else default_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self._database_path, check_same_thread=check_same_thread
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize_schema(self) -> None:
        price_extras_table_exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'price_extras'"
        ).fetchone() is not None
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT NOT NULL,
                phone TEXT,
                notes TEXT,
                deposit_paid INTEGER NOT NULL DEFAULT 0,
                address TEXT NOT NULL DEFAULT '',
                nail_condition TEXT NOT NULL DEFAULT '',
                health_notes TEXT NOT NULL DEFAULT '',
                deposit_paid_on TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS services (
                service_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                base_price REAL NOT NULL CHECK (base_price >= 0),
                length_prices TEXT NOT NULL,
                design_add_on_prices TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 120 CHECK (
                    duration_minutes >= 5 AND duration_minutes <= 240
                    AND duration_minutes % 5 = 0
                )
            );
            CREATE TABLE IF NOT EXISTS price_extras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category TEXT NOT NULL DEFAULT 'design',
                price REAL NOT NULL CHECK (price >= 0),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS appointments (
                appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_email TEXT NOT NULL COLLATE NOCASE,
                service_id INTEGER NOT NULL,
                appointment_time TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('PENDING', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')
                ),
                notes TEXT,
                nail_length TEXT NOT NULL DEFAULT '',
                design_add_ons TEXT NOT NULL DEFAULT '[]',
                selected_extras TEXT NOT NULL DEFAULT '{}',
                total_price REAL NOT NULL DEFAULT 0 CHECK (total_price >= 0),
                duration_minutes INTEGER NOT NULL DEFAULT 120 CHECK (
                    duration_minutes >= 5 AND duration_minutes <= 240
                    AND duration_minutes % 5 = 0
                ),
                cancellation_fee REAL NOT NULL DEFAULT 0 CHECK (cancellation_fee >= 0),
                allergies TEXT NOT NULL DEFAULT '',
                travel_fee REAL NOT NULL DEFAULT 0 CHECK (travel_fee >= 0),
                discount REAL NOT NULL DEFAULT 0 CHECK (discount >= 0),
                amount_paid REAL NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
                payment_note TEXT NOT NULL DEFAULT '',
                visit_type TEXT NOT NULL DEFAULT 'STUDIO' CHECK (
                    visit_type IN ('STUDIO', 'HOME_SERVICE')
                ),
                service_address TEXT NOT NULL DEFAULT '',
                booking_email_sent_at TEXT,
                reminder_sent_at TEXT,
                thank_you_sent_at TEXT,
                calendar_sequence INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (client_email) REFERENCES clients(email),
                FOREIGN KEY (service_id) REFERENCES services(service_id)
            );
            CREATE TABLE IF NOT EXISTS loyalty_cards (
                client_email TEXT PRIMARY KEY COLLATE NOCASE,
                stamps INTEGER NOT NULL DEFAULT 0 CHECK (stamps >= 0),
                qr_code_path TEXT,
                card_code TEXT,
                view_code TEXT,
                FOREIGN KEY (client_email) REFERENCES clients(email)
            );
            CREATE TABLE IF NOT EXISTS loyalty_monthly_stamps (
                appointment_id INTEGER PRIMARY KEY,
                client_email TEXT NOT NULL COLLATE NOCASE,
                card_month TEXT NOT NULL,
                stamped_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
            );
            CREATE INDEX IF NOT EXISTS idx_loyalty_monthly_stamps_client_month
                ON loyalty_monthly_stamps(client_email, card_month, active);
            CREATE TABLE IF NOT EXISTS loyalty_prizes (
                prize_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                milestone TEXT NOT NULL CHECK (milestone IN ('5', '10', 'both')),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS loyalty_prize_draws (
                draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_email TEXT NOT NULL COLLATE NOCASE,
                card_month TEXT NOT NULL,
                milestone INTEGER NOT NULL CHECK (milestone IN (5, 10)),
                status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending', 'Drawn', 'Given')),
                prize_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                drawn_at TEXT,
                given_at TEXT,
                UNIQUE (client_email, card_month, milestone)
            );
            CREATE TABLE IF NOT EXISTS stamp_tokens (
                token TEXT PRIMARY KEY UNIQUE,
                appointment_id INTEGER NOT NULL,
                card_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            );
            CREATE TABLE IF NOT EXISTS stamp_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                card_code TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('STAMP', 'REVERSAL')),
                reason TEXT NOT NULL DEFAULT '',
                admin_role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                allow_restamp INTEGER NOT NULL DEFAULT 0
                    CHECK (allow_restamp IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS loyalty_reward_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_code TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                admin_role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS loyalty_web_settings (
                setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
                port INTEGER NOT NULL DEFAULT 8765
                    CHECK (port BETWEEN 1 AND 65535)
            );
            CREATE TABLE IF NOT EXISTS loyalty_settings (
                setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
                stamps_required INTEGER NOT NULL CHECK (stamps_required > 0)
            );
            CREATE TABLE IF NOT EXISTS studio_settings (
                setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
                default_travel_fee REAL NOT NULL DEFAULT 0 CHECK (
                    default_travel_fee >= 0
                ),
                travel_buffer_minutes INTEGER NOT NULL DEFAULT 30 CHECK (
                    travel_buffer_minutes >= 0
                    AND travel_buffer_minutes % 5 = 0
                ),
                service_area_note TEXT NOT NULL DEFAULT
                    'Home service is available around the Pila area. A travel fee applies.',
                allowed_areas TEXT NOT NULL DEFAULT '["Pila"]',
                cleaning_buffer_minutes INTEGER NOT NULL DEFAULT 0
                    CHECK (cleaning_buffer_minutes >= 0 AND cleaning_buffer_minutes % 5 = 0),
                studio_address TEXT NOT NULL DEFAULT '',
                maps_embed_url TEXT NOT NULL DEFAULT '',
                map_latitude TEXT NOT NULL DEFAULT '',
                map_longitude TEXT NOT NULL DEFAULT '',
                map_image_path TEXT NOT NULL DEFAULT '',
                loyalty_facebook TEXT NOT NULL DEFAULT '@pearl''s signailture',
                loyalty_phone TEXT NOT NULL DEFAULT '09690811806',
                loyalty_valid_until TEXT NOT NULL DEFAULT '',
                owner_provider_name TEXT NOT NULL DEFAULT
                    'Nicole Pearl Millari Teodoro',
                review_url TEXT NOT NULL DEFAULT '',
                online_booking_url TEXT NOT NULL DEFAULT '',
                minimum_spend_per_appointment REAL NOT NULL DEFAULT 500
                    CHECK (minimum_spend_per_appointment >= 0),
                map_link_url TEXT NOT NULL DEFAULT '',
                loyalty_terms TEXT NOT NULL DEFAULT
                    'This loyalty card is non-transferable.
Earn sticker for every minimum spend of P500 per visit.
Earn 1 prize draw for every 5 stickers collected!
Card must be presented upon purchase to receive sticker.
Loyalty cards are valid only until expiry date'
            );
            CREATE TABLE IF NOT EXISTS weekly_hours (
                weekday INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
                is_open INTEGER NOT NULL DEFAULT 1,
                open_time TEXT NOT NULL DEFAULT '08:00',
                close_time TEXT NOT NULL DEFAULT '18:00'
            );
            CREATE TABLE IF NOT EXISTS schedule_breaks (
                break_id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedule_closures (
                closure_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS loyalty_stamp_log (
                appointment_id INTEGER PRIMARY KEY,
                client_email TEXT NOT NULL COLLATE NOCASE,
                awarded_at TEXT NOT NULL,
                FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id),
                FOREIGN KEY (client_email) REFERENCES clients(email)
            );
            CREATE TABLE IF NOT EXISTS gallery_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                photo_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                client_email TEXT COLLATE NOCASE,
                appointment_id INTEGER UNIQUE,
                entry_type TEXT NOT NULL CHECK (entry_type IN ('BOOKED', 'WALK_IN')),
                status TEXT NOT NULL CHECK (
                    status IN ('WAITING', 'SERVING', 'DONE', 'CANCELLED')
                ),
                created_at TEXT NOT NULL,
                ticket_number TEXT NOT NULL,
                ticket_date TEXT NOT NULL,
                queue_date TEXT NOT NULL DEFAULT '',
                sort_time TEXT NOT NULL DEFAULT '',
                skip_count INTEGER NOT NULL DEFAULT 0,
                skip_after_entry_id INTEGER,
                UNIQUE (ticket_date, ticket_number),
                FOREIGN KEY (client_email) REFERENCES clients(email),
                FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
            );
            """
        )
        if not price_extras_table_exists:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO price_extras (name, category, price, active)
                    VALUES (?, 'design', ?, 1)
                    """,
                    [
                        ("Simple", 180),
                        ("Minimalist", 300),
                        ("Intricate", 300),
                        ("Chrome", 230),
                        ("Cat-eye", 280),
                        ("Hand-painted", 350),
                    ],
                )
        for weekday in range(7):
            self._connection.execute(
                """
                INSERT OR IGNORE INTO weekly_hours
                    (weekday, is_open, open_time, close_time)
                VALUES (?, 1, '08:00', '18:00')
                """,
                (weekday,),
            )
        self._migrate_policy_columns()
        self._migrate_queue_columns()
        self._migrate_loyalty_card_codes()
        self._migrate_loyalty_view_codes()
        self._migrate_loyalty_transaction_audit()
        self._migrate_loyalty_monthly_stamps()
        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO loyalty_settings (setting_id, stamps_required)
                VALUES (1, 10)
                """
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO loyalty_web_settings (setting_id, port)
                VALUES (1, 8765)
                """
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO studio_settings
                    (setting_id, default_travel_fee, travel_buffer_minutes,
                     service_area_note, allowed_areas)
                    VALUES (1, 0, 30, ?, '["Pila"]')
                """,
                (
                    "Home service is available around the Pila area. A travel fee applies.",
                ),
            )
            service_count = self._connection.execute(
                "SELECT COUNT(*) FROM services"
            ).fetchone()[0]
            if service_count == 0:
                self._connection.executemany(
                    """
                    INSERT INTO services
                        (name, description, base_price, length_prices,
                         design_add_on_prices, duration_minutes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "Hardgel Extension",
                            "",
                            550,
                            '{"Short": 50, "Medium": 100, "Long": 150, "Extra Long": 200}',
                            "{}",
                            120,
                        ),
                        (
                            "BIAB - Structured Plain Nails",
                            "",
                            380,
                            '{"Short": 50, "Medium": 100, "Long": 150, "Extra Long": 200}',
                            "{}",
                            90,
                        ),
                        (
                            "Softgel Extension",
                            "",
                            450,
                            '{"Short": 50, "Medium": 100, "Long": 150, "Extra Long": 200}',
                            "{}",
                            120,
                        ),
                        (
                            "Smart Pedicure",
                            "",
                            350,
                            "{}",
                            "{}",
                            120,
                        ),
                        (
                            "Smart Pedicure + Nail Reconstruction",
                            "",
                            470,
                            "{}",
                            "{}",
                            140,
                        ),
                    ],
                )

    def close(self) -> None:
        self._connection.close()

    def _migrate_policy_columns(self) -> None:
        migrations = {
            "loyalty_cards": {
                "card_code": "TEXT",
                "view_code": "TEXT",
            },
            "clients": {
                "deposit_paid": "INTEGER NOT NULL DEFAULT 0",
                "address": "TEXT NOT NULL DEFAULT ''",
                "nail_condition": "TEXT NOT NULL DEFAULT ''",
                "health_notes": "TEXT NOT NULL DEFAULT ''",
                "deposit_paid_on": "TEXT NOT NULL DEFAULT ''",
            },
            "services": {
                "duration_minutes": "INTEGER NOT NULL DEFAULT 120",
            },
            "appointments": {
                "duration_minutes": "INTEGER NOT NULL DEFAULT 120",
                "cancellation_fee": "REAL NOT NULL DEFAULT 0",
                "allergies": "TEXT NOT NULL DEFAULT ''",
                "travel_fee": "REAL NOT NULL DEFAULT 0",
                "discount": "REAL NOT NULL DEFAULT 0",
                "amount_paid": "REAL NOT NULL DEFAULT 0",
                "payment_note": "TEXT NOT NULL DEFAULT ''",
                "visit_type": "TEXT NOT NULL DEFAULT 'STUDIO'",
                "service_address": "TEXT NOT NULL DEFAULT ''",
                "selected_extras": "TEXT NOT NULL DEFAULT '{}'",
                "booking_email_sent_at": "TEXT",
                "reminder_sent_at": "TEXT",
                "thank_you_sent_at": "TEXT",
                "calendar_sequence": "INTEGER NOT NULL DEFAULT 0",
            },
            "studio_settings": {
                "allowed_areas": "TEXT NOT NULL DEFAULT '[\"Pila\"]'",
                "cleaning_buffer_minutes": "INTEGER NOT NULL DEFAULT 0",
                "studio_address": "TEXT NOT NULL DEFAULT ''",
                "maps_embed_url": "TEXT NOT NULL DEFAULT ''",
                "map_latitude": "TEXT NOT NULL DEFAULT ''",
                "map_longitude": "TEXT NOT NULL DEFAULT ''",
                "map_image_path": "TEXT NOT NULL DEFAULT ''",
                "loyalty_facebook": "TEXT NOT NULL DEFAULT '@pearl''s signailture'",
                "loyalty_phone": "TEXT NOT NULL DEFAULT '09690811806'",
                "loyalty_valid_until": "TEXT NOT NULL DEFAULT ''",
                "owner_provider_name": (
                    "TEXT NOT NULL DEFAULT 'Nicole Pearl Millari Teodoro'"
                ),
                "review_url": "TEXT NOT NULL DEFAULT ''",
                "online_booking_url": "TEXT NOT NULL DEFAULT ''",
                "minimum_spend_per_appointment": (
                    "REAL NOT NULL DEFAULT 500 CHECK "
                    "(minimum_spend_per_appointment >= 0)"
                ),
                "map_link_url": "TEXT NOT NULL DEFAULT ''",
                "loyalty_terms": (
                    "TEXT NOT NULL DEFAULT 'This loyalty card is non-transferable.\n"
                    "Earn sticker for every minimum spend of P500 per visit.\n"
                    "Earn 1 prize draw for every 5 stickers collected!\n"
                    "Card must be presented upon purchase to receive sticker.\n"
                    "Loyalty cards are valid only until expiry date'"
                ),
            },
        }
        for table_name, columns in migrations.items():
            existing_columns = {
                row["name"]
                for row in self._connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            newly_added: set[str] = set()
            for column_name, definition in columns.items():
                if column_name not in existing_columns:
                    self._connection.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                    )
                    newly_added.add(column_name)
            if table_name == "appointments" and "duration_minutes" in newly_added:
                if "duration_hours" in existing_columns:
                    self._connection.execute(
                        """
                        UPDATE appointments
                        SET duration_minutes = CAST(ROUND(duration_hours * 60) AS INTEGER)
                        """
                    )
            if (
                table_name == "studio_settings"
                and "owner_provider_name" in newly_added
            ):
                self._connection.execute(
                    """
                    UPDATE studio_settings
                    SET owner_provider_name = 'Nicole Pearl Millari Teodoro'
                    WHERE owner_provider_name = ''
                    """
                )

    def _migrate_queue_columns(self) -> None:
        existing_columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(queue_entries)"
            ).fetchall()
        }
        migrations = {
            "queue_date": "TEXT NOT NULL DEFAULT ''",
            "sort_time": "TEXT NOT NULL DEFAULT ''",
            "skip_count": "INTEGER NOT NULL DEFAULT 0",
            "skip_after_entry_id": "INTEGER",
        }
        with self._connection:
            for column_name, definition in migrations.items():
                if column_name not in existing_columns:
                    self._connection.execute(
                        f"ALTER TABLE queue_entries ADD COLUMN {column_name} {definition}"
                    )
            self._connection.execute(
                """
                UPDATE queue_entries
                SET queue_date = CASE
                        WHEN entry_type = 'BOOKED' AND EXISTS (
                            SELECT 1 FROM appointments
                            WHERE appointments.appointment_id = queue_entries.appointment_id
                        ) THEN (
                            SELECT date(appointment_time) FROM appointments
                            WHERE appointments.appointment_id = queue_entries.appointment_id
                        )
                        ELSE ticket_date
                    END
                WHERE queue_date = ''
                """
            )
            self._connection.execute(
                """
                UPDATE queue_entries
                SET sort_time = CASE
                        WHEN entry_type = 'BOOKED' AND EXISTS (
                            SELECT 1 FROM appointments
                            WHERE appointments.appointment_id = queue_entries.appointment_id
                        ) THEN (
                            SELECT appointment_time FROM appointments
                            WHERE appointments.appointment_id = queue_entries.appointment_id
                        )
                        ELSE created_at
                    END
                WHERE sort_time = ''
                """
            )

    def _migrate_loyalty_card_codes(self) -> None:
        rows = self._connection.execute(
            "SELECT client_email FROM loyalty_cards WHERE card_code IS NULL OR card_code = ''"
        ).fetchall()
        with self._connection:
            for row in rows:
                self._connection.execute(
                    "UPDATE loyalty_cards SET card_code = ? WHERE client_email = ?",
                    (self._new_loyalty_card_code(), row["client_email"]),
                )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_loyalty_cards_card_code
                ON loyalty_cards(card_code)
                """
            )

    def _migrate_loyalty_view_codes(self) -> None:
        rows = self._connection.execute(
            "SELECT client_email FROM loyalty_cards WHERE view_code IS NULL OR view_code = ''"
        ).fetchall()
        with self._connection:
            for row in rows:
                self._connection.execute(
                    "UPDATE loyalty_cards SET view_code = ? WHERE client_email = ?",
                    (self._new_loyalty_view_code(), row["client_email"]),
                )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_loyalty_cards_view_code
                ON loyalty_cards(view_code)
                """
            )

    def _migrate_loyalty_transaction_audit(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(stamp_transactions)"
            ).fetchall()
        }
        if "allow_restamp" not in columns:
            self._connection.execute(
                """
                ALTER TABLE stamp_transactions
                ADD COLUMN allow_restamp INTEGER NOT NULL DEFAULT 0
                    CHECK (allow_restamp IN (0, 1))
                """
            )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO stamp_transactions
                    (appointment_id, card_code, type, reason, admin_role, created_at)
                SELECT stamp.appointment_id, card.card_code, 'STAMP',
                       'Existing stamp', 'Legacy', stamp.awarded_at
                FROM loyalty_stamp_log AS stamp
                JOIN loyalty_cards AS card
                  ON card.client_email = stamp.client_email
                WHERE card.card_code IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM stamp_transactions AS audit
                      WHERE audit.appointment_id = stamp.appointment_id
                        AND audit.type = 'STAMP'
                  )
                """
            )

    def _migrate_loyalty_monthly_stamps(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO loyalty_monthly_stamps
                    (appointment_id, client_email, card_month, stamped_at, active)
                SELECT stamp.appointment_id, stamp.client_email,
                       substr(appointment.appointment_time, 1, 7),
                       stamp.awarded_at,
                       CASE WHEN (
                           SELECT tx.type
                           FROM stamp_transactions AS tx
                           WHERE tx.appointment_id = stamp.appointment_id
                           ORDER BY tx.id DESC LIMIT 1
                       ) = 'REVERSAL' THEN 0 ELSE 1 END
                FROM loyalty_stamp_log AS stamp
                JOIN appointments AS appointment
                  ON appointment.appointment_id = stamp.appointment_id
                WHERE length(appointment.appointment_time) >= 7
                  AND substr(appointment.appointment_time, 1, 7)
                      GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
                """
            )

    def _new_loyalty_card_code(self) -> str:
        while True:
            code = secrets.token_urlsafe(8)
            exists = self._connection.execute(
                "SELECT 1 FROM loyalty_cards WHERE card_code = ?", (code,)
            ).fetchone()
            if exists is None:
                return code
        self._connection.commit()

    def _new_loyalty_view_code(self) -> str:
        while True:
            code = secrets.token_urlsafe(16)
            exists = self._connection.execute(
                "SELECT 1 FROM loyalty_cards WHERE view_code = ?", (code,)
            ).fetchone()
            if exists is None:
                return code

    def add_client(self, client: Customer) -> Customer:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO clients
                    (email, name, phone, notes, deposit_paid, address,
                     nail_condition, health_notes, deposit_paid_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client.email,
                    client.name,
                    client.phone,
                    client.notes,
                    int(client.deposit_paid),
                    client.address,
                    client.nail_condition,
                    client.health_notes,
                    client.deposit_paid_on.isoformat() if client.deposit_paid_on else "",
                ),
            )
        return client

    def get_client(self, email: str) -> Customer | None:
        row = self._connection.execute(
            """
            SELECT email, name, phone, notes, deposit_paid, address,
                   nail_condition, health_notes, deposit_paid_on
            FROM clients WHERE email = ?
            """,
            (email.strip().lower(),),
        ).fetchone()
        return self._client_from_row(row) if row else None

    def get_clients(self) -> list[Customer]:
        rows = self._connection.execute(
            """
            SELECT email, name, phone, notes, deposit_paid, address,
                   nail_condition, health_notes, deposit_paid_on
            FROM clients ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        return [self._client_from_row(row) for row in rows]

    def update_client(self, client: Customer) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE clients
                SET name = ?, phone = ?, notes = ?, deposit_paid = ?,
                    address = ?, nail_condition = ?, health_notes = ?,
                    deposit_paid_on = ?
                WHERE email = ?
                """,
                (
                    client.name,
                    client.phone,
                    client.notes,
                    int(client.deposit_paid),
                    client.address,
                    client.nail_condition,
                    client.health_notes,
                    client.deposit_paid_on.isoformat() if client.deposit_paid_on else "",
                    client.email,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No client found for {client.email}")

    def mark_client_deposit_paid(self, email: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE clients SET deposit_paid = 1, deposit_paid_on = ? WHERE email = ?",
                (date.today().isoformat(), email.strip().lower()),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No client found for {email}")

    def delete_client(self, email: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM clients WHERE email = ?", (email.strip().lower(),)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No client found for {email}")

    def add_service(self, service: Service) -> Service:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO services
                    (name, description, base_price, length_prices,
                     design_add_on_prices, duration_minutes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    service.name,
                    service.description,
                    service.base_price,
                    json.dumps(service.length_prices),
                    json.dumps(service.design_add_on_prices),
                    service.duration_minutes,
                ),
            )
        return self.get_service(cursor.lastrowid)

    def get_service(self, service_id: int) -> Service | None:
        row = self._connection.execute(
            "SELECT * FROM services WHERE service_id = ?", (service_id,)
        ).fetchone()
        return self._service_from_row(row) if row else None

    def get_services(self) -> list[Service]:
        rows = self._connection.execute(
            "SELECT * FROM services ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [self._service_from_row(row) for row in rows]

    def update_service(self, service: Service) -> None:
        if service.service_id is None:
            raise ValueError("service.service_id is required to update a service")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE services
                SET name = ?, description = ?, base_price = ?, length_prices = ?,
                    design_add_on_prices = ?, duration_minutes = ?
                WHERE service_id = ?
                """,
                (
                    service.name,
                    service.description,
                    service.base_price,
                    json.dumps(service.length_prices),
                    json.dumps(service.design_add_on_prices),
                    service.duration_minutes,
                    service.service_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No service found with ID {service.service_id}")

    def delete_service(self, service_id: int) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM services WHERE service_id = ?", (service_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No service found with ID {service_id}")

    def add_price_extra(self, extra: PriceExtra) -> PriceExtra:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO price_extras (name, category, price, active)
                VALUES (?, ?, ?, ?)
                """,
                (extra.name, extra.category, extra.price, int(extra.active)),
            )
        return self.get_price_extra(cursor.lastrowid)

    def get_price_extra(self, extra_id: int) -> PriceExtra:
        row = self._connection.execute(
            "SELECT * FROM price_extras WHERE id = ?", (extra_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"No extra found with ID {extra_id}")
        return self._price_extra_from_row(row)

    def get_price_extras(self, active_only: bool = False) -> list[PriceExtra]:
        query = "SELECT * FROM price_extras"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY name COLLATE NOCASE"
        rows = self._connection.execute(query).fetchall()
        return [self._price_extra_from_row(row) for row in rows]

    def update_price_extra(self, extra: PriceExtra) -> None:
        if extra.extra_id is None:
            raise ValueError("extra.extra_id is required to update an extra")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE price_extras
                SET name = ?, category = ?, price = ?, active = ?
                WHERE id = ?
                """,
                (
                    extra.name,
                    extra.category,
                    extra.price,
                    int(extra.active),
                    extra.extra_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No extra found with ID {extra.extra_id}")

    def delete_price_extra(self, extra_id: int) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM price_extras WHERE id = ?", (extra_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No extra found with ID {extra_id}")

    def add_appointment(self, appointment: Appointment) -> Appointment:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO appointments
                    (client_email, service_id, appointment_time, status, notes, nail_length,
                     design_add_ons, selected_extras, total_price, duration_minutes,
                     cancellation_fee, allergies,
                     travel_fee, discount, amount_paid, payment_note, visit_type,
                     service_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    appointment.client_email,
                    appointment.service_id,
                    self._serialize_time(appointment.appointment_time),
                    appointment.status.value,
                    appointment.notes,
                    appointment.nail_length,
                    json.dumps(appointment.design_add_ons),
                    json.dumps(appointment.selected_extras),
                    appointment.total_price,
                    appointment.duration_minutes,
                    appointment.cancellation_fee,
                    appointment.allergies,
                    appointment.travel_fee,
                    appointment.discount,
                    appointment.amount_paid,
                    appointment.payment_note,
                    appointment.visit_type.value,
                    appointment.service_address,
                ),
            )
        return self.get_appointment(cursor.lastrowid)

    def get_appointment(self, appointment_id: int) -> Appointment | None:
        row = self._connection.execute(
            "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
        return self._appointment_from_row(row) if row else None

    def get_appointments(self) -> list[Appointment]:
        rows = self._connection.execute(
            "SELECT * FROM appointments ORDER BY appointment_time, appointment_id"
        ).fetchall()
        return [self._appointment_from_row(row) for row in rows]

    def get_due_appointment_reminders(
        self, appointment_date: date
    ) -> list[dict[str, str | int]]:
        rows = self._connection.execute(
            """
            SELECT a.appointment_id, a.client_email, c.name AS client_name,
                   s.name AS service_name, a.appointment_time,
                   a.duration_minutes, a.calendar_sequence
            FROM appointments AS a
            JOIN clients AS c ON c.email = a.client_email
            JOIN services AS s ON s.service_id = a.service_id
            WHERE date(a.appointment_time) = ?
              AND a.status IN ('PENDING', 'CONFIRMED')
              AND a.reminder_sent_at IS NULL
              AND TRIM(c.email) <> ''
            ORDER BY a.appointment_time, a.appointment_id
            """,
            (appointment_date.isoformat(),),
        ).fetchall()
        return [
            {
                "appointment_id": int(row["appointment_id"]),
                "client_email": str(row["client_email"]),
                "client_name": str(row["client_name"]),
                "service_name": str(row["service_name"]),
                "appointment_time": str(row["appointment_time"]),
                "duration_minutes": int(row["duration_minutes"]),
                "calendar_sequence": int(row["calendar_sequence"]),
            }
            for row in rows
        ]

    def get_appointment_email_sent_at(
        self, appointment_id: int, email_type: str
    ) -> str | None:
        column = self._appointment_email_column(email_type)
        row = self._connection.execute(
            f"SELECT {column} FROM appointments WHERE appointment_id = ?",
            (appointment_id,),
        ).fetchone()
        return str(row[column]) if row is not None and row[column] else None

    def mark_appointment_email_sent(
        self, appointment_id: int, email_type: str, sent_at: datetime
    ) -> bool:
        column = self._appointment_email_column(email_type)
        with self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE appointments
                SET {column} = ?
                WHERE appointment_id = ? AND {column} IS NULL
                """,
                (sent_at.isoformat(), appointment_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _appointment_email_column(email_type: str) -> str:
        columns = {
            "booking": "booking_email_sent_at",
            "reminder": "reminder_sent_at",
            "thank_you": "thank_you_sent_at",
        }
        try:
            return columns[email_type]
        except KeyError as error:
            raise ValueError(f"Unknown appointment email type: {email_type}") from error

    def get_report_appointments(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT a.appointment_id, a.appointment_time, a.status, a.visit_type,
                   a.total_price, a.travel_fee, a.discount, a.amount_paid,
                   a.cancellation_fee, c.name AS client_name,
                   c.email AS client_email, s.name AS service_name
            FROM appointments AS a
            JOIN clients AS c ON c.email = a.client_email
            JOIN services AS s ON s.service_id = a.service_id
            WHERE date(a.appointment_time) BETWEEN ? AND ?
            ORDER BY a.appointment_time, a.appointment_id
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pending_payment_rows(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT a.appointment_id, a.appointment_time, a.total_price,
                   a.travel_fee, a.discount, a.amount_paid,
                   a.total_price + a.travel_fee - a.discount AS final_price,
                   a.total_price + a.travel_fee - a.discount - a.amount_paid AS balance,
                   c.name AS client_name, c.email AS client_email,
                   s.name AS service_name
            FROM appointments AS a
            JOIN clients AS c ON c.email = a.client_email
            JOIN services AS s ON s.service_id = a.service_id
            WHERE a.status = 'COMPLETED'
              AND a.total_price + a.travel_fee - a.discount - a.amount_paid > 0
            ORDER BY a.appointment_time, a.appointment_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pending_request_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS request_count FROM appointments WHERE status = 'PENDING'"
        ).fetchone()
        return int(row["request_count"])

    def get_report_status_counts(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT status, COUNT(*) AS appointment_count,
                   SUM(cancellation_fee) AS cancellation_fees
            FROM appointments
            WHERE date(appointment_time) BETWEEN ? AND ?
            GROUP BY status
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_report_revenue(self, start_date: date, end_date: date) -> float:
        row = self._connection.execute(
            """
            SELECT COALESCE(SUM(amount_paid), 0) AS revenue
            FROM appointments
            WHERE date(appointment_time) BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
        return float(row["revenue"])

    def get_report_by_service(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT s.service_id, s.name AS service_name,
                   COUNT(a.appointment_id) AS appointment_count,
                   COALESCE(SUM(a.amount_paid), 0) AS revenue
            FROM services AS s
            LEFT JOIN appointments AS a
              ON a.service_id = s.service_id
             AND date(a.appointment_time) BETWEEN ? AND ?
            GROUP BY s.service_id, s.name
            ORDER BY s.name COLLATE NOCASE
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_report_by_visit_type(
        self, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT visit_type, COUNT(*) AS appointment_count,
                   COALESCE(SUM(amount_paid), 0) AS revenue,
                   COALESCE(SUM(travel_fee), 0) AS travel_fees
            FROM appointments
            WHERE date(appointment_time) BETWEEN ? AND ?
            GROUP BY visit_type
            ORDER BY visit_type
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_booking_history(self, client_email: str) -> list[Appointment]:
        rows = self._connection.execute(
            """
            SELECT * FROM appointments
            WHERE client_email = ?
            ORDER BY appointment_time DESC, appointment_id DESC
            """,
            (client_email.strip().lower(),),
        ).fetchall()
        return [self._appointment_from_row(row) for row in rows]

    def update_appointment(
        self,
        appointment: Appointment,
        increment_calendar_sequence: bool = False,
    ) -> None:
        if appointment.appointment_id is None:
            raise ValueError("appointment.appointment_id is required to update an appointment")
        serialized_time = self._serialize_time(appointment.appointment_time)
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE appointments
                SET client_email = ?, service_id = ?, appointment_time = ?, status = ?, notes = ?,
                    nail_length = ?, design_add_ons = ?, total_price = ?,
                    selected_extras = ?,
                    duration_minutes = ?, cancellation_fee = ?, allergies = ?,
                    travel_fee = ?, discount = ?, amount_paid = ?, payment_note = ?
                    , visit_type = ?, service_address = ?,
                    reminder_sent_at = CASE
                        WHEN appointment_time != ? THEN NULL
                        ELSE reminder_sent_at
                    END,
                    calendar_sequence = calendar_sequence + ?
                WHERE appointment_id = ?
                """,
                (
                    appointment.client_email,
                    appointment.service_id,
                    serialized_time,
                    appointment.status.value,
                    appointment.notes,
                    appointment.nail_length,
                    json.dumps(appointment.design_add_ons),
                    appointment.total_price,
                    json.dumps(appointment.selected_extras),
                    appointment.duration_minutes,
                    appointment.cancellation_fee,
                    appointment.allergies,
                    appointment.travel_fee,
                    appointment.discount,
                    appointment.amount_paid,
                    appointment.payment_note,
                    appointment.visit_type.value,
                    appointment.service_address,
                    serialized_time,
                    int(increment_calendar_sequence),
                    appointment.appointment_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No appointment found with ID {appointment.appointment_id}")

    def delete_appointment(self, appointment_id: int) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM appointments WHERE appointment_id = ?", (appointment_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No appointment found with ID {appointment_id}")

    def get_or_create_loyalty_card(self, email: str) -> LoyaltyCard:
        normalized_email = email.strip().lower()
        row = self._connection.execute(
            "SELECT * FROM loyalty_cards WHERE client_email = ?", (normalized_email,)
        ).fetchone()
        if row:
            return self._loyalty_card_from_row(row)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO loyalty_cards
                    (client_email, stamps, qr_code_path, card_code, view_code)
                VALUES (?, 0, NULL, ?, ?)
                """,
                (
                    normalized_email,
                    self._new_loyalty_card_code(),
                    self._new_loyalty_view_code(),
                ),
            )
        card = self.get_loyalty_card(normalized_email)
        if card is None:
            raise RuntimeError("Loyalty card creation did not persist")
        return card

    def get_loyalty_card(self, email: str) -> LoyaltyCard | None:
        row = self._connection.execute(
            "SELECT * FROM loyalty_cards WHERE client_email = ?",
            (email.strip().lower(),),
        ).fetchone()
        return self._loyalty_card_from_row(row) if row else None

    def get_loyalty_cards(self) -> list[LoyaltyCard]:
        rows = self._connection.execute(
            "SELECT * FROM loyalty_cards ORDER BY client_email COLLATE NOCASE"
        ).fetchall()
        return [self._loyalty_card_from_row(row) for row in rows]

    def get_loyalty_card_by_code(self, card_code: str) -> LoyaltyCard | None:
        row = self._connection.execute(
            "SELECT * FROM loyalty_cards WHERE card_code = ?", (card_code.strip(),)
        ).fetchone()
        return self._loyalty_card_from_row(row) if row else None

    def get_web_card(
        self, view_code: str, today: date | None = None
    ) -> tuple[str, int, list[dict[str, object]], bool] | None:
        row = self._connection.execute(
            """
            SELECT clients.name, loyalty_cards.client_email
            FROM loyalty_cards
            JOIN clients ON clients.email = loyalty_cards.client_email
            WHERE loyalty_cards.view_code = ?
            """,
            (view_code,),
        ).fetchone()
        if row is None:
            return None
        current_month = (today or date.today()).strftime("%Y-%m")
        stamps = self._monthly_stamp_count(row["client_email"], current_month)
        previous_stamps = self._connection.execute(
            """
            SELECT 1 FROM loyalty_monthly_stamps
            WHERE client_email = ? AND card_month < ? LIMIT 1
            """,
            (row["client_email"], current_month),
        ).fetchone()
        expired = stamps == 0 and previous_stamps is not None
        draws = self.get_loyalty_prize_draws(
            client_email=str(row["client_email"]), card_month=current_month
        )
        return (str(row["name"]), stamps, draws, expired)

    def create_stamp_token(self, appointment_id: int) -> str:
        now = datetime.now(timezone.utc)
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            appointment = self._connection.execute(
                """
                SELECT client_email, status, total_price FROM appointments
                WHERE appointment_id = ?
                """,
                (appointment_id,),
            ).fetchone()
            if appointment is None:
                raise KeyError(f"No appointment found with ID {appointment_id}")
            if appointment["status"] != AppointmentStatus.COMPLETED.value:
                raise ValueError(
                    "A stamp link can only be created for a completed appointment"
                )
            self._ensure_appointment_qualifies(float(appointment["total_price"]))
            if self._appointment_is_stamped(appointment_id) or self._monthly_stamp_exists(
                appointment_id
            ):
                raise ValueError("This appointment has already earned a stamp")

            card = self._connection.execute(
                "SELECT card_code FROM loyalty_cards WHERE client_email = ?",
                (appointment["client_email"],),
            ).fetchone()
            if card is None:
                self._connection.execute(
                    """
                    INSERT INTO loyalty_cards
                        (client_email, stamps, qr_code_path, card_code, view_code)
                    VALUES (?, 0, NULL, ?, ?)
                    """,
                    (
                        appointment["client_email"],
                        self._new_loyalty_card_code(),
                        self._new_loyalty_view_code(),
                    ),
                )
                card = self._connection.execute(
                    "SELECT card_code FROM loyalty_cards WHERE client_email = ?",
                    (appointment["client_email"],),
                ).fetchone()
            if card is None or not card["card_code"]:
                raise RuntimeError("Could not create the client's loyalty card")

            token = secrets.token_urlsafe(16)
            self._connection.execute(
                """
                INSERT INTO stamp_tokens
                    (token, appointment_id, card_code, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token,
                    appointment_id,
                    card["card_code"],
                    now.isoformat(),
                    (now + timedelta(minutes=2)).isoformat(),
                ),
            )
        return token

    def redeem_stamp_token(
        self, token: str, now: datetime | None = None
    ) -> tuple[str, str | None]:
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            token_row = self._connection.execute(
                """
                SELECT token, appointment_id, card_code, expires_at, used_at
                FROM stamp_tokens WHERE token = ?
                """,
                (token,),
            ).fetchone()
            if token_row is None:
                return ("invalid", None)
            if token_row["used_at"] is not None:
                return ("used", None)
            try:
                expires_at = datetime.fromisoformat(token_row["expires_at"])
            except ValueError:
                return ("invalid", None)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if current_time >= expires_at.astimezone(timezone.utc):
                return ("expired", None)

            appointment = self._connection.execute(
                """
                SELECT client_email, total_price FROM appointments
                WHERE appointment_id = ? AND status = 'COMPLETED'
                """,
                (token_row["appointment_id"],),
            ).fetchone()
            card = self._connection.execute(
                """
                SELECT client_email, view_code FROM loyalty_cards
                WHERE card_code = ?
                """,
                (token_row["card_code"],),
            ).fetchone()
            if (
                appointment is None
                or card is None
                or appointment["client_email"].casefold()
                != card["client_email"].casefold()
            ):
                return ("invalid", None)
            if self._appointment_is_stamped(token_row["appointment_id"]):
                self._connection.execute(
                    "UPDATE stamp_tokens SET used_at = ? WHERE token = ?",
                    (current_time.isoformat(), token),
                )
                return ("used", None)
            if self._monthly_stamp_exists(token_row["appointment_id"]):
                self._connection.execute(
                    "UPDATE stamp_tokens SET used_at = ? WHERE token = ?",
                    (current_time.isoformat(), token),
                )
                return ("used", None)
            minimum_spend = self.get_minimum_spend_per_appointment()
            if float(appointment["total_price"]) < minimum_spend:
                self._connection.execute(
                    "UPDATE stamp_tokens SET used_at = ? WHERE token = ?",
                    (current_time.isoformat(), token),
                )
                return ("not_qualified", None)
            if not self._record_stamp_in_transaction(
                token_row["appointment_id"],
                token_row["card_code"],
                "Admin",
                "Stamp QR redeemed",
                current_time,
            ):
                return ("used", None)
            self._connection.execute(
                "UPDATE stamp_tokens SET used_at = ? WHERE token = ?",
                (current_time.isoformat(), token),
            )
            return ("success", str(card["view_code"]))

    def get_loyalty_web_port(self) -> int:
        row = self._connection.execute(
            "SELECT port FROM loyalty_web_settings WHERE setting_id = 1"
        ).fetchone()
        return int(row["port"]) if row else 8765

    def set_loyalty_web_port(self, port: int) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Server port must be between 1 and 65535")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO loyalty_web_settings (setting_id, port) VALUES (1, ?)
                ON CONFLICT(setting_id) DO UPDATE SET port = excluded.port
                """,
                (port,),
            )

    def count_unstamped_completed_visits(self, email: str) -> int:
        rows = self._connection.execute(
            """
            SELECT appointment.appointment_id, appointment.total_price
            FROM appointments AS appointment
            WHERE appointment.client_email = ?
              AND appointment.status = 'COMPLETED'
            """,
            (email.strip().lower(),),
        ).fetchall()
        return sum(
            not self._appointment_is_stamped(row["appointment_id"])
            and not self._monthly_stamp_exists(row["appointment_id"])
            for row in rows
        )

    def has_loyalty_stamp_for_appointment(self, appointment_id: int) -> bool:
        return (
            self._appointment_is_stamped(appointment_id)
            or self._monthly_stamp_exists(appointment_id)
        )

    def has_active_loyalty_stamp_for_appointment(self, appointment_id: int) -> bool:
        latest = self._connection.execute(
            """
            SELECT type FROM stamp_transactions
            WHERE appointment_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (appointment_id,),
        ).fetchone()
        if latest is not None:
            return latest["type"] == "STAMP"
        return (
            self._connection.execute(
                "SELECT 1 FROM loyalty_stamp_log WHERE appointment_id = ?",
                (appointment_id,),
            ).fetchone()
            is not None
        )

    def _appointment_is_stamped(self, appointment_id: int) -> bool:
        latest = self._connection.execute(
            """
            SELECT type, allow_restamp FROM stamp_transactions
            WHERE appointment_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (appointment_id,),
        ).fetchone()
        if latest is None:
            return (
                self._connection.execute(
                    "SELECT 1 FROM loyalty_stamp_log WHERE appointment_id = ?",
                    (appointment_id,),
                ).fetchone()
                is not None
            )
        if latest["type"] == "REVERSAL" and bool(latest["allow_restamp"]):
            return False
        return True

    def _monthly_stamp_exists(self, appointment_id: int) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM loyalty_monthly_stamps WHERE appointment_id = ?",
                (appointment_id,),
            ).fetchone()
            is not None
        )

    def _monthly_stamp_count(self, email: str, card_month: str) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS stamp_count FROM loyalty_monthly_stamps
            WHERE client_email = ? AND card_month = ? AND active = 1
            """,
            (email, card_month),
        ).fetchone()
        return int(row["stamp_count"]) if row else 0

    def get_minimum_spend_per_appointment(self) -> float:
        row = self._connection.execute(
            """
            SELECT minimum_spend_per_appointment
            FROM studio_settings WHERE setting_id = 1
            """
        ).fetchone()
        return float(row["minimum_spend_per_appointment"]) if row else 500.0

    def _ensure_appointment_qualifies(self, total_price: float) -> None:
        minimum_spend = self.get_minimum_spend_per_appointment()
        if total_price < minimum_spend:
            raise StampNotQualifiedError(total_price, minimum_spend)

    def _record_stamp_in_transaction(
        self,
        appointment_id: int,
        card_code: str,
        admin_role: str,
        reason: str,
        created_at: datetime,
    ) -> bool:
        appointment = self._connection.execute(
            """
            SELECT client_email FROM appointments
            WHERE appointment_id = ? AND status = 'COMPLETED'
            """,
            (appointment_id,),
        ).fetchone()
        card = self._connection.execute(
            "SELECT client_email FROM loyalty_cards WHERE card_code = ?",
            (card_code,),
        ).fetchone()
        if (
            appointment is None
            or card is None
            or appointment["client_email"].casefold()
            != card["client_email"].casefold()
            or self._appointment_is_stamped(appointment_id)
            or self._monthly_stamp_exists(appointment_id)
        ):
            return False
        appointment_details = self._connection.execute(
            """
            SELECT appointment_time, total_price FROM appointments
            WHERE appointment_id = ?
            """,
            (appointment_id,),
        ).fetchone()
        if appointment_details is None:
            return False
        total_price = float(appointment_details["total_price"])
        minimum_spend = self.get_minimum_spend_per_appointment()
        if total_price < minimum_spend:
            raise StampNotQualifiedError(total_price, minimum_spend)
        appointment_date = datetime.fromisoformat(
            str(appointment_details["appointment_time"])
        ).date()
        card_month = appointment_date.strftime("%Y-%m")
        stamps_before = self._monthly_stamp_count(card["client_email"], card_month)
        self._connection.execute(
            """
            INSERT INTO loyalty_monthly_stamps
                (appointment_id, client_email, card_month, stamped_at, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (
                appointment_id,
                card["client_email"],
                card_month,
                created_at.isoformat(),
            ),
        )
        has_stamp_log = self._connection.execute(
            "SELECT 1 FROM loyalty_stamp_log WHERE appointment_id = ?",
            (appointment_id,),
        ).fetchone()
        if has_stamp_log is None:
            self._connection.execute(
                """
                INSERT INTO loyalty_stamp_log
                    (appointment_id, client_email, awarded_at)
                VALUES (?, ?, ?)
                """,
                (appointment_id, card["client_email"], created_at.isoformat()),
            )
        self._connection.execute(
            "UPDATE loyalty_cards SET stamps = stamps + 1 WHERE card_code = ?",
            (card_code,),
        )
        self._connection.execute(
            """
            INSERT INTO stamp_transactions
                (appointment_id, card_code, type, reason, admin_role, created_at)
            VALUES (?, ?, 'STAMP', ?, ?, ?)
            """,
            (appointment_id, card_code, reason, admin_role, created_at.isoformat()),
        )
        milestone = stamps_before + 1
        if milestone in (5, 10):
            self._connection.execute(
                """
                INSERT OR IGNORE INTO loyalty_prize_draws
                    (client_email, card_month, milestone, status, created_at)
                VALUES (?, ?, ?, 'Pending', ?)
                """,
                (
                    card["client_email"],
                    card_month,
                    milestone,
                    created_at.isoformat(),
                ),
            )
        return True

    def award_next_unstamped_completed_visit(
        self, card_code: str, admin_role: str = "Staff"
    ) -> LoyaltyCard | None:
        if not isinstance(admin_role, str) or not admin_role.strip():
            raise ValueError("admin_role is required")
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            card_row = self._connection.execute(
                "SELECT * FROM loyalty_cards WHERE card_code = ?",
                (card_code.strip(),),
            ).fetchone()
            if card_row is None:
                return None
            appointments = self._connection.execute(
                """
                SELECT appointment.appointment_id, appointment.total_price
                FROM appointments AS appointment
                WHERE appointment.client_email = ?
                  AND appointment.status = 'COMPLETED'
                ORDER BY appointment.appointment_time, appointment.appointment_id
                """,
                (card_row["client_email"],),
            ).fetchall()
            appointment_id = next(
                (
                    row["appointment_id"]
                    for row in appointments
                    if not self._appointment_is_stamped(row["appointment_id"])
                    and not self._monthly_stamp_exists(row["appointment_id"])
                ),
                None,
            )
            if appointment_id is None:
                return None
            appointment_row = next(
                row for row in appointments
                if row["appointment_id"] == appointment_id
            )
            self._ensure_appointment_qualifies(float(appointment_row["total_price"]))
            if not self._record_stamp_in_transaction(
                appointment_id,
                card_code.strip(),
                admin_role.strip(),
                "Typed loyalty card code",
                datetime.now(timezone.utc),
            ):
                return None
            updated = self._connection.execute(
                "SELECT * FROM loyalty_cards WHERE card_code = ?",
                (card_code.strip(),),
            ).fetchone()
        return self._loyalty_card_from_row(updated) if updated else None

    def update_loyalty_card(self, card: LoyaltyCard) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE loyalty_cards SET qr_code_path = ?
                WHERE client_email = ?
                """,
                (card.qr_code_path, card.client_email),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No loyalty card found for {card.client_email}")

    def reverse_loyalty_stamp(
        self,
        appointment_id: int,
        reason: str,
        admin_role: str,
        allow_restamp: bool,
    ) -> LoyaltyCard:
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if len(normalized_reason) < 5:
            raise ValueError("A reversal reason must be at least 5 characters")
        if admin_role != "Admin":
            raise PermissionError("Only Admin can reverse a loyalty stamp")
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            latest = self._connection.execute(
                """
                SELECT card_code, type FROM stamp_transactions
                WHERE appointment_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (appointment_id,),
            ).fetchone()
            if latest is None or latest["type"] != "STAMP":
                raise ValueError("This appointment has no active stamp to reverse")
            claimed = self._connection.execute(
                """
                SELECT 1 FROM loyalty_reward_claims
                WHERE card_code = ? LIMIT 1
                """,
                (latest["card_code"],),
            ).fetchone()
            if claimed is not None:
                raise ValueError(
                    "A reward was already claimed for this card; the claim was not changed."
                )
            card = self._connection.execute(
                "SELECT client_email, stamps FROM loyalty_cards WHERE card_code = ?",
                (latest["card_code"],),
            ).fetchone()
            if card is None:
                raise KeyError("No loyalty card found for this stamp")
            if int(card["stamps"]) < 1:
                raise ValueError("This card has no available stamp to reverse")
            self._connection.execute(
                "UPDATE loyalty_cards SET stamps = stamps - 1 WHERE card_code = ?",
                (latest["card_code"],),
            )
            self._connection.execute(
                """
                UPDATE loyalty_monthly_stamps SET active = 0
                WHERE appointment_id = ?
                """,
                (appointment_id,),
            )
            self._connection.execute(
                """
                INSERT INTO stamp_transactions
                    (appointment_id, card_code, type, reason, admin_role,
                     created_at, allow_restamp)
                VALUES (?, ?, 'REVERSAL', ?, ?, ?, ?)
                """,
                (
                    appointment_id,
                    latest["card_code"],
                    normalized_reason,
                    admin_role,
                    datetime.now(timezone.utc).isoformat(),
                    int(allow_restamp),
                ),
            )
            updated = self._connection.execute(
                "SELECT * FROM loyalty_cards WHERE card_code = ?",
                (latest["card_code"],),
            ).fetchone()
        if updated is None:
            raise RuntimeError("The loyalty card could not be loaded after reversal")
        return self._loyalty_card_from_row(updated)

    def get_loyalty_stamp_history(self, email: str) -> list[dict[str, object]]:
        card = self._connection.execute(
            "SELECT card_code FROM loyalty_cards WHERE client_email = ?",
            (email.strip().lower(),),
        ).fetchone()
        if card is None:
            return []
        rows = self._connection.execute(
            """
            SELECT id, appointment_id, type, reason, created_at
            FROM stamp_transactions
            WHERE card_code = ?
            ORDER BY id DESC
            """,
            (card["card_code"],),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_reward_claim_history(self, email: str) -> list[dict[str, str]]:
        card = self._connection.execute(
            "SELECT card_code FROM loyalty_cards WHERE client_email = ?",
            (email.strip().lower(),),
        ).fetchone()
        if card is None:
            return []
        rows = self._connection.execute(
            """
            SELECT claimed_at, admin_role FROM loyalty_reward_claims
            WHERE card_code = ?
            ORDER BY id DESC
            """,
            (card["card_code"],),
        ).fetchall()
        return [
            {"claimed_at": str(row["claimed_at"]), "admin_role": str(row["admin_role"])}
            for row in rows
        ]

    def get_loyalty_prizes(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT prize_id, name, milestone, active
            FROM loyalty_prizes ORDER BY name COLLATE NOCASE, prize_id
            """
        ).fetchall()
        return [
            {
                "prize_id": int(row["prize_id"]),
                "name": str(row["name"]),
                "milestone": str(row["milestone"]),
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    def add_loyalty_prize(
        self, name: str, milestone: str, active: bool, admin_role: str
    ) -> int:
        self._require_loyalty_admin(admin_role)
        normalized_name = self._validate_prize(name, milestone, active)
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO loyalty_prizes (name, milestone, active)
                VALUES (?, ?, ?)
                """,
                (normalized_name, milestone, int(active)),
            )
        return int(cursor.lastrowid)

    def update_loyalty_prize(
        self,
        prize_id: int,
        name: str,
        milestone: str,
        active: bool,
        admin_role: str,
    ) -> None:
        self._require_loyalty_admin(admin_role)
        normalized_name = self._validate_prize(name, milestone, active)
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE loyalty_prizes SET name = ?, milestone = ?, active = ?
                WHERE prize_id = ?
                """,
                (normalized_name, milestone, int(active), prize_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No loyalty prize found with ID {prize_id}")

    def delete_loyalty_prize(self, prize_id: int, admin_role: str) -> None:
        self._require_loyalty_admin(admin_role)
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM loyalty_prizes WHERE prize_id = ?", (prize_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No loyalty prize found with ID {prize_id}")

    def get_loyalty_prize_draws(
        self,
        client_email: str | None = None,
        card_month: str | None = None,
    ) -> list[dict[str, object]]:
        query = """
            SELECT draw.draw_id, draw.client_email, client.name AS client_name,
                   draw.card_month, draw.milestone, draw.status,
                   draw.prize_name, draw.created_at, draw.drawn_at, draw.given_at
            FROM loyalty_prize_draws AS draw
            LEFT JOIN clients AS client ON client.email = draw.client_email
        """
        filters: list[str] = []
        parameters: list[object] = []
        if client_email is not None:
            filters.append("draw.client_email = ?")
            parameters.append(client_email.strip().lower())
        if card_month is not None:
            filters.append("draw.card_month = ?")
            parameters.append(card_month)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY draw.card_month DESC, draw.client_email COLLATE NOCASE, draw.milestone"
        rows = self._connection.execute(query, parameters).fetchall()
        return [
            {
                "draw_id": int(row["draw_id"]),
                "client_email": str(row["client_email"]),
                "client_name": str(row["client_name"] or ""),
                "card_month": str(row["card_month"]),
                "milestone": int(row["milestone"]),
                "status": str(row["status"]),
                "prize_name": str(row["prize_name"]),
                "created_at": str(row["created_at"]),
                "drawn_at": row["drawn_at"],
                "given_at": row["given_at"],
            }
            for row in rows
        ]

    def draw_loyalty_prize(
        self, draw_id: int, admin_role: str
    ) -> dict[str, object]:
        self._require_loyalty_admin(admin_role)
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            draw = self._connection.execute(
                """
                SELECT milestone, status FROM loyalty_prize_draws
                WHERE draw_id = ?
                """,
                (draw_id,),
            ).fetchone()
            if draw is None:
                raise KeyError(f"No loyalty prize draw found with ID {draw_id}")
            if draw["status"] != "Pending":
                raise ValueError("Only pending prize draws can be drawn")
            prizes = self._connection.execute(
                """
                SELECT prize_id, name FROM loyalty_prizes
                WHERE active = 1 AND milestone IN (?, 'both')
                ORDER BY prize_id
                """,
                (str(draw["milestone"]),),
            ).fetchall()
            if not prizes:
                raise ValueError(
                    f"No active prizes are available for the {draw['milestone']}th-stamp milestone."
                )
            prize = secrets.choice(prizes)
            self._connection.execute(
                """
                UPDATE loyalty_prize_draws
                SET status = 'Drawn', prize_name = ?, drawn_at = ?
                WHERE draw_id = ? AND status = 'Pending'
                """,
                (prize["name"], datetime.now(timezone.utc).isoformat(), draw_id),
            )
        result = next(
            item for item in self.get_loyalty_prize_draws()
            if item["draw_id"] == draw_id
        )
        return result

    def mark_loyalty_prize_given(self, draw_id: int, admin_role: str) -> None:
        self._require_loyalty_admin(admin_role)
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE loyalty_prize_draws
                SET status = 'Given', given_at = ?
                WHERE draw_id = ? AND status = 'Drawn'
                """,
                (datetime.now(timezone.utc).isoformat(), draw_id),
            )
        if cursor.rowcount == 0:
            raise ValueError("Only a drawn prize can be marked as given")

    @staticmethod
    def _require_loyalty_admin(admin_role: str) -> None:
        if admin_role != "Admin":
            raise PermissionError("Only Admin can manage loyalty prizes")

    @staticmethod
    def _validate_prize(name: str, milestone: str, active: bool) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Prize name is required")
        if milestone not in {"5", "10", "both"}:
            raise ValueError("Prize milestone must be 5, 10, or both")
        if not isinstance(active, bool):
            raise TypeError("Prize active state must be a boolean")
        return name.strip()

    def claim_loyalty_reward(self, email: str, admin_role: str) -> LoyaltyCard:
        if admin_role != "Admin":
            raise PermissionError("Only Admin can claim a loyalty reward")
        normalized_email = email.strip().lower()
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            card_row = self._connection.execute(
                "SELECT * FROM loyalty_cards WHERE client_email = ?",
                (normalized_email,),
            ).fetchone()
            if card_row is None:
                raise KeyError(f"No loyalty card found for {normalized_email}")
            required_row = self._connection.execute(
                "SELECT stamps_required FROM loyalty_settings WHERE setting_id = 1"
            ).fetchone()
            required = int(required_row["stamps_required"]) if required_row else 10
            if int(card_row["stamps"]) < required:
                raise ValueError(
                    "This loyalty card does not have enough stamps to claim a reward"
                )
            if not card_row["card_code"]:
                raise RuntimeError("Loyalty card has no card code")
            self._connection.execute(
                """
                UPDATE loyalty_cards SET stamps = stamps - ?
                WHERE client_email = ?
                """,
                (required, normalized_email),
            )
            self._connection.execute(
                """
                INSERT INTO loyalty_reward_claims (card_code, claimed_at, admin_role)
                VALUES (?, ?, ?)
                """,
                (
                    card_row["card_code"],
                    datetime.now(timezone.utc).isoformat(),
                    admin_role,
                ),
            )
            updated = self._connection.execute(
                "SELECT * FROM loyalty_cards WHERE client_email = ?",
                (normalized_email,),
            ).fetchone()
        if updated is None:
            raise RuntimeError("Loyalty card could not be loaded after reward claim")
        return self._loyalty_card_from_row(updated)

    def delete_loyalty_card(self, email: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM loyalty_cards WHERE client_email = ?",
                (email.strip().lower(),),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No loyalty card found for {email}")

    def get_loyalty_settings(self) -> LoyaltySettings:
        row = self._connection.execute(
            "SELECT stamps_required FROM loyalty_settings WHERE setting_id = 1"
        ).fetchone()
        if row is None:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO loyalty_settings (setting_id, stamps_required)
                    VALUES (1, 10)
                    """
                )
            return LoyaltySettings()
        return LoyaltySettings(row["stamps_required"])

    def update_loyalty_settings(self, settings: LoyaltySettings) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO loyalty_settings (setting_id, stamps_required)
                VALUES (1, ?)
                ON CONFLICT(setting_id) DO UPDATE SET stamps_required = excluded.stamps_required
                """,
                (settings.get_stamps_required(),),
            )

    def get_studio_settings(self) -> StudioSettings:
        row = self._connection.execute(
            """
            SELECT default_travel_fee, travel_buffer_minutes, service_area_note,
                   allowed_areas, cleaning_buffer_minutes, studio_address,
                   maps_embed_url, map_latitude, map_longitude, map_image_path,
                   loyalty_facebook, loyalty_phone, loyalty_valid_until,
                   loyalty_terms, owner_provider_name, review_url,
                   online_booking_url, minimum_spend_per_appointment,
                   map_link_url
            FROM studio_settings WHERE setting_id = 1
            """
        ).fetchone()
        if row is None:
            return StudioSettings()
        return StudioSettings(
            row["default_travel_fee"],
            row["travel_buffer_minutes"],
            row["service_area_note"],
            json.loads(row["allowed_areas"]),
            row["cleaning_buffer_minutes"],
            row["studio_address"],
            row["maps_embed_url"],
            row["map_latitude"],
            row["map_longitude"],
            row["map_image_path"],
            row["loyalty_facebook"],
            row["loyalty_phone"],
            row["loyalty_valid_until"],
            row["loyalty_terms"],
            row["owner_provider_name"],
            row["review_url"],
            row["online_booking_url"],
            row["minimum_spend_per_appointment"],
            row["map_link_url"],
        )

    def update_studio_settings(self, settings: StudioSettings) -> None:
        if not isinstance(settings, StudioSettings):
            raise TypeError("settings must be StudioSettings")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO studio_settings
                    (setting_id, default_travel_fee, travel_buffer_minutes,
                     service_area_note, allowed_areas, cleaning_buffer_minutes,
                     studio_address, maps_embed_url, map_latitude,
                     map_longitude, map_image_path, loyalty_facebook,
                     loyalty_phone, loyalty_valid_until, loyalty_terms,
                     owner_provider_name, review_url, online_booking_url,
                     minimum_spend_per_appointment, map_link_url)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(setting_id) DO UPDATE SET
                    default_travel_fee = excluded.default_travel_fee,
                    travel_buffer_minutes = excluded.travel_buffer_minutes,
                    service_area_note = excluded.service_area_note,
                    allowed_areas = excluded.allowed_areas,
                    cleaning_buffer_minutes = excluded.cleaning_buffer_minutes,
                    studio_address = excluded.studio_address,
                    maps_embed_url = excluded.maps_embed_url,
                    map_latitude = excluded.map_latitude,
                    map_longitude = excluded.map_longitude,
                    map_image_path = excluded.map_image_path,
                    loyalty_facebook = excluded.loyalty_facebook,
                    loyalty_phone = excluded.loyalty_phone,
                    loyalty_valid_until = excluded.loyalty_valid_until,
                    loyalty_terms = excluded.loyalty_terms,
                    owner_provider_name = excluded.owner_provider_name,
                    review_url = excluded.review_url,
                    online_booking_url = excluded.online_booking_url,
                    minimum_spend_per_appointment =
                        excluded.minimum_spend_per_appointment,
                    map_link_url = excluded.map_link_url
                """,
                (
                    settings.default_travel_fee,
                    settings.travel_buffer_minutes,
                    settings.service_area_note,
                    json.dumps(settings.allowed_areas),
                    settings.cleaning_buffer_minutes,
                    settings.studio_address,
                    settings.maps_embed_url,
                    settings.map_latitude,
                    settings.map_longitude,
                    settings.map_image_path,
                    settings.loyalty_facebook,
                    settings.loyalty_phone,
                    settings.loyalty_valid_until,
                    settings.loyalty_terms,
                    settings.owner_provider_name,
                    settings.review_url,
                    settings.online_booking_url,
                    settings.minimum_spend_per_appointment,
                    settings.map_link_url,
                ),
            )

    def get_weekly_hours(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT weekday, is_open, open_time, close_time FROM weekly_hours ORDER BY weekday"
        ).fetchall()
        return [
            {
                "weekday": row["weekday"],
                "is_open": bool(row["is_open"]),
                "open_time": row["open_time"],
                "close_time": row["close_time"],
            }
            for row in rows
        ]

    def save_weekly_hours(self, hours: list[dict[str, object]]) -> None:
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO weekly_hours (weekday, is_open, open_time, close_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(weekday) DO UPDATE SET
                    is_open = excluded.is_open,
                    open_time = excluded.open_time,
                    close_time = excluded.close_time
                """,
                [
                    (
                        entry["weekday"],
                        int(bool(entry["is_open"])),
                        entry["open_time"],
                        entry["close_time"],
                    )
                    for entry in hours
                ],
            )

    def get_schedule_breaks(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT break_id, label, start_time, end_time FROM schedule_breaks ORDER BY start_time"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_schedule_break(self, label: str, start_time: str, end_time: str) -> int:
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO schedule_breaks (label, start_time, end_time) VALUES (?, ?, ?)",
                (label, start_time, end_time),
            )
        return int(cursor.lastrowid)

    def remove_schedule_break(self, break_id: int) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM schedule_breaks WHERE break_id = ?", (break_id,)
            )

    def get_schedule_closures(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT closure_id, start_datetime, end_datetime, reason
            FROM schedule_closures ORDER BY start_datetime
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_schedule_closure(
        self, start_datetime: str, end_datetime: str, reason: str
    ) -> int:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO schedule_closures (start_datetime, end_datetime, reason)
                VALUES (?, ?, ?)
                """,
                (start_datetime, end_datetime, reason),
            )
        return int(cursor.lastrowid)

    def remove_schedule_closure(self, closure_id: int) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM schedule_closures WHERE closure_id = ?",
                (closure_id,),
            )

    def add_gallery_item(self, item: GalleryItem) -> GalleryItem:
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO gallery_items (title, description, photo_path)
                VALUES (?, ?, ?)
                """,
                (item.title, item.description, item.photo_path),
            )
        return self.get_gallery_item(cursor.lastrowid)

    def get_gallery_item(self, item_id: int) -> GalleryItem | None:
        row = self._connection.execute(
            "SELECT * FROM gallery_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return self._gallery_item_from_row(row) if row else None

    def get_gallery_items(self) -> list[GalleryItem]:
        rows = self._connection.execute(
            "SELECT * FROM gallery_items ORDER BY item_id DESC"
        ).fetchall()
        return [self._gallery_item_from_row(row) for row in rows]

    def update_gallery_item(self, item: GalleryItem) -> None:
        if item.item_id is None:
            raise ValueError("item.item_id is required to update a gallery item")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE gallery_items SET title = ?, description = ?, photo_path = ?
                WHERE item_id = ?
                """,
                (item.title, item.description, item.photo_path, item.item_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No gallery item found with ID {item.item_id}")

    def delete_gallery_item(self, item_id: int) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM gallery_items WHERE item_id = ?", (item_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No gallery item found with ID {item_id}")

    def add_queue_entry(
        self,
        entry: QueueEntry,
        appointment_id: int | None = None,
    ) -> QueueEntry:
        created_at = self._serialize_time(entry.created_at)
        ticket_date = entry.queue_date.isoformat()
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                """
                SELECT MAX(CAST(SUBSTR(ticket_number, 3) AS INTEGER)) AS last_number
                FROM queue_entries WHERE ticket_date = ?
                """,
                (ticket_date,),
            ).fetchone()
            sequence_number = (row["last_number"] or 0) + 1
            ticket_number = f"A-{sequence_number:03d}"
            cursor = self._connection.execute(
                """
                INSERT INTO queue_entries
                    (client_name, client_email, appointment_id, entry_type, status, created_at,
                     ticket_number, ticket_date, queue_date, sort_time, skip_count,
                     skip_after_entry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.client_name,
                    entry.client_email,
                    appointment_id,
                    entry.entry_type.value,
                    entry.status.value,
                    created_at,
                    ticket_number,
                    ticket_date,
                    entry.queue_date.isoformat(),
                    entry.sort_time.isoformat(),
                    entry.skip_count,
                    entry.skip_after_entry_id,
                ),
            )
        entry_id = cursor.lastrowid
        if entry_id is None:
            raise RuntimeError("Queue entry insert did not return an ID")
        saved_entry = self.get_queue_entry(entry_id)
        if saved_entry is None:
            raise RuntimeError("Queue entry insert did not persist")
        return saved_entry

    def get_queue_entry(self, entry_id: int) -> QueueEntry | None:
        row = self._connection.execute(
            "SELECT * FROM queue_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        return self._queue_entry_from_row(row) if row else None

    def get_queue_entry_by_appointment(self, appointment_id: int) -> QueueEntry | None:
        row = self._connection.execute(
            "SELECT * FROM queue_entries WHERE appointment_id = ?",
            (appointment_id,),
        ).fetchone()
        return self._queue_entry_from_row(row) if row else None

    def get_queue_entries(self, queue_date: date | None = None) -> list[QueueEntry]:
        selected_date = (queue_date or date.today()).isoformat()
        rows = self._connection.execute(
            """
            SELECT * FROM queue_entries
            WHERE queue_date = ?
            ORDER BY queue_date, sort_time, entry_id
            """,
            (selected_date,),
        ).fetchall()
        return [self._queue_entry_from_row(row) for row in rows]

    def get_all_queue_entries(self) -> list[QueueEntry]:
        rows = self._connection.execute(
            """
            SELECT * FROM queue_entries
            ORDER BY queue_date, sort_time, entry_id
            """
        ).fetchall()
        return [self._queue_entry_from_row(row) for row in rows]

    def update_queue_entry(self, entry: QueueEntry) -> None:
        if entry.entry_id is None:
            raise ValueError("entry.entry_id is required to update a queue entry")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE queue_entries
                SET status = ?, queue_date = ?, sort_time = ?, skip_count = ?,
                    skip_after_entry_id = ?
                WHERE entry_id = ?
                """,
                (
                    entry.status.value,
                    entry.queue_date.isoformat(),
                    entry.sort_time.isoformat(),
                    entry.skip_count,
                    entry.skip_after_entry_id,
                    entry.entry_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No queue entry found with ID {entry.entry_id}")

    @staticmethod
    def _serialize_time(value: datetime | str) -> str:
        return value.isoformat() if isinstance(value, datetime) else value

    @staticmethod
    def _client_from_row(row: sqlite3.Row) -> Customer:
        paid_on_value = row["deposit_paid_on"]
        paid_on = date.fromisoformat(paid_on_value) if paid_on_value else None
        return Customer(
            row["name"],
            row["email"],
            row["phone"],
            row["notes"],
            bool(row["deposit_paid"]),
            row["address"],
            row["nail_condition"],
            row["health_notes"],
            paid_on,
        )

    @staticmethod
    def _service_from_row(row: sqlite3.Row) -> Service:
        return Service(
            name=row["name"],
            base_price=row["base_price"],
            description=row["description"],
            length_prices=json.loads(row["length_prices"]),
            design_add_on_prices=json.loads(row["design_add_on_prices"]),
            service_id=row["service_id"],
            duration_minutes=row["duration_minutes"],
        )

    @staticmethod
    def _price_extra_from_row(row: sqlite3.Row) -> PriceExtra:
        return PriceExtra(
            name=row["name"],
            category=row["category"],
            price=row["price"],
            active=bool(row["active"]),
            extra_id=row["id"],
        )

    @staticmethod
    def _appointment_from_row(row: sqlite3.Row) -> Appointment:
        return Appointment(
            client_email=row["client_email"],
            service_id=row["service_id"],
            appointment_time=row["appointment_time"],
            status=AppointmentStatus(row["status"]),
            notes=row["notes"],
            nail_length=row["nail_length"],
            design_add_ons=json.loads(row["design_add_ons"]),
            selected_extras=json.loads(row["selected_extras"]),
            total_price=row["total_price"],
            appointment_id=row["appointment_id"],
            duration_minutes=row["duration_minutes"],
            cancellation_fee=row["cancellation_fee"],
            allergies=row["allergies"],
            travel_fee=row["travel_fee"],
            discount=row["discount"],
            amount_paid=row["amount_paid"],
            payment_note=row["payment_note"],
            visit_type=VisitType(row["visit_type"]),
            service_address=row["service_address"],
            allow_missing_service_address=True,
        )

    def _loyalty_card_from_row(self, row: sqlite3.Row) -> LoyaltyCard:
        return LoyaltyCard(
            row["client_email"],
            self._monthly_stamp_count(
                row["client_email"], date.today().strftime("%Y-%m")
            ),
            row["qr_code_path"],
            row["card_code"],
            row["view_code"],
        )

    @staticmethod
    def _gallery_item_from_row(row: sqlite3.Row) -> GalleryItem:
        return GalleryItem(
            title=row["title"],
            description=row["description"],
            photo_path=row["photo_path"],
            item_id=row["item_id"],
        )

    @staticmethod
    def _queue_entry_from_row(row: sqlite3.Row) -> QueueEntry:
        return QueueEntry(
            client_name=row["client_name"],
            client_email=row["client_email"],
            entry_type=QueueEntryType(row["entry_type"]),
            status=QueueStatus(row["status"]),
            created_at=row["created_at"],
            entry_id=row["entry_id"],
            ticket_number=row["ticket_number"],
            appointment_id=row["appointment_id"],
            queue_date=row["queue_date"] or row["ticket_date"],
            sort_time=row["sort_time"] or row["created_at"],
            skip_count=row["skip_count"],
            skip_after_entry_id=row["skip_after_entry_id"],
        )
