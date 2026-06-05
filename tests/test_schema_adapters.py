from __future__ import annotations

import sqlite3

import pytest

from promptquery.db import SQLiteDatabase, make_database
from promptquery.schema import introspect


class _FakePostgresDB:
    dialect = "postgres"

    def fetch_dicts(self, sql: str) -> list[dict]:
        if "FROM pg_class" in sql:
            return [
                {"schema": "public", "name": "users", "comment": "accounts"},
                {"schema": "sales", "name": "orders", "comment": None},
            ]
        if "FROM pg_attribute" in sql:
            return [
                {
                    "schema": "public",
                    "table_name": "users",
                    "name": "id",
                    "data_type": "bigint",
                    "nullable": False,
                    "is_primary_key": True,
                },
                {
                    "schema": "sales",
                    "table_name": "orders",
                    "name": "user_id",
                    "data_type": "bigint",
                    "nullable": False,
                    "is_primary_key": False,
                },
            ]
        if "FROM pg_constraint" in sql:
            return [
                {
                    "schema": "sales",
                    "table_name": "orders",
                    "column_name": "user_id",
                    "referenced_schema": "public",
                    "referenced_table": "users",
                    "referenced_column": "id",
                },
            ]
        raise AssertionError(f"unexpected query: {sql}")


def test_postgres_introspection_preserves_existing_row_mapping():
    schema = introspect(_FakePostgresDB())

    assert [table.qualified_name for table in schema.tables] == ["users", "sales.orders"]
    users = schema.tables[0]
    orders = schema.tables[1]

    assert users.comment == "accounts"
    assert users.columns[0].name == "id"
    assert users.columns[0].is_primary_key is True
    assert orders.foreign_keys[0].referenced_table == "users"


def test_make_database_selects_sqlite_for_sqlite_dsn(tmp_path):
    db_file = tmp_path / "shop.db"

    db = make_database(f"sqlite:///{db_file}")

    assert isinstance(db, SQLiteDatabase)
    assert db.path == str(db_file)


def test_sqlite_database_does_not_create_missing_file(tmp_path):
    db_file = tmp_path / "missing.db"
    db = SQLiteDatabase(f"sqlite:///{db_file}")

    with pytest.raises(sqlite3.OperationalError):
        db.connect()

    assert not db_file.exists()


def test_sqlite_introspection_reads_tables_views_columns_and_foreign_keys(tmp_path):
    db_file = tmp_path / "shop.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE authors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                author_id INTEGER NOT NULL REFERENCES authors(id),
                title TEXT,
                slug TEXT GENERATED ALWAYS AS (lower(title)) VIRTUAL
            )
        """)
        conn.execute("CREATE VIEW book_titles AS SELECT title FROM books")

    with SQLiteDatabase(f"sqlite:///{db_file}") as db:
        schema = introspect(db)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO authors (name) VALUES ('blocked')")

    tables = {table.name: table for table in schema.tables}
    assert set(tables) == {"authors", "book_titles", "books"}
    assert tables["authors"].qualified_name == "authors"

    author_columns = {column.name: column for column in tables["authors"].columns}
    assert author_columns["id"].is_primary_key is True
    assert author_columns["id"].nullable is False
    assert author_columns["name"].data_type == "TEXT"
    assert author_columns["name"].nullable is False

    book_columns = {column.name: column for column in tables["books"].columns}
    assert book_columns["slug"].data_type == "TEXT"
    assert book_columns["title"].nullable is True

    assert tables["books"].foreign_keys[0].column == "author_id"
    assert tables["books"].foreign_keys[0].referenced_schema == "main"
    assert tables["books"].foreign_keys[0].referenced_table == "authors"
    assert tables["books"].foreign_keys[0].referenced_column == "id"
