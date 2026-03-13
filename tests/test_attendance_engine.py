from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from attendance_system.config import AppConfig, DatabaseConfig, RemoteSyncConfig
from attendance_system.models import AttendanceSession, DevicePresence, Employee
from attendance_system.services.attendance_engine import AttendanceEngine
from attendance_system.services.remote_sync import (
    build_entry_payload,
    build_exit_payload,
)


class FakePresenceSource:
    source_name = "fake_source"

    def __init__(self, devices: list[DevicePresence] | None = None) -> None:
        self.devices = devices or []

    def scan(self) -> list[DevicePresence]:
        return list(self.devices)


@dataclass
class LoggedEvent:
    employee_id: int | None
    mac_address: str
    event_type: str


class InMemoryStore:
    def __init__(self) -> None:
        self.employees: dict[str, Employee] = {}
        self.open_sessions: dict[str, AttendanceSession] = {}
        self.events: list[LoggedEvent] = []
        self.next_session_id = 1

    def list_open_sessions(self) -> list[AttendanceSession]:
        return list(self.open_sessions.values())

    def get_active_employees_by_macs(
        self, mac_addresses: Iterable[str]
    ) -> dict[str, Employee]:
        return {
            mac: employee
            for mac in mac_addresses
            if (employee := self.employees.get(mac)) is not None and employee.active
        }

    def get_employee_by_id(self, employee_id: int) -> Employee | None:
        for employee in self.employees.values():
            if employee.id == employee_id:
                return employee
        return None

    def create_session(
        self,
        employee: Employee,
        device: DevicePresence,
        entry_time: datetime,
    ) -> AttendanceSession:
        session = AttendanceSession(
            id=self.next_session_id,
            employee_id=employee.id,
            mac_address=device.mac_address,
            ip_address=device.ip_address,
            hostname=device.hostname,
            entry_time=entry_time,
            last_seen=entry_time,
            exit_time=None,
            status="open",
            created_at=entry_time,
            updated_at=entry_time,
        )
        self.next_session_id += 1
        self.open_sessions[device.mac_address] = session
        return session

    def touch_session(
        self,
        session_id: int,
        seen_at: datetime,
        ip_address: str | None,
        hostname: str | None,
    ) -> None:
        for mac, session in list(self.open_sessions.items()):
            if session.id == session_id:
                session.last_seen = seen_at
                session.ip_address = ip_address
                session.hostname = hostname
                self.open_sessions[mac] = session
                return

    def close_session(self, session_id: int, exit_time: datetime) -> None:
        for session in self.open_sessions.values():
            if session.id == session_id:
                session.status = "closed"
                session.exit_time = exit_time
        for mac in [
            mac
            for mac, session in self.open_sessions.items()
            if session.id == session_id
        ]:
            self.open_sessions.pop(mac, None)

    def close_stale_open_sessions(self, before: datetime, exit_time: datetime) -> int:
        closed = 0
        for mac, session in list(self.open_sessions.items()):
            if session.last_seen < before:
                session.status = "closed"
                session.exit_time = exit_time
                self.open_sessions.pop(mac, None)
                closed += 1
        return closed

    def log_raw_event(
        self,
        employee_id: int | None,
        mac_address: str,
        ip_address: str | None,
        hostname: str | None,
        event_type: str,
        event_time: datetime,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.events.append(
            LoggedEvent(
                employee_id=employee_id,
                mac_address=mac_address,
                event_type=event_type,
            )
        )


class FakeRemoteSyncClient:
    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.raise_on_send = raise_on_send
        self.opened: list[int] = []
        self.closed: list[tuple[int, datetime]] = []

    def send_session_opened(self, session: AttendanceSession) -> None:
        if self.raise_on_send:
            raise RuntimeError("remote sync failed")
        self.opened.append(session.id)

    def send_session_closed(
        self,
        session: AttendanceSession,
        *,
        closed_at: datetime,
    ) -> None:
        if self.raise_on_send:
            raise RuntimeError("remote sync failed")
        self.closed.append((session.id, closed_at))


def make_config(*, remote_sync_enabled: bool = True) -> AppConfig:
    return AppConfig(
        database=DatabaseConfig(
            host="127.0.0.1",
            port=3306,
            user="test",
            password="secret",
            name="attendance_system",
        ),
        presence_source="lease_file",
        lease_file_path=None,  # type: ignore[arg-type]
        poll_interval_seconds=15,
        exit_grace_period_seconds=120,
        log_level="INFO",
        timezone_name="America/Toronto",
        log_unknown_devices=True,
        remote_sync=RemoteSyncConfig(
            enabled=remote_sync_enabled,
            base_url="https://telegram-manager.example.com",
            ingest_token="secret-token",
            timeout_seconds=10,
        ),
    )


def make_employee() -> Employee:
    return Employee(
        id=1,
        name="John Doe",
        telegram_id="123456789",
        mac_address="aa:bb:cc:dd:ee:ff",
        active=True,
        created_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
    )


def make_device() -> DevicePresence:
    return DevicePresence(
        mac_address="aa:bb:cc:dd:ee:ff",
        ip_address="192.168.50.20",
        hostname="john-iphone",
        source="fake_source",
    )


def test_registered_device_opens_session_and_logs_entry() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    remote_sync = FakeRemoteSyncClient()
    engine = AttendanceEngine(
        config=make_config(),
        presence_source=source,
        store=store,
        remote_sync=remote_sync,
    )

    engine.run_cycle(datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc))

    assert len(store.open_sessions) == 1
    assert [event.event_type for event in store.events] == ["seen", "entry"]
    assert remote_sync.opened == [1]


def test_grace_period_prevents_early_exit() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    engine = AttendanceEngine(config=make_config(), presence_source=source, store=store)
    start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    engine.run_cycle(start)
    source.devices = []
    engine.run_cycle(start + timedelta(seconds=30))

    assert len(store.open_sessions) == 1
    assert "pending_exit" in [event.event_type for event in store.events]


def test_device_reappearing_before_grace_keeps_session_open() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    engine = AttendanceEngine(config=make_config(), presence_source=source, store=store)
    start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    engine.run_cycle(start)
    source.devices = []
    engine.run_cycle(start + timedelta(seconds=30))
    source.devices = [make_device()]
    engine.run_cycle(start + timedelta(seconds=90))

    assert len(store.open_sessions) == 1
    assert all(event.event_type != "exit" for event in store.events)


def test_device_absent_past_grace_closes_session() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    remote_sync = FakeRemoteSyncClient()
    engine = AttendanceEngine(
        config=make_config(),
        presence_source=source,
        store=store,
        remote_sync=remote_sync,
    )
    start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    engine.run_cycle(start)
    source.devices = []
    engine.run_cycle(start + timedelta(seconds=10))
    engine.run_cycle(start + timedelta(seconds=130))

    assert len(store.open_sessions) == 0
    assert store.events[-1].event_type == "exit"
    assert remote_sync.closed[0][0] == 1


def test_entry_payload_uses_entry_time_and_stable_source_event_id() -> None:
    employee = make_employee()
    entry_time = datetime(2026, 3, 10, 13, 5, 12, tzinfo=timezone.utc)
    session = AttendanceSession(
        id=481,
        employee_id=employee.id,
        mac_address=employee.mac_address,
        ip_address="192.168.50.20",
        hostname="john-iphone",
        entry_time=entry_time,
        last_seen=entry_time,
        exit_time=None,
        status="open",
        created_at=entry_time,
        updated_at=entry_time,
    )

    payload = build_entry_payload(session)

    assert payload["sourceEventId"] == "session-481-entry"
    assert payload["eventType"] == "in"
    assert payload["occurredAt"] == "2026-03-10T13:05:12.000Z"
    assert "telegramUserId" not in payload


def test_exit_payload_uses_last_seen_not_close_time() -> None:
    employee = make_employee()
    entry_time = datetime(2026, 3, 10, 13, 5, 12, tzinfo=timezone.utc)
    last_seen = datetime(2026, 3, 10, 18, 10, 0, tzinfo=timezone.utc)
    closed_at = datetime(2026, 3, 10, 18, 12, 0, tzinfo=timezone.utc)
    session = AttendanceSession(
        id=481,
        employee_id=employee.id,
        mac_address=employee.mac_address,
        ip_address="192.168.50.20",
        hostname="john-iphone",
        entry_time=entry_time,
        last_seen=last_seen,
        exit_time=closed_at,
        status="closed",
        created_at=entry_time,
        updated_at=closed_at,
    )

    payload = build_exit_payload(session, closed_at=closed_at)

    assert payload["sourceEventId"] == "session-481-exit"
    assert payload["eventType"] == "out"
    assert payload["occurredAt"] == "2026-03-10T18:10:00.000Z"
    assert payload["metadata"]["closedAt"] == "2026-03-10T18:12:00.000Z"
    assert "telegramUserId" not in payload


def test_unknown_device_is_logged_without_session() -> None:
    store = InMemoryStore()
    source = FakePresenceSource(
        [
            DevicePresence(
                mac_address="11:22:33:44:55:66",
                ip_address="192.168.50.21",
                hostname="visitor",
                source="fake_source",
            )
        ]
    )
    engine = AttendanceEngine(config=make_config(), presence_source=source, store=store)

    engine.run_cycle(datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc))

    assert len(store.open_sessions) == 0
    assert store.events[0].event_type == "unknown_device"


def test_repeated_poll_is_idempotent_for_open_sessions() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    engine = AttendanceEngine(config=make_config(), presence_source=source, store=store)
    start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    engine.run_cycle(start)
    engine.run_cycle(start + timedelta(seconds=10))
    engine.run_cycle(start + timedelta(seconds=20))

    assert len(store.open_sessions) == 1
    entry_events = [event for event in store.events if event.event_type == "entry"]
    assert len(entry_events) == 1


def test_remote_sync_fires_regardless_of_telegram_id() -> None:
    """Server resolves staff from MAC — telegram_id on the local record is irrelevant."""
    store = InMemoryStore()
    employee = replace(make_employee(), telegram_id="")
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    remote_sync = FakeRemoteSyncClient()
    engine = AttendanceEngine(
        config=make_config(),
        presence_source=source,
        store=store,
        remote_sync=remote_sync,
    )

    engine.run_cycle(datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc))

    assert remote_sync.opened == [1]


def test_remote_sync_failure_does_not_stop_polling_cycle() -> None:
    store = InMemoryStore()
    employee = make_employee()
    store.employees[employee.mac_address] = employee
    source = FakePresenceSource([make_device()])
    remote_sync = FakeRemoteSyncClient(raise_on_send=True)
    engine = AttendanceEngine(
        config=make_config(),
        presence_source=source,
        store=store,
        remote_sync=remote_sync,
    )

    engine.run_cycle(datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc))

    assert len(store.open_sessions) == 1
