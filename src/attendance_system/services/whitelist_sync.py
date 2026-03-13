from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING
from urllib import error, request

if TYPE_CHECKING:
    from attendance_system.config import RemoteSyncConfig
    from attendance_system.db.repositories import MysqlAttendanceStore

logger = logging.getLogger(__name__)

_SYNC_INTERVAL_SECONDS = 600  # 10 minutes


class WhitelistSyncService:
    """Keeps an in-memory set of registered MACs in sync with the server.

    On each successful sync it also upserts the employee records into the local
    database so that the attendance engine can create sessions (which require an
    employee FK) without any schema changes.
    """

    def __init__(
        self,
        config: RemoteSyncConfig,
        store: MysqlAttendanceStore,
        sync_interval: int = _SYNC_INTERVAL_SECONDS,
    ) -> None:
        self._config = config
        self._store = store
        self._sync_interval = sync_interval
        self._whitelist: frozenset[str] = frozenset()
        self._lock = threading.RLock()
        self._wakeup = threading.Event()
        self._endpoint = (
            f"{config.base_url.rstrip('/')}/api/integrations/attendance-system/mac-addresses"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Attempt an initial sync, then launch the background refresh thread."""
        self._do_sync()
        thread = threading.Thread(target=self._sync_loop, name="whitelist-sync", daemon=True)
        thread.start()

    def get_whitelist(self) -> frozenset[str]:
        with self._lock:
            return self._whitelist

    def trigger_immediate_sync(self) -> None:
        """Signal the background thread to sync right now (used after a 404)."""
        self._wakeup.set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sync_loop(self) -> None:
        while True:
            self._wakeup.wait(timeout=self._sync_interval)
            self._wakeup.clear()
            self._do_sync()

    def _do_sync(self) -> None:
        if not self._config.enabled:
            return
        try:
            entries = self._fetch_whitelist()
        except Exception:
            logger.warning(
                "Whitelist sync failed — keeping last known list.",
                exc_info=True,
            )
            return

        macs = frozenset(e["macAddress"].lower() for e in entries)
        with self._lock:
            self._whitelist = macs

        try:
            self._store.sync_employees_from_whitelist(entries)
        except Exception:
            logger.warning("Failed to upsert whitelist employees into local DB.", exc_info=True)

        logger.info("Whitelist synced.", extra={"mac_count": len(macs)})

    def _fetch_whitelist(self) -> list[dict]:
        req = request.Request(
            self._endpoint,
            method="GET",
            headers={
                "Authorization": f"Bearer {self._config.ingest_token}",
                "User-Agent": "attendance-system/0.1.0",
            },
        )
        with request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        if not body.get("ok"):
            raise RuntimeError(f"Server returned ok=false: {body}")

        return body.get("data", [])
