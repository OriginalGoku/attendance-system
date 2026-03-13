from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib import error, request

from attendance_system.config import RemoteSyncConfig
from attendance_system.models import AttendanceSession
from attendance_system.utils.time import format_utc_timestamp

if TYPE_CHECKING:
    from attendance_system.services.whitelist_sync import WhitelistSyncService

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

    * Drops ``telegramUserId`` — the server resolves staff from MAC address.
    * Only pushes events for MACs present in the current server whitelist.
    * Retries transient errors (network / 5xx) with exponential backoff.
    * On HTTP 404 (MAC de-registered) logs a warning and triggers an immediate
      whitelist re-sync so the local list stays current.
    """

    def __init__(
        self,
        config: RemoteSyncConfig,
        whitelist: WhitelistSyncService | None = None,
    ) -> None:
        self.config = config
        self._whitelist = whitelist
        self._endpoint = (
            f"{self.config.base_url.rstrip('/')}/api/integrations/attendance-system/events"
            if self.config.base_url
            else ""
        )

    # ------------------------------------------------------------------
    # Protocol-facing methods (called by AttendanceEngine)
    # ------------------------------------------------------------------

    def send_session_opened(self, session: AttendanceSession) -> None:
        if not self._mac_is_whitelisted(session.mac_address):
            return
        self.send_event(build_entry_payload(session))

    def send_session_closed(
        self,
        session: AttendanceSession,
        *,
        closed_at: datetime,
    ) -> None:
        if not self._mac_is_whitelisted(session.mac_address):
            return
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
                        "MAC not registered on server — skipping event and triggering whitelist re-sync.",
                        extra={"source_event_id": source_event_id, "mac_address": mac},
                    )
                    if self._whitelist is not None:
                        self._whitelist.trigger_immediate_sync()
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

    def _mac_is_whitelisted(self, mac: str) -> bool:
        if not self.config.enabled:
            return False
        if self._whitelist is None:
            return True  # no whitelist service — allow all (e.g. testing)
        return mac.lower() in self._whitelist.get_whitelist()
