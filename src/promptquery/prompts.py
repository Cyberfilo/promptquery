from __future__ import annotations

from .schema import Table


SYSTEM_PROMPT = """\
You are a senior data engineer writing PostgreSQL queries.

Rules:
1. Generate ONE PostgreSQL SELECT query that answers the user's question.
2. Use ONLY the tables and columns listed in the schema below. Do not invent columns.
3. NEVER write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, COPY, or any DDL/DML.
4. Prefer explicit JOINs over implicit ones. Always qualify columns when joining.
5. If the schema below is insufficient to answer the question, output a single SELECT that
   returns an error message string (e.g. SELECT 'insufficient schema: missing X' AS error)
   rather than guessing.
6. Output ONLY the SQL inside a ```sql code block. No prose, no explanation.

Available schema:
{schema}
"""


def format_schema(tables: list[Table]) -> str:
    blocks: list[str] = []
    for t in tables:
        lines = [f"TABLE {t.qualified_name}"]
        if t.comment:
            lines.append(f"  -- {t.comment}")
        for c in t.columns:
            modifiers = []
            if c.is_primary_key:
                modifiers.append("PK")
            if not c.nullable:
                modifiers.append("NOT NULL")
            mod_str = f"  [{', '.join(modifiers)}]" if modifiers else ""
            lines.append(f"  {c.name} {c.data_type}{mod_str}")
        for fk in t.foreign_keys:
            ref = fk.referenced_table
            if fk.referenced_schema and fk.referenced_schema != "public":
                ref = f"{fk.referenced_schema}.{fk.referenced_table}"
            lines.append(f"  FK {fk.column} -> {ref}({fk.referenced_column})")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_system_prompt(tables: list[Table]) -> str:
    return SYSTEM_PROMPT.format(schema=format_schema(tables))
