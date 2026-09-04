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
