from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from attendance_system.config import AppConfig
from attendance_system.models import AttendanceSession, DevicePresence
from attendance_system.presence.base import PresenceSource
from attendance_system.types import AttendanceStore
from attendance_system.utils.time import now_utc

logger = logging.getLogger(__name__)


class AttendanceEngine:
    """Translate device presence into attendance sessions."""

    def __init__(
        self,
        *,
        config: AppConfig,
        presence_source: PresenceSource,
        store: AttendanceStore,
    ) -> None:
        self.config = config
        self.presence_source = presence_source
        self.store = store
        self.pending_exits: dict[str, datetime] = {}

    def run_cycle(self, current_time: datetime | None = None) -> None:
        cycle_time = current_time or now_utc()
        devices = self._deduplicate_devices(self.presence_source.scan())
        open_sessions = {
            session.mac_address: session for session in self.store.list_open_sessions()
        }
        employees = self.store.get_active_employees_by_macs(devices.keys())

        for mac_address, device in devices.items():
            employee = employees.get(mac_address)
            if employee is None:
                if self.config.log_unknown_devices:
                    self.store.log_raw_event(
                        employee_id=None,
                        mac_address=mac_address,
                        ip_address=device.ip_address,
                        hostname=device.hostname,
                        event_type="unknown_device",
                        event_time=cycle_time,
                        metadata={"source": device.source},
                    )
                    logger.info(
                        "Unknown device detected.",
                        extra={
                            "mac_address": mac_address,
                            "ip_address": device.ip_address,
                            "hostname": device.hostname,
                        },
                    )
                continue

            self.store.log_raw_event(
                employee_id=employee.id,
                mac_address=mac_address,
                ip_address=device.ip_address,
                hostname=device.hostname,
                event_type="seen",
                event_time=cycle_time,
                metadata={"source": device.source},
            )

            existing_session = open_sessions.get(mac_address)
            if existing_session is None:
                session = self.store.create_session(
                    employee=employee,
                    device=device,
                    entry_time=cycle_time,
                )
                open_sessions[mac_address] = session
                self.store.log_raw_event(
                    employee_id=employee.id,
                    mac_address=mac_address,
                    ip_address=device.ip_address,
                    hostname=device.hostname,
                    event_type="entry",
                    event_time=cycle_time,
                    metadata={"session_id": session.id, "source": device.source},
                )
                logger.info(
                    "Opened attendance session.",
                    extra={
                        "employee_id": employee.id,
                        "employee_name": employee.name,
                        "session_id": session.id,
                        "mac_address": mac_address,
                    },
                )
            else:
                self.store.touch_session(
                    session_id=existing_session.id,
                    seen_at=cycle_time,
                    ip_address=device.ip_address,
                    hostname=device.hostname,
                )

            self.pending_exits.pop(mac_address, None)

        self._process_absent_devices(
            open_sessions=open_sessions,
            active_macs=set(devices.keys()),
            cycle_time=cycle_time,
        )

    def run_forever(self) -> None:
        logger.info(
            "Starting attendance polling loop.",
            extra={"poll_interval_seconds": self.config.poll_interval_seconds},
        )
        while True:
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Polling loop failed.")
            time.sleep(self.config.poll_interval_seconds)

    def _process_absent_devices(
        self,
        *,
        open_sessions: dict[str, AttendanceSession],
        active_macs: set[str],
        cycle_time: datetime,
    ) -> None:
        grace_period = timedelta(seconds=self.config.exit_grace_period_seconds)
        for mac_address, session in open_sessions.items():
            if mac_address in active_macs:
                continue

            missing_since = self.pending_exits.get(mac_address)
            if missing_since is None:
                self.pending_exits[mac_address] = cycle_time
                self.store.log_raw_event(
                    employee_id=session.employee_id,
                    mac_address=mac_address,
                    ip_address=session.ip_address,
                    hostname=session.hostname,
                    event_type="pending_exit",
                    event_time=cycle_time,
                    metadata={
                        "session_id": session.id,
                        "grace_period_seconds": self.config.exit_grace_period_seconds,
                    },
                )
                continue

            if cycle_time - missing_since >= grace_period:
                self.store.close_session(session.id, cycle_time)
                self.store.log_raw_event(
                    employee_id=session.employee_id,
                    mac_address=mac_address,
                    ip_address=session.ip_address,
                    hostname=session.hostname,
                    event_type="exit",
                    event_time=cycle_time,
                    metadata={
                        "session_id": session.id,
                        "grace_period_seconds": self.config.exit_grace_period_seconds,
                    },
                )
                self.pending_exits.pop(mac_address, None)
                logger.info(
                    "Closed attendance session.",
                    extra={
                        "employee_id": session.employee_id,
                        "session_id": session.id,
                        "mac_address": mac_address,
                    },
                )

    @staticmethod
    def _deduplicate_devices(devices: list[DevicePresence]) -> dict[str, DevicePresence]:
        deduplicated: dict[str, DevicePresence] = {}
        for device in devices:
            deduplicated[device.mac_address] = device
        return deduplicated
