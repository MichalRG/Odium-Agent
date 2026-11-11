# AI Engineering Nest v4.4 — portable agent orchestrator

Provider-independent Python orchestrator for **Codex CLI** and **Claude Code CLI**. The `build-feature` skill is only an entrypoint: the actual stage transitions and gates live in `ai_nest/cli.py`.

## Install or upgrade

Requirements: Python 3.11+, Git, Bash, and one supported provider CLI. **Run generated code only in an isolated, credential-free VM/container.** Git worktrees are not security boundaries.

```bash
# Guided setup in a terminal: asks what it should do and shows the defaults
python /path/to/odium-agent/install.py /your/folder
# Recommended: local install, nothing is added to the project's Git history
python /path/to/odium-agent/install.py /your/git/repo --local --template python
# Committed install (Nest files are committed, CI workflow included):
python /path/to/odium-agent/install.py /your/git/repo --template python
# Upgrade either kind (repeat --local for a local install):
python /path/to/odium-agent/install.py /your/git/repo --update-code
```

**Guided setup.** Run in a terminal, the installer asks about everything the flags leave open:
- whether to run `git init` when the folder is not a repository;
- whether to add files of 5 MB or more to `.gitignore` while the repository has no commits;
- whether to use a local install;
- which stacks to configure (`NAME[:FOLDER]`), suggesting the ones it detects in the root and first-level folders;
- whether to make the first commit, showing the Git identity it will use;
- whether to start `bootstrap`. This one defaults to no, because it runs an AI agent.

Without a terminal (scripts, CI, agents), it asks nothing and does nothing extra, and a folder without Git stays an error. `--yes` takes the defaults without asking: `git init`, ignore large files, the detected stacks and the first commit. It never starts `bootstrap`. An agent should ask the user first, then call for example `install.py <folder> --local --yes --template python-uv:app`.

**Local install (`--local`).** The installer lists every Nest file in `.git/info/exclude` (a per-clone ignore file that is never committed) and never modifies files the project tracks: an existing `AGENTS.md`, `CLAUDE.md`, `.gitignore` or `.claude/settings.json` is left as it is. It adds the same build-output rules as committed mode (`__pycache__/`, `node_modules/`, `dist/` and so on) to that block. `git status` stays clean, so there is nothing to commit. The orchestrator copies its trusted files (`scripts/verify.*`, `nest.config.json`, instruction files) into every worktree and blocks an agent stage that changes or deletes them, because Git cannot see edits to excluded files. Limits: the Nest exists only in this clone (each developer or container installs it), there is no AI Nest CI job, and to commit a file of your own at an excluded path (for example a new `AGENTS.md`) use `git add -f` or remove its line from the `AI Nest local install` block. To uninstall, delete the files listed in that block and the block itself.

**Verify templates (`--template NAME[:FOLDER]`).** Writes `scripts/verify.config.json` from `ai_nest/templates/verify/<name>.json`; an existing file is kept unless `--force`. `FOLDER` sets the `cwd` of every check and setup command. Repeat the option for a repository with several stacks; check names then get the folder as a prefix (`app-unit`, `frontend-build`):

```bash
python /path/to/odium-agent/install.py /your/git/repo --local --template python-uv:app --template angular:frontend
```

| Template | Checks | Notes |
|---|---|---|
| `python` | `ruff check .`, `pytest -q tests` | needs ruff and pytest in the active environment |
| `python-uv` | `uv run --locked ruff check .`, `uv run --locked pytest -q` | adds `uv sync --locked`; ruff and pytest are dev dependencies |
| `java-maven` | `mvn -B -ntp test`, `mvn -DskipTests package` | Maven downloads dependencies itself |
| `java-gradle` | `./gradlew test`, `./gradlew assemble` | uses the project's Gradle wrapper |
| `typescript` | `tsc --noEmit`, `npm test`, `npm run build` | also adds `npm ci` to `environment.setup_commands` |
| `angular` | `npm test -- --watch=false`, `ng build` | adds `npm ci`; Karma needs a headless browser in containers |
| `go` | `go vet ./...`, `go test ./...`, `go build ./...` | |
| `dotnet` | `dotnet build`, `dotnet test` | |

Every template has a `unit` suite, which `tdd.red_commands` runs for the RED step. Build and dependency files (`pom.xml`, Gradle/Maven wrappers, `go.mod`, `*.csproj`, `package.json`, `pyproject.toml`, lint configs) are protected from coding agents.

Without a template, copy `scripts/verify.config.json.example` to `scripts/verify.config.json`. Edit it to list **real** unit, integration, static, build, and security commands. Do not accept the example without matching the project. `nest.config.json` must contain `verification.commands=[{"name":"verify-all","argv":["bash","scripts/verify.sh"],"cwd":"."}]` and the safety protections in the supplied v4.4 config.

**Upgrade policy:** The installer includes a versioned `ai_nest/installation.json` inventory (tracked in Git), the installer itself, and runtime regression tests under `ai_nest/selftests/`. On `--update-code`, supported v1/v2 configurations are backed up and migrated without replacing your real project checks. Missing safety protections are merged; unsupported configurations are left untouched. If `tdd.protected_tests` was enabled, the upgrade disables it until a genuinely isolated test runner exists. The installer also reconciles known obsolete AI Nest instructions, while preserving custom project rules and backing up modified documents. It adjusts outer verification timeouts to cover **declared check budgets** when the actual manifest exists. After upgrade, re-run `doctor`, review and commit changed files. The install manifest supports drift diagnostics but is **not a security boundary**.

For fresh Node/Angular worktrees, provision dependencies with explicitly configured environment steps in `nest.config.json`:

```json
"environment": {
  "setup_commands": [
    {"name":"frontend-npm-ci","argv":["npm","ci","--no-audit","--no-fund"],"cwd":"frontend"}
  ]
}
```

For Python, also install declared pinned dependencies (e.g. an appropriate `pip install -r ...` step) before verification. Test runs may execute untrusted project scripts. This is intentional and needs OS-level sandboxing.

### Models per agent stage

`models` in `nest.config.json` picks the model and reasoning effort for each agent stage, per provider. A stage without an entry uses `default`; a provider without entries uses its CLI's own default (for Claude Code that is the account default, because agents run with project settings only). The nest passes them as `codex exec -m <model> -c model_reasoning_effort="<effort>"` or `claude --model <model> --effort <effort>` and prints the choice for every stage.

```json
"models": {
  "codex": {
    "default": {"model": "gpt-6.1-sol", "effort": "medium"},
    "explore": {"model": "gpt-6-luna", "effort": "high"},
    "plan": {"model": "gpt-6-astra", "effort": "high"}
  },
  "claude": {
    "default": {"model": "claude-sonnet-5-5", "effort": "medium"},
    "plan": {"model": "claude-opus-5-5", "effort": "high"},
    "security_review": {"model": "claude-fable-5-2", "effort": "high"}
  }
}
```

Full model IDs keep runs reproducible; Claude aliases such as `opus` or `fable` follow the newest version instead.

Stages: `explore`, `specify`, `plan`, `tests`, `protected_tests`, `implement`, `repair`, `bootstrap`, `review`, `security_review`. Upgrading adds the release defaults for missing entries and keeps yours. The chat that runs `$build-feature` uses your own Codex or Claude settings, not this section.

### TDD configuration

The v4.4 starter has TDD enabled and requires an explicit RED command (typically a focused unit or integration test suite):

```json
"tdd": {
  "enabled": true,
  "protected_tests": false,
  "red_commands": [
    {"name":"public-tdd-red","argv":["bash","scripts/verify.sh","--suite","unit"],"cwd":"."}
  ]
}
```

RED requires named expected tests and credible failures; specific missing-symbol import/compile errors are accepted only if they reference generated public tests and symbols used by those tests. The default already-GREEN policy is to block; it can be explicitly set to `allow` for existing functionality. Exit codes are configurable with `tdd.accepted_red_exit_codes` (default `[1,2]`), but exit codes alone never prove RED. Framework-specific failure interpretation is **conservative, not infallible**; configure the RED suite appropriately. Test path recognition uses anchored recursive `safety.test_path_globs`, where `**/` matches zero or more directories and `*` matches within one segment. Nested helpers, fixtures and fixture data are protected from the coder. Nested files and fixtures anywhere under a configured test directory are treated as tests; the coder cannot modify them. The test engineer can add new test files by default; updates to existing tests require explicitly setting `safety.allow_existing_test_modifications=true`, and independent review of the diff.

If `protected_tests=true`, AI Nest runs an additional test agent in a separate worktree. **Protected test source and raw logs are not handed to the coder, but this is not OS-enforced confidentiality**: a malicious process with broad local filesystem access could read sibling worktrees. Use separately isolated workers/containers for actual secrecy.

### Verify installation

```bash
bash scripts/verify.sh --list
bash scripts/verify.sh
python ai_nest/cli.py doctor --provider codex
python -m unittest discover -s ai_nest/selftests -p 'test_*.py' -q  # installed runtime regression suite
```

Commit all installed/configured files before running. `git status --short` must be clean; only committed `HEAD` is used for new worktrees. A committed install appends `.ai-nest/`, `__pycache__/`, `.DS_Store`, `node_modules/`, and common build caches to `.gitignore` without overwriting existing ignore rules. Do **not** commit secrets.

```bash
# Move any extracted ai-nest-complete-v*/ folder OUTSIDE this repository first.
git add -A  # review `git diff --cached` before committing
# Inspect the staged changes: this includes install.py and ai_nest/selftests/.
# Inspect changes, then commit normally
```

### Start a feature

The easy way is one chat: Codex `$build-feature <what you want>` or Claude Code `/build-feature <what you want>`. The chat comes back to you only when the nest has questions, when the plan is ready for your approval, and with the result. It uses these two commands, which you can also run yourself:

```bash
# 1. Scout, specify and plan, then stop. Changes no code.
#    Exit 0: plan printed for approval. Exit 2: questions printed; answer them in the
#    request and run `plan` again with the same --session (the planner sees the earlier runs).
python ai_nest/cli.py plan --provider codex --session projects-pagination \
  --allow-host-execution "Implement project pagination"

# 2. Implement exactly the approved plan: tests (RED), code, verification, review.
#    Refused when HEAD moved since planning; then plan again.
python ai_nest/cli.py run --from-plan <plan-run-id> --provider codex --allow-host-execution
```

The plan also lists the commits for the finished work: each one a coherent change with its tests, in dependency order. The report repeats them as `planned_commits`, and the chat commits along them at the merge.

Build a large request in slices: one plan, approval, run and merge per slice, all in the same `--session`, each planned after the previous slice is merged. The chat proposes slices when a plan is large. Smaller slices verify faster, get a more focused review and lose less when an attempt fails.

To skip the approval, `run --session <name> --allow-host-execution "<request>"` does both steps in one command and blocks on open questions. Use `--provider claude` for Claude Code agents.

### Start from an empty project (`bootstrap`)

Feature runs need a working baseline, and their agents may not create build files. For a greenfield repository, first configure the checks for the project you want (for example with `--template python-uv:app`), make one commit (`git commit --allow-empty -m "Initial commit"` is enough in a local install), then let the Nest scaffold it:

```bash
python ai_nest/cli.py bootstrap --provider claude --allow-host-execution \
  "Scaffold the uv app in app/ as described in docs/architecture.md"
```

`bootstrap` runs explore, specify and plan, then one scaffolding agent that sees the exact check and setup commands. It may **create** build files, lockfiles, a `.gitignore` per project folder and one smoke test per test runner. It may not modify or delete existing build, test or gate files, and never touches Nest files. The orchestrator refuses to start when the baseline already passes, blocks changes that contain `node_modules/`, `.venv/` or `__pycache__/`, verifies the result in a fresh checkout with your setup commands and always runs the security reviewer, because the scaffold adds dependencies. The report lists `created_protected_files`: review them before you commit, because from then on they are protected gates. TDD is skipped for this run only. The agent needs network access for the package managers (Codex: the bootstrap stage enables sandbox network access). Add a second stack later the same way: add its checks, commit, run `bootstrap` again.

Skill invocation: Codex `$build-feature ...` or Claude Code `/build-feature ...`. For long-running commands, use a terminal/job runner that supports the complete CLI lifetime; a single Claude Code Bash tool call may time out. Do not assume a skill invocation itself is an external durable job.

## Actual v4.4 workflow

1. Orchestrator creates run ID, named session, branch and worktrees; baseline checks run after configured dependency setup.
2. **Explorer** investigates code and **specification writer** establishes acceptance criteria; **planner** produces task plan.
3. **Test engineer** writes public TDD tests. The orchestrator independently runs targeted RED commands and records results. An additional protected-test engineer runs if configured. The `static` suite of `scripts/verify.config.json` (lint) also runs on the new tests: the coder may not edit tests, so a lint failure goes back to the test engineer once, and stops the run if it persists. Failures that name missing symbols (type checkers before the code exists) are expected RED and pass on.
4. Public tests are applied to the **coder** worktree. Coder writes production code only, while public tests remain unchanged. Failed policy checks lead to a bounded clean retry.
5. Orchestrator combines public, protected and implementation patches in a fresh verification checkout, sets up dependencies and executes mandatory project gates.
6. When protected tests are enabled, the orchestrator re-verifies code + **public** tests in a separate review checkout. Otherwise it checks the public patch identity and can skip a redundant second gate (configurable). Code reviewer examines final diff and evidence; high/critical findings block by default, low/medium are advisory. It also reviews design quality: it looks for the project's standards documents (names with `standard`, `convention`, `style`, `guideline`, `architecture`, `adr`, `decision`, and project sections of `AGENTS.md`/`CLAUDE.md`) and, when none exist, compares with the patterns the codebase already applies. It checks redundancy, fitting (not forced) design patterns and single responsibility. Breaking a documented standard blocks; findings backed only by general practice, and findings in test files (the coder cannot edit tests), are advisory. Medium/low findings in production files (`review_policy.fix_severities`) still go back to the coder while attempts remain: the code was verified and approved, the coder fixes the findings, and the result is verified and reviewed again. If that fix attempt fails, the approved attempt stays the result and the report records `review_fix_failed`.
7. Optional **security reviewer** runs when the orchestrator's final-diff routing policy matches sensitive paths or a relevant historical high-severity finding. Routing decisions are saved. Any repair re-enters verification.
8. Success produces a local `verified` result **only**. No push, PR, merge, deploy, remote CI or human approval is implied.

### Run evidence

```text
.ai-nest/
  runs/<run-id>/report.json
  runs/<run-id>/artifacts/{public_tests.patch,protected_tests.patch,public_red.json,checks_attempt_*.json,...}
  sessions/<session-slug>/session.json
  sessions/<session-slug>/runs/<run-id>/handoffs/*.json
  sessions/<session-slug>/runs/<run-id>/routing.json
  sessions/<session-slug>/runs/<run-id>/result.json
```

Agents return machine-readable reports; orchestrator writes session records and controls who receives previous findings. Protected test notes are not injected into coder context. Raw protected logs are stored on the host and must be access-controlled at OS/storage level.

```bash
python ai_nest/cli.py sessions list
python ai_nest/cli.py sessions show projects-pagination
```

## Controls and limits

- Agent writes to `AGENTS.md`, `.claude/`, `.agents/`, `.github/`, `ai_nest/`, `nest.config.json`, verification scripts, package scripts (`package.json`), pytest/Angular settings and other protected files block the run.
- Risk routing comes **only** from the orchestrator, not agent prompts. Full dynamic selection for every role is not implemented; the core stages are still fixed. Security review is conditional.
- A configured check failure, missing check manifest, missing binaries or runtime timeout never becomes a passing result. Every agent stage pins the expected Git HEAD: unauthorized commits/rebases trigger a failed attempt. Invalid provider JSON is reported as blocked after persisting available output logs. Subprocess timeouts kill process groups on POSIX.
- Verification configuration changes, new dependencies and CI policy changes require separate trusted maintenance, not autonomous coder edits. The GitHub Actions template should be customized with install/service steps, and a PR that changes protected files will require a separately reviewed exception procedure.
- Claude read-only stages have Bash for authorized investigation but are checked for source mutations. The CLI adapters use stdin for prompts to avoid OS argument-length failures.
- Protected evaluation is **not fully secure on a shared host**. Do not deploy this to privileged repositories without external sandboxing, separate identities, enforced network policy and explicit CI protections.
- No live Codex or Claude CLI execution has been verified by the included mock-based tests. Check your installed CLI version and run a controlled provider smoke test before relying on it.

## Regression tests

From the repository root (the suite lives in `ai_nest/selftests/`):

```bash
python -m unittest discover -s ai_nest/selftests -p 'test_*.py' -v
```

Includes mocked full flow with public RED/hidden-test separation, Git/worktree install tests, provider argument tests, policy cases and verify-runner tests. No real model correctness is claimed.

## v4.4 gates and repair diagnostics

- Configure `safety.test_path_globs` and `safety.protected_basenames` in the committed policy. Verification files such as `pyproject.toml`, `package.json`, lockfiles, pytest config and `.github` must not be writable by a coding agent.
- `tdd.already_green_policy` defaults to `block`; `allow` is explicit. Generated tests that cannot collect due to a missing *new* symbol can form valid RED evidence, but unrelated missing dependencies or test setup errors block the run.
- `cleanup.blocked_worktrees` defaults to true. Failed worktrees and temporary branches are removed after logs, patches and persistent session reports are written. Verified worktrees remain for inspection.
- With `tdd.protected_tests=false`, sanitized public failure tails are handed to the repair agent. With protected tests enabled, all raw verification output is withheld from coder context. Protected tests are **not confidential** if all workers share unrestricted host filesystem access.
- On Claude, the CLI uses `--setting-sources project --strict-mcp-config`. It narrows settings sources but does not guarantee user/managed plugin or tool isolation; use a disposable environment and audit project settings.
- `limits.agent_timeout_seconds` (default 1800) is a window, not a hard stop, for stages that write files (tests, implement, repair). At the end of each window the orchestrator checks the worktree: if the files reached a state it has not seen before, the agent gets another window, up to `limits.agent_max_seconds` (default 14400) in total. If nothing changed in the last window, or the files went back to an earlier state, the agent is stopped. A coder stopped this way keeps its unfinished code: it goes through the same policy checks and verification, and `repair` continues it. Read-only stages stop after one window.
- `limits.review_diff_max_chars` (default 400000, about 100k tokens) caps the diff of code and public tests that the reviewers get inline. Lockfiles are left out. The diff is never truncated: a larger diff blocks the run after verification, so split the feature into slices or raise the limit within the review models' context.
- `limits.check_timeout_seconds` applies per **orchestrator check**, not to each check inside `scripts/verify.py`. Set the outer timeout larger than the total runtime of configured checks and their individual budgets.
- This package ships an example verification manifest, **not working project checks**. Configure `scripts/verify.config.json`, `tdd.red_commands`, and any `environment.setup_commands` for your stack before executing features. CI runs configured setup commands and has optional requirements/npm lockfile setup; customize service dependencies and multi-workspace installations for your repository.

## Run all bundled tests

```bash
python -m unittest discover -s ai_nest/selftests -p 'test_*.py' -v
```

The tests use a fake CLI adapter and actual temporary Git repositories; they do not validate live model behavior.

## v4.4 integrity and RED policy

- Every repair resets the worktree to the **original pinned `base_commit`**, not mutable `HEAD`; commits made by agents cannot survive into the result.
- An attempt blocked before verification (policy violation, moved HEAD, no changes) is reset with nothing kept, so the next attempt runs `implement` again with the block reason as feedback. `repair` runs only on code that reached verification.
- `tdd.protected_tests` defaults to **false**. A shared host filesystem does not keep hidden tests secret. Only enable this in separately isolated workers.
- Missing new Python/TypeScript modules are accepted as TDD RED only when the module is present in planner `tasks[].files` and referenced by generated public tests. Missing unrelated dependencies block.
- Test engineers may add a **new** `tests/conftest.py`; editing existing fixtures remains prohibited. Such new fixture files are permitted only when validated as test-agent additions in the local workflow; CI `verify --base` blocks them by default because it cannot verify the test-agent origin. A project may explicitly opt into added-only fixtures with `safety.allow_new_test_fixtures_in_ci=true` in a trusted base-commit policy; edits to existing fixtures remain blocked. Require human review for such new fixtures.
- `scripts/verify.config.json.example` is a template, **not** a working project configuration. Configure actual paths, packages, dependencies, commands and budgets. The runtime fails closed without a real manifest.
- Supported v1/v2 `nest.config.json` files are migrated and backed up during `--update-code`, without replacing project-specific test commands. Review any `protected_tests: true` setting manually.
- Local Git worktrees and CLI flags are not OS isolation. Agents may access host filesystem/MCP tools unless separately sandboxed.


## Verify the installed runtime itself

The distribution ZIP and project installation contain `install.py` and the regression suite at `ai_nest/selftests/`. Application `tests/` is never used as the self-test source. In a project, these tests are kept under `ai_nest/selftests/` rather than merged with application tests. Run:

```bash
python -m unittest discover -s ai_nest/selftests -p 'test_*.py' -q
```

The installation manifest must be committed once so fresh clones and CI can pass the installation check. If the runtime is upgraded, run the installer and commit its updated manifest and files.

To check the installed files and configuration, run `python ai_nest/cli.py doctor --provider codex`. It checks a generated tracked `ai_nest/installation.json` file and reports drift in core runtime files and obsolete Claude instructions. The manifest is local diagnostic metadata; agents with host access can tamper with it, so it is not a security guarantee.

**Never assume the project-specific `scripts/verify.config.json` is automatically configured.** The example uses `backend/` and `frontend/` directories that may not exist. Replace it with actual project commands. If eight checks have 600-second budgets, your outer timeout must be at least 4830 seconds or the individual budgets must be reduced. The shipped CI job allows 100 minutes, but you should lower check budgets and tune the CI limit for your actual stack. The installer can adjust an existing manifest's outer budget on upgrade but cannot choose your project's tests.

The installer updates its own AI Nest CI workflow on `--update-code` (backing up the previous workflow first); merge any project-specific CI changes after upgrading. It never deletes unrelated project verification workflows automatically. During upgrades the installer preserves unrelated project files. It only removes the old duplicate `verify.yml` when it can identify it as AI Nest-owned; it reports uncertain `examples/` directories and `.claude/settings.json` hooks for manual review.

## v4.4 distribution fixes

- `ai_nest/installation.json` is tracked, so new clones do not require rerunning the installer to pass integrity diagnostics. Its hashes are informational drift checks, not security enforcement.
- The installer selects `ai_nest/selftests/` only; it cannot mistake a project `tests/` directory for AI Nest tests.
- The AI Nest-owned workflow is upgraded with a backup. CI now has a 100-minute ceiling, but project verification commands and their budgets must be configured explicitly.
- A nested extracted distribution in a project repository is reported by `doctor` to avoid accidental duplicate commits. Move the extracted release outside before staging.
- Existing application `tests/test_verify_runner.py`, duplicate CI workflows, and custom settings/hooks are not blindly removed; inspect and remove confirmed legacy artifacts.
