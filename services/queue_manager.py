from datetime import date, datetime

from database import Database
from models import (
    AppointmentStatus,
    QueueEntry,
    QueueEntryType,
    QueueStatus,
)
from services.appointment_manager import AppointmentManager
from services.notification_service import EmailCallback


class QueueManager:
    """Manages daily lines and computes live positions from active entries."""

    def __init__(
        self,
        database: Database,
        appointment_manager: AppointmentManager,
    ) -> None:
        self._database = database
        self._appointment_manager = appointment_manager
        appointment_manager.set_queue_manager(self)

    @property
    def appointment_manager(self) -> AppointmentManager:
        return self._appointment_manager

    def add_walk_in(self, name: str) -> QueueEntry:
        now = datetime.now()
        entry = QueueEntry(
            client_name=name,
            entry_type=QueueEntryType.WALK_IN,
            created_at=now,
            queue_date=now.date(),
            sort_time=now,
        )
        return self._database.add_queue_entry(entry)

    def enroll_booked(self, appointment_id: int) -> QueueEntry:
        appointment = self._appointment_manager.get_appointment(appointment_id)
        if appointment.status is not AppointmentStatus.CONFIRMED:
            raise ValueError("Only confirmed appointments can join the queue")
        appointment_time = self._as_datetime(appointment.appointment_time)
        entry = self._database.get_queue_entry_by_appointment(appointment_id)
        if entry is None:
            entry = QueueEntry(
                client_name=self._appointment_manager.get_client_name(
                    appointment.client_email
                ),
                client_email=appointment.client_email,
                entry_type=QueueEntryType.BOOKED,
                created_at=datetime.now(),
                queue_date=appointment_time.date(),
                sort_time=appointment_time,
                appointment_id=appointment_id,
            )
            return self._database.add_queue_entry(entry, appointment_id)

        changed = (
            entry.queue_date != appointment_time.date()
            or entry.sort_time != appointment_time
        )
        if changed:
            self._clear_skips_after(entry)
            entry.update_schedule(appointment_time.date(), appointment_time)
            entry.update_skip(0, None)
        if entry.status in (QueueStatus.DONE, QueueStatus.CANCELLED):
            entry.update_status(QueueStatus.WAITING)
            entry.update_skip(0, None)
            changed = True
        if changed:
            self._database.update_queue_entry(entry)
        return entry

    def sync_appointment(self, appointment_id: int) -> None:
        appointment = self._appointment_manager.get_appointment(appointment_id)
        entry = self._database.get_queue_entry_by_appointment(appointment_id)
        if entry is None:
            if appointment.status is AppointmentStatus.CONFIRMED:
                self.enroll_booked(appointment_id)
            return

        if appointment.status is AppointmentStatus.CONFIRMED:
            appointment_time = self._as_datetime(appointment.appointment_time)
            changed = (
                entry.queue_date != appointment_time.date()
                or entry.sort_time != appointment_time
            )
            if changed:
                self._clear_skips_after(entry)
                entry.update_schedule(appointment_time.date(), appointment_time)
                entry.update_skip(0, None)
            if entry.status in (QueueStatus.DONE, QueueStatus.CANCELLED):
                entry.update_status(QueueStatus.WAITING)
                entry.update_skip(0, None)
                changed = True
        else:
            desired_status = (
                QueueStatus.DONE
                if appointment.status is AppointmentStatus.COMPLETED
                else QueueStatus.CANCELLED
            )
            changed = entry.status is not desired_status
            entry.update_status(desired_status)
            self._clear_skips_after(entry)
        if changed:
            self._database.update_queue_entry(entry)

    def get_queue(self, queue_date: date | None = None) -> list[QueueEntry]:
        return self._get_active_entries(queue_date or date.today())

    def get_position(self, entry_id: int) -> int | None:
        entry = self._database.get_queue_entry(entry_id)
        if entry is None:
            return None
        active = self._get_active_entries(entry.queue_date)
        return next(
            (
                position
                for position, candidate in enumerate(active, start=1)
                if candidate.entry_id == entry_id
            ),
            None,
        )

    def call_next(self, email_callback: EmailCallback | None = None) -> QueueEntry:
        active = self._get_active_entries(date.today())
        if any(entry.status is QueueStatus.SERVING for entry in active):
            raise ValueError("A client is already being served")
        next_entry = next(
            (entry for entry in active if entry.status is QueueStatus.WAITING),
            None,
        )
        if next_entry is None:
            raise ValueError("There are no waiting clients in today's queue")
        self._clear_skips_after(next_entry)
        next_entry.update_skip(0, None)
        next_entry.update_status(QueueStatus.SERVING)
        self._database.update_queue_entry(next_entry)
        if (
            next_entry.entry_type is QueueEntryType.BOOKED
            and next_entry.client_email is not None
        ):
            self._appointment_manager.notify_queue_called(
                next_entry.client_email,
                email_callback or (lambda _success, _error: None),
            )
        return next_entry

    def mark_done(self, entry_id: int) -> QueueEntry:
        entry = self._get_today_entry(entry_id)
        if entry.status is not QueueStatus.SERVING:
            raise ValueError("Only the serving queue entry can be marked done")
        self._clear_skips_after(entry)
        entry.update_status(QueueStatus.DONE)
        self._database.update_queue_entry(entry)
        appointment_id = entry.appointment_id
        if entry.entry_type is QueueEntryType.BOOKED and appointment_id is not None:
            appointment = self._appointment_manager.get_appointment(appointment_id)
            if appointment.status is AppointmentStatus.CONFIRMED:
                self._appointment_manager.update_status(
                    appointment_id,
                    AppointmentStatus.COMPLETED,
                    lambda _success, _error: None,
                )
        return entry

    def cancel_entry(self, entry_id: int) -> QueueEntry:
        entry = self._get_today_entry(entry_id)
        if entry.status not in (QueueStatus.WAITING, QueueStatus.SERVING):
            raise ValueError("Only active queue entries can be cancelled")
        self._clear_skips_after(entry)
        entry.update_status(QueueStatus.CANCELLED)
        self._database.update_queue_entry(entry)
        return entry

    def skip_next(self) -> QueueEntry:
        waiting = [
            entry
            for entry in self._get_active_entries(date.today())
            if entry.status is QueueStatus.WAITING
        ]
        if len(waiting) < 2:
            raise ValueError("There must be another waiting client to skip behind")
        entry, following = waiting[:2]
        self._clear_skips_after(entry)
        entry.update_skip(entry.skip_count + 1, following.entry_id)
        self._database.update_queue_entry(entry)
        return entry

    def get_now_serving(self, queue_date: date | None = None) -> QueueEntry | None:
        return next(
            (
                entry
                for entry in self._get_active_entries(queue_date or date.today())
                if entry.status is QueueStatus.SERVING
            ),
            None,
        )

    def find_entry(self, ticket_or_email: str) -> QueueEntry | None:
        query = ticket_or_email.strip().casefold()
        if not query:
            return None
        today = date.today()
        matches = [
            entry
            for entry in self._database.get_all_queue_entries()
            if entry.status in (QueueStatus.WAITING, QueueStatus.SERVING)
            and (
                (entry.ticket_number or "").casefold() == query
                or (entry.client_email or "").casefold() == query
            )
        ]
        return min(
            matches,
            key=lambda entry: (
                0 if entry.queue_date == today else 1 if entry.queue_date > today else 2,
                abs((entry.queue_date - today).days),
                entry.queue_date,
                entry.sort_time,
                entry.entry_id or 0,
            ),
            default=None,
        )

    def _get_active_entries(self, queue_date: date) -> list[QueueEntry]:
        active = [
            entry
            for entry in self._database.get_queue_entries(queue_date)
            if entry.status in (QueueStatus.WAITING, QueueStatus.SERVING)
        ]
        serving = sorted(
            (entry for entry in active if entry.status is QueueStatus.SERVING),
            key=lambda entry: (entry.sort_time, entry.entry_id or 0),
        )
        waiting = sorted(
            (entry for entry in active if entry.status is QueueStatus.WAITING),
            key=lambda entry: (entry.sort_time, entry.entry_id or 0),
        )
        return serving + self._apply_skip_order(waiting)

    @staticmethod
    def _apply_skip_order(entries: list[QueueEntry]) -> list[QueueEntry]:
        persisted_entries = [entry for entry in entries if entry.entry_id is not None]
        if len(persisted_entries) != len(entries):
            return entries
        by_id = {
            entry.entry_id: entry
            for entry in persisted_entries
            if entry.entry_id is not None
        }
        rank = {
            entry.entry_id: index
            for index, entry in enumerate(persisted_entries)
            if entry.entry_id is not None
        }
        successors: dict[int, list[int]] = {entry_id: [] for entry_id in by_id}
        indegree = {entry_id: 0 for entry_id in by_id}
        for entry in persisted_entries:
            target_id = entry.skip_after_entry_id
            if (
                entry.entry_id is not None
                and entry.skip_count > 0
                and target_id in by_id
                and target_id != entry.entry_id
            ):
                successors[target_id].append(entry.entry_id)
                indegree[entry.entry_id] += 1
        ready = sorted(
            (entry_id for entry_id, count in indegree.items() if count == 0),
            key=rank.__getitem__,
        )
        ordered: list[QueueEntry] = []
        while ready:
            entry_id = ready.pop(0)
            ordered.append(by_id[entry_id])
            for successor_id in successors[entry_id]:
                indegree[successor_id] -= 1
                if indegree[successor_id] == 0:
                    ready.append(successor_id)
                    ready.sort(key=rank.__getitem__)
        if len(ordered) != len(entries):
            ordered.extend(
                by_id[entry_id]
                for entry_id in sorted(
                    (key for key, count in indegree.items() if count),
                    key=rank.__getitem__,
                )
            )
        return ordered

    def _clear_skips_after(self, target: QueueEntry) -> None:
        if target.entry_id is None:
            return
        for entry in self._database.get_queue_entries(target.queue_date):
            if entry.skip_after_entry_id == target.entry_id:
                entry.update_skip(0, None)
                self._database.update_queue_entry(entry)

    def _get_today_entry(self, entry_id: int) -> QueueEntry:
        entry = self._database.get_queue_entry(entry_id)
        if entry is None or entry.queue_date != date.today():
            raise KeyError(f"No queue entry found with ID {entry_id} for today's queue")
        return entry

    @staticmethod
    def _as_datetime(value: datetime | str) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
