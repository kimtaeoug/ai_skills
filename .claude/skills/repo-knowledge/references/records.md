# Record contract

The portable folder can be copied to either runtime's skill directory without
rewriting instructions. `knowledge.py --help` lists commands. Pass `--repo` before
the command. `source` and `query` never write; `init`, `put`, `refresh`, `drop` do.

## Storage and ontology

`.repo-knowledge/knowledge.json` contains `version: 1`, `ontology`, and `records`
(an object keyed by record ID). These are local, reviewable project artifacts;
commit/share them only according to the target repository's policy. No remote
service receives data from the helper. The host agent still reads retrieved text.

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

`query` ranks case-insensitive query-term matches in summaries, aliases, endpoint
IDs and relation names. It appends fresh one-hop neighbors, then returns bounded
results and current excerpts. The caller turns those into a cited answer or plan.
This is local lexical RAG; there is no automatic AST extraction, embedding service,
cross-language semantic matcher or exhaustive call-graph guarantee.

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
