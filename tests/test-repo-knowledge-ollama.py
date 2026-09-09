#!/usr/bin/env python3
"""Real Ollama extraction check; requires qwen2.5-coder:7b on localhost."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.error import URLError

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/repo-knowledge/scripts/knowledge.py"
sys.path.insert(0, str(SCRIPT.parent))
import ollama_extract


def main():
    with patch.object(ollama_extract, "urlopen", side_effect=URLError(PermissionError("blocked"))):
        try:
            ollama_extract.request("/api/version")
            raise AssertionError("sandbox denial was accepted")
        except ValueError as error:
            assert "sandbox" in str(error).casefold(), error
    with tempfile.TemporaryDirectory(prefix="knowledge ollama ") as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", directory], check=True)
        source = root / "auth.py"
        source.write_text(
            "MAX_LOGIN_ATTEMPTS = 5\n\n"
            "def can_retry(failed_attempts):\n"
            "    return failed_attempts < MAX_LOGIN_ATTEMPTS\n",
            encoding="utf-8",
        )

        def run(*args, ok=True):
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", directory, *args],
                capture_output=True, text=True, timeout=240,
                env={**os.environ, "REPO_KNOWLEDGE_OLLAMA_MODEL":
                     os.environ.get("REPO_KNOWLEDGE_OLLAMA_MODEL", "qwen2.5-coder:7b")},
            )
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        run("init")
        extracted = run("extract", "auth.py", "--max-records", "2")
        assert extracted["stored"] is False
        assert extracted["model"] == os.environ.get(
            "REPO_KNOWLEDGE_OLLAMA_MODEL", "qwen2.5-coder:7b")
        assert 1 <= len(extracted["records"]) <= 2
        assert run("status")["records"] == 0
        assert any("MAX_LOGIN_ATTEMPTS" in record["summary"]
                   for record in extracted["records"]), extracted
        assert all(record["subject"]["type"] != "document"
                   for record in extracted["records"]), extracted
        batch = root / "accepted.json"
        batch.write_text(json.dumps(extracted["records"]), encoding="utf-8")
        stored = run("put", str(batch))
        assert set(stored["stored"]) == {record["id"] for record in extracted["records"]}
        assert run("status")["records"] == len(extracted["records"])
        assert run("query", "login retry", "--mode", "lexical")["results"]
        for record in extracted["records"]:
            assert record["evidence"][0]["path"] == "auth.py"
            assert record["evidence"][0]["sha256"]
            assert 1 <= record["evidence"][0]["start"] <= record["evidence"][0]["end"] <= 4
            assert "indexed_commit" not in record
        batch = root / "reviewed.json"
        batch.write_text(json.dumps(extracted["records"]), encoding="utf-8")
        stored = run("put", str(batch))
        assert set(stored["stored"]) == {record["id"] for record in extracted["records"]}
        assert run("query", "login attempts", "--mode", "lexical")["results"]

        run("extract", "missing.py", ok=False)
        run("extract", "auth.py", "--start", "4", "--end", "2", ok=False)
    print("PASS: real Ollama structured extraction, review-before-put, evidence validation, accepted-record retrieval")


if __name__ == "__main__":
    main()
