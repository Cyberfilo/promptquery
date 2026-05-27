from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Database


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool


@dataclass(frozen=True)
class ForeignKey:
    column: str
    referenced_schema: str
    referenced_table: str
    referenced_column: str


@dataclass
class Table:
    schema: str
    name: str
    comment: str | None = None
    columns: list[Column] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        if self.schema == "public":
            return self.name
        return f"{self.schema}.{self.name}"


@dataclass
class Schema:
    tables: list[Table]

    def by_qualified_name(self) -> dict[str, Table]:
        return {t.qualified_name: t for t in self.tables}


INTROSPECT_TABLES = """
SELECT n.nspname AS schema,
       c.relname AS name,
       obj_description(c.oid) AS comment
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname, c.relname
"""

INTROSPECT_COLUMNS = """
SELECT n.nspname AS schema,
       c.relname AS table_name,
       a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS nullable,
       EXISTS (
           SELECT 1 FROM pg_index i
           WHERE i.indrelid = c.oid
             AND i.indisprimary
             AND a.attnum = ANY(i.indkey)
       ) AS is_primary_key
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0
  AND NOT a.attisdropped
  AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname, c.relname, a.attnum
"""

INTROSPECT_FKS = """
SELECT
    ns.nspname  AS schema,
    cls.relname AS table_name,
    att.attname AS column_name,
    fns.nspname AS referenced_schema,
    fcls.relname AS referenced_table,
    fatt.attname AS referenced_column
FROM pg_constraint con
JOIN pg_class cls         ON cls.oid = con.conrelid
JOIN pg_namespace ns      ON ns.oid = cls.relnamespace
JOIN pg_class fcls        ON fcls.oid = con.confrelid
JOIN pg_namespace fns     ON fns.oid = fcls.relnamespace
JOIN LATERAL unnest(con.conkey)  WITH ORDINALITY AS k(attnum, ord)  ON TRUE
JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = k.ord
JOIN pg_attribute att     ON att.attrelid = con.conrelid  AND att.attnum  = k.attnum
JOIN pg_attribute fatt    ON fatt.attrelid = con.confrelid AND fatt.attnum = fk.attnum
WHERE con.contype = 'f'
  AND ns.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY ns.nspname, cls.relname, con.conname, k.ord
"""


def introspect(db: "Database") -> Schema:
    tables_rows = db.fetch_dicts(INTROSPECT_TABLES)
    columns_rows = db.fetch_dicts(INTROSPECT_COLUMNS)
    fks_rows = db.fetch_dicts(INTROSPECT_FKS)

    tables: dict[tuple[str, str], Table] = {}
    for row in tables_rows:
        key = (row["schema"], row["name"])
        tables[key] = Table(
            schema=row["schema"],
            name=row["name"],
            comment=row["comment"],
        )

    for row in columns_rows:
        key = (row["schema"], row["table_name"])
        table = tables.get(key)
        if table is None:
            continue
        table.columns.append(Column(
            name=row["name"],
            data_type=row["data_type"],
            nullable=bool(row["nullable"]),
            is_primary_key=bool(row["is_primary_key"]),
        ))

    for row in fks_rows:
        key = (row["schema"], row["table_name"])
        table = tables.get(key)
        if table is None:
            continue
        table.foreign_keys.append(ForeignKey(
            column=row["column_name"],
            referenced_schema=row["referenced_schema"],
            referenced_table=row["referenced_table"],
            referenced_column=row["referenced_column"],
        ))

    return Schema(tables=list(tables.values()))
