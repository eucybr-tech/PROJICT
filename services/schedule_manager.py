from datetime import date, datetime, time, timedelta

from database import Database
from models import VisitType


class ScheduleManager:
    """Validated schedule operations backed by Database persistence."""

    WEEKDAYS = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )

    def __init__(self, database: Database) -> None:
        # Dependency injection: schedule persistence stays behind Database.
        self._database = database

    @property
    def database(self) -> Database:
        return self._database

    def get_weekly_hours(self) -> list[dict[str, object]]:
        return self._database.get_weekly_hours()

    def save_weekly_hours(self, hours: list[dict[str, object]]) -> None:
        if len(hours) != 7:
            raise ValueError("Weekly hours must include all seven weekdays")
        normalized: list[dict[str, object]] = []
        for weekday, entry in enumerate(hours):
            if entry.get("weekday") != weekday:
                raise ValueError("Weekly hours must be ordered Monday through Sunday")
            opened = entry.get("is_open")
            if not isinstance(opened, bool):
                raise TypeError("is_open must be a bool")
            opening = self._parse_time(entry.get("open_time"), "open_time")
            closing = self._parse_time(entry.get("close_time"), "close_time")
            if closing <= opening:
                raise ValueError(
                    f"Closing time must be after opening time on {self.WEEKDAYS[weekday]}"
                )
            normalized.append(
                {
                    "weekday": weekday,
                    "is_open": opened,
                    "open_time": opening.strftime("%H:%M"),
                    "close_time": closing.strftime("%H:%M"),
                }
            )
        self._database.save_weekly_hours(normalized)

    def get_breaks(self) -> list[dict[str, object]]:
        return self._database.get_schedule_breaks()

    def add_break(self, label: str, start_time: time, end_time: time) -> int:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Break label is required")
        start = self._parse_time(start_time, "start_time")
        end = self._parse_time(end_time, "end_time")
        if start >= end:
            raise ValueError("Break start time must be before end time")
        for current in self.get_breaks():
            current_start = time.fromisoformat(str(current["start_time"]))
            current_end = time.fromisoformat(str(current["end_time"]))
            if start < current_end and current_start < end:
                raise ValueError("Breaks cannot overlap")
        return self._database.add_schedule_break(
            label.strip(), start.strftime("%H:%M"), end.strftime("%H:%M")
        )

    def remove_break(self, break_id: int) -> None:
        self._database.remove_schedule_break(break_id)

    def get_closures(self) -> list[dict[str, object]]:
        return self._database.get_schedule_closures()

    def add_closure(
        self, start_datetime: datetime, end_datetime: datetime, reason: str
    ) -> int:
        if not isinstance(start_datetime, datetime) or not isinstance(
            end_datetime, datetime
        ):
            raise TypeError("Closure bounds must be datetimes")
        if start_datetime >= end_datetime:
            raise ValueError("Closure end must be after its start")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Closure reason is required")
        return self._database.add_schedule_closure(
            start_datetime.isoformat(),
            end_datetime.isoformat(),
            reason.strip(),
        )

    def remove_closure(self, closure_id: int) -> None:
        self._database.remove_schedule_closure(closure_id)

    def get_day_hours(self, selected_date: date) -> dict[str, object]:
        if not isinstance(selected_date, date) or isinstance(selected_date, datetime):
            raise TypeError("selected_date must be a date")
        entry = self.get_weekly_hours()[selected_date.weekday()]
        return entry

    def is_open(self, selected_date: date) -> bool:
        return bool(self.get_day_hours(selected_date)["is_open"])

    def get_day_breaks(self) -> list[dict[str, object]]:
        return self.get_breaks()

    def get_closures_for_date(self, selected_date: date) -> list[dict[str, object]]:
        day_start = datetime.combine(selected_date, time.min)
        day_end = datetime.combine(selected_date, time.max)
        return [
            closure
            for closure in self.get_closures()
            if datetime.fromisoformat(str(closure["start_datetime"])) < day_end
            and datetime.fromisoformat(str(closure["end_datetime"])) > day_start
        ]

    def get_schedule_issue(
        self,
        appointment_start: datetime,
        duration_minutes: int,
        visit_type: VisitType,
    ) -> str | None:
        if not isinstance(appointment_start, datetime):
            raise TypeError("appointment_start must be a datetime")
        if (
            isinstance(duration_minutes, bool)
            or not isinstance(duration_minutes, int)
            or duration_minutes <= 0
        ):
            raise ValueError("duration_minutes must be a positive integer")
        if not isinstance(visit_type, VisitType):
            raise ValueError("visit_type must be a VisitType value")

        entry = self.get_day_hours(appointment_start.date())
        if not entry["is_open"]:
            return "The studio is closed on this day."
        opening = time.fromisoformat(str(entry["open_time"]))
        closing = time.fromisoformat(str(entry["close_time"]))
        day_open = datetime.combine(appointment_start.date(), opening)
        day_close = datetime.combine(appointment_start.date(), closing)

        settings = self._database.get_studio_settings()
        travel = (
            settings.travel_buffer_minutes
            if visit_type is VisitType.HOME_SERVICE
            else 0
        )
        blocked_start = appointment_start - timedelta(minutes=travel)
        blocked_end = (
            appointment_start
            + timedelta(minutes=duration_minutes + travel)
            + timedelta(minutes=settings.cleaning_buffer_minutes)
        )
        if blocked_start < day_open or blocked_end > day_close:
            return "Appointment falls outside the day's working hours."

        for break_entry in self.get_breaks():
            break_start = datetime.combine(
                appointment_start.date(),
                time.fromisoformat(str(break_entry["start_time"])),
            )
            break_end = datetime.combine(
                appointment_start.date(),
                time.fromisoformat(str(break_entry["end_time"])),
            )
            if blocked_start < break_end and break_start < blocked_end:
                return f"Appointment overlaps the {break_entry['label']} break."

        for closure in self.get_closures_for_date(appointment_start.date()):
            closure_start = datetime.fromisoformat(str(closure["start_datetime"]))
            closure_end = datetime.fromisoformat(str(closure["end_datetime"]))
            if blocked_start < closure_end and closure_start < blocked_end:
                return f"Appointment overlaps a closure: {closure['reason']}."
        return None

    def get_closed_dates(self, start_date: date, end_date: date) -> set[date]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        hours_by_weekday = self.get_weekly_hours()
        closures = self.get_closures()
        result: set[date] = set()
        cursor = start_date
        while cursor <= end_date:
            day_start = datetime.combine(cursor, time.min)
            day_end = datetime.combine(cursor, time.max)
            has_closure = any(
                datetime.fromisoformat(str(closure["start_datetime"])) < day_end
                and datetime.fromisoformat(str(closure["end_datetime"])) > day_start
                for closure in closures
            )
            if not hours_by_weekday[cursor.weekday()]["is_open"] or has_closure:
                result.add(cursor)
            cursor += timedelta(days=1)
        return result

    @staticmethod
    def _parse_time(value: object, field_name: str) -> time:
        if isinstance(value, time):
            return value.replace(second=0, microsecond=0)
        if isinstance(value, str):
            try:
                return time.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{field_name} must be a valid time") from error
        raise TypeError(f"{field_name} must be a time or HH:MM string")
