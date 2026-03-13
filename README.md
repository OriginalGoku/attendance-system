# Attendance System

`attendance-system` is a local-first Python service that infers staff attendance from devices connected to a dedicated Wi-Fi hotspot named `Site-Staff`.

The production environment is a Raspberry Pi running Raspberry Pi OS Bookworm where:

- `wlan0` hosts the `Site-Staff` hotspot
- `eth0` provides internet uplink
- staff phones join the hotspot
- device presence is translated into attendance sessions

## How Attendance Is Inferred

Each employee is identified by:

- employee name
- Telegram ID
- registered device MAC address

Attendance logic:

1. A registered device appears in the hotspot presence source.
2. The system opens an attendance session and logs raw audit events.
3. Repeated polls while the device remains connected only update `last_seen`.
4. If the device disappears, the system starts a grace-period timer.
5. If the device returns before the grace period expires, the session stays open.
6. If the device is still absent after the grace period, the system closes the session.

Unknown devices are logged to the raw event table but do not open attendance sessions.

## Important Device Requirement

This design assumes MAC addresses remain stable.

Employees must disable private/random MAC addressing for the `Site-Staff` SSID on their phones. If they do not, the attendance system cannot reliably map the phone to the employee registry.

## Project Structure

```text
attendance-system/
├── .env.example
├── .gitignore
├── README.md
├── deploy/
│   └── systemd/
│       ├── attendance-system.env.example
│       └── attendance-system.service
├── fixtures/
│   ├── sample_leases_empty.txt
│   ├── sample_leases_multiple_devices.txt
│   └── sample_leases_one_device.txt
├── pyproject.toml
├── scripts/
│   ├── install_systemd_service.sh
│   └── simulate_lease_changes.py
├── sql/
│   ├── schema.sql
│   └── seed_example.sql
├── src/
│   └── attendance_system/
│       ├── __init__.py
│       ├── config.py
│       ├── logging_config.py
│       ├── main.py
│       ├── models.py
│       ├── types.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── connection.py
│       │   └── repositories.py
│       ├── presence/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── lease_file.py
│       ├── services/
│       │   ├── attendance_engine.py
│       │   └── remote_sync.py
│       └── utils/
│           ├── __init__.py
│           ├── mac.py
│           └── time.py
└── tests/
    ├── test_attendance_engine.py
    ├── test_lease_parser.py
    └── test_mac_utils.py
```

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and update:

- `ATTENDANCE_DB_HOST`
- `ATTENDANCE_DB_PORT`
- `ATTENDANCE_DB_USER`
- `ATTENDANCE_DB_PASSWORD`
- `ATTENDANCE_DB_NAME`
- `ATTENDANCE_LEASE_FILE_PATH`
- `ATTENDANCE_POLL_INTERVAL_SECONDS`
- `ATTENDANCE_EXIT_GRACE_PERIOD_SECONDS`
- `ATTENDANCE_LOG_LEVEL`
- `ATTENDANCE_TIMEZONE`
- `ATTENDANCE_REMOTE_SYNC_ENABLED`
- `ATTENDANCE_REMOTE_BASE_URL`
- `ATTENDANCE_REMOTE_INGEST_TOKEN`
- `ATTENDANCE_REMOTE_TIMEOUT_SECONDS`

The default timezone is `America/Toronto`.

## Remote Sync To `telegram_manager`

The Pi remains responsible for local attendance detection and local MySQL persistence.
An optional one-way sync can forward session boundary events to the remote `telegram_manager` app.

Remote sync behavior:

- session open sends `eventType: "in"`
- session close sends `eventType: "out"`
- entry idempotency key: `session-{session_id}-entry`
- exit idempotency key: `session-{session_id}-exit`
- exit `occurredAt` uses the session `last_seen` timestamp, not the grace-period close timestamp

Remote sync configuration:

```env
ATTENDANCE_REMOTE_SYNC_ENABLED=true
ATTENDANCE_REMOTE_BASE_URL=https://your-telegram-manager.example.com
ATTENDANCE_REMOTE_INGEST_TOKEN=your-app-level-bearer-token
ATTENDANCE_REMOTE_TIMEOUT_SECONDS=10
```

Remote request contract:

- method: `POST`
- URL: `https://<telegram-manager-base-url>/api/integrations/attendance-system/events`
- header: `Authorization: Bearer <ATTENDANCE_SYSTEM_INGEST_SECRET>`

If remote sync fails:

- local MySQL attendance behavior still succeeds
- the polling cycle continues
- a structured error is logged

If an employee has no `telegram_id`, remote sync is skipped and a warning is logged.

## MySQL / MariaDB Setup

This project uses MariaDB on Raspberry Pi OS Bookworm (compatible with MySQL).

### 1. Create the database and user

```sql
CREATE DATABASE attendance_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'attendance_user'@'localhost' IDENTIFIED BY 'change_me';
GRANT ALL PRIVILEGES ON attendance_system.* TO 'attendance_user'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Apply schema

```bash
mysql -u attendance_user -p attendance_system < sql/schema.sql
```

### 3. Optional seed data

```bash
mysql -u attendance_user -p attendance_system < sql/seed_example.sql
```

## CLI Reference

### Validate configuration

```bash
attendance-system validate-config
```

### Parse the configured lease file

```bash
attendance-system parse-leases
```

### Run one polling cycle

```bash
attendance-system run-once
```

### Run continuously

```bash
attendance-system run
```

### Seed an employee from the CLI

```bash
attendance-system seed-employee \
  --name "John Doe" \
  --telegram-id "123456789" \
  --mac-address "aa:bb:cc:dd:ee:ff"
```

### Close stale sessions manually

```bash
attendance-system close-stale-sessions --minutes 240
```

## Local Simulation

The presence source reads a dnsmasq-format lease file with lines in this format:

```text
<expiry_epoch> <mac> <ip> <hostname> <client_id>
```

Example:

```text
4102444800 aa:bb:cc:dd:ee:ff 192.168.50.20 john-iphone *
```

Fixture files are included in `fixtures/`.

You can also simulate a changing lease file with:

```bash
python scripts/simulate_lease_changes.py \
  --output /tmp/site-staff.leases \
  --loop
```

Then point `ATTENDANCE_LEASE_FILE_PATH` at `/tmp/site-staff.leases`.

## Running Tests

```bash
pytest
```

The tests cover:

- lease-file parsing
- MAC normalization
- attendance session opening
- grace-period exit handling
- unknown device handling
- idempotent repeated polling behavior

## Logging

Application logs are structured JSON lines written to stdout.

The service logs:

- startup configuration summary without secrets
- database connection failures
- lease parsing issues
- session opens and closes
- unknown devices
- polling loop errors

## Raspberry Pi Deployment

### Hotspot configuration

The hotspot is managed by NetworkManager. The `site-ap` connection profile runs
`wlan0` as an access point in `ipv4.method: shared` mode, which causes NetworkManager
to spawn an internal dnsmasq instance for DHCP on the `192.168.50.0/24` range.

Key facts about the hotspot setup:

- SSID: `Site-Staff`
- Interface: `wlan0`
- Gateway / Pi IP: `192.168.50.1`
- DHCP range: `192.168.50.10 – 192.168.50.254`
- Lease time: 3600 seconds

### Lease file

NetworkManager writes DHCP leases for hotspot clients to:

```
/var/lib/NetworkManager/dnsmasq-wlan0.leases
```

This is the authoritative presence source. Do **not** use `/var/lib/misc/dnsmasq.leases`;
the standalone `dnsmasq` service conflicts with NetworkManager's internal instance and
fails to start, so that file is stale.

> **Note:** The `/var/lib/NetworkManager/` directory is owned by root with mode `700`.
> Even though the lease file itself is world-readable, non-root processes cannot traverse
> the directory without an explicit ACL. See the ACL step below.

### Full deployment procedure

#### 1. Clone the repository

```bash
sudo mkdir -p /opt/attendance-system
sudo chown $USER:$USER /opt/attendance-system
git clone <repo-url> /opt/attendance-system
cd /opt/attendance-system
```

#### 2. Create the virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

#### 3. Apply the database schema

```bash
mysql -u attendance_user -pchange_me -h 127.0.0.1 attendance_system < sql/schema.sql
```

#### 4. Create the runtime environment file

```bash
sudo mkdir -p /etc/attendance-system
sudo cp deploy/systemd/attendance-system.env.example /etc/attendance-system/attendance-system.env
sudo nano /etc/attendance-system/attendance-system.env
```

Set at minimum:

```ini
ATTENDANCE_LEASE_FILE_PATH=/var/lib/NetworkManager/dnsmasq-wlan0.leases
ATTENDANCE_DB_PASSWORD=<your-password>
```

#### 5. Grant lease-file access to the service user

The service runs as a non-root user. Grant it execute (traverse) access to the
NetworkManager directory so it can read the world-readable lease file:

```bash
sudo setfacl -m u:<service-user>:x /var/lib/NetworkManager/
```

To make this survive reboots, install the provided helper unit:

```bash
sudo cp /etc/systemd/system/nm-lease-acl.service /etc/systemd/system/nm-lease-acl.service
```

Or create `/etc/systemd/system/nm-lease-acl.service` manually:

```ini
[Unit]
Description=Grant attendance service access to NetworkManager dnsmasq lease directory
After=NetworkManager.service
Before=attendance-system.service

[Service]
Type=oneshot
ExecStart=/usr/bin/setfacl -m u:<service-user>:x /var/lib/NetworkManager/
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nm-lease-acl.service
```

#### 6. Edit the service unit for your username

Open `deploy/systemd/attendance-system.service` and set `User` and `Group` to the
account that owns the project (the default placeholder is `pi`):

```ini
User=<your-username>
Group=<your-username>
```

#### 7. Install and enable the attendance service

```bash
chmod +x scripts/install_systemd_service.sh
./scripts/install_systemd_service.sh /opt/attendance-system
sudo systemctl start attendance-system.service
sudo systemctl status attendance-system.service
```

#### 8. Seed employee records

```bash
source .venv/bin/activate
attendance-system seed-employee \
  --name "Jane Smith" \
  --telegram-id "987654321" \
  --mac-address "aa:bb:cc:dd:ee:ff"
```

#### 9. Verify operation

```bash
# Check lease file is being parsed
attendance-system parse-leases

# Run one cycle manually
attendance-system run-once

# Follow live logs
journalctl -u attendance-system.service -f
```

### Service unit summary

| Setting | Value |
|---|---|
| Unit file (source) | `deploy/systemd/attendance-system.service` |
| Unit file (installed) | `/etc/systemd/system/attendance-system.service` |
| Environment file | `/etc/attendance-system/attendance-system.env` |
| Working directory | `/opt/attendance-system` |
| Executable | `/opt/attendance-system/.venv/bin/attendance-system` |
| Restart policy | `always`, 5 s back-off |

### Known constraints and risks

| Item | Detail |
|---|---|
| ACL resets on NM directory recreation | If a package upgrade recreates `/var/lib/NetworkManager/`, the ACL is lost mid-session. It is reapplied automatically on the next reboot via `nm-lease-acl.service`. |
| Lease file path is interface-bound | If `wlan0` is renamed or the NM connection is recreated, NM writes to a different filename (e.g. `dnsmasq-wlan1.leases`). Update `ATTENDANCE_LEASE_FILE_PATH` if the interface name changes. |
| Standalone dnsmasq conflict | The system package `dnsmasq.service` is enabled but fails to start because NetworkManager already owns the DHCP port. This is expected. Consider running `sudo systemctl disable dnsmasq` to suppress the noise in system logs. |
| MAC randomization | Employees must disable private/random MAC for the `Site-Staff` SSID before registering their device MAC. |

## Assumptions

- MAC addresses are the primary identity key for devices.
- MAC addresses are normalized to lowercase before any comparison or persistence.
- Attendance timestamps are stored as UTC `DATETIME(6)` values.
- The application timezone is configured as `America/Toronto` for operational use.
- A single open attendance session per device is enforced by application logic.
