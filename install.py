#!/usr/bin/env python3
"""Install AI Engineering Nest into an existing project without overwriting settings."""
from pathlib import Path
import argparse
import json
import os
import copy
import hashlib
import datetime as dt
import re
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
RELEASE = '4.4'
# Never select the application test directory as AI Nest's self-test source.
SELFTEST_SOURCE = SOURCE / 'ai_nest' / 'selftests'
FILES = [
    'ai_nest/cli.py',
    'ai_nest/memory.py',
    'install.py',
    *[str(p.relative_to(SOURCE)) for p in (SOURCE / 'ai_nest' / 'prompts').glob('*.md')],
    '.agents/skills/build-feature/SKILL.md',
    '.claude/skills/build-feature/SKILL.md',
    'scripts/verify.sh',
    'scripts/verify.py',
    'scripts/verify.config.json.example',
    'ai_nest/templates/ai-nest-verify.yml',
    '.github/workflows/ai-nest-verify.yml',
    'nest.config.json',
    '.claude/settings.json',
    *[str(p.relative_to(SOURCE)) for p in sorted((SOURCE / 'ai_nest' / 'templates' / 'verify').glob('*.json'))],
    # Keep the runtime's regression suite available in the installed project.
    # Do not inject these tests into the application's own test directories.
    *[f'ai_nest/selftests/{p.name}' for p in SELFTEST_SOURCE.glob('test_*.py')],
]
# The Nest's own repository runs a CI of its own, so the project workflow ships as a template.
SOURCE_OF = {'.github/workflows/ai-nest-verify.yml': 'ai_nest/templates/ai-nest-verify.yml'}
BRIDGES = {
    'AGENTS.md': '\n\n## AI Engineering Nest\n\nUse `python ai_nest/cli.py doctor` and the AI Nest workflow documented in `AI_NEST_README.md`. Never bypass gates or modify the AI Nest policy files to make code pass.\n',
    'CLAUDE.md': '\n\n## AI Engineering Nest\n\nRead and follow AGENTS.md. Use the provider-independent CLI in AI_NEST_README.md for enforced verification.\n',
    'GEMINI.md': '\n\n# AI Engineering Nest\n\n@./AGENTS.md\n',
    '.github/copilot-instructions.md': '\n\n# AI Engineering Nest\n\nFollow AGENTS.md and AI_NEST_README.md. Do not claim verification without successful independent checks.\n',
}


TEMPLATES = sorted(p.stem for p in (SOURCE / 'ai_nest' / 'templates' / 'verify').glob('*.json'))
# Paths a local install keeps out of Git (anchored, so same-named files in subfolders are unaffected).
LOCAL_EXCLUDES = ['/.ai-nest/', '/ai_nest/', '/install.py', '/nest.config.json', '/AI_NEST_README.md',
                  '/scripts/verify.sh', '/scripts/verify.py', '/scripts/verify.config.json',
                  '/scripts/verify.config.json.example', '/.agents/skills/build-feature/',
                  '/.claude/skills/build-feature/', '/.claude/settings.json', '/AGENTS.md', '/CLAUDE.md',
                  '/GEMINI.md', '/.github/copilot-instructions.md']
# Build/dependency output that would otherwise leak into agent change sets.
GENERATED_IGNORES = ['__pycache__/', '*.pyc', '.pytest_cache/', '.DS_Store', 'node_modules/', 'dist/', 'build/', 'coverage/']
# A workspace verifies each repository with its own checks, so it gets no verify.sh, CI workflow or self-tests.
WORKSPACE_SKIPS = ('scripts/', '.github/', 'ai_nest/templates/ai-nest-verify.yml', 'ai_nest/selftests/')
EXCLUDE_BEGIN, EXCLUDE_END = '# >>> AI Nest local install (managed by install.py) >>>', '# <<< AI Nest local install <<<'


def has_git(dst: Path) -> bool:
    try:
        return (dst / '.git').exists() or git_out(dst, 'rev-parse', '--show-toplevel').returncode == 0
    except OSError:  # Git itself is not installed
        return False


def nested_repositories(dst: Path) -> list[str]:
    return [p.name for p in sorted(dst.iterdir()) if p.is_dir() and (p / '.git').exists()]


def tracked_files(dst: Path) -> set[str]:
    p = subprocess.run(['git', 'ls-files', '-z'], cwd=dst, capture_output=True, text=True)
    return set(filter(None, p.stdout.split('\0')))


def write_local_excludes(dst: Path, entries: list[str]) -> Path:
    """Hide files via .git/info/exclude: local to this clone, never committed."""
    out = subprocess.run(['git', 'rev-parse', '--git-path', 'info/exclude'], cwd=dst,
                         capture_output=True, text=True, check=True).stdout.strip()
    path = Path(out) if Path(out).is_absolute() else dst / out
    block = '\n'.join([EXCLUDE_BEGIN, *entries, EXCLUDE_END])
    old = path.read_text(encoding='utf-8') if path.is_file() else ''
    pattern = re.compile(re.escape(EXCLUDE_BEGIN) + '.*?' + re.escape(EXCLUDE_END), re.S)
    new = pattern.sub(lambda _: block, old) if pattern.search(old) else old.rstrip('\n') + ('\n\n' if old.strip() else '') + block + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding='utf-8')
    return path


def template_spec(value: str) -> tuple[str, str]:
    """'python' or 'python:backend' -> (template, folder); the folder may not exist yet (bootstrap creates it)."""
    name, _, folder = value.partition(':')
    if name not in TEMPLATES:
        raise argparse.ArgumentTypeError(f'unknown template {name!r}; choose from {", ".join(TEMPLATES)}')
    if folder.startswith('/') or '\\' in folder or '..' in folder.split('/'):
        raise argparse.ArgumentTypeError(f'folder must be relative inside the repository: {folder!r}')
    folder = folder.rstrip('/') or '.'
    return name, folder


def template_checks(specs: list[tuple[str, str]]) -> tuple[list[dict], list[dict], list[str]]:
    """Checks, setup commands and required suites of the stack templates, run in each stack's folder."""
    checks, setup, suites = [], [], []
    for name, folder in specs:
        part = json.loads((SOURCE / 'ai_nest' / 'templates' / 'verify' / f'{name}.json').read_text(encoding='utf-8'))
        # Several stacks share one manifest, so names get a folder prefix to stay unique.
        prefix = '' if len(specs) == 1 else re.sub(r'[^A-Za-z0-9_-]', '-', folder if folder != '.' else name) + '-'
        checks += [{**c, 'name': prefix + c['name'], 'cwd': folder} for c in part['checks']]
        setup += [{**c, 'name': prefix + c['name'], 'cwd': folder} for c in part.get('nest_setup_commands', [])]
        suites += [x for x in part.get('required_suites', []) if x not in suites]
    return checks, setup, suites


def apply_template(dst: Path, specs: list[tuple[str, str]], force: bool) -> None:
    target = dst / 'scripts' / 'verify.config.json'
    label = ' + '.join(f'{name}:{folder}' for name, folder in specs)
    if target.exists() and not force:
        print(f'Template {label}: scripts/verify.config.json already exists; left unchanged.')
        return
    checks, setup, suites = template_checks(specs)
    data = {'version': 1, 'default_timeout_seconds': 600, 'required_suites': suites, 'checks': checks}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f'Template {label}: wrote scripts/verify.config.json; edit commands and cwd for your layout.')
    cfg_path = dst / 'nest.config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    env = cfg.setdefault('environment', {})
    if setup and not env.get('setup_commands'):
        env['setup_commands'] = setup  # fresh worktrees have no node_modules
        cfg_path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
        print('  Added environment.setup_commands: ' + ', '.join(s['name'] for s in setup))


def configure_workspace(dst: Path) -> list[str]:
    """Give each repository its own checks, from the stacks found in it; entries already there are kept."""
    path = dst / 'nest.config.json'
    try:
        cfg = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        print('WARNING: nest.config.json is invalid; workspace.repos not updated.')
        return []
    before = json.dumps(cfg)
    repos = cfg.setdefault('workspace', {}).setdefault('repos', {})
    # Runs use the repository's checks; the single-repository verify.sh commands would only mislead.
    cfg.setdefault('verification', {})['commands'] = []
    cfg.setdefault('tdd', {})['red_commands'] = []
    lines = []
    for name in nested_repositories(dst):
        # Build output must not leak into a run's change set; the block stays in this clone only.
        write_local_excludes(dst / name, GENERATED_IGNORES)
        if name not in repos:
            checks, setup, _ = template_checks([template_spec(s) for s in detect_stacks(dst / name)])
            repos[name] = {'checks': checks, 'setup_commands': setup}
        names = [c.get('name', '?') for c in repos[name].get('checks', [])] if isinstance(repos[name], dict) else []
        lines.append(f'{name}: ' + (', '.join(names) or 'NO CHECKS: add them by hand'))
    if json.dumps(cfg) != before:
        path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    return lines


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup_file(dst: Path, path: Path) -> Path:
    target_dir = dst / '.ai-nest' / 'config-backups'
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f'{path.name}.{dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.bak'
    shutil.copy2(path, backup)
    return backup


def migrate_old_instructions(dst: Path) -> list[str]:
    """Remove only known obsolete AI Nest instructions, preserving user rules."""
    changed = []
    claude = dst / 'CLAUDE.md'
    if claude.is_file():
        content = claude.read_text(encoding='utf-8')
        lines = content.splitlines()
        filtered = [line for line in lines if '.claude/agents/' not in line and
                    'New behavior gets a test' not in line]
        if filtered != lines:
            backup_file(dst, claude)
            filtered.append('')
            filtered.append('In AI Nest runs, only the test engineer writes tests; see AGENTS.md.')
            claude.write_text('\n'.join(filtered).strip() + '\n', encoding='utf-8')
            changed.append('CLAUDE.md (removed obsolete Nest instructions; backed up)')
    for rel in ('AGENTS.md', '.github/copilot-instructions.md', 'GEMINI.md'):
        path = dst / rel
        if not path.is_file():
            continue
        content = path.read_text(encoding='utf-8')
        # Correct deleted old doc references without touching arbitrary README links.
        new = re.sub(r'(?<!AI_NEST_)README\.md', 'AI_NEST_README.md', content) if 'AI Engineering Nest' in content or rel.endswith('copilot-instructions.md') else content
        new = new.replace('`AI_NEST_README.md` (or the template `AI_NEST_README.md`)', '`AI_NEST_README.md`')
        new = new.replace('AI_NEST_README.md (or the template AI_NEST_README.md)', 'AI_NEST_README.md')
        # Previous installers could append identical Nest paragraphs repeatedly.
        if rel.endswith('copilot-instructions.md'):
            lines = new.splitlines()
            dedup = []
            seen = set()
            for line in lines:
                if 'AI_NEST_README.md' in line or 'Follow AGENTS.md' in line or 'Follow `AGENTS.md`' in line:
                    if line.strip() in seen:
                        continue
                    seen.add(line.strip())
                dedup.append(line)
            new = '\n'.join(dedup).strip() + '\n'
        if rel == 'GEMINI.md' and ('AI Engineering Nest' in new or '@./AGENTS.md' in new):
            # Only deduplicate literal AI Nest bridge lines; preserve project instructions.
            nest_bridge_lines = {'# Gemini CLI compatibility', '# AI Engineering Nest',
                                 '@./AGENTS.md',
                                 'The portable orchestrator supports Codex and Claude CLIs, not Gemini directly.'}
            seen_bridge = set()
            kept = []
            for line in new.splitlines():
                if line.strip() in nest_bridge_lines:
                    if line.strip() in seen_bridge:
                        continue
                    seen_bridge.add(line.strip())
                kept.append(line)
            new = '\n'.join(kept).strip() + '\n'
        if new != content:
            backup_file(dst, path)
            path.write_text(new, encoding='utf-8')
            changed.append(rel + ' (stale Nest doc references / duplicate instructions cleaned; backed up)')
    return changed


def report_legacy_files(dst: Path) -> list[str]:
    notes = []
    old_workflow = dst / '.github/workflows/verify.yml'
    if old_workflow.is_file():
        content = old_workflow.read_text(encoding='utf-8', errors='replace')
        if 'AI Nest' in content or 'ai_nest/cli.py' in content:
            backup_file(dst, old_workflow)
            old_workflow.unlink()
            notes.append('Removed old AI Nest verify.yml (backup saved)')
        else:
            notes.append('WARNING: .github/workflows/verify.yml exists; inspect for duplicate CI (not deleted)')
    examples = dst / 'examples'
    if examples.is_dir():
        notes.append('WARNING: examples/ exists; not deleted because ownership is unknown')
    settings = dst / '.claude/settings.json'
    if settings.exists() and '"coder"' in settings.read_text(encoding='utf-8', errors='replace'):
        notes.append('WARNING: .claude/settings.json exists; review hooks for legacy subagents (not deleted)')
    return notes


def previous_records(dst: Path) -> dict | None:
    """What the last install recorded per Nest path; None before the first install.

    'installed': the Nest wrote the file, sha256 is what it wrote. 'project': the project's own file
    at a Nest path, never replaced by --update-code. 'preserved': origin unknown (older installers).
    """
    try:
        files = json.loads((dst / 'ai_nest' / 'installation.json').read_text(encoding='utf-8'))['files']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {name: entry for name, entry in files.items() if isinstance(entry, dict)} if isinstance(files, dict) else None


def write_installation_manifest(dst: Path, records: dict, mode: str = 'committed') -> Path:
    """Diagnostic integrity manifest, not a security boundary against agents."""
    path = dst / 'ai_nest' / 'installation.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'release': RELEASE, 'mode': mode, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                                'files': records, 'configuration_schema': 2}, indent=2) + '\n', encoding='utf-8')
    return path


def migrate_existing_config(dst: Path) -> None:
    """Safely upgrade supported policy fields without replacing project commands.

    Config files are backed up before any migration. Nonstandard settings are
    preserved; users must still choose real test commands and environment setup.
    """
    target = dst / 'nest.config.json'
    default = json.loads((SOURCE / 'nest.config.json').read_text(encoding='utf-8'))
    if not target.is_file():
        return
    try:
        old = json.loads(target.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        print('WARNING: existing nest.config.json is invalid; inspect manually.')
        return
    if old.get('version') not in (1, 2):
        print('WARNING: cannot migrate unknown nest.config.json version automatically.')
        return
    merged = copy.deepcopy(old)
    def merge_missing(destination, defaults):
        for k, v in defaults.items():
            if k not in destination:
                destination[k] = copy.deepcopy(v)
            elif isinstance(v, dict) and isinstance(destination[k], dict):
                merge_missing(destination[k], v)
    merge_missing(merged, default)
    for key in ('blocked_paths', 'protected_basenames', 'test_path_globs'):
        current = merged.setdefault('safety', {}).get(key, [])
        if not isinstance(current, list):
            print(f'WARNING: cannot migrate safety.{key}; config unchanged.')
            return
        # For tests, avoid broad patterns that match non-test source/config files.
        if key == 'test_path_globs':
            current = [x for x in current if x not in ('*.spec.*', '**/*.spec.*',
                                                       '*.test.*', '**/*.test.*')]
        merged['safety'][key] = list(dict.fromkeys(current + default['safety'][key]))
    merged['safety'].pop('test_path_markers', None)  # unused legacy setting
    if merged.get('tdd', {}).get('protected_tests', False):
        print('WARNING: disabling protected_tests=true during upgrade: worktrees do not protect files from host processes.')
        merged['tdd']['protected_tests'] = False
    # Adjust outer timeout for the actual committed check manifest, not an example.
    check_manifest = dst / 'scripts' / 'verify.config.json'
    if check_manifest.is_file() and any(c.get('argv', [])[:2] == ['bash', 'scripts/verify.sh']
                                        for c in merged.get('verification', {}).get('commands', [])):
        try:
            checks = json.loads(check_manifest.read_text(encoding='utf-8'))
            declared = sum(int(c.get('timeout_seconds', checks.get('default_timeout_seconds', 600)))
                           for c in checks.get('checks', []))
            limits = merged.setdefault('limits', {})
            if int(limits.get('check_timeout_seconds', 600)) < declared + 30:
                limits['check_timeout_seconds'] = declared + 30
                print(f'WARNING: raised outer check_timeout_seconds to {declared + 30}s to cover declared check budgets; review this value.')
        except (ValueError, OSError, TypeError) as ex:
            print(f'WARNING: cannot migrate verification timeout: {ex}')
    merged['version'] = 2
    merged['policy_version'] = '2026-11'
    if merged != old:
        backup = dst / '.ai-nest' / 'config-backups' / f'nest.config.{dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        target.write_text(json.dumps(merged, indent=2) + '\n', encoding='utf-8')
        print(f'Updated nest.config.json policy (v{old["version"]} -> v2); backup: {backup}')
        print('ACTION REQUIRED: review timeouts, TDD policy, real project checks and commit.')
    if merged.get('tdd', {}).get('protected_tests', False):
        print('WARNING: protected_tests=true is not confidential without isolated containers.')


def install(dst: Path, force: bool = False, update_code: bool = False, local: bool = False,
            templates: list[tuple[str, str]] | None = None) -> None:
    dst = dst.resolve()
    # Without Git the files are copied and every Git step is skipped; runs need Git later.
    git = has_git(dst)
    local = local and git
    if dst == SOURCE:
        raise RuntimeError('Source and destination cannot be the same folder')
    workspace = not git and bool(nested_repositories(dst))
    if workspace and templates:
        raise RuntimeError('--template writes scripts/verify.config.json, which a workspace does not use; '
                           'edit workspace.repos in nest.config.json instead')
    installed, preserved = [], []
    previous = previous_records(dst)
    records = {}
    # Local mode never writes a file the project tracks.
    tracked = tracked_files(dst) if local else set()
    updatable = ('ai_nest/', '.agents/skills/', '.claude/skills/')
    updatable_files = {'scripts/verify.sh', 'scripts/verify.py', 'install.py'}
    for name in FILES:
        source = SOURCE / SOURCE_OF.get(name, name)
        target = dst / name
        if (local or not git) and name == '.github/workflows/ai-nest-verify.yml':
            continue  # CI checkouts cannot see an uncommitted Nest
        if workspace and name.startswith(WORKSPACE_SKIPS):
            continue
        record = (previous or {}).get(name, {})
        status = record.get('status')
        # A file found at a Nest path on the first install, or where the Nest never installed one, is
        # the project's. An upgrade of an install without a manifest cannot tell, so it backs files up.
        project_file = target.is_file() and (status == 'project' or (previous is None and not update_code)
                                             or (previous is not None and name not in previous))
        if name in tracked or (project_file and not force):
            preserved.append(name)
            if target.is_file():
                records[name] = {'status': 'project', 'sha256': sha256_file(target)}
            continue
        replace_on_update = (name.startswith(updatable) or name in updatable_files
                             or name == '.github/workflows/ai-nest-verify.yml')
        if target.exists() and not force and not (update_code and replace_on_update):
            preserved.append(name)
            records[name] = record or {'status': 'preserved', 'sha256': sha256_file(target)}
            continue
        if update_code and name == '.github/workflows/ai-nest-verify.yml' and target.is_file() \
                and 'AI Nest' not in target.read_text(encoding='utf-8', errors='replace'):
            preserved.append(name)
            records[name] = {'status': 'project', 'sha256': sha256_file(target)}
            print('WARNING: Non-Nest CI workflow at .github/workflows/ai-nest-verify.yml left unchanged.')
            continue
        # Keep a copy of anything that is not exactly what the Nest wrote last time.
        written = record.get('sha256') if status == 'installed' else None
        if target.is_file() and sha256_file(target) not in (written, sha256_file(source)):
            print(f'Backed up {name} before replacing it: {backup_file(dst, target)}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        installed.append(name)
        records[name] = {'status': 'installed', 'sha256': sha256_file(target)}
    if update_code and not force:
        migrate_existing_config(dst)
        if not local:  # these edit project instruction files
            installed.extend(migrate_old_instructions(dst))
            for note in report_legacy_files(dst):
                print(note)
    doc = dst / 'AI_NEST_README.md'
    if 'AI_NEST_README.md' not in tracked and (not doc.exists() or force or update_code):
        shutil.copy2(SOURCE / 'AI_NEST_README.md', doc)
        installed.append('AI_NEST_README.md')
    for name, bridge in BRIDGES.items():
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(SOURCE / name, target)
            installed.append(name)
        elif not local and 'AI Engineering Nest' not in target.read_text(encoding='utf-8'):
            with target.open('a', encoding='utf-8') as f:
                f.write(bridge)
            installed.append(f'{name} (appended)')
        else:
            preserved.append(name)
    claude_doc = dst / 'CLAUDE.md'
    if claude_doc.is_file():
        text = claude_doc.read_text(encoding='utf-8')
        if '.claude/agents/' in text or 'New behavior gets a test' in text:
            print('WARNING: CLAUDE.md may contain obsolete agent/test ownership instructions.')
            print('  Review against AGENTS.md; coder should not be instructed to modify tests.')
    if templates:
        apply_template(dst, templates, force)
    configured = configure_workspace(dst) if workspace else []
    ignores = dst / '.gitignore'
    lines = ignores.read_text(encoding='utf-8').splitlines() if ignores.exists() else []
    wanted = ['.ai-nest/', *GENERATED_IGNORES]
    missing = [rule for rule in wanted if rule not in lines]
    if not git:
        pass
    elif local:
        exclude = write_local_excludes(dst, [e for e in LOCAL_EXCLUDES if e.strip('/') not in tracked] + GENERATED_IGNORES)
        installed.append(f'{exclude.relative_to(dst) if exclude.is_relative_to(dst) else exclude} (AI Nest block)')
    elif missing:
        with ignores.open('a', encoding='utf-8') as f:
            f.write(('\n' if lines else '') + '\n'.join(missing) + '\n')
        installed.append('.gitignore (appended)')
    # The legacy .ai-nest/installation.json is ignored and cannot survive cloning.
    # Keep it in place as a historical diagnostic, but write the active manifest
    # into the tracked ai_nest/ directory.
    mode = 'local' if local else 'committed' if git else 'workspace' if workspace else 'no-git'
    manifest_path = write_installation_manifest(dst, records, mode)
    print(f'Installation manifest: {manifest_path}' + (' (commit this file)' if mode == 'committed' else ''))
    print('Installed/updated:')
    for name in installed:
        print('  +', name)
    if preserved:
        print('Preserved (not overwritten):')
        for name in preserved:
            print('  =', name)
    if workspace:
        repos = nested_repositories(dst)
        print(f'\nWorkspace install in {dst}. Git repositories inside: {", ".join(repos)}.')
        print('A run works in one repository, on a new branch and worktree of it, and verifies the change with')
        print("that repository's checks: workspace.repos in nest.config.json, found from its stacks. Edit them to fit:")
        for line in configured:
            print('  ' + line)
        print('Next:')
        print(f'  python ai_nest/cli.py doctor --repo {repos[0]} --provider codex')
        print(f'  python ai_nest/cli.py verify --repo {repos[0]} --allow-host-execution  # runs its checks once')
        print(f'  python ai_nest/cli.py plan --repo {repos[0]} --allow-host-execution "<request>"')
        return
    manifest = dst / 'scripts' / 'verify.config.json'
    if not manifest.is_file():
        print('\nACTION REQUIRED: scripts/verify.config.json is not configured.')
        print(f'  rerun with --template NAME[:FOLDER] ({", ".join(TEMPLATES)}), or:')
        print('  cp scripts/verify.config.json.example scripts/verify.config.json')
        print('  Edit checks and required_suites for your project; no tests are assumed to pass.')
    if not git:
        print(f'\nNo Git repository in {dst}: the Nest files are copied, and no Git step ran.')
        nested = nested_repositories(dst)
        if nested:
            print(f'  Git repositories inside: {", ".join(nested)}. Runs work per repository, so to use the Nest')
            print(f'  in one of them, install into it: python {SOURCE / "install.py"} {dst / nested[0]} --local')
        print('  Runs need Git: when you want them here, run git init, make a first commit and rerun this')
        print('  installer with --update-code.')
        return
    if local:
        print('\nLocal install: Nest files are listed in .git/info/exclude, so git status stays clean and nothing is committed.')
        print('Next: configure real project checks, then run:')
    else:
        print('\nNext: configure real project checks and setup commands, review policy, commit, then run:')
        print('  git add -A && git diff --cached --stat  # REVIEW before committing')
    try:
        checks = json.loads(manifest.read_text(encoding='utf-8')).get('checks', [])
    except (OSError, ValueError, AttributeError):
        checks = []
    missing = sorted({c.get('cwd', '.') for c in checks if isinstance(c, dict) and not (dst / c.get('cwd', '.')).is_dir()})
    if missing:  # greenfield: the configured project folders do not exist yet
        print(f'  python ai_nest/cli.py bootstrap --provider claude --allow-host-execution "<what to build>"  # creates {", ".join(missing)}')
    print('  bash scripts/verify.sh --list')
    print('  python ai_nest/cli.py doctor --provider codex')


# First match per folder wins, so the more specific stack comes first. Gradle templates run
# ./gradlew, so they match only the wrapper's folder, never a module folder below it.
STACK_MARKERS = [('angular', ('angular.json',)), ('python-uv', ('uv.lock',)),
                 ('python', ('pyproject.toml', 'requirements.txt', 'setup.py')),
                 ('typescript', ('tsconfig.json', 'package.json')), ('java-maven', ('pom.xml',)),
                 ('android-kotlin', ('*/src/main/AndroidManifest.xml',)),
                 ('java-gradle', ('gradlew',)), ('go', ('go.mod',)),
                 ('dotnet', ('*.csproj', '*.sln'))]
LARGE_FILE_BYTES = 5 * 1024 * 1024


def git_out(dst: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=dst, capture_output=True, text=True)


def detect_stacks(dst: Path) -> list[str]:
    """Template suggestions for projects at the root or one folder below it."""
    folders = [dst, *sorted(p for p in dst.iterdir() if p.is_dir() and not p.name.startswith('.')
                            and p.name not in ('node_modules', 'ai_nest', 'scripts'))]
    found = []
    for folder in folders:
        for name, markers in STACK_MARKERS:
            if any(next(folder.glob(m), None) for m in markers):
                found.append(name if folder == dst else f'{name}:{folder.name}')
                break
    return found


def large_paths(dst: Path) -> list[tuple[str, int]]:
    """Ignore rules for big files in a repository without commits, grouped by top-level folder."""
    rules = {}
    for root, dirs, files in os.walk(dst):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.venv')]
        for name in files:
            path = Path(root) / name
            if path.stat().st_size >= LARGE_FILE_BYTES and git_out(dst, 'check-ignore', '-q', str(path)).returncode:
                rel = path.relative_to(dst)
                rule = f'/{rel.parts[0]}/' if len(rel.parts) > 1 else f'/{rel}'
                rules[rule] = rules.get(rule, 0) + path.stat().st_size
    return sorted(rules.items())


def guided_setup(args) -> int:
    """Ask what a bare install leaves open; --yes takes the defaults, a script without --yes changes nothing extra."""
    interactive = sys.stdin.isatty() and not args.yes

    def ask(question: str, default: str) -> str:
        if not interactive:
            return default if args.yes else ''
        try:
            return input(f'{question} ').strip() or default
        except (EOFError, KeyboardInterrupt):
            raise RuntimeError('Setup cancelled') from None

    def confirm(question: str, default: bool) -> bool:
        return ask(f'{question} [{"Y/n" if default else "y/N"}]', 'y' if default else 'n').lower().startswith('y')

    dst = args.repository.resolve()
    git = has_git(dst)
    # Git is opt-in: never for a folder that holds repositories, which a parent repository would break.
    if not git and not nested_repositories(dst) and confirm(
            f'{dst} is not a Git repository. Run git init? (No: copy the files and skip every Git step)', args.yes):
        git_out(dst, 'init', '-q')
        print(f'Initialized Git repository in {dst}')
        git = True
    fresh = git and bool(git_out(dst, 'rev-parse', '--verify', '-q', 'HEAD').returncode)
    if fresh:
        big = large_paths(dst)
        listing = '\n  '.join(f'{rule}  ({size // (1024 * 1024)} MB)' for rule, size in big)
        if big and confirm(f'These large files should not go into Git:\n  {listing}\nAdd them to .gitignore?', True):
            with (dst / '.gitignore').open('a', encoding='utf-8') as f:
                f.write(''.join(f'{rule}\n' for rule, _ in big))
    if git and interactive and not args.local and not args.update_code:
        args.local = confirm('Keep AI Nest out of the project history (local install, nothing to commit)?', True)
    templates = args.template
    workspace = not git and bool(nested_repositories(dst))  # its repositories get their checks in install()
    while not templates and not workspace and not (dst / 'scripts' / 'verify.config.json').exists():
        suggested = ' '.join(detect_stacks(dst))
        answer = ask(f'Which stacks should the checks cover? Enter NAME[:FOLDER] values ({", ".join(TEMPLATES)}),\n'
                     f'for example "python-uv:app angular:frontend". Empty = configure later. [{suggested}]', suggested)
        try:
            templates = [template_spec(value) for value in answer.split()]
            break
        except argparse.ArgumentTypeError as ex:
            if not interactive:
                raise RuntimeError(str(ex)) from ex
            print(ex)
    install(dst, args.force, args.update_code, args.local, templates)
    if fresh:
        who = ' '.join(git_out(dst, 'config', key).stdout.strip() for key in ('user.name', 'user.email'))
        if confirm(f'\nCreate the first commit of the current files as "{who}"?', True):
            git_out(dst, 'add', '-A')
            commit = git_out(dst, 'commit', '-qm', 'Initial commit')
            print('Created the first commit.' if commit.returncode == 0 else f'Commit failed: {commit.stderr.strip()}')
    # Setup only: the installer never starts an agent. Features and bootstrap start from the chat.
    return 0


def main():
    p = argparse.ArgumentParser(description='Install portable AI Engineering Nest into a Git repo')
    p.add_argument('repository', type=Path)
    p.add_argument('--yes', action='store_true',
                   help='Do not prompt: run git init, ignore large files, use detected stacks and make the first commit')
    p.add_argument('--force', action='store_true', help='Replace AI Nest core/config files, also project files at Nest paths, after backing up changed ones '
                        '(never replaces existing instruction bridges)')
    p.add_argument('--update-code', action='store_true',
                   help='Upgrade runtime, skills, verifier and docs; migrate supported v1 config with a backup, preserve other settings and instructions; '
                        'keep project files at Nest paths and back up Nest files changed since the last install')
    p.add_argument('--local', action='store_true',
                   help='Keep AI Nest out of the project history: list its files in .git/info/exclude and never modify tracked files')
    p.add_argument('--template', type=template_spec, action='append', metavar='NAME[:FOLDER]',
                   help=f'Write scripts/verify.config.json from stack templates ({", ".join(TEMPLATES)}); '
                        'repeat for several stacks, e.g. --template python-uv:app --template angular:frontend')
    args = p.parse_args()
    if not args.repository.is_dir():
        p.error('Directory does not exist')
    try:
        return guided_setup(args)
    except (RuntimeError, OSError) as ex:
        print(f'Installation blocked: {ex}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
