from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib import error, request

from attendance_system.config import RemoteSyncConfig
from attendance_system.models import AttendanceSession
from attendance_system.utils.time import format_utc_timestamp

logger = logging.getLogger(__name__)

# Retry configuration for transient errors (connection errors, 5xx).
_MAX_ATTEMPTS = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 60.0


def build_entry_payload(session: AttendanceSession) -> dict[str, Any]:
    return {
        "sourceEventId": f"session-{session.id}-entry",
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


def build_exit_payload(
    session: AttendanceSession,
    *,
    closed_at: datetime,
) -> dict[str, Any]:
    return {
        "sourceEventId": f"session-{session.id}-exit",
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


class RemoteAttendanceSyncClient:
    """Best-effort HTTP client for the remote attendance-system ingest endpoint.

    * Forwards ALL session open/close events regardless of MAC address — the
      remote server is responsible for deciding what to do with each device.
    * Retries transient errors (network / 5xx) with exponential backoff.
    """

    def __init__(
        self,
        config: RemoteSyncConfig,
    ) -> None:
        self.config = config
        self._endpoint = (
            f"{self.config.base_url.rstrip('/')}/api/integrations/attendance-system/events"
            if self.config.base_url
            else ""
        )

    # ------------------------------------------------------------------
    # Protocol-facing methods (called by AttendanceEngine)
    # ------------------------------------------------------------------

    def send_session_opened(self, session: AttendanceSession) -> None:
        self.send_event(build_entry_payload(session))

    def send_session_closed(
        self,
        session: AttendanceSession,
        *,
        closed_at: datetime,
    ) -> None:
        self.send_event(build_exit_payload(session, closed_at=closed_at))

    # ------------------------------------------------------------------
    # Core send (with retry + logging)
    # ------------------------------------------------------------------

    def send_event(self, payload: dict[str, Any]) -> None:
        if not self.config.enabled:
            return

        source_event_id = payload.get("sourceEventId", "?")
        mac = payload.get("macAddress", "?")
        backoff = _INITIAL_BACKOFF_SECONDS

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                result = self._post(payload)
                self._log_response(result, source_event_id=source_event_id, mac=mac)
                return
            except error.HTTPError as exc:
                if exc.code == 404:
                    logger.warning(
                        "Server returned 404 for event push — endpoint may be misconfigured.",
                        extra={"source_event_id": source_event_id, "mac_address": mac},
                    )
                    return  # do not retry 404s
                if exc.code >= 500:
                    logger.warning(
                        "Server error on event push (attempt %d/%d): HTTP %d",
                        attempt,
                        _MAX_ATTEMPTS,
                        exc.code,
                        extra={"source_event_id": source_event_id},
                    )
                else:
                    # 4xx other than 404 — non-retriable
                    logger.error(
                        "Non-retriable HTTP error on event push: %d",
                        exc.code,
                        extra={"source_event_id": source_event_id},
                    )
                    return
            except Exception:
                logger.warning(
                    "Transient error on event push (attempt %d/%d).",
                    attempt,
                    _MAX_ATTEMPTS,
                    exc_info=True,
                    extra={"source_event_id": source_event_id},
                )

            if attempt < _MAX_ATTEMPTS:
                time.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

        logger.error(
            "Giving up on event push after %d attempts.",
            _MAX_ATTEMPTS,
            extra={"source_event_id": source_event_id, "mac_address": mac},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.ingest_token}",
                "Content-Type": "application/json",
                "User-Agent": "attendance-system/0.1.0",
            },
        )
        with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _log_response(
        self,
        result: dict[str, Any],
        *,
        source_event_id: str,
        mac: str,
    ) -> None:
        if result.get("inserted"):
            outcome = "accepted"
        elif result.get("skipped"):
            outcome = "skipped (server: already clocked in/out)"
        elif result.get("ok") and not result.get("inserted"):
            outcome = "duplicate (sourceEventId already exists)"
        else:
            outcome = f"unexpected response: {result}"

        logger.info(
            "Remote event push: %s.",
            outcome,
            extra={"source_event_id": source_event_id, "mac_address": mac},
        )

