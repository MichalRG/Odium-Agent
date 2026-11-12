# AI Engineering Nest v4.4 — portable agent orchestrator

Provider-independent Python orchestrator for **Codex CLI**, **Claude Code CLI** and **GitHub Copilot CLI**. The `build-feature` skill is only an entrypoint: the actual stage transitions and gates live in `ai_nest/cli.py`.

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
- whether to run `git init` when the folder is not a repository (default no). It is not offered for a folder that holds Git repositories, because a parent repository would break them;
- whether to add files of 5 MB or more to `.gitignore` while the repository has no commits;
- whether to use a local install;
- which stacks to configure (`NAME[:FOLDER]`), suggesting the ones it detects in the root and first-level folders;
- whether to make the first commit, showing the Git identity it will use.

The installer only sets the Nest up: it copies its files and writes the check configuration. It never starts an agent and never changes project code; features and `bootstrap` start from the chat.

**Without Git** the installer copies the Nest's files and skips every Git step (`.git/info/exclude`, `.gitignore`, the CI workflow, the first commit). Runs need Git: `doctor`, `plan` and `run` say so until you run `git init`, make a first commit and rerun the installer with `--update-code`. For a folder that holds several repositories, the installer lists them; install into each repository you want to work on.

Without a terminal (scripts, CI, agents), it asks nothing and does nothing extra. `--yes` takes the defaults without asking: `git init` (except in a folder that holds repositories), ignore large files, the detected stacks and the first commit. It never starts `bootstrap`. An agent should ask the user first, then call for example `install.py <folder> --local --yes --template python-uv:app`.

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
| `android-kotlin` | `./gradlew lintDebug`, `./gradlew testDebugUnitTest`, `./gradlew assembleDebug` | Android app with Kotlin and the Gradle wrapper; needs a JDK and the Android SDK through `ANDROID_HOME`, because `local.properties` is not in a fresh checkout. Instrumented tests (`src/androidTest`) need an emulator and are not run. Add `ktlint` or `detekt` checks if the project uses them |
| `typescript` | `tsc --noEmit`, `npm test`, `npm run build` | also adds `npm ci` to `environment.setup_commands` |
| `angular` | `npm test -- --watch=false`, `ng build` | adds `npm ci`; Karma needs a headless browser in containers |
| `go` | `go vet ./...`, `go test ./...`, `go build ./...` | |
| `dotnet` | `dotnet build`, `dotnet test` | |

Every template has a `unit` suite, which `tdd.red_commands` runs for the RED step. Build and dependency files (`pom.xml`, Gradle/Maven wrappers, the Gradle version catalog `libs.versions.toml`, `go.mod`, `*.csproj`, `package.json`, `pyproject.toml`, lint configs) are protected from coding agents.

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

`models` in `nest.config.json` picks the model and reasoning effort for each agent stage, per provider. A stage without an entry uses `default`; a provider without entries uses its CLI's own default (for Claude Code that is the account default, because agents run with project settings only). The nest passes them as `codex exec -m <model> -c model_reasoning_effort="<effort>"` `claude --model <model> --effort <effort>` or `copilot --model <model> --reasoning-effort <effort>`, and prints the choice for every stage. The shipped configuration has no `copilot` entries, so Copilot stages use your account's default model; add entries with Copilot's own model names (for example `claude-sonnet-5.5`, as `/model` in Copilot CLI lists them).

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

Stages: `explore`, `specify`, `plan`, `tests`, `protected_tests`, `implement`, `repair`, `bootstrap`, `review`, `security_review`. Upgrading adds the release defaults for missing entries and keeps yours. The chat that runs `$build-feature` uses your own Codex, Claude or Copilot settings, not this section.

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

The easy way is one chat: Codex `$build-feature <what you want>` or Claude Code `/build-feature <what you want>`. GitHub Copilot CLI loads the same skill from `.agents/skills/`: ask it to use the `build-feature` skill, with `--provider copilot` to run the subagents on Copilot too. The chat comes back to you only when the nest has questions, when the plan is ready for your approval, and with the result. It uses these two commands, which you can also run yourself:

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

The plan also lists the commits for the finished work: each one a coherent change with its tests, in dependency order, with its message in English. The report repeats them as `planned_commits`, and the chat commits along them at the merge.

Build a large request in slices: one plan, approval, run and merge per slice, all in the same `--session`, each planned after the previous slice is merged. The chat proposes slices when a plan is large. Smaller slices verify faster, get a more focused review and lose less when an attempt fails.

To skip the approval, `run --session <name> --allow-host-execution "<request>"` does both steps in one command and blocks on open questions. Use `--provider claude` for Claude Code agents or `--provider copilot` for GitHub Copilot CLI agents.

**Copilot CLI as provider.** Log in once with `copilot login`. Copilot CLI has no option to enforce an output schema, so the orchestrator appends the stage schema to the prompt, reads the last assistant message from `--output-format json` and checks it against the schema itself; an answer that does not match blocks the stage like invalid JSON from the other providers. Read-only stages run with `--deny-tool=write`. Copilot's own `--sandbox` is not used, because it needs host features many containers lack.

### Start from an empty project (`bootstrap`)

Feature runs need a working baseline, and their agents may not create build files. For a greenfield repository, first configure the checks for the project you want (for example with `--template python-uv:app`), make one commit (`git commit --allow-empty -m "Initial commit"` is enough in a local install), then let the Nest scaffold it:

```bash
python ai_nest/cli.py bootstrap --provider claude --allow-host-execution \
  "Scaffold the uv app in app/ as described in docs/architecture.md"
```

`bootstrap` runs explore, specify and plan, then one scaffolding agent that sees the exact check and setup commands. It may **create** build files, lockfiles, a `.gitignore` per project folder and one smoke test per test runner. It may not modify or delete existing build, test or gate files, and never touches Nest files. The orchestrator refuses to start when the baseline already passes, blocks changes that contain `node_modules/`, `.venv/` or `__pycache__/`, verifies the result in a fresh checkout with your setup commands and always runs the security reviewer, because the scaffold adds dependencies. The report lists `created_protected_files`: review them before you commit, because from then on they are protected gates. TDD is skipped for this run only. The agent needs network access for the package managers (Codex: the bootstrap stage enables sandbox network access). Add a second stack later the same way: add its checks, commit, run `bootstrap` again.

Skill invocation: Codex `$build-feature ...`, Claude Code `/build-feature ...`, or ask Copilot CLI to use the `build-feature` skill. For long-running commands, use a terminal/job runner that supports the complete CLI lifetime; a single Claude Code Bash tool call may time out. Do not assume a skill invocation itself is an external durable job.

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

- **Protected files.** An agent change to `AGENTS.md`, `.claude/`, `.agents/`, `.github/`, `ai_nest/`, `nest.config.json`, the verification scripts, `package.json`, lockfiles, test or lint settings, or any other path in `safety.blocked_paths` and `safety.protected_basenames` blocks the attempt. `safety.test_path_globs` decides what counts as a test. Changes to checks, dependencies or CI are maintenance by a person, never an agent edit; a PR that changes protected files needs its own reviewed exception.
- **Nothing fails open.** A failed check, a missing manifest or binary, or a timeout never becomes a pass. Timeouts kill the whole process group on POSIX. Invalid provider JSON blocks the stage after its output logs are saved.
- **Pinned base.** Every stage pins Git HEAD: an agent commit or rebase fails the attempt. Every repair resets the worktree to the original `base_commit`, so agent commits never reach the result. An attempt blocked before verification (policy violation, moved HEAD, no changes) is reset with nothing kept, and the next attempt runs `implement` again with the reason as feedback; `repair` runs only on code that reached verification.
- **Fixed stages.** Risk routing comes only from the orchestrator, never from agent prompts. The core stages are fixed; only the security review is conditional.
- **RED policy.** `tdd.already_green_policy` defaults to `block`; `allow` is explicit. A test that fails on a missing *new* symbol is valid RED. A missing new Python or TypeScript module counts only when it is in the planner's `tasks[].files` and referenced by the generated tests. Unrelated missing dependencies and broken test setups block. A test may assert on errors such as `SyntaxError` or `ENOENT` itself: those words block RED only when the expected tests never ran.
- **Fixtures.** The test engineer may add a **new** `tests/conftest.py`; editing an existing fixture is blocked. CI `verify --base` blocks new fixtures as well, because it cannot tell which agent added them, unless the trusted base policy sets `safety.allow_new_test_fixtures_in_ci=true`. Review such fixtures by hand.
- **Failure feedback.** With `tdd.protected_tests=false` (the default) the repair agent gets sanitized tails of the public failure logs. With protected tests on, all raw verification output is withheld from the coder.
- **Agent time.** `limits.agent_timeout_seconds` (default 1800) is a window, not a hard stop, for stages that write files (tests, implement, repair). At the end of each window the orchestrator checks the worktree: if the files reached a state it has not seen before, the agent gets another window, up to `limits.agent_max_seconds` (default 14400) in total. If nothing changed in the last window, or the files went back to an earlier state, the agent is stopped. A coder stopped this way keeps its unfinished code: it goes through the same policy checks and verification, and `repair` continues it. Read-only stages stop after one window.
- **Review size.** `limits.review_diff_max_chars` (default 400000, about 100k tokens) caps the diff of code and public tests that the reviewers get inline. Lockfiles are left out. The diff is never truncated: a larger diff blocks the run after verification, so split the feature into slices or raise the limit within the review models' context.
- **Check time.** `limits.check_timeout_seconds` applies per **orchestrator check**, not to each check inside `scripts/verify.py`, so it must cover the sum of the manifest's check budgets: eight checks of 600 seconds need at least 4830. The shipped CI job allows 100 minutes; lower the check budgets and the CI limit to fit your stack. On upgrade the installer raises the outer budget when the manifest needs it, but it cannot choose your tests.
- **Cleanup.** `cleanup.blocked_worktrees` (default true) removes failed worktrees and their temporary branches after logs, patches and session reports are written. Verified worktrees stay for inspection.
- **Project checks are yours.** The package ships an example manifest that uses `backend/` and `frontend/`, not working checks. Configure `scripts/verify.config.json`, `tdd.red_commands` and any `environment.setup_commands` before running features; the runtime fails closed without a real manifest, and `verify.py` rejects unknown keys in a check. Customize the CI template's install and service steps for your repository.
- **Not a sandbox.** Git worktrees and CLI flags are not OS isolation: agents can reach the host filesystem and MCP tools. Hidden tests are not confidential while workers share a filesystem, so enable `tdd.protected_tests` only in separately isolated workers. Codex stages run in its `--sandbox`. The read-only stages of Claude and Copilot keep a shell for investigation, and the orchestrator checks them for source changes afterwards. Claude runs with `--setting-sources project --strict-mcp-config` and Copilot with `--no-custom-instructions --disable-builtin-mcps`; neither isolates user or managed plugins, tools or MCP servers. Do not point this at privileged repositories without external sandboxing, separate identities and network policy. Prompts go through stdin, so long contexts never hit argument-length limits.
- **Providers.** The self-tests use stand-in CLIs, not live models. Check your installed CLI version and run a controlled smoke test before you rely on a provider.

## Self-tests

```bash
python -m unittest discover -s ai_nest/selftests -p 'test_*.py' -q
```

The suite lives in `ai_nest/selftests/`, in this repository and in every installed project; the installer never takes a project's own `tests/` for it. It runs the real orchestrator against stand-in provider CLIs and real temporary Git repositories: the full flow with public RED and hidden-test separation, install and upgrade, provider arguments, policies and the verify runner. It does not test live model behaviour. In this repository, `bash scripts/verify.sh` runs it.

## Upgrades and distribution

- An existing folder is safe to install into. A file already at a Nest path on the first install, for example a project's own `scripts/verify.sh` or `install.py`, stays and is recorded as the project's in `ai_nest/installation.json`; `--update-code` never replaces it, only `--force` does. Before the installer replaces any file that differs from what the Nest last wrote there, it copies it to `.ai-nest/config-backups/` and prints where.
- `ai_nest/installation.json` is tracked. Commit it once, so fresh clones and CI pass the installation check, and commit the updated manifest after every upgrade. `doctor` uses its hashes to report drift in core files and obsolete Claude instructions. Agents with host access can change it, so it is a diagnostic, not a security guarantee.
- `--update-code` replaces the AI Nest CI workflow (from `ai_nest/templates/ai-nest-verify.yml`) and backs up the old one when you changed it; merge your own CI changes back after upgrading. It never deletes unrelated workflows: an old duplicate `verify.yml` goes only when it is clearly AI Nest's, and `examples/` folders and `.claude/settings.json` hooks are reported for manual review instead.
- `doctor` reports a release archive extracted inside the repository (`ai-nest-complete-v*/`); move it out before staging.
