from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SessionStatus = Literal["open", "closed"]


@dataclass(slots=True, frozen=True)
class Employee:
    id: int
    name: str
    telegram_id: str
    mac_address: str
    active: bool
    created_at: datetime


@dataclass(slots=True)
class AttendanceSession:
    id: int
    employee_id: int
    mac_address: str
    ip_address: str | None
    hostname: str | None
    entry_time: datetime
    last_seen: datetime
    exit_time: datetime | None
    status: SessionStatus
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class RawPresenceEvent:
    id: int | None
    employee_id: int | None
    mac_address: str
    ip_address: str | None
    hostname: str | None
    event_type: str
    event_time: datetime
    metadata: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class DevicePresence:
    mac_address: str
    ip_address: str | None
    hostname: str | None
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
