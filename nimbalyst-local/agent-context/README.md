# agent-context

`agent-context.sh` shares Claude Code and Codex CLI context through a separate bare Git repository at `<target-git-common-dir>/agent-context.git`. It never creates refs or objects in the target development repository.

Run commands from any directory; `--target` defaults to the current directory.

```bash
CLI=/Users/deratio/skills/nimbalyst-local/agent-context/agent-context.sh
REPO=/path/to/development-repo

# Create (or verify) the isolated bare store.
"$CLI" init --target "$REPO"

# Append a plan, decision, or summary. Event body comes from stdin.
printf '%s\n' 'Implement the parser first.' |
  "$CLI" append claude plan --session claude-42 --target "$REPO"

printf '%s\n' 'Use native Git plumbing only.' |
  "$CLI" append codex decision --responds-to <commit-oid> --target "$REPO"

# Append a self-contained handoff checkpoint. Its covers_through field is set to its parent.
printf '%s\n' 'goal: ship the CLI
confirmed decisions/invariants: separate bare repo
completed work: parser done
active plan: add resume
next action: test it
open questions: none' |
  "$CLI" checkpoint codex --target "$REPO"

# Rebuild the agent's current context: latest checkpoint body, then later events.
"$CLI" resume codex --target "$REPO"

# Debug the agent's first-parent history and inspect both persistent tips.
"$CLI" log codex --target "$REPO"
"$CLI" status --target "$REPO"
```

The only allowed agents are `claude` and `codex`; event types are `plan`, `decision`, `summary`, and `checkpoint`. Appends use an expected-old-value `git update-ref` compare-and-swap. On a race, the script rereads the tip and rebuilds the commit with that new parent before retrying, so the ref only advances fast-forward.

After 20 non-checkpoint events since the last checkpoint, `append` automatically creates a source-backed checkpoint and reports its OID on stderr. Use `checkpoint` whenever a human or agent can provide the preferred concise rollup. Cross-clone remote syncing is intentionally not implemented.

## Workspace onboarding

This source package can install automatic context recovery into another Git repository. It does not install anything into this source workspace.

`hooks/onboard.sh <claude|codex>` is the target-repository hook entrypoint. It resolves the Git root, calls the vendored CLI's read-only `status --target <root>` to detect the store, then:

- prints a bounded `resume` result when the store exists;
- prints exactly `agent-context is not set up; invoke the agent-context-setup skill to enable it.` when it does not; and
- never calls `init` itself.

The hook keeps automatic injection below 8,000 characters. It preserves a checkpoint body and removes oldest replayed event blocks first, adding an omission note. A checkpoint body that alone exceeds that ceiling is not injected; the hook directs the agent to run `agent-context.sh resume` manually instead. `status` is deliberately non-mutating: use `init` to create a missing store.

The installable source artifacts are:

```text
SKILL.md
install.sh
bootstrap.sh
hooks/onboard.sh
templates/claude-settings.hooks.json
templates/codex-hooks.json
templates/codex-config-toml-fragment.toml
```

First, bootstrap this whole source package as a global skill. With no argument, it creates non-destructive symlinks under `~/.claude/skills/agent-context-setup` and `~/.codex/skills/agent-context-setup`; existing paths are reported and skipped. The optional base-directory argument is useful for testing.

```bash
PACKAGE=/path/to/nimbalyst-local/agent-context
"$PACKAGE/bootstrap.sh"
```

That makes `agent-context-setup` available in every workspace. On an explicit setup request (or after the hook's not-set-up suggestion), invoke the global skill. Its adjacent `install.sh` vendors the portable runtime into the target repository as `.agent-context/agent-context.sh` and `.agent-context/hooks/onboard.sh`, initializes the target's separate bare store, and merges hook configuration. Target repositories do not receive a copy of the setup skill.

The JSON files under `templates/` are fragments, not replacement configuration files. `install.sh` merges their `hooks.SessionStart` entry into existing `.claude/settings.json` and `.codex/hooks.json`, preserving unrelated keys and hook arrays. It uses `jq` when available, otherwise Python 3. The TOML merge is intentionally line-oriented rather than a full TOML parser: it finds or appends `[features]` and sets `hooks = true` plus the documented compatibility alias `codex_hooks = true`. Review unusual hand-written TOML after installation.

For Claude Code, `SessionStart` is matched only on `startup|resume`; the hook's stdout is session context, so the hard bound prevents Claude's 10,000-character hook-output spill behavior. For Codex, the template uses the simplest documented `SessionStart` form: plain stdout becomes extra developer context. Codex requires hook trust review for project-local hooks; open `/hooks` after installation and trust the new hook. Current Codex documentation names `[features].hooks` as canonical and `codex_hooks` as a supported deprecated alias, so the template sets both for compatibility.

The global skill uses standard YAML frontmatter (`name` and `description`) plus Markdown instructions. Its description is the invocation trigger: explicit setup requests or the hook's not-set-up suggestion. `SKILL.md` invokes its sibling `install.sh`, so the package is self-contained wherever it is symlinked or copied.

To run the end-to-end smoke test:

```bash
bash /Users/deratio/skills/nimbalyst-local/agent-context/smoke-test.sh
bash /Users/deratio/skills/nimbalyst-local/agent-context/onboarding-smoke-test.sh
```
