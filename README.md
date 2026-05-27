# PromptQuery

> Natural-language SQL for production-scale Postgres schemas.

PromptQuery is an open-source CLI that replaces `psql` with natural language — and is the first NL→SQL tool designed to work on real production databases with hundreds of tables.

```bash
$ promptquery postgresql://prod-db/mycompany
? how many users signed up from Italy last month
```

PromptQuery introspects your schema, generates the SQL, shows it for confirmation, and runs it read-only.

## Why this is different

Every existing NL→SQL tool dumps the full schema into the LLM prompt. That works on a 10-table demo. On a real 500+ table production schema it sends ~50k tokens of mostly-irrelevant context per query — slow, expensive, and (we measured) it actually *hurts* accuracy because the model over-attends to the wrong tables.

**PromptQuery's core bet: schema retrieval, in two stages.**

1. **TF-IDF (with stemming)** narrows the schema from hundreds of tables to ~50 candidates in microseconds, for free.
2. **An LLM table-selector** (a cheap model — `gpt-4o-mini` by default) picks the ~15 semantically relevant tables from those candidates. This handles the cases TF-IDF can't, e.g. *"invoice"* → `account_move`, *"shipment"* → `stock_picking`.
3. **FK-graph expansion** walks one hop in each direction to pull in join targets.

```
[Question] → [TF-IDF top 50] → [LLM selector top 15] → [FK expand to 25]
          → [SQL generator LLM] → [Safety guard] → [Confirm] → [Execute]
```

### Empirical result

Benchmarked on Odoo's real 675-table production schema, gpt-4o for SQL generation, gpt-4o-mini for the selector:

| Pipeline | Pass rate | Avg tokens / query | Avg latency |
|---|---|---|---|
| Naive (full schema in prompt) | 84.0% | ~50,000 | 3.4 s |
| PromptQuery v0.1 (TF-IDF only) | 76.0% | ~2,000 | 2.0 s |
| **PromptQuery v0.2 (TF-IDF + LLM selector)** | **100.0%** | ~5,000 | 5.6 s |

PromptQuery v0.2 is **+16 pp more accurate** and roughly **10× cheaper per query** than dumping the full schema, at the cost of one extra small LLM call.

Reproduce with `python -m eval.parsing_bench --fixture eval/fixtures/odoo.schema.json --questions eval.questions.odoo --model gpt-4o --selector-model gpt-4o-mini`.

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
| `--model` | LLM used for SQL generation (e.g. `claude-sonnet-4-6`, `gpt-4o`) |
| `--selector-model` | LLM used for the table-selector step. Cheaper model recommended (default: same as `--model`) |
| `--top-k` | TF-IDF candidates passed to the LLM selector (default 50) |
| `--select` | Tables the LLM selector picks from the candidates (default 15) |
| `--max-tables` | Cap on tables sent to the SQL generator after FK expansion (default 25) |
| `--no-selector` | Disable the LLM selector and use TF-IDF + FK expansion only (v0.1 behaviour) |
| `-y, --yes` | Skip the confirmation prompt before running queries |

## Safety

- The session opens with `default_transaction_read_only = on`.
- Every generated query is parsed with `sqlglot` and rejected unless it is a single `SELECT` (CTEs and `UNION` allowed).
- Every query is shown to you before it runs. Confirm with `y`.

## What PromptQuery does NOT do

- No writes — `SELECT`-only by design.
- Postgres only (MySQL and SQLite planned for v0.3).
- No multi-DB sessions.
- No data visualization — rows only.

## Roadmap

- **v0.2** (shipped) — LLM-assisted table selector + stemmed TF-IDF retrieval.
- **v0.3** — local LLMs (Ollama), schema anonymisation for GDPR, query-history-as-few-shot.
- **v0.4** — MySQL + SQLite adapters, MCP server mode, public competitor benchmark.

## License

Apache-2.0 — see [LICENSE](LICENSE).

Apache-2.0 was chosen over MIT for its **explicit patent grant** and **automatic termination of patent licenses against contributors who sue downstream users**. For a tool that orchestrates LLM-generated SQL across an active patent landscape, the patent clauses matter.
