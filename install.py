#!/usr/bin/env python3
"""Install AI Engineering Nest into an existing project without overwriting settings."""
from pathlib import Path
import argparse
import json
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
    '.github/workflows/ai-nest-verify.yml',
    'nest.config.json',
    '.claude/settings.json',
    *[str(p.relative_to(SOURCE)) for p in sorted((SOURCE / 'ai_nest' / 'templates' / 'verify').glob('*.json'))],
    # Keep the runtime's regression suite available in the installed project.
    # Do not inject these tests into the application's own test directories.
    *[f'ai_nest/selftests/{p.name}' for p in SELFTEST_SOURCE.glob('test_*.py')],
]
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
EXCLUDE_BEGIN, EXCLUDE_END = '# >>> AI Nest local install (managed by install.py) >>>', '# <<< AI Nest local install <<<'


def tracked_files(dst: Path) -> set[str]:
    p = subprocess.run(['git', 'ls-files', '-z'], cwd=dst, capture_output=True, text=True)
    return set(filter(None, p.stdout.split('\0')))


def write_local_excludes(dst: Path, tracked: set[str]) -> Path:
    """Hide Nest files via .git/info/exclude: local to this clone, never committed."""
    out = subprocess.run(['git', 'rev-parse', '--git-path', 'info/exclude'], cwd=dst,
                         capture_output=True, text=True, check=True).stdout.strip()
    path = Path(out) if Path(out).is_absolute() else dst / out
    entries = [e for e in LOCAL_EXCLUDES if e.strip('/') not in tracked]
    block = '\n'.join([EXCLUDE_BEGIN, *entries, EXCLUDE_END])
    old = path.read_text(encoding='utf-8') if path.is_file() else ''
    pattern = re.compile(re.escape(EXCLUDE_BEGIN) + '.*?' + re.escape(EXCLUDE_END), re.S)
    new = pattern.sub(lambda _: block, old) if pattern.search(old) else old.rstrip('\n') + ('\n\n' if old.strip() else '') + block + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding='utf-8')
    return path


def apply_template(dst: Path, name: str, force: bool) -> None:
    target = dst / 'scripts' / 'verify.config.json'
    if target.exists() and not force:
        print(f'Template {name}: scripts/verify.config.json already exists; left unchanged.')
        return
    data = json.loads((SOURCE / 'ai_nest' / 'templates' / 'verify' / f'{name}.json').read_text(encoding='utf-8'))
    setup = data.pop('nest_setup_commands', [])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f'Template {name}: wrote scripts/verify.config.json; edit commands and cwd for your layout.')
    cfg_path = dst / 'nest.config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    env = cfg.setdefault('environment', {})
    if setup and not env.get('setup_commands'):
        env['setup_commands'] = setup  # fresh worktrees have no node_modules
        cfg_path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
        print('  Added environment.setup_commands: ' + ', '.join(s['name'] for s in setup))


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


def write_installation_manifest(dst: Path, installed: list[str], preserved: list[str], mode: str = 'committed') -> Path:
    """Diagnostic integrity manifest, not a security boundary against agents."""
    relative_files = [name for name in FILES if (dst / name).is_file()]
    statuses = {}
    for name in relative_files:
        statuses[name] = {'status': 'preserved' if name in preserved else 'installed',
                          'sha256': sha256_file(dst / name)}
    path = dst / 'ai_nest' / 'installation.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'release': RELEASE, 'mode': mode, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                                'files': statuses, 'configuration_schema': 2}, indent=2) + '\n', encoding='utf-8')
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
        import datetime
        backup = dst / '.ai-nest' / 'config-backups' / f'nest.config.{datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        target.write_text(json.dumps(merged, indent=2) + '\n', encoding='utf-8')
        print(f'Updated nest.config.json policy (v{old["version"]} -> v2); backup: {backup}')
        print('ACTION REQUIRED: review timeouts, TDD policy, real project checks and commit.')
    if merged.get('tdd', {}).get('protected_tests', False):
        print('WARNING: protected_tests=true is not confidential without isolated containers.')


def install(dst: Path, force: bool = False, update_code: bool = False, local: bool = False,
            template: str | None = None) -> None:
    dst = dst.resolve()
    if not (dst / '.git').exists() and subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=dst, capture_output=True).returncode:
        raise RuntimeError('Destination must be an existing Git repository')
    if dst == SOURCE:
        raise RuntimeError('Source and destination cannot be the same folder')
    installed, preserved = [], []
    # Local mode never writes a file the project tracks.
    tracked = tracked_files(dst) if local else set()
    updatable = ('ai_nest/', '.agents/skills/', '.claude/skills/')
    updatable_files = {'scripts/verify.sh', 'scripts/verify.py', 'install.py'}
    for name in FILES:
        source = SOURCE / name
        target = dst / name
        if local and name == '.github/workflows/ai-nest-verify.yml':
            continue  # CI checkouts cannot see an uncommitted Nest
        if name in tracked:
            preserved.append(name)
            continue
        replace_on_update = (name.startswith(updatable) or name in updatable_files
                             or name == '.github/workflows/ai-nest-verify.yml')
        if target.exists() and not force and not (update_code and replace_on_update):
            preserved.append(name)
            continue
        # Back up existing Nest-owned CI because projects may have customized it.
        if update_code and name == '.github/workflows/ai-nest-verify.yml' and target.is_file():
            old_ci = target.read_text(encoding='utf-8', errors='replace')
            if 'AI Nest' not in old_ci and 'AI Nest verification' not in old_ci:
                preserved.append(name)
                print('WARNING: Non-Nest CI workflow at .github/workflows/ai-nest-verify.yml left unchanged.')
                continue
            backup = backup_file(dst, target)
            print(f'WARNING: upgrading AI Nest CI workflow; review custom steps and backup: {backup}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        installed.append(name)
    if update_code and not force:
        migrate_existing_config(dst)
        if not local:  # these edit project instruction files
            installed.extend(migrate_old_instructions(dst))
            for note in report_legacy_files(dst):
                print(note)
    doc = dst / 'AI_NEST_README.md'
    if 'AI_NEST_README.md' not in tracked and (not doc.exists() or force or update_code):
        shutil.copy2(SOURCE / ('README.md' if (SOURCE / 'README.md').is_file() else 'AI_NEST_README.md'), doc)
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
    if template:
        apply_template(dst, template, force)
    ignores = dst / '.gitignore'
    lines = ignores.read_text(encoding='utf-8').splitlines() if ignores.exists() else []
    wanted = ['.ai-nest/', '__pycache__/', '*.pyc', '.pytest_cache/', '.DS_Store', 'node_modules/', 'dist/', 'build/', 'coverage/']
    missing = [rule for rule in wanted if rule not in lines]
    if local:
        exclude = write_local_excludes(dst, tracked)
        installed.append(f'{exclude.relative_to(dst) if exclude.is_relative_to(dst) else exclude} (AI Nest block)')
    elif missing:
        with ignores.open('a', encoding='utf-8') as f:
            f.write(('\n' if lines else '') + '\n'.join(missing) + '\n')
        installed.append('.gitignore (appended)')
    # The legacy .ai-nest/installation.json is ignored and cannot survive cloning.
    # Keep it in place as a historical diagnostic, but write the active manifest
    # into the tracked ai_nest/ directory.
    manifest_path = write_installation_manifest(dst, installed, preserved, 'local' if local else 'committed')
    print(f'Installation manifest: {manifest_path}' + ('' if local else ' (commit this file)'))
    print('Installed/updated:')
    for name in installed:
        print('  +', name)
    if preserved:
        print('Preserved (not overwritten):')
        for name in preserved:
            print('  =', name)
    manifest = dst / 'scripts' / 'verify.config.json'
    if not manifest.is_file():
        print('\nACTION REQUIRED: scripts/verify.config.json is not configured.')
        print(f'  rerun with --template {{{",".join(TEMPLATES)}}}, or:')
        print('  cp scripts/verify.config.json.example scripts/verify.config.json')
        print('  Edit checks and required_suites for your project; no tests are assumed to pass.')
    if local:
        print('\nLocal install: Nest files are listed in .git/info/exclude, so git status stays clean and nothing is committed.')
        print('Next: configure real project checks, then run:')
    else:
        print('\nNext: configure real project checks and setup commands, review policy, commit, then run:')
        print('  git add -A && git diff --cached --stat  # REVIEW before committing')
    print('  bash scripts/verify.sh --list')
    print('  python ai_nest/cli.py doctor --provider codex')


def main():
    p = argparse.ArgumentParser(description='Install portable AI Engineering Nest into a Git repo')
    p.add_argument('repository', type=Path)
    p.add_argument('--force', action='store_true', help='Replace AI Nest core/config files (never replaces existing instruction bridges)')
    p.add_argument('--update-code', action='store_true',
                   help='Upgrade runtime, skills, verifier and docs; migrate supported v1 config with a backup, preserve other settings and instructions')
    p.add_argument('--local', action='store_true',
                   help='Keep AI Nest out of the project history: list its files in .git/info/exclude and never modify tracked files')
    p.add_argument('--template', choices=TEMPLATES, help='Write scripts/verify.config.json from a stack template')
    args = p.parse_args()
    if not args.repository.is_dir():
        p.error('Directory does not exist')
    try:
        install(args.repository, args.force, args.update_code, args.local, args.template)
        return 0
    except (RuntimeError, OSError) as ex:
        print(f'Installation blocked: {ex}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
