from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeQuery(Exception):
    """Raised when a generated SQL statement is not a pure read-only SELECT."""


_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,
)

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.With,
    exp.Subquery,
)

# Postgres functions that can mutate state even from inside a SELECT.
_DANGEROUS_FUNCTIONS = {
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "lo_import",
    "lo_export",
    "dblink_exec",
    "set_config",
    "load_extension",
}


def validate_select_only(sql: str, *, dialect: str = "postgres") -> None:
    sql = (sql or "").strip()
    if not sql:
        raise UnsafeQuery("empty SQL")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        raise UnsafeQuery(f"could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if not statements:
        raise UnsafeQuery("empty SQL")
    if len(statements) > 1:
        raise UnsafeQuery("multiple statements are not allowed")

    stmt = statements[0]

    if not isinstance(stmt, _ALLOWED_ROOTS):
        raise UnsafeQuery(
            f"only SELECT queries are allowed (got {type(stmt).__name__})"
        )

    for forbidden in _FORBIDDEN_NODES:
        node = stmt.find(forbidden)
        if node is not None:
            raise UnsafeQuery(
                f"{type(node).__name__.upper()} statements are not allowed"
            )

    for func in stmt.find_all(exp.Anonymous):
        name = (func.name or "").lower()
        if name in _DANGEROUS_FUNCTIONS:
            raise UnsafeQuery(f"function {name!r} is not allowed")

    for func in stmt.find_all(exp.Func):
        name = (func.sql_name() or "").lower()
        if name in _DANGEROUS_FUNCTIONS:
            raise UnsafeQuery(f"function {name!r} is not allowed")
