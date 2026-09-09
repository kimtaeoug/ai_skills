"""Derived PostgreSQL/pgvector index. JSON records remain authoritative."""
from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SIGNATURE = MODEL + ":fastembed-0.8.0:384:cosine:v1"


def namespace(root):
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()


def fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def connect(readonly=False):
    try:
        import psycopg
    except ImportError:
        raise ValueError("Install the skill requirements in its .venv to use PostgreSQL vectors.") from None
    try:
        with psycopg.connect(os.environ.get("REPO_KNOWLEDGE_DSN", "dbname=repo_knowledge"),
                             connect_timeout=3) as connection:
            connection.read_only = readonly
            if readonly:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            connection.execute("SET LOCAL statement_timeout = '30s'")
            yield connection
    except psycopg.Error as error:
        # Connection errors can include credentials supplied in a DSN: do not echo them.
        raise ValueError("PostgreSQL vector operation failed (" + type(error).__name__ +
                         "). Check REPO_KNOWLEDGE_DSN, database/extension permissions; run index.") from None


def embedder(download=False):
    try:
        from fastembed import TextEmbedding
        if version("fastembed") != "0.8.0":
            raise ValueError("Install pinned fastembed==0.8.0, then rebuild with index.")
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "repo-knowledge/models"
        return TextEmbedding(model_name=MODEL, cache_dir=str(cache), threads=2,
                             local_files_only=not download)
    except Exception as error:
        raise ValueError("Local embedding model unavailable (" + type(error).__name__ +
                         "). Install requirements and run index to cache the model.") from None


def record_text(record):
    return " ".join([record["summary"], record["subject"]["id"], record["relation"],
                     record["object"]["id"], *record.get("aliases", [])])


def build(root, fresh, rebuild=False):
    with connect() as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute("CREATE SCHEMA IF NOT EXISTS repo_knowledge")
        connection.execute("""CREATE TABLE IF NOT EXISTS repo_knowledge.indexes (
            repo text PRIMARY KEY, signature text NOT NULL)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS repo_knowledge.embeddings (
            repo text NOT NULL REFERENCES repo_knowledge.indexes(repo) ON DELETE CASCADE,
            id text NOT NULL, fingerprint text NOT NULL, embedding vector(384) NOT NULL,
            PRIMARY KEY (repo, id))""")
        key = namespace(root)
        connection.execute("SELECT pg_advisory_xact_lock(%s)",
                           (int.from_bytes(bytes.fromhex(key[:16]), "big", signed=True),))
        row = connection.execute("SELECT signature FROM repo_knowledge.indexes WHERE repo = %s",
                                 (key,)).fetchone()
        rebuilt = rebuild or row is None or row[0] != SIGNATURE
        existing = dict(connection.execute(
            "SELECT id, fingerprint FROM repo_knowledge.embeddings WHERE repo = %s", (key,)).fetchall())
        current = {record_id: fingerprint(record) for record_id, record in fresh.items()}
        removed = sorted(set(existing) - set(current))
        changed = sorted(k for k in current if rebuilt or existing.get(k) != current[k])
        unchanged = sorted(set(current) - set(changed))

        connection.execute("""INSERT INTO repo_knowledge.indexes VALUES (%s, %s)
            ON CONFLICT (repo) DO UPDATE SET signature = EXCLUDED.signature""", (key, SIGNATURE))
        if removed:
            connection.execute("DELETE FROM repo_knowledge.embeddings WHERE repo = %s AND id = ANY(%s)",
                               (key, removed))
        if changed:
            model = embedder(download=True)
            embeddings = list(model.passage_embed([record_text(fresh[k]) for k in changed]))
            if len(embeddings) != len(changed):
                raise ValueError("Embedding count mismatch; previous index preserved.")
            for record_id, vector in zip(changed, embeddings):
                connection.execute("""INSERT INTO repo_knowledge.embeddings (repo,id,fingerprint,embedding)
                    VALUES (%s,%s,%s,%s::vector)
                    ON CONFLICT (repo,id) DO UPDATE
                    SET fingerprint=EXCLUDED.fingerprint, embedding=EXCLUDED.embedding""",
                                   (key, record_id, current[record_id], json.dumps(vector.tolist())))
    return {"indexed": len(fresh), "backend": "postgresql/pgvector", "model": MODEL,
            "namespace": namespace(root), "embedded": len(changed), "deleted": len(removed),
            "unchanged": len(unchanged), "rebuilt": rebuilt}


def search(root, fresh, text, limit):
    with connect(readonly=True) as connection:
        row = connection.execute("SELECT signature FROM repo_knowledge.indexes WHERE repo = %s",
                                 (namespace(root),)).fetchone()
        if row is None or row[0] != SIGNATURE:
            raise ValueError("Vector index missing or model changed; run index.")
        eligible = {k: fingerprint(r) for k, r in fresh.items()}
        parameters = (json.dumps(eligible), namespace(root))
        clause = """FROM repo_knowledge.embeddings e
            JOIN jsonb_each_text(%s::jsonb) f ON e.id = f.key AND e.fingerprint = f.value
            WHERE e.repo = %s"""
        # Filter evidence and JSON revisions before ranking, so stale top hits cannot hide fresh results.
        count = connection.execute("SELECT count(*) " + clause, parameters).fetchone()[0]
        hits = []
        if count and text.strip():
            vector = next(embedder().query_embed(text))
            hits = connection.execute("SELECT e.id, e.embedding <=> %s::vector AS distance " + clause +
                                      " ORDER BY distance, e.id LIMIT %s",
                                      (json.dumps(vector.tolist()), *parameters, limit)).fetchall()
    return hits, {"backend": "postgresql/pgvector", "model": MODEL, "eligible_records": count,
                  "unindexed_fresh_records": len(fresh) - count}
