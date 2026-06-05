# PromptQuery — Architecture

This document explains how PromptQuery is structured internally. It's written for contributors and the curious. For usage, see the [README](README.md).

## The request lifecycle

When you type a question into the REPL, here is what happens:

```
question
   │
   ▼
┌──────────────────┐
│ retrieval.py     │  Rank tables by TF-IDF over their name, comment, column
│ TfIdfRetriever   │  names, and FK targets. Question is tokenized with
│                  │  snake_case + camelCase splitting and stopword filtering.
└────────┬─────────┘  Returns top-K tables.
         │
         ▼
┌──────────────────┐
│ retrieval.py     │  Walk the FK graph one hop outward (referenced tables)
│ expand_via_fks   │  AND one hop inward (tables that reference the seed).
│                  │  Capped at --max-tables to keep prompts compact.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ prompts.py       │  Render the chosen tables into the system prompt:
│ format_schema    │  TABLE name, columns with PK/NOT NULL flags, FKs.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ llm.py           │  Send to the configured provider (Anthropic by default,
│ Client.generate  │  OpenAI as fallback). Response is a markdown ```sql block.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ llm.extract_sql  │  Pull the SQL out of the code fence.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ safety.py        │  Parse with sqlglot in the database dialect. Reject anything
│ validate_select  │  that is not a single SELECT / WITH / UNION /
│ _only            │  INTERSECT / EXCEPT. Reject CTEs that hide DML
│                  │  (WITH x AS (DELETE ... RETURNING ...) SELECT ...).
│                  │  Reject calls to dangerous functions
│                  │  (pg_terminate_backend, set_config, lo_export, ...).
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ render.py        │  Pretty-print the SQL with syntax highlighting.
│ render_sql       │
└────────┬─────────┘
         │
         ▼
   "Run? [y/N]"
         │
         ▼
┌──────────────────┐
│ db.py            │  Execute. Postgres sessions use
│ Database.execute │  default_transaction_read_only = on; SQLite files open
│                  │  mode=ro and use PRAGMA query_only = ON, so even if
│                  │  safety.py failed the database itself refuses writes.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ render.py        │  Format as a rich.Table. NULLs styled, large blobs
│ render_results   │  summarized, truncate after 100 rows by default.
└──────────────────┘
```

## File inventory (`src/promptquery/`)

| File              | Purpose                                                                   |
|-------------------|---------------------------------------------------------------------------|
| `__init__.py`     | Package version.                                                          |
| `__main__.py`     | `python -m promptquery` entry point.                                      |
| `cli.py`          | Click command and prompt-toolkit REPL. Orchestrates the whole pipeline.   |
| `db.py`           | Postgres and SQLite connection wrappers. Sets the read-only session.      |
| `schema.py`       | Dataclasses + database-specific introspection adapters.                   |
| `retrieval.py`    | Tokenizer, TF-IDF ranker, FK-graph expander.                              |
| `llm.py`          | Provider clients (Anthropic, OpenAI), SQL extractor, provider factory.    |
| `prompts.py`      | System prompt template and schema-to-prompt formatter.                    |
| `safety.py`       | The sqlglot-based query guard.                                            |
| `render.py`       | SQL syntax rendering and result-table rendering with rich.                |

## File relationships

- **`schema.py` ↔ `retrieval.py`** — the ranker reads `Table.name`, `Table.comment`, `Table.columns`, and `Table.foreign_keys`. Adding a field to `Table` should prompt a decision about weighting it in `_table_terms`.
- **`schema.py` ↔ `prompts.py`** — `format_schema` walks the same dataclasses. Schema additions usually need a prompt update.
- **`cli.py` ↔ everything else** — the only file that knows the full pipeline. New stages (query history, post-execution feedback) wire in here.
- **`safety.py` ↔ `llm.py`** — `extract_sql` runs first; `validate_select_only` runs second. Together they handle the case where the model returns malformed output.
- **`db.py` ↔ `safety.py`** — two layers, intentionally redundant. Either alone is insufficient; together they keep execution read-only at both the SQL-parser and database-session layers.

## Design bets

### Why TF-IDF, not embeddings (yet)

TF-IDF works the moment you connect to a database. No model to download, no GPU, no API call to compute embeddings for hundreds of tables. The cost is that it cannot reason about synonyms — "customer" and "user" are different tokens to TF-IDF. That is the tradeoff v0.2 will revisit by adding embedding-based ranking as an optional layer on top.

### Why a separate FK-expansion pass

Many natural-language questions reference one core entity but require joins through several others. Asking "what's the average order value per country" needs `orders` (the main entity), but also `users` and `countries` (join targets). TF-IDF alone is unlikely to rank `countries` highly because the word "country" only appears once in its schema. The FK-graph walk catches join targets that pure relevance would miss.

### Why two safety layers

`safety.py` is the primary guard. It parses every statement in the selected database dialect and rejects anything other than a SELECT. The session-level read-only mode is the fallback: Postgres uses `default_transaction_read_only = on`, while SQLite files open with `mode=ro` and use `PRAGMA query_only = ON`. If a malicious prompt somehow produces SQL that the validator misclassifies (a parser bug, an unknown construct), the database itself refuses the write.

This redundancy is not paranoia. AI-generated SQL is, by construction, less predictable than human-written SQL. The cost of one accidental `DELETE` is high enough that doubling up is the only sensible default.

### Why introspect via `pg_catalog` instead of `information_schema`

`pg_catalog` is faster, more complete, and lets us read table comments via `obj_description`. We use `LATERAL unnest WITH ORDINALITY` to join `pg_constraint.conkey` with `pg_constraint.confkey` by ordinal position — the only correct way to handle composite foreign keys.

## What's not in v0.1

These are intentionally out of scope for the MVP. They are tracked in the [roadmap](README.md#roadmap).

- MySQL support — needs an adapter implementation and optional driver decision.
- Multi-database sessions in one REPL.
- Data visualization (charts, plots).
- Query-history persistence between sessions.
- Embedding-based retrieval.
- MCP server mode.

## Testing

Run the test suite:

```bash
pytest
```

All core tests are pure Python — no live external database required. SQLite adapter tests use temporary local database files. The integration test harness (docker-compose + a real Postgres) is queued for v0.2 alongside the public benchmark suite against Spider / BIRD.

The most safety-critical file is `tests/test_safety.py`. Cases there encode "things the validator MUST reject." Add cases when you discover new attack vectors; do not delete cases during refactors.

## Project layout

```
PromptQuery/
├── ARCHITECTURE.md          this file
├── LICENSE                  Apache-2.0
├── README.md                user-facing intro and install/usage
├── pyproject.toml           hatchling, scripts: promptquery + prq
├── src/promptquery/         the package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── db.py
│   ├── schema.py
│   ├── retrieval.py
│   ├── llm.py
│   ├── prompts.py
│   ├── safety.py
│   └── render.py
└── tests/                   pytest suite
    ├── test_schema_adapters.py
    ├── test_safety.py
    └── test_retrieval.py
```

## Contributing

PRs welcome. Run `pytest` before opening one. Keep the safety test suite untouched unless you're adding cases.
