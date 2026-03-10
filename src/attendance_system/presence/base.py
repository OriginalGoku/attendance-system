from __future__ import annotations

from abc import ABC, abstractmethod

from attendance_system.models import DevicePresence


class PresenceSource(ABC):
    """Abstract interface for device-presence providers."""

    source_name: str

    @abstractmethod
    def scan(self) -> list[DevicePresence]:
        """Return the devices currently present."""
