#!/usr/bin/env python3
"""Run: python3 tests/test-repo-knowledge-sync.py (stdlib, isolated Git repositories)."""
import copy
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock


HELPER = Path(__file__).resolve().parents[1] / ".claude/skills/repo-knowledge/scripts/knowledge.py"


def load_helper():
    sys.path.insert(0, str(HELPER.parent))
    spec = importlib.util.spec_from_file_location("repo_knowledge_helper", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    assert HELPER.is_file(), "repo-knowledge CLI has not been implemented"
    with tempfile.TemporaryDirectory(prefix="knowledge sync ") as directory:
        root = Path(directory)

        def git(*args):
            return subprocess.run(["git", "-C", directory, *args], check=True, capture_output=True)

        def run(*args, ok=True):
            result = subprocess.run([sys.executable, str(HELPER), "--repo", directory, *args],
                                    capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        def write_review(name, payload):
            path = root / ".repo-knowledge" / name
            path.write_text(json.dumps(payload), encoding="utf-8")
            return path

        def source_without_text(path, start=1, end=None):
            evidence = run("source", path, "--start", str(start), *(["--end", str(end)] if end else []))
            evidence.pop("text")
            return evidence

        def review_for(plan, files, decisions, records=None):
            return {"version": 1, "base_token": plan["base_token"],
                    "selected_paths": plan["selected_paths"], "files": files,
                    "decisions": decisions, "records": records or []}

        git("init", "-q")
        (root / "auth.py").write_text("LIMIT = 5\n", encoding="utf-8")
        (root / "test_auth.py").write_text("from auth import LIMIT\nassert LIMIT == 5\n", encoding="utf-8")
        (root / "readme.md").write_text("Auth limit is documented elsewhere.\n", encoding="utf-8")
        (root / ".env").write_text("SECRET=ignored\n", encoding="utf-8")
        (root / "ignored.log").write_text("ignored\n", encoding="utf-8")
        (root / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
        run("init")
        store = root / ".repo-knowledge/knowledge.json"
        auth_evidence = source_without_text("auth.py")
        test_evidence = source_without_text("test_auth.py")
        readme_evidence = source_without_text("readme.md")
        auth_record = {
            "id": "auth-limit", "subject": {"id": "auth.py:LIMIT", "type": "symbol"},
            "relation": "implements", "object": {"id": "login-retry-limit", "type": "concept"},
            "summary": "LIMIT is 5.", "aliases": [], "epistemic": "observed",
            "evidence": [auth_evidence],
        }
        test_record = {
            "id": "auth-test", "subject": {"id": "test_auth.py", "type": "test"},
            "relation": "tests", "object": {"id": "auth.py:LIMIT", "type": "symbol"},
            "summary": "The auth test covers LIMIT.", "aliases": [], "epistemic": "observed",
            "evidence": [test_evidence],
        }
        multi_record = {
            "id": "auth-multi", "subject": {"id": "auth.py:multi", "type": "symbol"},
            "relation": "implements", "object": {"id": "multi-limit", "type": "concept"},
            "summary": "A record can cite auth and docs together.", "aliases": [], "epistemic": "observed",
            "evidence": [auth_evidence, readme_evidence],
        }
        type_mismatch_record = {
            "id": "type-mismatch", "subject": {"id": "readme.md", "type": "document"},
            "relation": "documents", "object": {"id": "auth.py:LIMIT", "type": "concept"},
            "summary": "Same id string with a different type is not a graph neighbor.",
            "aliases": [], "epistemic": "observed", "evidence": [readme_evidence],
        }
        batch = root / ".repo-knowledge/input.json"
        batch.write_text(json.dumps([auth_record, test_record, multi_record, type_mismatch_record]),
                         encoding="utf-8")
        run("put", str(batch))
        original = json.loads(store.read_text(encoding="utf-8"))
        original_test_record = copy.deepcopy(original["records"]["auth-test"])
        before = store.read_bytes()
        for bad_sync in (None, [], True, {"version": 2, "reviewed_files": {}},
                         {"version": True, "reviewed_files": {}},
                         {"version": 1.0, "reviewed_files": {}},
                         {"version": 1, "reviewed_files": []}):
            broken = copy.deepcopy(original)
            broken["sync"] = bad_sync
            store.write_text(json.dumps(broken), encoding="utf-8")
            assert "Invalid sync metadata" in run("sync-plan", ok=False)
            assert "Invalid sync metadata" in run("status", ok=False)
            store.write_bytes(before)

        first = run("sync-plan", "--path", "auth.py")
        second = run("sync-plan", "--path", "auth.py")
        default = run("sync-plan")
        assert ".env" in default["excluded_paths"]
        assert all(c["path"] != ".env" for c in default["changes"])
        assert run("sync-plan", "--path", ".env")["changes"][0]["kind"] == "unavailable"
        assert "Operational paths cannot be selected" in run("sync-plan", "--path",
                                                             ".repo-knowledge/input.json", ok=False)
        assert first == second
        assert before == store.read_bytes()
        assert first["stored"] is False
        assert first["changes"][0]["kind"] == "unreviewed"
        assert first["direct_ids"] == ["auth-limit", "auth-multi"]
        assert first["related_ids"] == ["auth-test"]
        assert "type-mismatch" not in first["related_ids"]
        assert first["remaining_paths"]

        baseline_review = review_for(first, [{"path": "auth.py", "sha256": auth_evidence["sha256"],
                                             "review_reason": "Reviewed the full file."}],
                                     [{"id": "auth-limit", "action": "keep",
                                       "review_reason": "The stored fact matches current source."},
                                      {"id": "auth-multi", "action": "keep",
                                       "review_reason": "Both evidence files are current."},
                                      {"id": "auth-test", "action": "keep",
                                       "review_reason": "Related test remains current."}],
                                     [])
        run("sync-apply", str(write_review("baseline.json", baseline_review)))

        (root / "auth.py").write_text("LIMIT = 6\n", encoding="utf-8")
        plan = run("sync-plan", "--path", "auth.py")
        assert plan["changes"][0]["kind"] == "modified"
        current = source_without_text("auth.py")
        replacement = copy.deepcopy(auth_record)
        replacement["summary"] = "LIMIT is 6."
        replacement["evidence"] = [current]
        replacement_multi = copy.deepcopy(multi_record)
        replacement_multi["summary"] = "The multi-evidence record was reviewed after auth changed."
        replacement_multi["evidence"] = [current, readme_evidence]
        ok_review = review_for(plan, [{"path": "auth.py", "sha256": current["sha256"],
                                      "review_reason": "Reviewed the full file."}],
                               [{"id": "auth-limit", "action": "replace",
                                 "review_reason": "The constant changed."},
                                {"id": "auth-multi", "action": "replace",
                                 "review_reason": "One evidence file changed, so the record was reviewed."},
                                {"id": "auth-test", "action": "keep",
                                 "review_reason": "Read the current test; it imports the same symbol."}],
                               [replacement, replacement_multi])

        for name, payload in {
            "missing.json": {**ok_review, "decisions": ok_review["decisions"][:1]},
            "duplicate.json": {**ok_review, "decisions": ok_review["decisions"] + [ok_review["decisions"][0]]},
            "bad-hash.json": {**ok_review, "files": [{**ok_review["files"][0], "sha256": "0" * 64}]},
            "replace-missing.json": {**ok_review, "records": []},
            "unrelated-overwrite.json": {**ok_review, "records": [copy.deepcopy(original_test_record)]},
            "bad-endpoint.json": {**ok_review, "records": [{**replacement,
                "subject": {"id": "auth.py:LIMIT", "type": "test"}}, replacement_multi]},
        }.items():
            snapshot = store.read_bytes()
            run("sync-apply", str(write_review(name, payload)), ok=False)
            assert store.read_bytes() == snapshot
        run("sync-apply", str(write_review("not-object.json", [])), ok=False)
        for bad_version in (True, 1.0):
            snapshot = store.read_bytes()
            run("sync-apply", str(write_review("bad-version.json", {**ok_review,
                                                                    "version": bad_version})), ok=False)
            assert store.read_bytes() == snapshot

        result = run("sync-apply", str(write_review("review.json", ok_review)))
        saved = json.loads(store.read_text(encoding="utf-8"))
        assert result["stored_ids"] == ["auth-limit", "auth-multi"]
        assert result["kept_ids"] == ["auth-test"]
        assert saved["records"]["auth-test"] == original_test_record
        assert saved["sync"]["reviewed_files"]["auth.py"] == current["sha256"]
        assert "readme.md" not in saved["sync"]["reviewed_files"]
        assert result["vectors_next"] == "Run index"

        run("sync-apply", str(write_review("replay.json", ok_review)), ok=False)
        same_plan = run("sync-plan", "--path", "auth.py")
        same_review = review_for(same_plan, [{"path": "auth.py", "sha256": current["sha256"],
                                             "review_reason": "Reviewed again."}],
                                 [{"id": "auth-limit", "action": "keep",
                                   "review_reason": "Byte-identical review remains current."},
                                  {"id": "auth-multi", "action": "keep",
                                   "review_reason": "Multi-evidence record remains current."},
                                  {"id": "auth-test", "action": "keep",
                                   "review_reason": "Related record remains current."}],
                                 [])
        assert run("sync-apply", str(write_review("same.json", same_review)))["kept_ids"] == [
            "auth-limit", "auth-multi", "auth-test"]
        default_after_reviews = run("sync-plan")
        assert not any(c["path"].startswith(".repo-knowledge/")
                       for c in default_after_reviews["changes"])
        assert ".env" not in default_after_reviews["remaining_paths"]
        assert not any(path.startswith(".repo-knowledge/") for path in default_after_reviews["remaining_paths"])

        (root / "scratch.py").write_text("value = 1\n", encoding="utf-8")
        new_plan = run("sync-plan", "--path", "scratch.py")
        scratch = source_without_text("scratch.py")
        zero_fact = review_for(new_plan, [{"path": "scratch.py", "sha256": scratch["sha256"],
                                          "review_reason": "Reviewed; no durable facts."}],
                               [], [])
        run("sync-apply", str(write_review("zero.json", zero_fact)))
        assert all(c["path"] != "scratch.py" for c in run("sync-plan")["changes"])
        (root / "link.py").write_text("x = 1\n", encoding="utf-8")
        link_plan = run("sync-plan", "--path", "link.py")
        link_source = source_without_text("link.py")
        link_review = review_for(link_plan, [{"path": "link.py", "sha256": link_source["sha256"],
                                             "review_reason": "Reviewed; no durable facts."}], [], [])
        run("sync-apply", str(write_review("link.json", link_review)))
        (root / "link.py").unlink()
        (root / "link.py").symlink_to("readme.md")
        assert run("sync-plan", "--path", "link.py")["changes"][0]["kind"] == "unavailable"
        run("source", "link.py", ok=False)

        stale_plan = run("sync-plan", "--path", "readme.md")
        (root / "other.py").write_text("x = 1\n", encoding="utf-8")
        readme_source = source_without_text("readme.md")
        stale_review = review_for(stale_plan, [{"path": "readme.md", "sha256": readme_source["sha256"],
                                               "review_reason": "Reviewed docs."}],
                                  [], [])
        snapshot = store.read_bytes()
        assert "Sync snapshot changed" in run("sync-apply", str(write_review("stale.json", stale_review)), ok=False)
        assert store.read_bytes() == snapshot
        boundary_plan = run("sync-plan", "--path", "other.py")
        boundary_source = source_without_text("other.py")
        boundary_review = review_for(boundary_plan, [{"path": "other.py", "sha256": boundary_source["sha256"],
                                                     "review_reason": "Reviewed other source."}], [], [])
        snapshot = store.read_bytes()
        helper = load_helper()
        calls = []

        original_inventory = helper.inventory

        def inventory_with_edit(repo):
            calls.append(None)
            if len(calls) == 2:
                (root / "other.py").write_text("changed during sync\n", encoding="utf-8")
            return original_inventory(repo)
        with mock.patch.object(helper, "inventory", side_effect=inventory_with_edit):
            try:
                resolved_root = root.resolve()
                with helper.writer(resolved_root):
                    helper.execute(SimpleNamespace(command="sync-apply",
                                                   input=str(write_review("boundary.json", boundary_review))),
                                   resolved_root)
            except ValueError as error:
                assert "Sync snapshot changed" in str(error)
            else:
                raise AssertionError("sync-apply accepted a source edit before save")
        assert store.read_bytes() == snapshot

        git("checkout", "-qb", "changed")
        (root / "auth.py").write_text("LIMIT = 7\n", encoding="utf-8")
        assert run("sync-plan", "--path", "auth.py")["changes"][0]["kind"] == "modified"

        (root / "auth_copy.py").write_text("LIMIT = 7\n", encoding="utf-8")
        (root / "auth_twin.py").write_text("LIMIT = 7\n", encoding="utf-8")
        assert run("sync-plan", "--path", "auth.py")["rename_hints"] == []
        (root / "auth.py").rename(root / "renamed_auth.py")
        rename_plan = run("sync-plan")
        assert any(c["path"] == "auth.py" and c["kind"] == "missing" for c in rename_plan["changes"])
        assert {"from": "auth.py", "to": "renamed_auth.py", "sha256": current["sha256"]} not in rename_plan["rename_hints"]

        (root / "auth_copy.py").unlink()
        (root / "auth_twin.py").unlink()
        (root / "renamed_auth.py").write_text("LIMIT = 6\n", encoding="utf-8")
        hint_plan = run("sync-plan")
        assert {"from": "auth.py", "to": "renamed_auth.py", "sha256": current["sha256"]} in hint_plan["rename_hints"]

        drop_plan = run("sync-plan", "--path", "auth.py")
        assert drop_plan["direct_ids"] == ["auth-limit", "auth-multi"], drop_plan
        assert drop_plan["related_ids"] == ["auth-test"], drop_plan
        drop_review = review_for(drop_plan, [{"path": "auth.py", "sha256": None,
                                             "review_reason": "File is gone; drop stale fact."}],
                                 [{"id": "auth-limit", "action": "drop",
                                   "review_reason": "The evidence file was removed."},
                                  {"id": "auth-multi", "action": "drop",
                                   "review_reason": "One evidence file was removed."},
                                  {"id": "auth-test", "action": "drop",
                                   "review_reason": "The test now describes a removed symbol."}],
                                 [])
        run("sync-apply", str(write_review("drop.json", drop_review)))
        assert "auth-limit" not in json.loads(store.read_text(encoding="utf-8"))["records"]
        deleted_hits = {hit["record"]["id"] for hit in run("query", "LIMIT")["results"]}
        assert not (deleted_hits & {"auth-limit", "auth-multi", "auth-test"})

        scratch_record = {
            "id": "scratch", "subject": {"id": "scratch.py", "type": "module"},
            "relation": "implements", "object": {"id": "scratch-fact", "type": "concept"},
            "summary": "Scratch exists.", "aliases": [], "epistemic": "observed",
            "evidence": [source_without_text("scratch.py")],
        }
        batch.write_text(json.dumps([scratch_record]), encoding="utf-8")
        run("put", str(batch))
        run("drop", "scratch")
        assert "scratch.py" in json.loads(store.read_text(encoding="utf-8"))["sync"]["reviewed_files"]
        run("refresh")
        assert "scratch.py" in json.loads(store.read_text(encoding="utf-8"))["sync"]["reviewed_files"]

        (root / ".repo-knowledge/.write-lock").write_text("busy", encoding="utf-8")
        run("sync-apply", str(write_review("locked.json", zero_fact)), ok=False)
        assert (root / ".repo-knowledge/.write-lock").read_text(encoding="utf-8") == "busy"
        (root / ".repo-knowledge/.write-lock").unlink()

    with tempfile.TemporaryDirectory(prefix="knowledge guide ") as directory:
        root = Path(directory)

        def git2(*args):
            return subprocess.run(["git", "-C", directory, *args], check=True, capture_output=True)

        def run2(*args, ok=True):
            result = subprocess.run([sys.executable, str(HELPER), "--repo", directory, *args],
                                    capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        git2("init", "-q")
        (root / "AGENTS.md").write_text("Rules\n", encoding="utf-8")
        git2("add", ".")
        git2("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
        run2("init")
        guide = root / ".repo-knowledge/guide.md"
        guide.write_text("custom\n", encoding="utf-8")
        run2("init")
        assert guide.read_text(encoding="utf-8") == "custom\n"
        run2("init", "--update-guide")
        assert (root / ".repo-knowledge/guide.md.bak").read_text(encoding="utf-8") == "custom\n"
        assert "sync-plan" in guide.read_text(encoding="utf-8")
        before = guide.read_bytes()
        run2("init", "--update-guide", ok=False)
        assert guide.read_bytes() == before

    print("PASS: incremental sync plan/apply lifecycle, replay, locks, guide update")


if __name__ == "__main__":
    main()
