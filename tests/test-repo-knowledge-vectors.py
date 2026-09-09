#!/usr/bin/env python3
"""Run with the skill's vector-enabled Python; first index downloads the model."""
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager
import os
import psycopg
import subprocess
import sys
import tempfile
from unittest.mock import patch

SCRIPT = Path(os.environ.get("REPO_KNOWLEDGE_HELPER", Path(__file__).resolve().parents[1] /
                             ".claude/skills/repo-knowledge/scripts/knowledge.py"))
sys.path.insert(0, str(SCRIPT.parent))
import vectors


@contextmanager
def repository():
    with tempfile.TemporaryDirectory(prefix="knowledge vectors ") as directory:
        try:
            yield directory
        finally:
            key = hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()
            with psycopg.connect(os.environ.get("REPO_KNOWLEDGE_DSN", "dbname=repo_knowledge")) as connection:
                if connection.execute("SELECT to_regclass('repo_knowledge.indexes')").fetchone()[0]:
                    connection.execute("DELETE FROM repo_knowledge.indexes WHERE repo = %s", (key,))


def main():
    with repository() as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", directory], check=True)

        def run(*args, ok=True):
            result = subprocess.run([os.environ.get("REPO_KNOWLEDGE_PYTHON", sys.executable),
                                     str(SCRIPT), "--repo", directory, *args],
                                    capture_output=True, text=True)
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        run("init")
        records = []
        for key, summary in {
            "password": "Users who forget their password can reset it using an email recovery link.",
            "refund": "Customers receive a refund to their credit card when they cancel a payment.",
            "image": "Uploaded photographs are resized into small thumbnails for the image gallery.",
        }.items():
            path = key + ".md"
            (root / path).write_text(summary + "\n")
            evidence = run("source", path)
            evidence.pop("text")
            records.append({"id": key, "subject": {"id": path, "type": "document"},
                            "relation": "documents", "object": {"id": key, "type": "concept"},
                            "summary": summary, "epistemic": "observed", "evidence": [evidence]})

        def put(items):
            batch = root / "batch.json"
            batch.write_text(json.dumps(items))
            run("put", str(batch))

        put(records)
        question = "비밀번호를 잊어버렸을 때 어떻게 복구하나요?"
        assert run("query", question)["results"] == []
        run("query", question, "--mode", "vector", ok=False)
        built = run("index")
        assert built["indexed"] == 3
        assert built["embedded"] == 3
        assert built["deleted"] == 0
        assert built["unchanged"] == 0
        assert built["rebuilt"] is True
        assert built["backend"] == "postgresql/pgvector"
        def snapshot():
            with psycopg.connect(os.environ.get("REPO_KNOWLEDGE_DSN", "dbname=repo_knowledge")) as connection:
                signature = connection.execute(
                    "SELECT signature FROM repo_knowledge.indexes WHERE repo = %s",
                    (built["namespace"],)).fetchone()[0]
                rows = connection.execute(
                    "SELECT id, fingerprint, embedding::text FROM repo_knowledge.embeddings WHERE repo = %s ORDER BY id",
                    (built["namespace"],)).fetchall()
                assert connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
                return signature, rows
        before = snapshot()
        assert len(json.loads(before[1][0][2])) == 384
        second = run("index")
        assert second["indexed"] == 3
        assert second["embedded"] == 0
        assert second["deleted"] == 0
        assert second["unchanged"] == 3
        assert second["rebuilt"] is False
        fresh_records = json.loads((root / ".repo-knowledge/knowledge.json").read_text())["records"]
        with patch.object(vectors, "embedder", side_effect=AssertionError("Unexpected embedder")):
            assert vectors.build(root, fresh_records)["embedded"] == 0
        with psycopg.connect(os.environ.get("REPO_KNOWLEDGE_DSN", "dbname=repo_knowledge")) as connection:
            connection.execute("UPDATE repo_knowledge.indexes SET signature = 'old' WHERE repo = %s",
                               (built["namespace"],))
        rebuilt = run("index")
        assert rebuilt["indexed"] == 3
        assert rebuilt["embedded"] == 3
        assert rebuilt["deleted"] == 0
        assert rebuilt["unchanged"] == 0
        assert rebuilt["rebuilt"] is True
        before = snapshot()
        assert run("query", question, "--mode", "lexical")["results"] == []
        for mode in ("vector", "hybrid", "auto"):
            hits = run("query", question, "--mode", mode, "--limit", "1")
            assert hits["results"][0]["record"]["id"] == "password", hits
        assert snapshot() == before
        with tempfile.TemporaryDirectory() as other:
            try:
                vectors.search(Path(other), {}, question, 1)
                raise AssertionError("Different repository saw this repository's index")
            except ValueError as error:
                assert "missing" in str(error)
        # A DB insertion failure must roll back deletion of the old index.
        class BadVector:
            def tolist(self):
                return [1.0, 2.0]

        class BadModel:
            def passage_embed(self, texts):
                return [BadVector() for _ in texts]

        with patch.object(vectors, "embedder", return_value=BadModel()):
            try:
                vectors.build(root, {r["id"]: r for r in records}, rebuild=True)
                raise AssertionError("Invalid vector dimensions accepted")
            except ValueError:
                pass
        assert snapshot() == before

        class ExtraModel:
            def passage_embed(self, texts):
                return [BadVector() for _ in range(len(texts) + 1)]

        with patch.object(vectors, "embedder", return_value=ExtraModel()):
            try:
                vectors.build(root, {r["id"]: r for r in records}, rebuild=True)
                raise AssertionError("Extra embeddings accepted")
            except ValueError as error:
                assert "count mismatch" in str(error)
        assert snapshot() == before
        # Model inference must work from cache even when HTTP calls are forbidden.
        with patch("httpx.Client.send", side_effect=AssertionError("Unexpected HTTP")), \
                patch("requests.Session.request", side_effect=AssertionError("Unexpected HTTP")):
            assert len(next(vectors.embedder().query_embed(question))) == 384
        (root / "password.md").write_text("Recovery is disabled.\n")
        hits = run("query", question, "--mode", "vector", "--limit", "1")
        assert len(hits["results"]) == 1  # Exclude stale rows BEFORE the limit.
        assert hits["results"][0]["record"]["id"] != "password"
        records[1]["summary"] += " Reviewed refund policy."
        put([records[1]])
        assert [h["record"]["id"] for h in run("query", question, "--mode", "vector")["results"]] == ["image"]
        changed = run("index")
        assert changed["indexed"] == 2
        assert changed["embedded"] == 1
        assert changed["deleted"] == 1
        assert changed["unchanged"] == 1
        assert changed["rebuilt"] is False
        (root / "image.md").unlink()
        assert [h["record"]["id"] for h in run("query", question, "--mode", "vector")["results"]] == ["refund"]
        fresh_records = json.loads((root / ".repo-knowledge/knowledge.json").read_text())["records"]
        with patch.object(vectors, "embedder", side_effect=AssertionError("Unexpected embedder")):
            deleted = vectors.build(root, {"refund": fresh_records["refund"]})
        assert deleted["indexed"] == 1
        assert deleted["embedded"] == 0
        assert deleted["deleted"] == 1
        assert deleted["unchanged"] == 1
        assert deleted["rebuilt"] is False
        assert run("query", "취소한 결제 금액을 돌려받기", "--mode", "vector")["results"][0]["record"]["id"] == "refund"
        run("drop", "refund")
        assert run("query", question, "--mode", "vector")["results"] == []
        final = run("index")
        assert final["indexed"] == 0
        assert final["embedded"] == 0
        assert final["deleted"] == 1
        assert final["unchanged"] == 0
        assert final["rebuilt"] is False
    print("PASS: real Korean/English pgvector, hybrid, read-only/offline query, repo isolation, rollback, stale filtering before limit, replacement, deletion, rebuild")


if __name__ == "__main__":
    main()
