from __future__ import annotations

import math
import re
from collections import Counter

from .schema import Schema, Table


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with",
    "by", "from", "is", "are", "was", "were", "be", "been", "being",
    "id", "ids", "uuid", "fk", "pk", "ref",
    "how", "what", "when", "where", "who", "why", "which", "many", "much",
    "do", "does", "did", "have", "has", "had", "can", "could", "should",
    "show", "list", "get", "find", "give", "tell", "me",
}


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    expanded = _CAMEL_RE.sub(r"\1 \2", text).replace("_", " ").replace("-", " ")
    return [
        t.lower() for t in _WORD_RE.findall(expanded)
        if t.lower() not in _STOPWORDS
    ]


def _table_terms(table: Table) -> list[str]:
    terms: list[str] = []
    # Repeat name to weight it higher in TF
    terms.extend(tokenize(table.name) * 3)
    terms.extend(tokenize(table.schema))
    if table.comment:
        terms.extend(tokenize(table.comment) * 2)
    for col in table.columns:
        terms.extend(tokenize(col.name))
    for fk in table.foreign_keys:
        terms.extend(tokenize(fk.referenced_table))
    return terms


class TfIdfRetriever:
    def __init__(self, schema: Schema):
        self.schema = schema
        self.tables: list[Table] = list(schema.tables)
        self._docs: list[list[str]] = [_table_terms(t) for t in self.tables]
        self._n = max(len(self._docs), 1)

        df: Counter[str] = Counter()
        for doc in self._docs:
            for term in set(doc):
                df[term] += 1
        self._df = df

        self._vecs: list[dict[str, float]] = [self._tfidf(doc) for doc in self._docs]
        self._norms: list[float] = [_norm(v) for v in self._vecs]

    def _idf(self, term: str) -> float:
        return math.log((self._n + 1) / (self._df.get(term, 0) + 1)) + 1.0

    def _tfidf(self, doc: list[str]) -> dict[str, float]:
        tf = Counter(doc)
        return {term: count * self._idf(term) for term, count in tf.items()}

    def rank(self, query: str, top_k: int = 10) -> list[tuple[Table, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.tables:
            return [(t, 0.0) for t in self.tables[:top_k]]
        q_vec = self._tfidf(q_tokens)
        q_norm = _norm(q_vec)
        scored: list[tuple[Table, float]] = []
        for table, vec, norm in zip(self.tables, self._vecs, self._norms):
            dot = 0.0
            shorter, longer = (q_vec, vec) if len(q_vec) < len(vec) else (vec, q_vec)
            for term, weight in shorter.items():
                other = longer.get(term)
                if other is not None:
                    dot += weight * other
            score = dot / (q_norm * norm) if q_norm and norm else 0.0
            scored.append((table, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def _norm(v: dict[str, float]) -> float:
    return math.sqrt(sum(x * x for x in v.values())) or 1.0


def _fk_target_key(fk, default_schema: str = "public") -> tuple[str, str]:
    return (fk.referenced_schema or default_schema, fk.referenced_table)


def expand_via_fks(
    schema: Schema,
    seed: list[Table],
    max_total: int = 20,
) -> list[Table]:
    """Add tables connected to `seed` via foreign keys until `max_total` is reached.

    Walks one hop outward (seed -> referenced) AND inward (referencing -> seed).
    Preserves seed order; new tables are appended in discovery order.
    """
    if max_total <= 0:
        return []

    by_key: dict[tuple[str, str], Table] = {(t.schema, t.name): t for t in schema.tables}
    selected: dict[tuple[str, str], Table] = {}
    for t in seed:
        if len(selected) >= max_total:
            return list(selected.values())
        selected[(t.schema, t.name)] = t

    # Outbound: from selected to their referenced tables
    for table in list(selected.values()):
        for fk in table.foreign_keys:
            if len(selected) >= max_total:
                return list(selected.values())
            key = _fk_target_key(fk)
            if key in by_key and key not in selected:
                selected[key] = by_key[key]

    # Inbound: tables referencing anything in selected
    seed_keys = {(t.schema, t.name) for t in seed}
    for table in schema.tables:
        if len(selected) >= max_total:
            break
        key = (table.schema, table.name)
        if key in selected:
            continue
        if any(_fk_target_key(fk) in seed_keys for fk in table.foreign_keys):
            selected[key] = table

    return list(selected.values())
