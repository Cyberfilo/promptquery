# PromptQuery

> Natural-language SQL for production-scale Postgres schemas.

PromptQuery is an open-source CLI that replaces `psql` with natural language — and is the first NL→SQL tool designed to work on real production databases with hundreds of tables.

```bash
$ promptquery postgresql://prod-db/mycompany
? how many users signed up from Italy last month
```

PromptQuery introspects your schema, generates the SQL, shows it for confirmation, and runs it read-only.

## Why this is different

Every existing NL→SQL tool dumps the full schema into the LLM prompt. That works on a 10-table demo. It breaks at 100 tables. It's impossible at 500.

**PromptQuery's core bet: schema retrieval.** Before calling the LLM, rank tables by relevance to the question and only include the top ~20. The LLM never sees more than a fraction of the schema at once.

```
[Question] → [Rank by TF-IDF] → [Walk FK graph] → [Top 20 tables]
          → [LLM] → [SQL] → [Safety guard] → [Confirm] → [Execute]
```

## Install

```bash
pip install promptquery
```

Set an API key:

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
```

## Use

```bash
promptquery postgresql://localhost/mydb
```

Or the short alias:

```bash
prq postgresql://localhost/mydb
```

### Options

| Flag | Description |
|---|---|
| `--model` | Override LLM (e.g. `claude-sonnet-4-6`, `gpt-4o`) |
| `--top-k` | Initial number of tables to retrieve (default 10) |
| `--max-tables` | Cap on tables sent to LLM after FK expansion (default 20) |
| `-y, --yes` | Skip the confirmation prompt before running queries |

## Safety

- The session opens with `default_transaction_read_only = on`.
- Every generated query is parsed with `sqlglot` and rejected unless it is a single `SELECT` (CTEs and `UNION` allowed).
- Every query is shown to you before it runs. Confirm with `y`.

## What v0.1 does NOT do

- No writes — `SELECT`-only by design.
- Postgres only (MySQL and SQLite planned for v0.3).
- No multi-DB sessions.
- No data visualization — rows only.

## Roadmap

- **v0.2** — embedding-based ranking, query history as few-shot examples.
- **v0.3** — MySQL + SQLite, local LLMs (Ollama).
- **v0.4** — MCP server mode, public benchmark suite.

## License

MIT
