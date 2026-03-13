from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING
from urllib import error, request

from attendance_system.models import DevicePresence
from attendance_system.utils.time import format_utc_timestamp, now_utc

if TYPE_CHECKING:
    from attendance_system.config import RemoteSyncConfig

logger = logging.getLogger(__name__)

_BROADCAST_INTERVAL_SECONDS = 60


class DiscoveryBroadcastService:
    """Posts the full list of currently-visible devices to the server every minute.

    The server uses this feed to surface unknown devices in the admin dashboard
    so admins can assign MACs to staff without touching the Pi.  This is
    fire-and-forget: failures are logged at WARNING and never block detection.
    """

    def __init__(
        self,
        config: RemoteSyncConfig,
        interval: int = _BROADCAST_INTERVAL_SECONDS,
    ) -> None:
        self._config = config
        self._interval = interval
        self._latest_devices: list[DevicePresence] = []
        self._lock = threading.Lock()
        self._endpoint = (
            f"{config.base_url.rstrip('/')}/api/integrations/attendance-system/seen-macs"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        thread = threading.Thread(
            target=self._broadcast_loop, name="discovery-broadcast", daemon=True
        )
        thread.start()

    def update_scan_result(self, devices: list[DevicePresence]) -> None:
        """Called by the engine after each scan to keep our snapshot current."""
        with self._lock:
            self._latest_devices = list(devices)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _broadcast_loop(self) -> None:
        while True:
            time.sleep(self._interval)
            with self._lock:
                devices = list(self._latest_devices)
            self._do_broadcast(devices)

    def _do_broadcast(self, devices: list[DevicePresence]) -> None:
        if not self._config.enabled:
            return

        scanned_at = format_utc_timestamp(now_utc())
        device_list: list[dict] = []
        for d in devices:
            entry: dict = {"macAddress": d.mac_address}
            if d.hostname:
                entry["hostname"] = d.hostname
            if d.ip_address:
                entry["ipAddress"] = d.ip_address
            entry["lastSeenAt"] = scanned_at
            device_list.append(entry)

        payload = {"scannedAt": scanned_at, "devices": device_list}
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.ingest_token}",
                "Content-Type": "application/json",
                "User-Agent": "attendance-system/0.1.0",
            },
        )
        try:
            with request.urlopen(req, timeout=self._config.timeout_seconds) as _resp:
                pass
        except Exception:
            logger.warning(
                "Discovery broadcast failed.",
                exc_info=True,
                extra={"device_count": len(device_list)},
            )
