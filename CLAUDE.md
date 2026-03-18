# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A local-first Python service running on a Raspberry Pi that infers staff attendance by monitoring device MAC addresses on a dedicated `Site-Staff` Wi-Fi hotspot. It reads dnsmasq DHCP lease files to detect presence and manages attendance sessions in MySQL.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env  # Edit with DB credentials and lease file path
```

## Commands

```bash
# Run tests
pytest
pytest -v
pytest tests/test_attendance_engine.py  # Single file

# CLI entry points
attendance-system validate-config       # Validate env config
attendance-system parse-leases          # Show detected devices
attendance-system run-once              # Single polling cycle
attendance-system run                   # Continuous polling loop
attendance-system seed-employee --name "Name" --telegram-id "123" --mac-address "aa:bb:cc:dd:ee:ff"
attendance-system close-stale-sessions --minutes 240

# Simulate lease file changes for local testing
python scripts/simulate_lease_changes.py --output /tmp/site-staff.leases --loop
# Then set ATTENDANCE_LEASE_FILE_PATH=/tmp/site-staff.leases in .env
```

## Architecture

```
AttendanceEngine (polling loop)
    ├── PresenceSource (LeaseFilePresenceSource) — reads dnsmasq DHCP leases
    ├── AttendanceStore (MysqlAttendanceStore) — sessions, employees, raw events
    └── RemoteAttendanceSync (RemoteAttendanceSyncClient) — optional HTTP event push
```

**Key source paths:**
- `src/attendance_system/services/attendance_engine.py` — core session logic and grace period handling
- `src/attendance_system/presence/lease_file.py` — lease file parsing (format: `<epoch> <mac> <ip> <hostname> <client_id>`)
- `src/attendance_system/db/repositories.py` — all MySQL CRUD
- `src/attendance_system/services/remote_sync.py` — HTTP sync with retry/backoff
- `src/attendance_system/services/whitelist_sync.py` — background thread syncing employee MACs from remote
- `src/attendance_system/services/discovery_broadcast.py` — background thread broadcasting visible devices
- `src/attendance_system/config.py` — env-based config with validation
- `src/attendance_system/models.py` — `Employee`, `AttendanceSession`, `DevicePresence`, `RawPresenceEvent`
- `src/attendance_system/types.py` — `AttendanceStore` and `RemoteAttendanceSync` protocols

**Session lifecycle:** Device seen → `create_session()` → device disappears → grace period timer starts → device returns (timer clears) OR grace expires → `close_session()`. All events logged to `raw_presence_events`.

## Database

Three tables: `employees`, `attendance_sessions`, `raw_presence_events`. Schema at `sql/schema.sql`.

- MAC address is the primary identity key (normalized to lowercase)
- Sessions stored with UTC `DATETIME(6)`; app timezone configurable via `ATTENDANCE_TIMEZONE`
- One open session per device enforced at application level

## Remote Sync (Optional)

Controlled by `ATTENDANCE_REMOTE_SYNC_ENABLED`. When enabled, posts `in`/`out` events to a `telegram_manager` server. Non-blocking — failures are logged but don't affect local attendance. A 404 response triggers a whitelist sync.

## Deployment (Raspberry Pi)

Runs as a systemd service. Config lives at `/etc/attendance-system/attendance-system.env`. Install with `scripts/install_systemd_service.sh`. Logs via `journalctl -u attendance-system.service`.
