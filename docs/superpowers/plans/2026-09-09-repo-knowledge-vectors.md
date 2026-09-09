# Local vector retrieval

Keep `knowledge.json` authoritative. Add a derived PostgreSQL 18.4 + pgvector
index with local multilingual FastEmbed embeddings, shared by Claude Code and
Codex. Use schema `repo_knowledge`, database `repo_knowledge` by default or
`REPO_KNOWLEDGE_DSN`, and namespace rows by SHA-256 of the resolved absolute Git
root. Do not store credentials. No SQLite is shipped.

1. Add a failing real multilingual retrieval check.
2. Add `requirements.txt` with `psycopg[binary]` and FastEmbed 0.8.0; recommend
   Python 3.11 with `uv venv --python 3.11 .venv` and
   `uv pip install --python .venv/bin/python -r requirements.txt`.
3. Implement helper auto-reexec into `.venv` beside `SKILL.md` for `index` and `query`;
   explicit venv Python remains supported for copied installs.
4. Implement atomic full index rebuild, vector/hybrid retrieval, and freshness
   filtering against both current evidence hashes and the full JSON record
   fingerprint before `--limit`.
5. Add query modes: `auto` default uses hybrid when PostgreSQL index is
   accessible and reports lexical fallback otherwise; explicit `lexical`,
   `vector`, and `hybrid`, where vector/hybrid fail unavailable.
6. Keep queries read-only: no DB/schema/repo mutation and no model download.
   First `index` may download cached
   `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (~0.22 GB).
7. `index` after `put`, `refresh`, or `drop` transactionally rebuilds this
   repository's fresh records. `CREATE EXTENSION IF NOT EXISTS vector` is handled
   by `index` but needs permission or DBA setup.
8. Document exact cosine search only, no HNSW yet, semantic similarity as a lead
   rather than proof or threshold certainty.
9. Run legacy and real embedding checks; review failure/freshness paths.
10. Update the shared global installation, verify `.agents` and `.codex` aliases,
    publish scoped files.

Acceptance: Korean query finds an English fact without lexical overlap; changed,
deleted or replaced records never return obsolete vectors, even with limit 1;
failed builds preserve the previous index; queries do not modify repository data,
DB/schema, or download the model.

Sources: pgvector <https://github.com/pgvector/pgvector>; psycopg
<https://www.psycopg.org/psycopg3/docs/basic/usage.html>; FastEmbed pooled text
model list
<https://github.com/qdrant/fastembed/blob/main/fastembed/text/pooled_embedding.py>.
