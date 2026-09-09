#!/usr/bin/env python3
"""Run: python3 tests/test-repo-knowledge.py (stdlib, isolated Git repository)."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/repo-knowledge/scripts/knowledge.py"


def main():
    assert SCRIPT.is_file(), "repo-knowledge CLI has not been implemented"
    with tempfile.TemporaryDirectory(prefix="repo knowledge ") as directory:
        root = Path(directory)

        def git(*args):
            return subprocess.run(["git", "-C", directory, *args], check=True, capture_output=True)

        def run(*args, ok=True):
            result = subprocess.run([sys.executable, str(SCRIPT), "--repo", directory, *args],
                                    capture_output=True, text=True)
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        git("init", "-q")
        (root / "payment.py").write_text("def charge():\n    return 'paid'\n", encoding="utf-8")
        (root / "test_payment.py").write_text("assert charge() == 'paid'\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("Keep original rules.\n", encoding="utf-8")
        (root / "CLAUDE.md").write_bytes(b"Keep Claude rules.\r\n")
        (root / "AGENTS.override.md").write_text("Active override.\n", encoding="utf-8")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
        run("init")
        agents = (root / "AGENTS.md").read_bytes()
        claude = (root / "CLAUDE.md").read_bytes()
        run("init")
        assert agents == (root / "AGENTS.md").read_bytes()
        assert agents.startswith(b"Keep original rules.\n")
        assert claude == (root / "CLAUDE.md").read_bytes()
        assert claude.startswith(b"Keep Claude rules.\r\n")
        assert (root / "AGENTS.override.md").read_text().startswith("Active override.\n")
        evidence = run("source", "payment.py", "--start", "1", "--end", "2")
        assert "def charge" in evidence.pop("text")
        record = {
            "id": "payment-charge", "subject": {"id": "payment.py:charge", "type": "symbol"},
            "relation": "implements", "object": {"id": "payment", "type": "concept"},
            "summary": "Charge implements 결제 payment.", "aliases": ["결제"],
            "epistemic": "observed", "evidence": [evidence],
        }
        batch = root / "input.json"

        def put(records, ok=True):
            batch.write_text(json.dumps(records), encoding="utf-8")
            return run("put", str(batch), ok=ok)

        put([record])
        test_evidence = run("source", "test_payment.py", "--start", "1", "--end", "1")
        test_evidence.pop("text")
        related = {**copy.deepcopy(record), "id": "charge-test",
                   "subject": {"id": "test_payment.py", "type": "test"}, "relation": "tests",
                   "object": record["subject"], "summary": "Covers successful result.",
                   "aliases": [], "evidence": [test_evidence]}
        put([related])
        hits = run("query", "결제")["results"]
        assert [h["record"]["id"] for h in hits] == ["payment-charge", "charge-test"]
        assert hits[1]["match"] == "neighbor"
        assert len(run("query", "결제", "--limit", "1")["results"]) == 1
        assert run("query", "unmatchedword")["results"] == []
        run("query", "결제", "--limit", "0", ok=False)
        before = (root / ".repo-knowledge/knowledge.json").read_bytes()
        malformed = {**record, "relation": "invented"}
        put([malformed], ok=False)
        traversal = copy.deepcopy(record)
        traversal["evidence"][0]["path"] = "../outside.py"
        put([traversal], ok=False)
        inferred = {**record, "epistemic": "inferred"}
        put([inferred], ok=False)
        for rationale in (None, 42, [], "   "):
            put([{**inferred, "rationale": rationale}], ok=False)
        assert before == (root / ".repo-knowledge/knowledge.json").read_bytes()
        (root / ".env").write_text("SECRET=do-not-index\n", encoding="utf-8")
        git("add", ".env")
        run("source", ".env", ok=False)
        (root / "escape.py").symlink_to(root.parent / "outside.py")
        run("source", "escape.py", ok=False)
        (root / "test_payment.py").write_text("assert charge() != 'paid'\n", encoding="utf-8")
        assert [h["record"]["id"] for h in run("query", "결제")["results"]] == ["payment-charge"]
        (root / "payment.py").write_text("def charge():\n    return 'failed'\n", encoding="utf-8")
        (root / "test_payment.py").unlink()
        (root / "billing.py").write_text("retries = 0\n", encoding="utf-8")
        state = run("status")
        assert set(state["stale"]) == {"payment-charge", "charge-test"}
        assert "billing.py" in state["unrepresented_files"]
        assert ".env" not in state["unrepresented_files"]
        assert run("query", "결제")["results"] == []
        put([record], ok=False)  # Old content cannot be stamped as freshly reviewed.
        refreshed = run("refresh")
        assert set(refreshed["invalidated"]) == {"payment-charge", "charge-test"}
        evidence = run("source", "payment.py", "--start", "1", "--end", "2")
        evidence.pop("text")
        record["evidence"] = [evidence]
        record["summary"] = "결제 now returns failed."
        put([record])
        assert len(run("query", "결제")["results"]) == 1  # Dirty but reviewed is valid.
        (root / "payment.py").unlink()
        (root / "payment.py").symlink_to("billing.py")
        assert run("status")["stale"] == {"payment-charge": ["payment.py"]}
        assert run("query", "결제")["results"] == []
        assert run("refresh")["invalidated"] == {"payment-charge": ["payment.py"]}
        (root / "payment.py").unlink()
        (root / "payment.py").write_text("def charge():\n    return 'failed'\n", encoding="utf-8")
        put([record])
        run("drop", "payment-charge")
        assert run("query", "결제")["results"] == []
        (root / ".repo-knowledge/.write-lock").write_text("busy", encoding="utf-8")
        put([record], ok=False)
        (root / ".repo-knowledge/.write-lock").unlink()
        (root / "AGENTS.md").write_text("<!-- repo-knowledge:start -->\nbroken\n", encoding="utf-8")
        run("init", ok=False)
        assert "broken" in (root / "AGENTS.md").read_text()
        for i in range(25):
            (root / ("extra%d.py" % i)).write_text("value = 1\n", encoding="utf-8")
        query_status = run("query", "결제")["status"]
        assert len(query_status["unrepresented_files"]) <= 20
        assert query_status["unrepresented_files_count"] >= 25
    print("PASS: ingest, retrieval, graph, freshness, coverage gaps, safety, binding, writer lock")


if __name__ == "__main__":
    main()
