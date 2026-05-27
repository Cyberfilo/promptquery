# PromptQuery

> **Natural-language SQL for production-scale Postgres schemas.**

[![PyPI](https://img.shields.io/pypi/v/promptquery.svg)](https://pypi.org/project/promptquery/)
[![CI](https://github.com/Cyberfilo/promptquery/actions/workflows/ci.yml/badge.svg)](https://github.com/Cyberfilo/promptquery/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

PromptQuery is an open-source CLI that lets you query Postgres in plain English — engineered for **real production schemas with hundreds of tables**, not toy demos. It introspects your schema, generates SQL, shows it for confirmation, and runs it read-only.

```
$ prq postgresql://prod-db/mycompany
✓ 675 tables found (sql: openai/gpt-4o, selector: openai/gpt-4o-mini)

PromptQuery — ask a question in plain English, or type "exit".

? unpaid invoices over EUR 1000 with the customer name
Selecting from 50 candidates...
Generating SQL...
Using 14 tables: account_move, res_partner, account_payment, ...

  SELECT am.name AS invoice,
         am.amount_total AS total,
         p.name AS customer
  FROM account_move am
  JOIN res_partner p ON p.id = am.partner_id
  WHERE am.move_type = 'out_invoice'
    AND am.payment_state IN ('not_paid', 'partial')
    AND am.amount_total > 1000
  ORDER BY am.amount_total DESC;

Run? [y/N] y

 invoice       │   total │ customer
───────────────┼─────────┼──────────────────────
 INV/2026/0042 │ 1899.00 │ Marco Rossi
 INV/2026/0067 │ 1299.00 │ Acme Industries SRL
2 row(s)
```

---

## The numbers

Two independent production-scale schemas. SQL generation: `gpt-4o`. Table selection: `gpt-4o-mini`.

### Odoo 18 ERP — 675 tables ([`eval/fixtures/odoo.schema.json`](eval/fixtures/odoo.schema.json))

| Pipeline | Accuracy | Tokens / query | Latency |
|---|---:|---:|---:|
| Naive (full schema in prompt) | 84.0 % | ~50,000 | 3.4 s |
| PromptQuery v0.1 *(TF-IDF only)* | 76.0 % | ~2,000 | 2.0 s |
| **PromptQuery v0.2 *(TF-IDF + LLM selector)*** | **100.0 %** | **~5,000** | 5.6 s |

### EMBL-EBI RNAcentral — 216 tables, biology domain, [public read-only DB](https://rnacentral.org/help/public-database)

| Pipeline | Accuracy | Tokens / query | Latency |
|---|---:|---:|---:|
| Naive (full schema in prompt) | 82.0 % | ~22,000 | 3.0 s |
| PromptQuery v0.1 *(TF-IDF only)* | 74.0 % | ~2,000 | 1.9 s |
| **PromptQuery v0.2 *(TF-IDF + LLM selector)*** | **94.0 %** | **~5,000** | 4.8 s |

Pattern across both benchmarks: PromptQuery v0.2 wins by **+12 to +16 percentage-points** over the naive "stuff the whole schema into a prompt" baseline, at **~5-10× lower per-query token cost**, validated independently on two different production schemas and domains.

*Receipts in [`eval/results_odoo_v2.json`](eval/results_odoo_v2.json) and [`eval/results_rnacentral.json`](eval/results_rnacentral.json). Reproduce both with one command each — see [Benchmark](#benchmark) below.*

---

## Quick start

```bash
pip install promptquery

# Set ONE of these (PromptQuery auto-detects):
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...

# Connect and start asking:
prq postgresql://localhost/mydb
```

`prq` and `pquery` are short aliases for `promptquery`. All three commands work identically.

### One-shot mode (scripting / CI)

`--query` skips the REPL and returns machine-readable output. Progress messages go to stderr, results to stdout — pipe-friendly:

```bash
prq --query "how many users in Italy" postgresql://localhost/mydb         # JSON to stdout
prq --query "top 10 orders by total" --out csv postgresql://... > out.csv
prq --query "..." --out table postgresql://...                            # rich-formatted table
```

Exit codes: `0` success · `1` LLM/connection error · `2` safety-guard rejection · `3` execution error.

### Try it without setting up a database

EMBL-EBI publishes a **public read-only Postgres** with real biological RNA-sequence data (216 tables). Install PromptQuery and try it in under a minute:

```bash
pip install promptquery
export OPENAI_API_KEY=...

prq --query "show me the 5 latest blog posts with their title" \
  --selector-model gpt-4o-mini \
  postgresql://reader:NWDMCE5xdipIjRrp@hh-pgsql-public.ebi.ac.uk:5432/pfmegrnargs
```

(Credentials above are EMBL-EBI's public read-only — published for tutorial use.)

---

## How it works

```
question
   │
   ▼
┌───────────────────┐
│ TF-IDF (stemmed)  │  Microseconds. Free. Surfaces ~50 candidate tables
│ retriever         │  by lexical match on names, columns, and comments.
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ LLM table         │  One small LLM call. Handles semantic mismatches
│ selector          │  TF-IDF cannot: "invoice" → `account_move`,
│ (cheap model)     │  "shipment" → `stock_picking`. Picks ~15 tables.
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ FK-graph          │  One hop outward + inward to pick up join targets
│ expansion         │  the question didn't name explicitly. Cap at 25.
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ SQL generator     │  Your real LLM call. Receives ~25 tables, not 675.
│ (frontier model)  │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ Safety guard      │  sqlglot validator: rejects anything that isn't a
│ (sqlglot)         │  pure SELECT/CTE/UNION. Catches CTEs that hide DML.
└────────┬──────────┘
         │
         ▼
   "Run? [y/N]" → execute against a read-only Postgres session
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the deep dive (file inventory, design bets, the patent-landmine non-goals).

---

## Configuration

| Flag | Default | Description |
|---|---|---|
| `--model` | auto-detect | LLM for SQL generation (e.g. `gpt-4o`, `claude-sonnet-4-6`, `anthropic/claude-opus-4-7`) |
| `--selector-model` | same as `--model` | LLM for the table-selector step. **A cheaper model is recommended** (e.g. `gpt-4o-mini`) |
| `--top-k` | 50 | TF-IDF candidates passed to the LLM selector |
| `--select` | 15 | Tables the LLM selector picks from those candidates |
| `--max-tables` | 25 | Cap after FK expansion — what the SQL generator actually sees |
| `--no-selector` | — | Skip the LLM selector (v0.1 behaviour: TF-IDF + FK only) |
| `-y, --yes` | — | Skip the confirmation prompt before running |

### Environment

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Use OpenAI as the LLM provider |
| `ANTHROPIC_API_KEY` | Use Anthropic as the LLM provider |

If both are set, Anthropic is preferred. Override either with `--model anthropic/<name>` or `--model openai/<name>`.

---

## Safety

PromptQuery has **two independent layers** so a write is impossible, even if one layer fails:

1. **Session-level**: every Postgres session opens with `default_transaction_read_only = on` and a 60-second `statement_timeout`. The database itself refuses non-SELECT operations.
2. **Pre-execution**: every generated query is parsed with `sqlglot` and rejected unless it's a single `SELECT` / `WITH` / `UNION` / `INTERSECT` / `EXCEPT`. The validator also catches CTEs that hide DML (`WITH x AS (DELETE …) SELECT * FROM x`) and dangerous-function calls (`pg_terminate_backend`, `set_config`, `lo_export`, `dblink_exec`).

Every query is also shown to you before it runs. Confirm with `y`.

---

## Benchmark

The eval suite is part of the repo and reproducible:

```bash
# End-to-end (real Postgres + execution-equality scoring on the shop schema):
docker compose -f eval/docker-compose.yml up -d
PGPASSWORD=promptquery psql -h 127.0.0.1 -p 55432 -U promptquery -d shop \
    -f eval/fixtures/shop.sql \
    -f eval/fixtures/shop_seed.sql
python -m eval.end_to_end --model gpt-4o --pad 0 --pad 200

# Parsing-mode on Odoo 18 (675 tables):
python -m eval.parsing_bench \
    --fixture eval/fixtures/odoo.schema.json \
    --questions eval.questions.odoo \
    --model gpt-4o --selector-model gpt-4o-mini

# Parsing-mode on EMBL-EBI's public RNAcentral (216 tables, real biology data):
python -m eval.parsing_bench \
    --fixture eval/fixtures/rnacentral.schema.json \
    --questions eval.questions.rnacentral \
    --model gpt-4o --selector-model gpt-4o-mini
```

The committed [`eval/results_*.json`](eval/) files are receipts of every bench we've run — including unfavourable ones, on purpose.

See [`eval/END_TO_END.md`](eval/END_TO_END.md) for the harness internals.

---

## What PromptQuery does NOT do (yet)

- **No writes.** `SELECT` only, by design and by belt-and-suspenders.
- **Postgres only.** MySQL and SQLite are on the v0.4 roadmap.
- **One database at a time.** No multi-DB sessions.
- **No data visualisation.** Rows out, that's it. Pipe to `csv` / `jq` / your tool of choice.

---

## Roadmap

- **v0.2 (shipped)** — LLM-assisted table selector, stemmed TF-IDF.
- **v0.3** — local LLMs (Ollama), schema anonymisation (GDPR-by-default), query-history-as-few-shot.
- **v0.4** — MySQL + SQLite adapters, MCP server mode, public competitor benchmark.

---

## Development

```bash
git clone https://github.com/Cyberfilo/promptquery
cd promptquery
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,openai]"

# Run the unit tests:
.venv/bin/pytest

# Run the retrieval eval (no API key needed, no DB needed):
.venv/bin/python -m eval.retrieval
```

37 tests, all pure-Python — no live database or API key required for the core suite.

---

## License

[Apache-2.0](LICENSE). Apache-2.0 was chosen over MIT specifically for its **explicit patent grant** and **automatic termination** clauses, which matter for a tool that operates in an active NL-to-SQL patent landscape.
