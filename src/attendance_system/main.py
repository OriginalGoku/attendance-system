from __future__ import annotations

import argparse
import logging
from datetime import timedelta

from attendance_system.config import AppConfig, ConfigError
from attendance_system.logging_config import configure_logging
from attendance_system.presence.lease_file import (
    LeaseFilePresenceSource,
    parse_lease_file,
)
from attendance_system.services.attendance_engine import AttendanceEngine
from attendance_system.utils.mac import normalize_mac_address
from attendance_system.utils.time import now_utc

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wi-Fi attendance monitoring service.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-config", help="Validate environment configuration.")
    subparsers.add_parser("run", help="Run the attendance polling loop.")
    subparsers.add_parser("run-once", help="Run a single polling cycle.")
    subparsers.add_parser(
        "parse-leases", help="Print detected devices from the lease file."
    )

    seed_employee = subparsers.add_parser(
        "seed-employee", help="Create one employee record."
    )
    seed_employee.add_argument("--name", required=True)
    seed_employee.add_argument("--telegram-id", required=True)
    seed_employee.add_argument("--mac-address", required=True)
    seed_employee.add_argument("--inactive", action="store_true")

    close_stale = subparsers.add_parser(
        "close-stale-sessions", help="Close open sessions older than a threshold."
    )
    close_stale.add_argument("--minutes", type=int, required=True)

    return parser


def build_presence_source(config: AppConfig) -> LeaseFilePresenceSource:
    return LeaseFilePresenceSource(config.lease_file_path)


def build_store(config: AppConfig) -> MysqlAttendanceStore:
    from attendance_system.db.connection import DatabaseConnectionFactory
    from attendance_system.db.repositories import MysqlAttendanceStore

    return MysqlAttendanceStore(DatabaseConnectionFactory(config.database))


def build_remote_sync_client(config: AppConfig, whitelist=None):
    from attendance_system.services.remote_sync import RemoteAttendanceSyncClient

    return RemoteAttendanceSyncClient(config.remote_sync, whitelist=whitelist)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = AppConfig.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    configure_logging(config.log_level)
    logger.info("Configuration loaded.", extra={"config": config.sanitized()})

    if args.command == "validate-config":
        logger.info("Configuration is valid.")
        return 0

    if args.command == "parse-leases":
        records = parse_lease_file(config.lease_file_path)
        for record in records:
            print(
                f"{record.mac_address}\t{record.ip_address}\t{record.hostname or '-'}\t{record.expiry_epoch}"
            )
        return 0

    store = build_store(config)

    if args.command == "seed-employee":
        employee_id = store.create_employee(
            name=args.name,
            telegram_id=args.telegram_id,
            mac_address=normalize_mac_address(args.mac_address),
            active=not args.inactive,
        )
        print(f"Created employee with id={employee_id}")
        return 0

    if args.command == "close-stale-sessions":
        cutoff = now_utc() - timedelta(minutes=args.minutes)
        closed = store.close_stale_open_sessions(before=cutoff, exit_time=now_utc())
        print(f"Closed {closed} stale open session(s).")
        return 0

    whitelist_sync = None
    discovery_broadcast = None
    if config.remote_sync.enabled:
        from attendance_system.services.whitelist_sync import WhitelistSyncService
        from attendance_system.services.discovery_broadcast import DiscoveryBroadcastService

        whitelist_sync = WhitelistSyncService(config.remote_sync, store)
        whitelist_sync.start()

        discovery_broadcast = DiscoveryBroadcastService(config.remote_sync)
        discovery_broadcast.start()

    engine = AttendanceEngine(
        config=config,
        presence_source=build_presence_source(config),
        store=store,
        remote_sync=build_remote_sync_client(config, whitelist=whitelist_sync),
        discovery_broadcast=discovery_broadcast,
    )

    if args.command == "run-once":
        engine.run_cycle()
        return 0

    if args.command == "run":
        engine.run_forever()
        return 0

    parser.error("Unhandled command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
