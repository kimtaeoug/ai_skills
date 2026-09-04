---
name: agent-context-setup
description: Enable agent-context in the current Git repository. Use when the user explicitly asks to set up shared agent context, or after the onboarding hook says it is not set up.
---

# Agent context setup

Run this skill's adjacent installer against the current repository root:

```bash
"$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/install.sh" "$(git rev-parse --show-toplevel)"
```

The installer vendors the runtime into `.agent-context/`, initializes the separate bare context store, and merges the Claude Code and Codex lifecycle-hook configuration. Report its created or modified paths.

## Domain analysis

After the installer succeeds, check whether a domain summary already exists:

```bash
.agent-context/agent-context.sh domain-show --target "$(git rev-parse --show-toplevel)"
```

If it prints anything other than `No domain analysis yet for this repo.`, a domain summary already exists — skip analysis and tell the user it's already set (mention they can ask you to redo it if the repo has changed significantly).

Otherwise, analyze the repository yourself, with a **bounded** read:

- `README*` at the repository root.
- Top-level manifest files that exist (e.g. `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`).
- The directory structure two levels deep at most.
- Do **not** recursively read the whole tree — this is a quick orientation summary, not a full audit.

Write a summary in exactly this format, one confidence label per section from `high | medium | low | insufficient evidence`. Never state a business fact (company name, target users, business model) that isn't actually written in the files you read — if the evidence is thin, say `insufficient evidence` instead of guessing:

```
## Business domain
<what this repository is for, based only on what you read>
confidence: <high|medium|low|insufficient evidence>

## Technical stack
<languages/frameworks/architecture style you actually detected>
confidence: <high|medium|low|insufficient evidence>
```

Save it:

```bash
printf '%s\n' "$SUMMARY" | .agent-context/agent-context.sh domain-set --target "$(git rev-parse --show-toplevel)"
```

If any step in this Domain analysis section fails, do not treat the overall setup as failed — the installer already succeeded independently. Report that domain analysis failed and that `domain-set` can be retried manually later.
