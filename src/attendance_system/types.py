from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from attendance_system.models import AttendanceSession, DevicePresence, Employee

JSONDict = dict[str, Any]


class AttendanceStore(Protocol):
    def list_open_sessions(self) -> list[AttendanceSession]: ...

    def get_active_employees_by_macs(
        self, mac_addresses: Iterable[str]
    ) -> dict[str, Employee]: ...

    def get_employee_by_id(self, employee_id: int) -> Employee | None: ...

    def create_session(
        self,
        employee: Employee,
        device: DevicePresence,
        entry_time: datetime,
    ) -> AttendanceSession: ...

    def touch_session(
        self,
        session_id: int,
        seen_at: datetime,
        ip_address: str | None,
        hostname: str | None,
    ) -> None: ...

    def close_session(self, session_id: int, exit_time: datetime) -> None: ...

    def close_stale_open_sessions(
        self, before: datetime, exit_time: datetime
    ) -> int: ...

    def log_raw_event(
        self,
        employee_id: int | None,
        mac_address: str,
        ip_address: str | None,
        hostname: str | None,
        event_type: str,
        event_time: datetime,
        metadata: JSONDict | None = None,
    ) -> None: ...


class RemoteAttendanceSync(Protocol):
    def send_session_opened(
        self, session: AttendanceSession, employee: Employee
    ) -> None: ...

    def send_session_closed(
        self,
        session: AttendanceSession,
        employee: Employee,
        *,
        closed_at: datetime,
    ) -> None: ...
