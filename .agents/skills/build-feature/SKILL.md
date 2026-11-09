---
name: build-feature
description: Implement or repair a feature with the AI Engineering Nest Python orchestrator, public RED/GREEN TDD, named session handoffs, independent verification and risk-based security review.
---

# Build Feature

This skill **invokes** AI Nest. It is not the orchestrator and does not decide which agents run. Do not imitate agents in chat or skip the CLI's deterministic gates.

## Inputs

Use the user's exact feature request. Accept an optional descriptive `--session` name, repository root and requested provider (`codex` default; `claude` supported).

## Preflight

1. From the project root verify `AGENTS.md`, `nest.config.json`, `ai_nest/cli.py`, `ai_nest/memory.py`, `scripts/verify.sh`, `scripts/verify.py` and `scripts/verify.config.json` exist. **If missing, stop; do not invent the runtime.** Install the complete release using its root `install.py`; the installed repository also keeps an installer copy for inspection and future deployment.
2. Read `AGENTS.md`, `nest.config.json` and `AI_NEST_README.md`. `AGENTS.md` contains shared instructions; the Python CLI is the enforcement engine.
3. Run `python ai_nest/cli.py doctor` to check the installation manifest and stale configuration, then confirm Git has a committed `HEAD` and a clean tracked/untracked source state. Commit configuration before starting (a `--local` install keeps Nest files in `.git/info/exclude`, so there is nothing to commit); `.ai-nest/`, `__pycache__/`, `node_modules/` and other generated files belong in `.gitignore`.
4. Execute `bash scripts/verify.sh --list` and `python ai_nest/cli.py doctor --provider codex` (substitute `claude` when selected). Confirm `nest.config.json` is version 2 with `policy_version=2026-11`, `tdd.red_commands`, real project checks, and optional dependency provisioning. The outer verification timeout must cover the combined check budgets.
5. Running agent-written code is risky. Require an approved disposable, credential-free environment. `--allow-host-execution` is explicit user authorization, **not** a sandbox.

## Invoke

Use the installed Python CLI, from the repository root:

```bash
python ai_nest/cli.py run --provider codex --session <session-name> \
  --allow-host-execution "<exact feature request>"
```

Set the actual provider. Do not silently enable host execution without authorization. For runs that exceed a single interactive tool's timeout, use a suitable terminal/task runner and later inspect its exit status; do not claim a background run completed unless evidence exists.

## What the CLI currently enforces

1. Open named session; create artifacts and worktrees; verify clean baseline after dependency provisioning.
2. Explorer → specification → planner, with orchestrator-owned handoffs.
3. Public test engineer writes tests; orchestrator runs RED commands and checks expected test names. A separate protected test stage runs only when configured.
4. Coder receives planner output and public tests/guidance, never hidden test source or raw logs. Coder cannot change any tests, gate scripts or CI configuration.
5. Fresh verification combines all patches and runs `scripts/verify.sh`. A separate reviewer checkout repeats verification using public tests only.
6. Reviewer emits concrete findings. High/critical defects block by default; minor findings are advisory unless policy changes.
7. Orchestrator routes optional security review using final code paths and relevant history. If checks fail it runs a bounded repair loop.
8. On verified: leave local worktree and report, no automatic PR, push or merge. Failed runs preserve session evidence and remove transient worktrees by default.

The core explorer/planner/coder/reviewer stages remain fixed. Optional security review is implemented; **arbitrary dynamic agent routing is not**. Worktree separation is not a hardened security sandbox; hidden tests require externally isolated workers if secrecy matters.

## Report

Inspect `.ai-nest/runs/<run-id>/report.json`, session handoffs and the verification artifacts. Report the actual status, run/session IDs, executed stages, RED outcome, verification results, review/routing decisions, outstanding issues and worktree. Never claim tests or AI stages that were not actually executed.
