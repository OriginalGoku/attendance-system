from datetime import datetime, timezone
from pathlib import Path

from attendance_system.presence.lease_file import parse_lease_file, parse_lease_lines


def test_parse_lease_lines_ignores_malformed_and_expired_entries() -> None:
    lines = [
        "4102444800 AA:BB:CC:DD:EE:FF 192.168.50.20 john-iphone *",
        "1700000000 11:22:33:44:55:66 192.168.50.21 old-device *",
        "broken line",
    ]
    records = parse_lease_lines(
        lines,
        reference_time=datetime(2026, 3, 10, tzinfo=timezone.utc),
    )

    assert len(records) == 1
    assert records[0].mac_address == "aa:bb:cc:dd:ee:ff"
    assert records[0].hostname == "john-iphone"


def test_parse_lease_file_reads_fixture(tmp_path: Path) -> None:
    lease_path = tmp_path / "dnsmasq.leases"
    lease_path.write_text(
        "4102444800 aa:bb:cc:dd:ee:ff 192.168.50.20 john-iphone *\n",
        encoding="utf-8",
    )

    records = parse_lease_file(lease_path)

    assert len(records) == 1
    assert records[0].ip_address == "192.168.50.20"
