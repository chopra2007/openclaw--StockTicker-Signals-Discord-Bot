"""Web-only SQLite connections and explicit atomic schema migrations."""
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import sqlite3
import time


class WebStore:
    def __init__(self, path: Path):
        if not path.is_absolute():
            raise ValueError("web database path must be absolute")
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=2.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                               "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL) STRICT")
            versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            if versions - {1, 2, 3, 4}:
                raise ValueError("web schema is newer than this application")
            for version, name in [(1, '001_initial.sql'), (2, '002_source_policy.sql'), (3, '003_research.sql'), (4, '004_probe_ownership.sql')]:
                if version in versions:
                    continue
                script = (Path(__file__).parent / "migrations" / name).read_text(encoding="utf-8")
                # executescript implicitly commits. Parse complete SQL statements
                # instead so schema creation and version insertion remain atomic.
                statement = ""
                for line in script.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise ValueError("incomplete migration statement")
                connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)", (version,time.time()))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
