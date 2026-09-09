# Record contract

The portable folder can be copied to either runtime's skill directory without
rewriting instructions. `knowledge.py --help` lists commands. Pass `--repo` before
the command. `source` and `query` never write; `init`, `put`, `refresh`, `drop` do.
`index` writes only the derived PostgreSQL vector index.
`extract <path>` calls local Ollama and returns draft records without storing them.

## Storage and ontology

`.repo-knowledge/knowledge.json` contains `version: 1`, `ontology`, and `records`
(an object keyed by record ID). These are local, reviewable project artifacts;
commit/share them only according to the target repository's policy. Embeddings
are computed locally; vectors, record IDs and fingerprints are sent only to the
configured PostgreSQL database. The first `index` may download the embedding
model. The host agent still reads retrieved text.

PostgreSQL storage is derived, not canonical. The helper uses
`REPO_KNOWLEDGE_DSN` when set, otherwise database `repo_knowledge`; never store
credentials in the repository. Rows live under schema `repo_knowledge` and
are scoped by SHA-256 of the resolved absolute Git root. The vector column is
`vector(384)`, produced by FastEmbed 0.8.0 with the local multilingual
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model. There is no
SQLite index.

The default ontology's entity types are `module`, `symbol`, `concept`, `document`,
`test`, and `config`. Each relation has `from` and `to` lists of allowed types:

| Relation | Subject → object | Meaning |
| --- | --- | --- |
| `calls` | symbol → symbol | Direct call verified from implementation |
| `depends_on` | any → any | Explain the concrete dependency in the summary |
| `implements` | module/symbol → concept | Code realizes a domain concept or rule |
| `documents` | document → any | Describes intended or documented behavior |
| `tests` | test → module/symbol/concept | Test asserts behavior; not proof it passed |
| `configures` | config → module/symbol/concept | Setting controls this entity |

Node identity is `(type, id)`. Use repository-relative `path:symbol` for symbols,
paths for files/modules, and stable domain names for concepts. Two unrelated
packages' same-named symbols must not share an ID. Relations form the knowledge
graph; the ontology defines their vocabulary and valid endpoint types.

For a required new relation/type, edit `ontology` with the repository's normal
file tools, preserving records; run `status` to validate afterward. Migrate affected
records together when removing or restricting a type. A structurally valid graph
does not prove its semantic claims.

## Complete example

Suppose the inspected file `payment.py` contains:

```python
def charge():
    return "paid"
```

Run `source payment.py --start 1 --end 2`. Read its returned `text`, then assemble
the following JSON array in a temporary file **outside the target repository**.
Replace `SHA256_FROM_SOURCE` with the returned `sha256`; it is deliberately not
valid evidence until replaced. Never recompute a hash to relabel an old summary
as reviewed. If `put` reports stale evidence, read and interpret the file again.

```json
[
  {
    "id": "payment-charge",
    "subject": {"id": "payment.py:charge", "type": "symbol"},
    "relation": "implements",
    "object": {"id": "payment", "type": "concept"},
    "summary": "charge currently returns the literal paid; no provider call appears in this function.",
    "aliases": ["결제", "charge", "payment"],
    "epistemic": "inferred",
    "rationale": "The function name suggests the payment concept; its body only establishes the literal return value.",
    "evidence": [
      {"path": "payment.py", "start": 1, "end": 2, "sha256": "SHA256_FROM_SOURCE", "symbol": "charge"}
    ]
  }
]
```

Run `put <temporary-json-file>`, then `query '결제'`. The CLI adds `indexed_commit`
(null for an unborn repository). Record `id` is an upsert key; reusing it replaces
that record, never the entire store. Duplicate IDs in one batch are rejected.
All records in a batch are validated before saving. Updates use an exclusive
writer lock and atomic replacement. A crash can leave `.write-lock`; inspect the
owning activity before removing that lock. Do not run concurrent direct JSON edits.
Run `index` after `put`, `refresh` or `drop` to transactionally rebuild this
repository's derived vectors from the current fresh records.

For a first draft, run `extract payment.py --max-records 4`. It sends the selected
numbered source range to local Ollama at `127.0.0.1:11434`, using
`qwen2.5-coder:7b` unless `REPO_KNOWLEDGE_OLLAMA_MODEL` names another installed
generation model. The response uses a JSON Schema derived from the current
ontology, then the helper validates endpoint types, line bounds and record shape.
These checks cannot prove a summary is true. Read every cited line, remove invented
effects or missing prerequisites, and save only accepted `records` as the JSON array
given to `put`. Source edits during extraction cause `put` to reject the old hash.
Some CLI `workspace-write` sandboxes block localhost. In that case the helper
returns an explicit sandbox error; allow localhost for the command or run
`extract` outside that sandbox, then continue the same review-before-`put` flow.

Every record has a nonempty ID/summary, typed subject/object, valid relation,
`observed` or `inferred` epistemic label, and one or more evidence entries.
`aliases` and evidence `symbol` are optional; inferred records require `rationale`.
`observed` means the stated relationship is directly supported, not that the code
was executed. Preserve documentation/implementation conflicts as separate claims.
Do not persist a passing-test claim solely from the test's source text.

## Freshness, retrieval, scope

`status` compares evidence hashes to current UTF-8 working-tree files from Git's
tracked and nonignored untracked inventory. Deletion, changed contents, invalid
line ranges, ignored untracked files or exclusions invalidate evidence. A fresh
uncommitted file is usable after review; HEAD changing alone does not invalidate it.
Renames act as missing old sources plus new unrepresented files. Binary files,
symlinks, common secrets, generated directories, lockfiles and files over 1 MiB are
excluded. Submodules/nested repositories require a separately declared scope.

`query --mode lexical` ranks case-insensitive query-term matches in summaries,
aliases, endpoint IDs and relation names. `query --mode vector` searches exact
cosine distance over the derived pgvector rows. `query --mode hybrid` combines
both, and `query --mode auto` uses hybrid when the PostgreSQL index is accessible
or reports a lexical fallback. Explicit vector and hybrid modes fail when the
database, extension, index or cached model is unavailable. Results append fresh
one-hop neighbors, then return bounded records and current excerpts. The caller
turns those into a cited answer or plan. There is no automatic AST extraction,
remote embedding service or exhaustive call-graph guarantee.

Every vector candidate must match current evidence hashes and the complete JSON
record fingerprint before `--limit` is applied. Changed, deleted or replaced
records cannot be returned from stale vectors. Query never mutates
`knowledge.json`, the repository, the database schema or vector rows, and never
downloads the model; the first `index` may download the roughly 0.22 GB model to
FastEmbed's cache. Semantic similarity is not proof or certainty. No HNSW index is
created yet.

`evidence_files` means cited files, not full review. `unrepresented_files` and
`excluded_files` expose gaps. `refresh` invalidates by source content; it cannot
detect an unchanged document becoming conceptually wrong after another file changes.
The agent must examine related records and cite all prerequisite sources when
capturing a derived fact. Preserve evidence gaps instead of promoting guesses.

## Routine-use binding

`init` adds/replaces only its marked section in root `AGENTS.md` and `CLAUDE.md`,
and also an existing root `AGENTS.override.md`. Other text and existing knowledge
are preserved. It rejects malformed/duplicate markers and symlinked instruction
files; use a reviewed manual merge of the same pointer if such a layout is intended.
Nested overrides, runtime instruction limits, or disabled project instructions
can suppress consultation. Inspect the active instructions in the target scope.
Bindings guide the agent; they do not enforce actions with hooks. Reopen the
session when needed to load newly installed skills/project instructions.

## Optional vector setup

Legacy lexical retrieval works with Python 3.9+ and stdlib only. For vector or
hybrid retrieval, use Python 3.11 with the skill-local venv:

```bash
cd ~/.claude/skills/repo-knowledge
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
createdb repo_knowledge
```

Skip `createdb` if the database already exists, or set `REPO_KNOWLEDGE_DSN` for a
different configured PostgreSQL database. `index` runs `CREATE EXTENSION IF NOT
EXISTS vector`; that requires permission, otherwise a DBA must install pgvector
first.
