from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import errors as sqlglot_errors
from sqlglot import exp
from sqlglot.tokens import Tokenizer

from .schema import Column, ForeignKey, Schema, Table


TableKey = tuple[str, str]

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class _TableMapping:
    table: Table
    token: str
    columns_by_real: dict[str, str]
    columns_by_token: dict[str, str]


class SchemaAnonymizer:
    """Map schema identifiers to opaque tokens and generated SQL back again."""

    def __init__(self, schema: Schema):
        self._by_real_key: dict[TableKey, _TableMapping] = {}
        self._by_token: dict[str, _TableMapping] = {}

        for table_index, table in enumerate(schema.tables, start=1):
            table_token = f"table_{table_index:03d}"
            columns_by_real = {
                column.name: f"column_{column_index:03d}"
                for column_index, column in enumerate(table.columns, start=1)
            }
            mapping = _TableMapping(
                table=table,
                token=table_token,
                columns_by_real=columns_by_real,
                columns_by_token={v: k for k, v in columns_by_real.items()},
            )
            key = (table.schema, table.name)
            self._by_real_key[key] = mapping
            self._by_token[table_token.lower()] = mapping

    def anonymize_tables(self, tables: list[Table]) -> list[Table]:
        return [self.anonymize_table(table) for table in tables]

    def anonymize_table(self, table: Table) -> Table:
        mapping = self._mapping_for_table(table)
        return Table(
            schema="public",
            name=mapping.token,
            comment=None,
            columns=[
                Column(
                    name=mapping.columns_by_real[column.name],
                    data_type=column.data_type,
                    nullable=column.nullable,
                    is_primary_key=column.is_primary_key,
                )
                for column in table.columns
                if column.name in mapping.columns_by_real
            ],
            foreign_keys=[
                anonymized_fk
                for fk in table.foreign_keys
                if (anonymized_fk := self._anonymize_fk(mapping, fk)) is not None
            ],
        )

    def real_tables_from_anonymized(self, tables: list[Table]) -> list[Table]:
        real_tables: list[Table] = []
        seen: set[TableKey] = set()
        for table in tables:
            token = table.name.lower()
            mapping = self._by_token.get(token)
            if mapping is None:
                continue
            key = (mapping.table.schema, mapping.table.name)
            if key in seen:
                continue
            real_tables.append(mapping.table)
            seen.add(key)
        return real_tables

    def deanonymize_sql(self, sql: str) -> str:
        try:
            statements = [
                stmt
                for stmt in sqlglot.parse(sql, read="postgres")
                if stmt is not None
            ]
        except sqlglot_errors.SqlglotError:
            return sql

        if not statements:
            return sql

        for statement in statements:
            self._deanonymize_statement(statement)

        return ";\n".join(statement.sql(dialect="postgres") for statement in statements)

    def _mapping_for_table(self, table: Table) -> _TableMapping:
        key = (table.schema, table.name)
        try:
            return self._by_real_key[key]
        except KeyError as exc:
            raise ValueError(
                f"table is not part of the anonymized schema: {table.qualified_name}"
            ) from exc

    def _anonymize_fk(self, mapping: _TableMapping, fk: ForeignKey) -> ForeignKey | None:
        local_column = mapping.columns_by_real.get(fk.column)
        target_mapping = self._by_real_key.get(
            (fk.referenced_schema or "public", fk.referenced_table)
        )
        if local_column is None or target_mapping is None:
            return None

        target_column = target_mapping.columns_by_real.get(fk.referenced_column)
        if target_column is None:
            return None

        return ForeignKey(
            column=local_column,
            referenced_schema="public",
            referenced_table=target_mapping.token,
            referenced_column=target_column,
        )

    def _deanonymize_statement(self, statement: exp.Expression) -> None:
        table_by_qualifier: dict[str, _TableMapping] = {}
        referenced_mappings: list[_TableMapping] = []

        for table_expr in statement.find_all(exp.Table):
            mapping = self._by_token.get(table_expr.name.lower())
            if mapping is None:
                continue

            referenced_mappings.append(mapping)
            table_by_qualifier[mapping.token.lower()] = mapping
            table_by_qualifier[mapping.table.name.lower()] = mapping
            if table_expr.alias:
                table_by_qualifier[table_expr.alias.lower()] = mapping

            table_expr.set("this", _identifier(mapping.table.name))
            if mapping.table.schema == "public":
                table_expr.set("db", None)
            else:
                table_expr.set("db", _identifier(mapping.table.schema))

        for column_expr in statement.find_all(exp.Column):
            column_token = column_expr.name.lower()
            table_qualifier = column_expr.table.lower() if column_expr.table else ""

            if table_qualifier:
                mapping = table_by_qualifier.get(table_qualifier)
                if mapping is None:
                    continue
                real_column = mapping.columns_by_token.get(column_token)
                if real_column is None:
                    continue
                column_expr.set("this", _identifier(real_column))
                if table_qualifier == mapping.token.lower():
                    column_expr.set("table", _identifier(mapping.table.name))
                    if mapping.table.schema == "public":
                        column_expr.set("db", None)
                    else:
                        column_expr.set("db", _identifier(mapping.table.schema))
                continue

            matches = [
                (mapping, mapping.columns_by_token[column_token])
                for mapping in referenced_mappings
                if column_token in mapping.columns_by_token
            ]
            if len(matches) != 1:
                continue
            _, real_column = matches[0]
            column_expr.set("this", _identifier(real_column))


def _identifier(name: str) -> exp.Identifier:
    return exp.to_identifier(name, quoted=_needs_quotes(name))


def _needs_quotes(name: str) -> bool:
    return not _SAFE_IDENTIFIER_RE.match(name) or name.upper() in Tokenizer.KEYWORDS
