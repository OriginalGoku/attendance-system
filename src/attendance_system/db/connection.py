from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from attendance_system.config import DatabaseConfig


class DatabaseConnectionFactory:
    """Build MySQL connections with consistent options."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config

    def connect(self) -> Connection:
        return pymysql.connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password,
            database=self._config.name,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
