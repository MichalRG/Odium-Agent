---
name: build-feature
description: Implement or repair a feature with the AI Engineering Nest Python orchestrator in one conversation - scouting, questions and a plan for owner approval, then public RED/GREEN TDD, independent verification and risk-based security review.
---

# Build Feature

This skill **invokes** AI Nest. It is not the orchestrator and does not decide which agents run. Do not imitate agents in chat or skip the CLI's deterministic gates.

## Inputs

Use the user's exact feature request. Accept an optional descriptive `--session` name, repository root and requested provider (`codex` default; `claude` and `copilot` supported).

**Workspace.** When `nest.config.json` has `workspace.repos`, the folder holds several repositories and has no `scripts/verify.*` files: each repository is verified with its own checks from `workspace.repos.<name>`. Choose the repository the request is about, and ask when it is not clear. Add `--repo <name>` to every `cli.py` command, skip `bash scripts/verify.sh --list` (`doctor --repo <name>` lists the repository's checks), and run the merge commands in that repository's folder. A request that spans repositories is one plan, build and merge cycle per repository, in dependency order (for example the API before its client), with the same session.

**Home install.** When the Nest commands in this skill start with an absolute path (for example `python /Users/me/.ai-nest/ai_nest/cli.py`), the Nest is installed once in that folder and the repository holds no Nest files. Skip Preflight 1, `bash scripts/verify.sh --list` and the `.gitignore` advice of Preflight 3: registration hides `.ai-nest/` and build output in `.git/info/exclude`. Read `AGENTS.md`, `AI_NEST_README.md` and `nest.config.json` in that folder. Run every command from the repository root, without `--repo`. The repository's checks, runs and sessions are in its project folder, which `doctor` names. When `doctor` says that the repository is not registered, use the `nest-setup` skill first. The request file and the merge commands do not change.

**Commands and permissions.** The owner approves the work at the checkpoints. Do not make them approve it again command by command:
- Run every Nest command from the project root in exactly the form shown here: `python ai_nest/cli.py <command> …`. Never wrap it in `python -c`, a script, `cd … &&`, environment variables or `$(…)`. A wrapped command is different each time, so an "always allow" approval never matches it. Write the request with your file-editing tool to `.ai-nest/requests/<session>.md` (rewrite the whole file whenever the request changes) and pass `--request-file .ai-nest/requests/<session>.md`. Do not put the request on the command line.
- `plan`, `run` and `bootstrap` create Git branches and worktrees, start the provider's agents and run the checks. A sandbox that blocks writes to `.git` (the Codex sandbox does) stops them. Run them outside the sandbox at the first attempt. In Codex, ask with `prefix_rule: ["python", "ai_nest/cli.py"]`, so that the owner can allow all later Nest commands with one answer. Write the justification as one short sentence: what the command does and which permission it needs. Never phrase it as approval of the task or the plan.
- Do not run tests, builds, probes or diagnostics of your own: the nest runs the configured checks. When the work needs a check that the configured checks do not have (for example one that starts local servers, uses ports or the network), tell the owner at the next checkpoint and propose adding it to the checks in `nest.config.json`. When a one-off diagnostic cannot wait, put all of its steps in one script file under `.ai-nest/scratch/` and run that file with one command, so the owner can read what runs.

**Reference docs and context pack.** Documents about the project that Git does not track go in `.ai-nest/docs/` of the repository. The explorer reads them first. It also writes the session's context pack, `.ai-nest/context/<session>.md`: an outline of the affected code and the line ranges that the later stages start from. Read it when you report or answer questions at a checkpoint.

## Preflight

1. From the project root verify `AGENTS.md`, `nest.config.json`, `ai_nest/cli.py`, `ai_nest/memory.py`, `scripts/verify.sh`, `scripts/verify.py` and `scripts/verify.config.json` exist (in a workspace, all but the `scripts/` files). **If missing, stop; do not invent the runtime.** Install the complete release using its root `install.py`; the installed repository also keeps an installer copy for inspection and future deployment.
2. Read `AGENTS.md`, `nest.config.json` and `AI_NEST_README.md`. `AGENTS.md` contains shared instructions; the Python CLI is the enforcement engine.
3. Run `python ai_nest/cli.py doctor` to check the installation manifest and stale configuration, then confirm Git has a committed `HEAD` and a clean tracked/untracked source state. Commit configuration before starting (a `--local` install keeps Nest files in `.git/info/exclude`, so there is nothing to commit); `.ai-nest/`, `__pycache__/`, `node_modules/` and other generated files belong in `.gitignore`.
4. Execute `bash scripts/verify.sh --list` and `python ai_nest/cli.py doctor --provider codex` (substitute `claude` or `copilot` when selected). Confirm `nest.config.json` is version 2 with `policy_version=2026-11`, `tdd.red_commands`, real project checks, and optional dependency provisioning. The outer verification timeout must cover the combined check budgets.
5. Running agent-written code is risky. Require an approved disposable, credential-free environment. `--allow-host-execution` is explicit user authorization, **not** a sandbox.

## Invoke: one conversation, three checkpoints

The user invokes this skill once. Carry the whole feature through this conversation and come back to the user only at the **checkpoints** below. Between checkpoints, work without asking. The nest writes the specification and the plan; you relay them. Do not write, edit or shorten them yourself.

1. **Start.** Take the user's request as written. Choose a short session name from it (for example `epub-import`) and use the same name for the whole conversation. Get the user's authorization for `--allow-host-execution` once, before the first command (see Preflight 5).
2. **Plan.** Run:
   ```bash
   python ai_nest/cli.py plan --provider <provider> --session <session> \
     --allow-host-execution --request-file .ai-nest/requests/<session>.md
   ```
   The nest scouts the repository and its documents, writes the specification and the plan, and stops. It changes no code. When HEAD has not moved, a later `plan` in the same session whose request adds text at the end of the earlier request reuses the scouting and runs only the specification and the plan; with an unchanged request it prints the earlier result again without running agents. So keep the same session for every round, and add answers and feedback at the end of the request. Act on the exit code:
   - **2: questions.** **Checkpoint:** show the questions exactly as printed and wait for the answers. Then run `plan` again with the same session. The request is the original text, followed by `Owner answers:` and each question with its answer.
   - **0: plan ready.** **Checkpoint:** show the goal, acceptance criteria, constraints, risks, tasks, planned commits and the existing tests to change from the output (the full data is in `.ai-nest/runs/<run-id>/artifacts/planning.json`). Ask the user to approve it, change it or stop.
     - The existing tests to change are part of what the user approves: the test engineer may change those files, and no other existing tests. When the request changes behaviour that an existing test asserts and the plan does not list that test, say so and ask for the change as feedback.
     - For a change, run `plan` again with the same session. The request is the previous request, followed by `Owner feedback on the previous plan:` and the feedback. Then repeat this checkpoint.
     - When the plan has more than about 5 tasks, touches more than about 10 files, or joins parts that can work on their own (for example a data model, a CLI and platform adapters), recommend building it in slices (see Slices) and propose the slices in order.
   - **1: blocked.** Report the error and stop.
3. **Build.** Start this step only after the user approves the plan. Run:
   ```bash
   python ai_nest/cli.py run --from-plan <plan-run-id> --provider <provider> --allow-host-execution
   ```
   The nest writes failing public tests, implements, verifies in a fresh checkout, reviews and repairs within its budget. This step has no checkpoint. If the command says that HEAD moved, go back to step 2 and get approval for the new plan.
4. **Result.** **Checkpoint:** report as described in Report. When the run is verified, show `git -C <worktree> diff --stat HEAD`, offer the full diff, and show the commits you will make at the merge:
   - Take the `planned_commits` from `report.json`, in their order. Give each changed file (`git -C <worktree> status --porcelain`) to the commit whose tasks name it. A test file goes with the commit whose behaviour it covers. A file that several commits need goes in the first of them. A file that no task names goes where its content belongs.
   - Check the sizes in the actual diff: `git -C <worktree> diff --stat HEAD` for changed files, and the line count of each new file. Aim for about 50 to 400 changed lines per commit. Join a commit of less than about 50 lines, or one that only documents or completes another (notes, a dependency, a small helper), into the commit that it belongs to, with one message for both. Split a larger commit only where each part makes sense on its own.
   - When a commit only extends or corrects a commit of an earlier slice of the same work (for example the feature notes that each slice updates), propose to squash it into that commit, and name the commit.
   - For each commit, show its subject, a one-line body (what it adds and why) and its files. Write subjects and bodies in English, even when the user writes in another language; translate a planned message that is not in English.
   - When `planned_commits` is empty (a plan made before commit planning), propose one commit.
   When the run is blocked, give the cause and offer to plan again in the same session with the cause as owner feedback.
5. **Merge.** Do this only when the user tells you to. Make the commits shown at the Result checkpoint, with the user's changes and with every message in English, in order: for each one, run `git -C <worktree> add -- <files>` and `git -C <worktree> commit -m "<subject>" -m "<body>"`. Check that `git -C <worktree> status --porcelain` is empty at the end. Then, from the repository root, run `git merge --ff-only <branch>`, `git worktree remove <worktree>` and `git branch -d <branch>`. Run the commits and the merge as one `&&` chain, so that a sandbox asks the owner only once. Never push. The nest verified only the final state, not each commit on its own.
   - A squash into an earlier slice's commit is done only when the user agreed to it and that commit is not pushed (`git branch -r --contains <sha>` prints nothing). Make that commit with `git -C <worktree> commit --fixup=<sha>`, and end the chain, after `git branch -d`, with `git rebase --autosquash <sha>~1` in the repository root (Git 2.44 or later). If the rebase stops on a conflict, run `git rebase --abort` and tell the user that the change stays a separate `fixup!` commit.

**Slices.** A large request is built as a sequence of slices. Each slice is one full cycle of steps 2 to 5: its own plan, approval, build, result and merge. Use the same session for all slices, so that later slices see the handoffs of earlier ones. For each slice, the request is the original request, followed by `Build only this slice:` and the slice description, and then by `Already merged:` and the earlier slices. Plan a slice only after the previous slice is merged: an approved plan is pinned to the HEAD it was planned on.

Each `plan` and `run` takes minutes. Run them where a tool timeout cannot stop them (for example as a background job), and wait for the exit code. Never report a result that you did not see.

When the user asks to skip the checkpoints, `python ai_nest/cli.py run --provider <provider> --session <session> --allow-host-execution --request-file .ai-nest/requests/<session>.md` does steps 2 and 3 in one command and stops on open questions.

For an empty project, where the configured checks cannot run yet (`doctor` reports a missing check directory), run `python ai_nest/cli.py bootstrap` with the same options and a description of what to scaffold, before any feature run. It has no plan checkpoint. It scaffolds the project and is verified and reviewed like a feature. The user reviews `created_protected_files` before committing.

Set the actual provider. Do not enable host execution without authorization.

## What the CLI currently enforces

1. Open named session; create artifacts and worktrees; verify clean baseline after dependency provisioning.
2. Explorer → specification → planner, with orchestrator-owned handoffs. `plan` stops here; `run --from-plan` starts after here with the approved plan and refuses it when HEAD moved.
3. Public test engineer writes tests; orchestrator runs RED commands and checks expected test names. A separate protected test stage runs only when configured.
4. Coder receives planner output and public tests/guidance, never hidden test source or raw logs. Coder cannot change any tests, gate scripts or CI configuration.
5. Fresh verification combines all patches and runs `scripts/verify.sh`. When protected tests are enabled, a separate reviewer checkout repeats verification with public tests only.
6. Reviewer emits concrete findings, including design quality against the project's standards documents, or the codebase's own patterns when none exist. High/critical findings go to repair. When the code is verified and approved but has medium/low findings in production files, the coder fixes them in the next attempt, which is verified and reviewed again; if that fails, the approved attempt is the result. High/critical defects block by default; minor findings are advisory unless policy changes.
7. Orchestrator routes optional security review using final code paths and relevant history. If checks fail it runs a bounded repair loop.
8. On verified: leave local worktree and report, no automatic PR, push or merge. Failed runs preserve session evidence and remove transient worktrees by default.

The core explorer/planner/coder/reviewer stages remain fixed. Optional security review is implemented; **arbitrary dynamic agent routing is not**. Worktree separation is not a hardened security sandbox; hidden tests require externally isolated workers if secrecy matters.

## Report

Inspect `.ai-nest/runs/<run-id>/report.json`, session handoffs and the verification artifacts. Report the actual status, run/session IDs, executed stages, RED outcome, verification results, review/routing decisions, outstanding issues and worktree. Never claim tests or AI stages that were not actually executed.
