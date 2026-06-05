from __future__ import annotations

import sqlite3
from urllib.parse import quote

import psycopg
from psycopg.rows import dict_row


class Database:
    dialect = "postgres"
    default_schema = "public"

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn: psycopg.Connection | None = None

    def connect(self) -> None:
        self.conn = psycopg.connect(self.dsn, autocommit=True)
        with self.conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute("SET statement_timeout = '60s'")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require_conn(self) -> psycopg.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    def fetch_dicts(self, sql: str) -> list[dict]:
        conn = self._require_conn()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return list(cur.fetchall())

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                return [], []
            cols = [d.name for d in cur.description]
            rows = list(cur.fetchall())
        return cols, rows

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class SQLiteDatabase:
    dialect = "sqlite"
    default_schema = "main"

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.path = _sqlite_path_from_dsn(dsn)
        self.conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        if self.path == ":memory:":
            self.conn = sqlite3.connect(self.path)
        else:
            self.conn = sqlite3.connect(
                f"file:{quote(self.path, safe='/')}?mode=ro",
                uri=True,
            )
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA query_only = ON")
            self.conn.execute("PRAGMA busy_timeout = 60000")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    def fetch_dicts(self, sql: str) -> list[dict]:
        conn = self._require_conn()
        cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        conn = self._require_conn()
        cur = conn.execute(sql)
        if cur.description is None:
            return [], []
        cols = [d[0] for d in cur.description]
        rows = [tuple(row) for row in cur.fetchall()]
        return cols, rows

    def pragma_dicts(self, name: str, argument: str) -> list[dict]:
        conn = self._require_conn()
        cur = conn.execute(f"PRAGMA {name}({_quote_sqlite_literal(argument)})")
        return [dict(row) for row in cur.fetchall()]

    def __enter__(self) -> "SQLiteDatabase":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def make_database(dsn: str) -> Database | SQLiteDatabase:
    if dsn.startswith("sqlite:///"):
        return SQLiteDatabase(dsn)
    return Database(dsn)


def _sqlite_path_from_dsn(dsn: str) -> str:
    if not dsn.startswith("sqlite:///"):
        raise ValueError("SQLite DSNs must use sqlite:///path/to.db")

    path = dsn[len("sqlite:///"):]
    if not path:
        raise ValueError("SQLite DSN is missing a database path")
    if path == ":memory:":
        return path
    if dsn.startswith("sqlite:////"):
        return "/" + dsn[len("sqlite:////"):]
    return path


def _quote_sqlite_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
