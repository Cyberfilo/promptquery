import pytest

from promptquery.anonymize import SchemaAnonymizer
from promptquery.prompts import format_schema
from promptquery.safety import UnsafeQuery, validate_select_only
from promptquery.schema import Column, ForeignKey, Schema, Table


def _schema() -> Schema:
    users = Table(
        schema="public",
        name="users",
        comment="customer accounts with private emails",
        columns=[
            Column("id", "bigint", False, True),
            Column("email", "text", True, False),
        ],
    )
    orders = Table(
        schema="sales",
        name="orders",
        comment="commercial order history",
        columns=[
            Column("id", "bigint", False, True),
            Column("user_id", "bigint", False, False),
            Column("total", "numeric", False, False),
        ],
        foreign_keys=[ForeignKey("user_id", "public", "users", "id")],
    )
    return Schema(tables=[users, orders])


def test_anonymized_schema_hides_names_and_preserves_structure():
    anonymizer = SchemaAnonymizer(_schema())
    anonymized = anonymizer.anonymize_tables(_schema().tables)

    rendered = format_schema(anonymized)
    assert "TABLE table_001" in rendered
    assert "TABLE table_002" in rendered
    assert "column_001 bigint  [PK, NOT NULL]" in rendered
    assert "FK column_002 -> table_001(column_001)" in rendered

    for leaked in [
        "users",
        "orders",
        "email",
        "user_id",
        "customer accounts",
        "commercial order",
    ]:
        assert leaked not in rendered


def test_deanonymize_sql_maps_qualified_aliases_and_non_public_schema():
    anonymizer = SchemaAnonymizer(_schema())

    sql = anonymizer.deanonymize_sql(
        "SELECT o.column_003 "
        "FROM table_002 AS o "
        "JOIN table_001 AS u ON o.column_002 = u.column_001 "
        "WHERE o.column_003 > 0"
    )

    assert sql == (
        "SELECT o.total FROM sales.orders AS o "
        "JOIN users AS u ON o.user_id = u.id WHERE o.total > 0"
    )


def test_deanonymize_sql_maps_unqualified_column_for_single_table():
    anonymizer = SchemaAnonymizer(_schema())

    sql = anonymizer.deanonymize_sql("SELECT column_002 FROM table_001")

    assert sql == "SELECT email FROM users"


def test_deanonymize_preserves_multiple_statement_rejection():
    anonymizer = SchemaAnonymizer(_schema())

    sql = anonymizer.deanonymize_sql("SELECT column_001 FROM table_001; DELETE FROM table_001")

    assert "SELECT id FROM users" in sql
    assert "DELETE FROM users" in sql
    with pytest.raises(UnsafeQuery):
        validate_select_only(sql)


def test_real_tables_from_anonymized_returns_original_tables():
    schema = _schema()
    anonymizer = SchemaAnonymizer(schema)
    anonymized = anonymizer.anonymize_tables(schema.tables)

    restored = anonymizer.real_tables_from_anonymized([anonymized[1], anonymized[0], anonymized[1]])

    assert restored == [schema.tables[1], schema.tables[0]]
