# Changelog

## 0.2.2 — 2026-06-04

- **Deterministic by default.** SQL generation now runs at `temperature = 0` (plus a fixed `seed` on
  standard OpenAI chat models). Ask the same question twice, get the same SQL. Reasoning models
  (gpt-5 / o-series) are left to sample on their own, since they reject those parameters.
  (`src/promptquery/llm.py`)
- **Honest token benchmark.** New `eval/token_bench.py` measures the SQL-generator prompt size with
  `tiktoken` and commits the receipts (`eval/results_odoo_tokens.json`,
  `eval/results_rnacentral_tokens.json`). The README now reports the *measured* numbers — **~12–17×**
  fewer tokens than stuffing the whole schema into the prompt (previously under-stated as "5–10×").
- **README**: spelled out exactly what the benchmark "accuracy" measures (table-grounding, parsed
  with `sqlglot` — not execution-equality), added an honest comparison table, and added a
  `CONTRIBUTING.md`.
- **Docs**: fixed a stale "MIT" reference (the project is Apache-2.0).

## 0.2.1 — 2026-05-27

- Ship the `pquery` command alias on PyPI (third alias alongside `promptquery` and `prq`).

## 0.2.0 — 2026-05-27

- LLM-assisted table selector (TF-IDF top-50 → cheap-model selector → FK-graph expansion).
- Full end-to-end eval suite with committed receipts.
