from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from urllib import error, request

from attendance_system.config import RemoteSyncConfig
from attendance_system.models import AttendanceSession, Employee
from attendance_system.utils.time import format_utc_timestamp

logger = logging.getLogger(__name__)


def build_entry_payload(
    session: AttendanceSession,
    employee: Employee,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEventId": f"session-{session.id}-entry",
        "telegramUserId": employee.telegram_id,
        "macAddress": session.mac_address,
        "eventType": "in",
        "occurredAt": format_utc_timestamp(session.entry_time),
        "metadata": {
            "sessionId": session.id,
            "hostname": session.hostname,
            "ipAddress": session.ip_address,
            "lastSeenAt": format_utc_timestamp(session.last_seen),
        },
    }
    if note:
        payload["note"] = note
    return payload


def build_exit_payload(
    session: AttendanceSession,
    employee: Employee,
    *,
    closed_at: datetime,
    note: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEventId": f"session-{session.id}-exit",
        "telegramUserId": employee.telegram_id,
        "macAddress": session.mac_address,
        "eventType": "out",
        "occurredAt": format_utc_timestamp(session.last_seen),
        "metadata": {
            "sessionId": session.id,
            "hostname": session.hostname,
            "ipAddress": session.ip_address,
            "lastSeenAt": format_utc_timestamp(session.last_seen),
            "closedAt": format_utc_timestamp(closed_at),
        },
    }
    if note:
        payload["note"] = note
    return payload


class RemoteAttendanceSyncClient:
    """Best-effort HTTP client for the remote telegram_manager ingest endpoint."""

    def __init__(self, config: RemoteSyncConfig) -> None:
        self.config = config
        self.endpoint = (
            f"{self.config.base_url.rstrip('/')}/api/integrations/attendance-system/events"
            if self.config.base_url
            else ""
        )

    def send_session_opened(
        self, session: AttendanceSession, employee: Employee
    ) -> None:
        if not self._should_sync(employee):
            return
        self.send_event(build_entry_payload(session, employee))

    def send_session_closed(
        self,
        session: AttendanceSession,
        employee: Employee,
        *,
        closed_at: datetime,
    ) -> None:
        if not self._should_sync(employee):
            return
        self.send_event(build_exit_payload(session, employee, closed_at=closed_at))

    def send_event(self, payload: dict[str, Any]) -> None:
        if not self.config.enabled:
            return

        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.ingest_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(
                http_request, timeout=self.config.timeout_seconds
            ) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                if status_code >= 400:
                    raise error.HTTPError(
                        self.endpoint, status_code, "HTTP error", hdrs=None, fp=None
                    )
        except Exception:
            logger.exception(
                "Remote attendance sync failed.",
                extra={"source_event_id": payload.get("sourceEventId")},
            )

    def _should_sync(self, employee: Employee) -> bool:
        if not self.config.enabled:
            return False
        if not employee.telegram_id.strip():
            logger.warning(
                "Skipping remote sync because employee has no telegram_id.",
                extra={"employee_id": employee.id, "employee_name": employee.name},
            )
            return False
        return True
