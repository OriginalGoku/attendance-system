from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional in minimal environments

    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer.") from exc


@dataclass(slots=True, frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    name: str

    def sanitized(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "name": self.name,
        }


@dataclass(slots=True, frozen=True)
class RemoteSyncConfig:
    enabled: bool
    base_url: str
    ingest_token: str
    timeout_seconds: int

    def sanitized(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(slots=True, frozen=True)
class AppConfig:
    database: DatabaseConfig
    presence_source: str
    lease_file_path: Path
    poll_interval_seconds: int
    exit_grace_period_seconds: int
    log_level: str
    timezone_name: str
    log_unknown_devices: bool
    remote_sync: RemoteSyncConfig

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                f"Timezone {self.timezone_name!r} is not available on this system."
            ) from exc

    def sanitized(self) -> dict[str, object]:
        return {
            "presence_source": self.presence_source,
            "lease_file_path": str(self.lease_file_path),
            "poll_interval_seconds": self.poll_interval_seconds,
            "exit_grace_period_seconds": self.exit_grace_period_seconds,
            "log_level": self.log_level,
            "timezone_name": self.timezone_name,
            "log_unknown_devices": self.log_unknown_devices,
            "database": self.database.sanitized(),
            "remote_sync": self.remote_sync.sanitized(),
        }

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "AppConfig":
        load_dotenv(env_file, override=False)

        database = DatabaseConfig(
            host=os.getenv("ATTENDANCE_DB_HOST", "127.0.0.1"),
            port=_get_int("ATTENDANCE_DB_PORT", 3306),
            user=os.getenv("ATTENDANCE_DB_USER", "attendance_user"),
            password=os.getenv("ATTENDANCE_DB_PASSWORD", ""),
            name=os.getenv("ATTENDANCE_DB_NAME", "attendance_system"),
        )
        # SERVER_BASE_URL / ATTENDANCE_SYSTEM_INGEST_SECRET are the canonical
        # names going forward.  The older ATTENDANCE_REMOTE_* names are kept as
        # fallbacks so existing .env files continue to work without changes.
        base_url = (
            os.getenv("SERVER_BASE_URL")
            or os.getenv("ATTENDANCE_REMOTE_BASE_URL", "")
        ).strip()
        ingest_token = (
            os.getenv("ATTENDANCE_SYSTEM_INGEST_SECRET")
            or os.getenv("ATTENDANCE_REMOTE_INGEST_TOKEN", "")
        ).strip()
        remote_sync = RemoteSyncConfig(
            enabled=_get_bool("ATTENDANCE_REMOTE_SYNC_ENABLED", False),
            base_url=base_url,
            ingest_token=ingest_token,
            timeout_seconds=_get_int("ATTENDANCE_REMOTE_TIMEOUT_SECONDS", 10),
        )
        config = cls(
            database=database,
            presence_source=os.getenv("ATTENDANCE_PRESENCE_SOURCE", "lease_file"),
            lease_file_path=Path(
                os.getenv(
                    "ATTENDANCE_LEASE_FILE_PATH",
                    "./fixtures/sample_leases_one_device.txt",
                )
            ),
            poll_interval_seconds=_get_int("ATTENDANCE_POLL_INTERVAL_SECONDS", 15),
            exit_grace_period_seconds=_get_int(
                "ATTENDANCE_EXIT_GRACE_PERIOD_SECONDS", 120
            ),
            log_level=os.getenv("ATTENDANCE_LOG_LEVEL", "INFO").upper(),
            timezone_name=os.getenv("ATTENDANCE_TIMEZONE", "America/Toronto"),
            log_unknown_devices=_get_bool("ATTENDANCE_LOG_UNKNOWN_DEVICES", True),
            remote_sync=remote_sync,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.presence_source != "lease_file":
            raise ConfigError(
                "Unsupported ATTENDANCE_PRESENCE_SOURCE. Only 'lease_file' is currently implemented."
            )
        if self.poll_interval_seconds <= 0:
            raise ConfigError(
                "ATTENDANCE_POLL_INTERVAL_SECONDS must be greater than zero."
            )
        if self.exit_grace_period_seconds < 0:
            raise ConfigError(
                "ATTENDANCE_EXIT_GRACE_PERIOD_SECONDS cannot be negative."
            )
        if self.remote_sync.timeout_seconds <= 0:
            raise ConfigError(
                "ATTENDANCE_REMOTE_TIMEOUT_SECONDS must be greater than zero."
            )
        if self.remote_sync.enabled:
            if not self.remote_sync.base_url:
                raise ConfigError(
                    "ATTENDANCE_REMOTE_BASE_URL is required when remote sync is enabled."
                )
            if not self.remote_sync.ingest_token:
                raise ConfigError(
                    "ATTENDANCE_REMOTE_INGEST_TOKEN is required when remote sync is enabled."
                )
        if not self.lease_file_path:
            raise ConfigError("ATTENDANCE_LEASE_FILE_PATH is required.")
        _ = self.timezone
