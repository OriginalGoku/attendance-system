import pytest

from attendance_system.utils.mac import normalize_mac_address


def test_normalize_mac_address_lowercases_and_normalizes_dashes() -> None:
    assert normalize_mac_address("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_address_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_mac_address("not-a-mac")
