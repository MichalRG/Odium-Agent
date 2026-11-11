---
name: build-feature
description: Implement or repair a feature with the AI Engineering Nest Python orchestrator in one conversation - scouting, questions and a plan for owner approval, then public RED/GREEN TDD, independent verification and risk-based security review.
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

## Invoke: one conversation, three checkpoints

The user invokes this skill once. Carry the whole feature through this conversation and come back to the user only at the **checkpoints** below. Between checkpoints, work without asking. The nest writes the specification and the plan; you relay them. Do not write, edit or shorten them yourself.

1. **Start.** Take the user's request as written. Choose a short session name from it (for example `epub-import`) and use the same name for the whole conversation. Get the user's authorization for `--allow-host-execution` once, before the first command (see Preflight 5).
2. **Plan.** Run:
   ```bash
   python ai_nest/cli.py plan --provider <provider> --session <session> \
     --allow-host-execution "<request>"
   ```
   The nest scouts the repository and its documents, writes the specification and the plan, and stops. It changes no code. Act on the exit code:
   - **2: questions.** **Checkpoint:** show the questions exactly as printed and wait for the answers. Then run `plan` again with the same session. The request is the original text, followed by `Owner answers:` and each question with its answer.
   - **0: plan ready.** **Checkpoint:** show the goal, acceptance criteria, constraints, risks and tasks from the output (the full data is in `.ai-nest/runs/<run-id>/artifacts/planning.json`). Ask the user to approve it, change it or stop.
     - For a change, run `plan` again with the same session. The request is the previous request, followed by `Owner feedback on the previous plan:` and the feedback. Then repeat this checkpoint.
     - When the plan has more than about 5 tasks, touches more than about 10 files, or joins parts that can work on their own (for example a data model, a CLI and platform adapters), recommend building it in slices (see Slices) and propose the slices in order.
   - **1: blocked.** Report the error and stop.
3. **Build.** Start this step only after the user approves the plan. Run:
   ```bash
   python ai_nest/cli.py run --from-plan <plan-run-id> --provider <provider> --allow-host-execution
   ```
   The nest writes failing public tests, implements, verifies in a fresh checkout, reviews and repairs within its budget. This step has no checkpoint. If the command says that HEAD moved, go back to step 2 and get approval for the new plan.
4. **Result.** **Checkpoint:** report as described in Report. When the run is verified, show `git -C <worktree> diff --stat HEAD` and offer the full diff. When it is blocked, give the cause and offer to plan again in the same session with the cause as owner feedback.
5. **Merge.** Do this only when the user tells you to. In the worktree run `git add -A` and `git commit -m "<one-line summary>"`. Then, from the repository root, run `git merge --ff-only <branch>`, `git worktree remove <worktree>` and `git branch -d <branch>`. Never push.

**Slices.** A large request is built as a sequence of slices. Each slice is one full cycle of steps 2 to 5: its own plan, approval, build, result and merge. Use the same session for all slices, so that later slices see the handoffs of earlier ones. For each slice, the request is the original request, followed by `Build only this slice:` and the slice description, and then by `Already merged:` and the earlier slices. Plan a slice only after the previous slice is merged: an approved plan is pinned to the HEAD it was planned on.

Each `plan` and `run` takes minutes. Run them where a tool timeout cannot stop them (for example as a background job), and wait for the exit code. Never report a result that you did not see.

When the user asks to skip the checkpoints, `python ai_nest/cli.py run --provider <provider> --session <session> --allow-host-execution "<request>"` does steps 2 and 3 in one command and stops on open questions.

For an empty project, where the configured checks cannot run yet (`doctor` reports a missing check directory), run `python ai_nest/cli.py bootstrap` with the same options and a description of what to scaffold, before any feature run. It has no plan checkpoint. It scaffolds the project and is verified and reviewed like a feature. The user reviews `created_protected_files` before committing.

Set the actual provider. Do not enable host execution without authorization.

## What the CLI currently enforces

1. Open named session; create artifacts and worktrees; verify clean baseline after dependency provisioning.
2. Explorer → specification → planner, with orchestrator-owned handoffs. `plan` stops here; `run --from-plan` starts after here with the approved plan and refuses it when HEAD moved.
3. Public test engineer writes tests; orchestrator runs RED commands and checks expected test names. A separate protected test stage runs only when configured.
4. Coder receives planner output and public tests/guidance, never hidden test source or raw logs. Coder cannot change any tests, gate scripts or CI configuration.
5. Fresh verification combines all patches and runs `scripts/verify.sh`. A separate reviewer checkout repeats verification using public tests only.
6. Reviewer emits concrete findings. High/critical defects block by default; minor findings are advisory unless policy changes.
7. Orchestrator routes optional security review using final code paths and relevant history. If checks fail it runs a bounded repair loop.
8. On verified: leave local worktree and report, no automatic PR, push or merge. Failed runs preserve session evidence and remove transient worktrees by default.

The core explorer/planner/coder/reviewer stages remain fixed. Optional security review is implemented; **arbitrary dynamic agent routing is not**. Worktree separation is not a hardened security sandbox; hidden tests require externally isolated workers if secrecy matters.

## Report

Inspect `.ai-nest/runs/<run-id>/report.json`, session handoffs and the verification artifacts. Report the actual status, run/session IDs, executed stages, RED outcome, verification results, review/routing decisions, outstanding issues and worktree. Never claim tests or AI stages that were not actually executed.
