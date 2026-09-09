"""Pure incremental review planning for repository knowledge."""
import copy
import hashlib
import json
import re


HEX = re.compile(r"[0-9a-f]{64}")


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _operational(path):
    return path == ".repo-knowledge" or path.startswith(".repo-knowledge/")


def _sync(data):
    sync = data.get("sync", {"version": 1, "reviewed_files": {}})
    if not isinstance(sync, dict):
        raise ValueError("Invalid sync metadata")
    if type(sync.get("version")) is not int or sync.get("version") != 1 or not isinstance(sync.get("reviewed_files"), dict):
        raise ValueError("Invalid sync metadata")
    for path, digest in sync["reviewed_files"].items():
        _valid_path(path)
        if not isinstance(digest, str) or not HEX.fullmatch(digest):
            raise ValueError("Invalid reviewed file SHA-256")
    return sync


def _valid_path(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ".." in path.split("/"):
        raise ValueError("Expected a repository-relative POSIX path")


def _record_paths(record):
    return {source["path"] for source in record["evidence"]}


def _entities(record):
    return {(record[side]["type"], record[side]["id"]) for side in ("subject", "object")}


def _fresh(record, sources):
    return all(source["path"] in sources
               and sources[source["path"]][1] == source["sha256"]
               and source["end"] <= len(sources[source["path"]][0].splitlines())
               for source in record["evidence"])


def _evidence_hashes(data):
    hashes = {}
    for record in data["records"].values():
        for source in record["evidence"]:
            hashes.setdefault(source["path"], set()).add(source["sha256"])
    return hashes


def _before_hash(path, reviewed, evidence_hashes):
    if path in reviewed:
        return reviewed[path]
    hashes = evidence_hashes.get(path, set())
    return next(iter(hashes)) if len(hashes) == 1 else None


def _kind(path, reviewed, evidence_hashes, sources, excluded):
    if path in excluded:
        return "unavailable"
    if path not in sources:
        return "missing"
    if path not in reviewed:
        return "unreviewed"
    before = _before_hash(path, reviewed, evidence_hashes)
    if before is None:
        return "unreviewed"
    if before != sources[path][1]:
        return "modified"
    return "review"


def snapshot_token(data, sources, excluded):
    visible_excluded = sorted(path for path in excluded if not _operational(path))
    source_hashes = {path: digest for path, (_, digest) in sorted(sources.items())}
    return hashlib.sha256(_canon({"data": data, "sources": source_hashes,
                                  "excluded": visible_excluded})).hexdigest()


def make_plan(data, sources, excluded, selected_paths=None):
    sync = _sync(data)
    reviewed = sync["reviewed_files"]
    evidence_paths = {path for record in data["records"].values() for path in _record_paths(record)}
    evidence_hashes = _evidence_hashes(data)
    excluded_set = set(excluded)
    candidates = {path for path in set(reviewed) | evidence_paths | set(sources) if not _operational(path)}
    selected = []
    if selected_paths is None:
        for path in candidates:
            kind = _kind(path, reviewed, evidence_hashes, sources, excluded_set)
            if kind != "review":
                selected.append(path)
    else:
        if len(set(selected_paths)) != len(selected_paths):
            raise ValueError("Duplicate selected path")
        for path in selected_paths:
            _valid_path(path)
            if _operational(path):
                raise ValueError("Operational paths cannot be selected: " + path)
            if path not in candidates and path not in excluded_set:
                raise ValueError("Unknown path: " + path)
        selected = list(selected_paths)
    selected = sorted(selected)
    changes = []
    for path in selected:
        kind = _kind(path, reviewed, evidence_hashes, sources, excluded_set)
        changes.append({"path": path, "kind": kind, "before": _before_hash(path, reviewed, evidence_hashes),
                        "after": sources[path][1] if path in sources else None})

    direct = sorted(record_id for record_id, record in data["records"].items()
                    if _record_paths(record) & set(selected))
    direct_entities = set()
    for record_id in direct:
        direct_entities.update(_entities(data["records"][record_id]))
    related = sorted(record_id for record_id, record in data["records"].items()
                     if record_id not in direct and _entities(record) & direct_entities)

    missing = {path: reviewed.get(path) for path in selected if path not in sources and path not in excluded_set}
    old_by_hash = {}
    for path, digest in reviewed.items():
        if path not in sources and digest:
            old_by_hash.setdefault(digest, []).append(path)
    by_hash = {}
    for path, (_, digest) in sources.items():
        if path not in reviewed:
            by_hash.setdefault(digest, []).append(path)
    hints = []
    for old, digest in sorted(missing.items()):
        if digest and len(old_by_hash.get(digest, [])) == 1 and len(by_hash.get(digest, [])) == 1:
            hints.append({"from": old, "to": by_hash[digest][0], "sha256": digest})

    remaining = []
    for path in sorted(candidates - set(selected)):
        if _kind(path, reviewed, evidence_hashes, sources, excluded_set) != "review":
            remaining.append(path)
    return {"version": 1, "base_token": snapshot_token(data, sources, excluded),
            "selected_paths": selected, "changes": changes, "direct_ids": direct,
            "related_ids": related, "rename_hints": hints,
            "excluded_paths": sorted(path for path in excluded if not _operational(path)),
            "remaining_paths": remaining, "stored": False}


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " requires nonempty string")


def _review_maps(review):
    if not isinstance(review, dict):
        raise ValueError("Review must be an object")
    if type(review.get("version")) is not int or review.get("version") != 1 or not HEX.fullmatch(str(review.get("base_token", ""))):
        raise ValueError("Invalid review metadata")
    for key in ("selected_paths", "files", "decisions", "records"):
        if not isinstance(review.get(key), list):
            raise ValueError("Review " + key + " must be a list")
    if len(set(review["selected_paths"])) != len(review["selected_paths"]):
        raise ValueError("Duplicate selected path")
    for path in review["selected_paths"]:
        _valid_path(path)

    files = {}
    for item in review["files"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid review file")
        path = item.get("path")
        _valid_path(path)
        if path in files:
            raise ValueError("Duplicate reviewed file")
        digest = item.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not HEX.fullmatch(digest)):
            raise ValueError("Invalid reviewed file SHA-256")
        _nonempty(item.get("review_reason"), "File review")
        files[path] = digest

    decisions = {}
    for item in review["decisions"]:
        if not isinstance(item, dict) or item.get("action") not in {"replace", "drop", "keep"}:
            raise ValueError("Invalid decision")
        record_id = item.get("id")
        _nonempty(record_id, "Decision id")
        if record_id in decisions:
            raise ValueError("Duplicate decision")
        _nonempty(item.get("review_reason"), "Decision review")
        decisions[record_id] = item["action"]

    records = {}
    for record in review["records"]:
        if not isinstance(record, dict):
            raise ValueError("Invalid record")
        record_id = record.get("id")
        _nonempty(record_id, "Record id")
        if record_id in records:
            raise ValueError("Duplicate review record")
        records[record_id] = record
    return files, decisions, records


def apply_review(data, sources, excluded, review):
    files, decisions, records = _review_maps(review)
    if snapshot_token(data, sources, excluded) != review.get("base_token"):
        raise ValueError("Sync snapshot changed; rerun sync-plan")
    plan = make_plan(data, sources, excluded, review["selected_paths"])
    selected = set(plan["selected_paths"])
    if set(files) != selected:
        raise ValueError("Reviewed files must exactly match selected paths")
    for path, digest in files.items():
        expected = sources[path][1] if path in sources else None
        if digest != expected:
            raise ValueError("Reviewed file hash changed: " + path)
    impacted = set(plan["direct_ids"]) | set(plan["related_ids"])
    if set(decisions) != impacted:
        raise ValueError("Decisions must exactly match impacted records")
    for record_id, action in decisions.items():
        if action == "keep" and not _fresh(data["records"][record_id], sources):
            raise ValueError("Cannot keep stale record: " + record_id)
        if action == "replace" and record_id not in records:
            raise ValueError("Replacement record missing: " + record_id)
        if action != "replace" and record_id in records:
            raise ValueError("Only replace decisions may include same-id records")
    for record_id in records:
        if record_id in data["records"] and record_id not in impacted:
            raise ValueError("Cannot overwrite non-impacted record: " + record_id)
    for record_id, record in records.items():
        paths = _record_paths(record)
        if record_id not in data["records"] and not paths & selected:
            raise ValueError("New records require selected evidence: " + record_id)
        if not _fresh(record, sources):
            raise ValueError("Evidence changed or invalid; re-read source for " + record_id)

    new_data = copy.deepcopy(data)
    new_data.setdefault("sync", {"version": 1, "reviewed_files": {}})
    for record_id, action in sorted(decisions.items()):
        if action in {"replace", "drop"}:
            new_data["records"].pop(record_id, None)
    for record_id, record in sorted(records.items()):
        new_data["records"][record_id] = copy.deepcopy(record)
    for path in selected:
        if path in sources:
            new_data["sync"]["reviewed_files"][path] = sources[path][1]
        else:
            new_data["sync"]["reviewed_files"].pop(path, None)
    next_plan = make_plan(new_data, sources, excluded)
    return new_data, {"applied": True, "stored_ids": sorted(records),
                      "dropped_ids": sorted(k for k, v in decisions.items() if v == "drop"),
                      "kept_ids": sorted(k for k, v in decisions.items() if v == "keep"),
                      "reviewed_paths": sorted(selected),
                      "remaining_paths": next_plan["selected_paths"],
                      "vectors_next": "Run index"}
