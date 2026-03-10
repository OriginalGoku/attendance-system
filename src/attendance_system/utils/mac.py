from __future__ import annotations

import re

MAC_ADDRESS_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac_address(mac_address: str) -> str:
    """Normalize MAC addresses to lowercase colon-separated format."""

    normalized = mac_address.strip().lower().replace("-", ":")
    if not MAC_ADDRESS_RE.fullmatch(normalized):
        raise ValueError(f"Invalid MAC address: {mac_address!r}")
    return normalized
