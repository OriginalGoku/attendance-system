# Attendance System

`attendance-system` is a local-first Python service that infers staff attendance from devices connected to a dedicated Wi-Fi hotspot named `Site-Staff`.

The intended production environment is a Raspberry Pi running Raspberry Pi OS Bookworm where:

- `wlan0` hosts the `Site-Staff` hotspot
- `eth0` provides internet uplink
- staff phones join the hotspot
- device presence is translated into attendance sessions

This repository is designed to be developed on a normal laptop first. The first implementation uses a lease-file parser so the core business logic is testable without Raspberry Pi hardware.

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
attendance_raspberry_pi/
├── .env.example
├── .gitignore
├── README.md
├── fixtures/
│   ├── sample_leases_empty.txt
│   ├── sample_leases_multiple_devices.txt
│   └── sample_leases_one_device.txt
├── pyproject.toml
├── scripts/
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
│       │   └── attendance_engine.py
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
python3.11 -m venv .venv
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

The default timezone in this scaffold is `America/Toronto`.

## MySQL Setup

This project targets native MySQL for local development.

### 1. Create the database and user

Example:

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

## Running Locally

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

The initial presence source reads a lease file with lines in this format:

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

## Deployment Direction For Raspberry Pi

This repository keeps the attendance engine decoupled from Raspberry Pi shell commands, but it now includes deployment artifacts for running the service under `systemd` on Raspberry Pi OS Bookworm.

Future production presence-source work will add implementations for:

- `iw dev wlan0 station dump`
- `ip neigh`
- NetworkManager shared hotspot lease sources
- combined multi-source reconciliation

The current abstraction layer allows those adapters to be added without changing the attendance engine.

## Raspberry Pi Deployment With systemd

The repository now includes:

- [attendance-system.service](/Users/god/vs_code/attendance_raspberry_pi/deploy/systemd/attendance-system.service)
- [attendance-system.env.example](/Users/god/vs_code/attendance_raspberry_pi/deploy/systemd/attendance-system.env.example)
- [install_systemd_service.sh](/Users/god/vs_code/attendance_raspberry_pi/scripts/install_systemd_service.sh)

Suggested Raspberry Pi deployment flow:

1. Install Python and MySQL client dependencies on Raspberry Pi OS Bookworm.
2. Clone this repository to the Raspberry Pi, for example under `/opt/attendance-system`.
3. Create the virtual environment and install the package:

```bash
cd /opt/attendance-system
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

4. Configure hotspot networking for `Site-Staff` on `wlan0`.
5. Copy and edit the production environment file:

```bash
sudo mkdir -p /etc/attendance-system
sudo cp deploy/systemd/attendance-system.env.example /etc/attendance-system/attendance-system.env
sudo nano /etc/attendance-system/attendance-system.env
```

6. Update the lease-file path or future production presence-source configuration.
7. Install and enable the service:

```bash
chmod +x scripts/install_systemd_service.sh
./scripts/install_systemd_service.sh /opt/attendance-system
sudo systemctl start attendance-system.service
sudo systemctl status attendance-system.service
```

8. Inspect runtime logs:

```bash
journalctl -u attendance-system.service -f
```

9. Integrate with the future Telegram application.

The provided unit file expects:

- application code at `/opt/attendance-system`
- virtual environment at `/opt/attendance-system/.venv`
- environment file at `/etc/attendance-system/attendance-system.env`

Adjust these paths if you deploy elsewhere.

## Assumptions

- MAC addresses are the primary identity key for devices.
- MAC addresses are normalized to lowercase before any comparison or persistence.
- Attendance timestamps are stored in MySQL as UTC `DATETIME(6)` values.
- The application timezone is configured as `America/Toronto` for operational use.
- A single open attendance session per device is enforced by application logic.
