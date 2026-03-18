from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from attendance_system.db.connection import DatabaseConnectionFactory
from attendance_system.models import AttendanceSession, DevicePresence, Employee
from attendance_system.types import JSONDict
from attendance_system.utils.time import assume_utc, to_utc_naive


def _employee_from_row(row: dict[str, Any]) -> Employee:
    return Employee(
        id=int(row["id"]),
        name=str(row["name"]),
        telegram_id=str(row["telegram_id"]),
        mac_address=str(row["mac_address"]),
        active=bool(row["active"]),
        created_at=assume_utc(row["created_at"]),
    )


def _session_from_row(row: dict[str, Any]) -> AttendanceSession:
    return AttendanceSession(
        id=int(row["id"]),
        employee_id=int(row["employee_id"]) if row["employee_id"] is not None else None,
        mac_address=str(row["mac_address"]),
        ip_address=row["ip_address"],
        hostname=row["hostname"],
        entry_time=assume_utc(row["entry_time"]),
        last_seen=assume_utc(row["last_seen"]),
        exit_time=assume_utc(row["exit_time"]) if row["exit_time"] else None,
        status=row["status"],
        created_at=assume_utc(row["created_at"]),
        updated_at=assume_utc(row["updated_at"]),
    )


class MysqlAttendanceStore:
    """MySQL-backed persistence for employees, sessions, and raw events."""

    def __init__(self, connection_factory: DatabaseConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def list_open_sessions(self) -> list[AttendanceSession]:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, employee_id, mac_address, ip_address, hostname,
                           entry_time, last_seen, exit_time, status, created_at, updated_at
                    FROM attendance_sessions
                    WHERE status = 'open'
                    """
                )
                rows = cursor.fetchall()
        return [_session_from_row(row) for row in rows]

    def get_active_employees_by_macs(
        self, mac_addresses: Iterable[str]
    ) -> dict[str, Employee]:
        normalized = list(dict.fromkeys(mac_addresses))
        if not normalized:
            return {}

        placeholders = ", ".join(["%s"] * len(normalized))
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, name, telegram_id, mac_address, active, created_at
                    FROM employees
                    WHERE active = 1 AND mac_address IN ({placeholders})
                    """,
                    normalized,
                )
                rows = cursor.fetchall()
        return {row["mac_address"]: _employee_from_row(row) for row in rows}

    def get_employee_by_id(self, employee_id: int) -> Employee | None:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, telegram_id, mac_address, active, created_at
                    FROM employees
                    WHERE id = %s
                    """,
                    (employee_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _employee_from_row(row)

    def create_session(
        self,
        employee: Employee | None,
        device: DevicePresence,
        entry_time: datetime,
    ) -> AttendanceSession:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO attendance_sessions (
                        employee_id, mac_address, ip_address, hostname,
                        entry_time, last_seen, exit_time, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, 'open')
                    """,
                    (
                        employee.id if employee is not None else None,
                        device.mac_address,
                        device.ip_address,
                        device.hostname,
                        to_utc_naive(entry_time),
                        to_utc_naive(entry_time),
                    ),
                )
                session_id = int(cursor.lastrowid)
                cursor.execute(
                    """
                    SELECT id, employee_id, mac_address, ip_address, hostname,
                           entry_time, last_seen, exit_time, status, created_at, updated_at
                    FROM attendance_sessions
                    WHERE id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        return _session_from_row(row)

    def touch_session(
        self,
        session_id: int,
        seen_at: datetime,
        ip_address: str | None,
        hostname: str | None,
    ) -> None:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_sessions
                    SET last_seen = %s,
                        ip_address = %s,
                        hostname = %s
                    WHERE id = %s AND status = 'open'
                    """,
                    (to_utc_naive(seen_at), ip_address, hostname, session_id),
                )

    def close_session(self, session_id: int, exit_time: datetime) -> None:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_sessions
                    SET exit_time = %s,
                        status = 'closed'
                    WHERE id = %s AND status = 'open'
                    """,
                    (to_utc_naive(exit_time), session_id),
                )

    def close_stale_open_sessions(self, before: datetime, exit_time: datetime) -> int:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_sessions
                    SET exit_time = %s,
                        status = 'closed'
                    WHERE status = 'open' AND last_seen < %s
                    """,
                    (to_utc_naive(exit_time), to_utc_naive(before)),
                )
                return cursor.rowcount

    def log_raw_event(
        self,
        employee_id: int | None,
        mac_address: str,
        ip_address: str | None,
        hostname: str | None,
        event_type: str,
        event_time: datetime,
        metadata: JSONDict | None = None,
    ) -> None:
        metadata_json = json.dumps(metadata) if metadata is not None else None
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO raw_presence_events (
                        employee_id, mac_address, ip_address, hostname,
                        event_type, event_time, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        employee_id,
                        mac_address,
                        ip_address,
                        hostname,
                        event_type,
                        to_utc_naive(event_time),
                        metadata_json,
                    ),
                )

    def sync_employees_from_whitelist(self, entries: list[dict]) -> None:
        """Upsert employees from the server whitelist and deactivate removed ones.

        ``entries`` is the ``data`` list from the GET mac-addresses response.
        Employees whose MACs are no longer in the list are marked inactive so
        the attendance engine stops tracking them.
        """
        macs = [e["macAddress"].lower() for e in entries]
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                for entry in entries:
                    mac = entry["macAddress"].lower()
                    name = entry.get("staffName", mac)
                    cursor.execute(
                        """
                        INSERT INTO employees (name, telegram_id, mac_address, active)
                        VALUES (%s, '', %s, 1)
                        ON DUPLICATE KEY UPDATE name = VALUES(name), active = 1
                        """,
                        (name, mac),
                    )
                # Deactivate employees not in the current whitelist.
                if macs:
                    placeholders = ", ".join(["%s"] * len(macs))
                    cursor.execute(
                        f"""
                        UPDATE employees SET active = 0
                        WHERE mac_address NOT IN ({placeholders})
                        """,
                        macs,
                    )
                else:
                    cursor.execute("UPDATE employees SET active = 0")

    def create_employee(
        self, *, name: str, telegram_id: str, mac_address: str, active: bool = True
    ) -> int:
        with self.connection_factory.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO employees (name, telegram_id, mac_address, active)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (name, telegram_id, mac_address, 1 if active else 0),
                )
                return int(cursor.lastrowid)
