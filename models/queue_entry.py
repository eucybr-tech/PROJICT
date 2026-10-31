from datetime import date, datetime
from enum import Enum

from ._validation import validate_nonempty_text, validate_optional_text


class QueueEntryType(Enum):
    BOOKED = "BOOKED"
    WALK_IN = "WALK_IN"


class QueueStatus(Enum):
    WAITING = "WAITING"
    SERVING = "SERVING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class QueueEntry:
    def __init__(
        self,
        client_name: str,
        entry_type: QueueEntryType,
        status: QueueStatus = QueueStatus.WAITING,
        client_email: str | None = None,
        created_at: datetime | str | None = None,
        entry_id: int | None = None,
        ticket_number: str | None = None,
        appointment_id: int | None = None,
        queue_date: date | str | None = None,
        sort_time: datetime | str | None = None,
        skip_count: int = 0,
        skip_after_entry_id: int | None = None,
    ) -> None:
        if not isinstance(entry_type, QueueEntryType):
            raise ValueError("entry_type must be a QueueEntryType value")
        self._entry_id = entry_id
        self._client_name = validate_nonempty_text(client_name, "client_name")
        self._client_email = validate_optional_text(client_email, "client_email")
        self._entry_type = entry_type
        self._status = self._validate_status(status)
        self._created_at = created_at or datetime.now()
        if not isinstance(self._created_at, (datetime, str)):
            raise TypeError("created_at must be a datetime or ISO timestamp string")
        if isinstance(self._created_at, str):
            datetime.fromisoformat(self._created_at)
        self._ticket_number = (
            validate_nonempty_text(ticket_number, "ticket_number")
            if ticket_number is not None
            else None
        )
        if appointment_id is not None and (
            isinstance(appointment_id, bool)
            or not isinstance(appointment_id, int)
            or appointment_id <= 0
        ):
            raise ValueError("appointment_id must be a positive integer or None")
        self._appointment_id = appointment_id
        created_datetime = (
            self._created_at
            if isinstance(self._created_at, datetime)
            else datetime.fromisoformat(self._created_at)
        )
        if queue_date is None:
            normalized_queue_date = created_datetime.date()
        elif isinstance(queue_date, str):
            normalized_queue_date = date.fromisoformat(queue_date)
        elif isinstance(queue_date, date) and not isinstance(queue_date, datetime):
            normalized_queue_date = queue_date
        else:
            raise TypeError("queue_date must be a date or ISO date string")
        self._queue_date: date = normalized_queue_date
        if sort_time is None:
            normalized_sort_time = created_datetime
        elif isinstance(sort_time, str):
            normalized_sort_time = datetime.fromisoformat(sort_time)
        elif isinstance(sort_time, datetime):
            normalized_sort_time = sort_time
        else:
            raise TypeError("sort_time must be a datetime or ISO timestamp string")
        self._sort_time: datetime = normalized_sort_time
        if (
            isinstance(skip_count, bool)
            or not isinstance(skip_count, int)
            or skip_count < 0
        ):
            raise ValueError("skip_count must be a non-negative integer")
        self._skip_count = skip_count
        if skip_after_entry_id is not None and (
            isinstance(skip_after_entry_id, bool)
            or not isinstance(skip_after_entry_id, int)
            or skip_after_entry_id <= 0
        ):
            raise ValueError("skip_after_entry_id must be a positive integer or None")
        self._skip_after_entry_id = skip_after_entry_id

    @staticmethod
    def _validate_status(status: QueueStatus) -> QueueStatus:
        if not isinstance(status, QueueStatus):
            raise ValueError("status must be a QueueStatus value")
        return status

    @property
    def entry_id(self) -> int | None:
        return self._entry_id

    @property
    def client_name(self) -> str:
        return self._client_name

    @property
    def client_email(self) -> str | None:
        return self._client_email

    @property
    def entry_type(self) -> QueueEntryType:
        return self._entry_type

    @property
    def status(self) -> QueueStatus:
        return self._status

    @property
    def created_at(self) -> datetime | str:
        return self._created_at

    @property
    def ticket_number(self) -> str | None:
        return self._ticket_number

    @property
    def appointment_id(self) -> int | None:
        return self._appointment_id

    @property
    def queue_date(self) -> date:
        return self._queue_date

    @property
    def sort_time(self) -> datetime:
        return self._sort_time

    @property
    def skip_count(self) -> int:
        return self._skip_count

    @property
    def skip_after_entry_id(self) -> int | None:
        return self._skip_after_entry_id

    def update_status(self, status: QueueStatus) -> None:
        self._status = self._validate_status(status)

    def update_schedule(self, queue_date: date, sort_time: datetime) -> None:
        if not isinstance(queue_date, date) or isinstance(queue_date, datetime):
            raise TypeError("queue_date must be a date")
        if not isinstance(sort_time, datetime):
            raise TypeError("sort_time must be a datetime")
        self._queue_date = queue_date
        self._sort_time = sort_time

    def update_skip(self, skip_count: int, after_entry_id: int | None) -> None:
        if (
            isinstance(skip_count, bool)
            or not isinstance(skip_count, int)
            or skip_count < 0
        ):
            raise ValueError("skip_count must be a non-negative integer")
        if after_entry_id is not None and (
            isinstance(after_entry_id, bool)
            or not isinstance(after_entry_id, int)
            or after_entry_id <= 0
        ):
            raise ValueError("after_entry_id must be a positive integer or None")
        self._skip_count = skip_count
        self._skip_after_entry_id = after_entry_id
