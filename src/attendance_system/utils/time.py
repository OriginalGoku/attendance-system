from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def assume_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def format_utc_timestamp(value: datetime) -> str:
    return assume_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_timezone(value: datetime, timezone_name: str | ZoneInfo) -> datetime:
    zone = ZoneInfo(timezone_name) if isinstance(timezone_name, str) else timezone_name
    return value.astimezone(zone)
