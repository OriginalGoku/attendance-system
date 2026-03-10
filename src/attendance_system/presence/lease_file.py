from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from attendance_system.models import DevicePresence
from attendance_system.presence.base import PresenceSource
from attendance_system.utils.mac import normalize_mac_address
from attendance_system.utils.time import now_utc

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class LeaseRecord:
    expiry_epoch: int
    mac_address: str
    ip_address: str
    hostname: str | None
    client_id: str | None


def parse_lease_lines(
    lines: list[str],
    *,
    reference_time: datetime | None = None,
) -> list[LeaseRecord]:
    records: list[LeaseRecord] = []
    now = reference_time or now_utc()

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 5:
            logger.warning(
                "Ignoring malformed lease line.",
                extra={"line_number": line_number, "line": raw_line.rstrip()},
            )
            continue

        expiry_raw, mac_raw, ip_address, hostname, client_id = parts[:5]
        try:
            expiry_epoch = int(expiry_raw)
            mac_address = normalize_mac_address(mac_raw)
        except (ValueError, TypeError):
            logger.warning(
                "Ignoring malformed lease line.",
                extra={"line_number": line_number, "line": raw_line.rstrip()},
            )
            continue

        if expiry_epoch < int(now.timestamp()):
            continue

        records.append(
            LeaseRecord(
                expiry_epoch=expiry_epoch,
                mac_address=mac_address,
                ip_address=ip_address,
                hostname=None if hostname == "*" else hostname,
                client_id=None if client_id == "*" else client_id,
            )
        )

    return records


def parse_lease_file(
    lease_file_path: Path,
    *,
    reference_time: datetime | None = None,
) -> list[LeaseRecord]:
    if not lease_file_path.exists():
        raise FileNotFoundError(f"Lease file not found: {lease_file_path}")

    return parse_lease_lines(
        lease_file_path.read_text(encoding="utf-8").splitlines(),
        reference_time=reference_time,
    )


class LeaseFilePresenceSource(PresenceSource):
    source_name = "lease_file"

    def __init__(self, lease_file_path: Path) -> None:
        self.lease_file_path = lease_file_path

    def scan(self) -> list[DevicePresence]:
        records = parse_lease_file(self.lease_file_path)
        return [
            DevicePresence(
                mac_address=record.mac_address,
                ip_address=record.ip_address,
                hostname=record.hostname,
                source=self.source_name,
                metadata={"client_id": record.client_id, "expiry_epoch": record.expiry_epoch},
            )
            for record in records
        ]
