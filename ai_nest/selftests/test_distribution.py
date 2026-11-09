"""Exercise the shipped installer and verification integration from a fresh repo."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'selftests' else Path(__file__).resolve().parents[1]


def command(cwd, *args, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          env=env, check=False, timeout=45)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'project'
        self.repo.mkdir()
        self.assertEqual(command(self.repo, 'git', 'init', '-q').returncode, 0)
        command(self.repo, 'git', 'config', 'user.email', 'test@example.invalid')
        command(self.repo, 'git', 'config', 'user.name', 'test')

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        p = command(self.repo, sys.executable, str(ROOT / 'install.py'), str(self.repo))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_installed_skill_has_all_required_files(self):
        self.install()
        for file in ('AGENTS.md', 'nest.config.json', 'ai_nest/cli.py',
                     'ai_nest/memory.py', 'scripts/verify.sh', 'scripts/verify.py',
                     'scripts/verify.config.json.example',
                     '.agents/skills/build-feature/SKILL.md',
                     '.claude/skills/build-feature/SKILL.md',
                     'install.py', 'ai_nest/selftests/test_cli_e2e.py',
                     'ai_nest/selftests/test_nest.py'):
            self.assertTrue((self.repo / file).is_file(), file)
        cfg = json.loads((self.repo / 'nest.config.json').read_text())
        self.assertEqual(cfg['verification']['commands'][0]['argv'], ['bash', 'scripts/verify.sh'])
        for file in ('scripts/verify.sh', 'scripts/verify.py', 'scripts/verify.config.json'):
            self.assertIn(file, cfg['safety']['blocked_paths'])
        self.assertEqual((self.repo / '.agents/skills/build-feature/SKILL.md').read_text(),
                         (self.repo / '.claude/skills/build-feature/SKILL.md').read_text())

    def test_manifest_and_installed_selftests_are_available(self):
        self.install()
        manifest = self.repo / 'ai_nest/installation.json'
        self.assertTrue(manifest.is_file())
        data = json.loads(manifest.read_text())
        self.assertEqual(data['release'], '4.4')
        self.assertIn('ai_nest/cli.py', data['files'])
        check = command(self.repo, sys.executable, '-m', 'unittest',
                        'discover', '-s', 'ai_nest/selftests', '-p', 'test_verify_runner.py')
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_upgrade_deduplicates_gemini_bridge_and_corrects_old_readme_reference(self):
        self.install()
        gemini = self.repo / 'GEMINI.md'
        gemini.write_text('# My Gemini rule\n@./AGENTS.md\n@./AGENTS.md\n'
                          '# AI Engineering Nest\n# AI Engineering Nest\n')
        agents = self.repo / 'AGENTS.md'
        agents.write_text('## AI Engineering Nest\nSee AI_NEST_README.md (or the template AI_NEST_README.md)\n')
        p = command(self.repo, sys.executable, str(ROOT / 'install.py'), str(self.repo), '--update-code')
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        result = gemini.read_text()
        self.assertEqual(result.count('@./AGENTS.md'),1)
        self.assertEqual(result.count('# AI Engineering Nest'),1)
        self.assertIn('# My Gemini rule',result)
        self.assertNotIn('or the template AI_NEST_README.md',agents.read_text())

    def test_tracked_manifest_survives_fresh_clone_and_doctor(self):
        self.install()
        (self.repo / 'scripts/verify.config.json').write_text(json.dumps({
            'version': 1, 'required_suites': ['unit'],
            'checks': [{'name':'unit','suite':'unit','cwd':'.',
                        'argv':[sys.executable,'-c','print(1)'], 'timeout_seconds':30}]
        }))
        fake_bin = Path(self.tmp.name) / 'bin'
        fake_bin.mkdir()
        fake_provider = fake_bin / 'codex'
        fake_provider.write_text('#!/bin/sh\nexit 0\n')
        fake_provider.chmod(0o755)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get('PATH',''))
        self.assertEqual(command(self.repo, 'git', 'add', '-A').returncode, 0)
        tracked = command(self.repo, 'git', 'ls-files', '--cached', '--', 'ai_nest/installation.json')
        self.assertIn('ai_nest/installation.json', tracked.stdout)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Installed Nest').returncode, 0)
        clone = Path(self.tmp.name) / 'clone'
        self.assertEqual(command(Path(self.tmp.name), 'git', 'clone', '-q', str(self.repo), str(clone)).returncode,0)
        self.assertTrue((clone / 'ai_nest/installation.json').is_file())
        self.assertFalse((clone / '.ai-nest/installation.json').exists())
        check = command(clone, sys.executable, 'ai_nest/cli.py', 'doctor', '--provider','codex',env=env)
        self.assertEqual(check.returncode,0,check.stdout+check.stderr)
        self.assertNotIn('Missing ai_nest/installation.json', check.stdout)

    def test_in_repo_installer_never_uses_application_tests_as_selftests(self):
        self.install()
        app_tests = self.repo / 'tests'
        app_tests.mkdir(exist_ok=True)
        (app_tests / 'test_verify_runner.py').write_text('raise RuntimeError("APPLICATION TEST")\n')
        second = Path(self.tmp.name) / 'second'
        second.mkdir()
        self.assertEqual(command(second, 'git', 'init', '-q').returncode,0)
        result = command(second, sys.executable, str(self.repo / 'install.py'), str(second))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        runner = (second / 'ai_nest/selftests/test_verify_runner.py').read_text()
        self.assertNotIn('APPLICATION TEST', runner)
        self.assertTrue((second / 'ai_nest/selftests/test_cli_e2e.py').is_file())
        self.assertTrue((second / 'ai_nest/selftests/test_distribution.py').is_file())

    def test_update_replaces_owned_ci_with_backup_and_keeps_other_workflow(self):
        self.install()
        workflow = self.repo / '.github/workflows/ai-nest-verify.yml'
        workflow.write_text('name: AI Nest verification\njobs:\n  verify:\n    timeout-minutes: 30\n')
        other = self.repo / '.github/workflows/project.yml'
        other.write_text('name: Project CI\n')
        updated = command(self.repo, sys.executable, str(ROOT/'install.py'), str(self.repo), '--update-code')
        self.assertEqual(updated.returncode,0,updated.stdout+updated.stderr)
        self.assertIn('timeout-minutes: 100',workflow.read_text())
        self.assertEqual(other.read_text(),'name: Project CI\n')
        self.assertTrue(list((self.repo / '.ai-nest/config-backups').glob('ai-nest-verify.yml.*.bak')))

    def test_upgrade_reconciles_stale_rules_and_timeout(self):
        self.install()
        (self.repo/'CLAUDE.md').write_text('Keep custom project rule\nNew behavior gets a test\nUse .claude/agents/ for every review\n')
        cfg = json.loads((self.repo/'nest.config.json').read_text())
        cfg['tdd']['protected_tests'] = True
        cfg['limits']['check_timeout_seconds'] = 600
        (self.repo/'nest.config.json').write_text(json.dumps(cfg))
        (self.repo/'scripts/verify.config.json').write_text(json.dumps({
            'version': 1, 'default_timeout_seconds': 600,
            'checks': [{'name': 'check_'+str(i), 'suite': 'unit', 'argv': ['true']}
                       for i in range(8)]}))
        p = command(self.repo, sys.executable, str(ROOT/'install.py'), str(self.repo), '--update-code')
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        updated = json.loads((self.repo/'nest.config.json').read_text())
        self.assertEqual(updated['limits']['check_timeout_seconds'], 4830)
        self.assertFalse(updated['tdd']['protected_tests'])
        self.assertIn('Keep custom project rule', (self.repo/'CLAUDE.md').read_text())
        self.assertNotIn('.claude/agents/', (self.repo/'CLAUDE.md').read_text())
        self.assertNotIn('New behavior gets a test', (self.repo/'CLAUDE.md').read_text())
        self.assertTrue(list((self.repo/'.ai-nest/config-backups').glob('CLAUDE.md.*.bak')))

    def test_doctor_reports_core_drift_after_install(self):
        self.install()
        (self.repo/'scripts/verify.py').write_text('# unexpected runtime change\n')
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Initial').returncode, 0)
        result = command(self.repo, sys.executable, 'ai_nest/cli.py', 'doctor', '--provider', 'codex')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Core file changed since installation: scripts/verify.py', result.stdout)

    def test_ci_new_conftest_needs_explicit_base_policy(self):
        self.install()
        (self.repo/'scripts/verify.config.json').write_text(json.dumps({
            'version':1,'required_suites':['unit'],
            'checks':[{'name':'unit','suite':'unit','cwd':'.',
                       'argv':[sys.executable,'-c','print(1)']}]}))
        cfg = json.loads((self.repo/'nest.config.json').read_text())
        cfg['safety']['allow_new_test_fixtures_in_ci'] = False
        (self.repo/'nest.config.json').write_text(json.dumps(cfg))
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Base').returncode, 0)
        base = command(self.repo, 'git', 'rev-parse', 'HEAD').stdout.strip()
        (self.repo/'tests/unit').mkdir(parents=True)
        (self.repo/'tests/unit/conftest.py').write_text('# only new test fixture\n')
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'New fixture').returncode, 0)
        result = command(self.repo, sys.executable, 'ai_nest/cli.py', 'verify',
                         '--base',base,'--allow-host-execution')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Protected paths changed', result.stderr)

    def test_ci_added_fixture_opt_in_allows_additions_but_not_edits(self):
        self.install()
        (self.repo/'scripts/verify.config.json').write_text(json.dumps({
            'version':1,'required_suites':['unit'],
            'checks':[{'name':'unit','suite':'unit','cwd':'.',
                       'argv':[sys.executable,'-c','print(1)']}]}))
        cfg = json.loads((self.repo/'nest.config.json').read_text())
        cfg['safety']['allow_new_test_fixtures_in_ci'] = True
        (self.repo/'nest.config.json').write_text(json.dumps(cfg))
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Base').returncode, 0)
        base = command(self.repo,'git','rev-parse','HEAD').stdout.strip()
        (self.repo/'tests/unit').mkdir(parents=True)
        fixture = self.repo/'tests/unit/conftest.py'
        fixture.write_text('# new fixture\n')
        command(self.repo, 'git', 'add', '.')
        command(self.repo, 'git', 'commit', '-qm', 'New fixture')
        first = command(self.repo, sys.executable, 'ai_nest/cli.py', 'verify',
                        '--base',base,'--allow-host-execution')
        self.assertEqual(first.returncode, 0, first.stderr+first.stdout)
        added_base = command(self.repo,'git','rev-parse','HEAD').stdout.strip()
        fixture.write_text('# modified fixture\n')
        command(self.repo, 'git', 'add', '.')
        command(self.repo, 'git', 'commit', '-qm', 'Modify fixture')
        second = command(self.repo, sys.executable, 'ai_nest/cli.py', 'verify',
                         '--base',added_base,'--allow-host-execution')
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('Protected paths changed',second.stderr)

    def test_doctor_fails_closed_until_manifest_exists(self):
        self.install()
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Initial').returncode, 0)
        result = command(self.repo, sys.executable, 'ai_nest/cli.py', 'doctor', '--provider', 'codex')
        self.assertEqual(result.returncode, 1)
        self.assertIn('verify.config.json is missing', result.stdout)

    def test_installed_verify_and_cli_propagate_real_failures(self):
        self.install()
        tests = self.repo / 'checks'
        tests.mkdir()
        test = tests / 'test_feature.py'
        test.write_text('import unittest\nclass Check(unittest.TestCase):\n'
                        '    def test_behavior(self):\n        self.assertEqual(2 + 2, 4)\n')
        manifest = {
            'version': 1, 'required_suites': ['unit'],
            'checks': [{'name': 'project-unit', 'suite': 'unit', 'cwd': '.',
                        'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'checks']}],
        }
        (self.repo / 'scripts/verify.config.json').write_text(json.dumps(manifest))
        self.assertEqual(command(self.repo, 'git', 'add', '.').returncode, 0)
        self.assertEqual(command(self.repo, 'git', 'commit', '-qm', 'Install Nest').returncode, 0)
        direct = command(self.repo, 'bash', 'scripts/verify.sh')
        self.assertEqual(direct.returncode, 0, direct.stdout + direct.stderr)
        orchestrated = command(self.repo, sys.executable, 'ai_nest/cli.py',
                               'verify', '--allow-host-execution')
        self.assertEqual(orchestrated.returncode, 0, orchestrated.stdout + orchestrated.stderr)
        self.assertTrue((self.repo / '.ai-nest/verify-report.json').is_file())
        test.write_text(test.read_text().replace('2 + 2, 4', '2 + 2, 5'))
        self.assertEqual(command(self.repo, 'bash', 'scripts/verify.sh').returncode, 1)
        self.assertEqual(command(self.repo, sys.executable, 'ai_nest/cli.py',
                                 'verify', '--allow-host-execution').returncode, 1)

    def test_upgrade_preserves_custom_config_but_updates_skill_and_runner(self):
        (self.repo / 'AGENTS.md').write_text('Keep custom rules\n')
        (self.repo / 'nest.config.json').write_text('{"version": 99}\n')
        self.install()
        skill = self.repo / '.agents/skills/build-feature/SKILL.md'
        skill.write_text('old skill')
        runner = self.repo / 'scripts/verify.py'
        runner.write_text('old runner')
        p = command(self.repo, sys.executable, str(ROOT / 'install.py'), str(self.repo), '--update-code')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.repo / 'nest.config.json').read_text(), '{"version": 99}\n')
        self.assertTrue((self.repo / 'AGENTS.md').read_text().startswith('Keep custom rules'))
        self.assertIn('## Invoke', skill.read_text())
        self.assertIn('def main()', runner.read_text())


if __name__ == '__main__':
    unittest.main()

class ConfigMigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_commands_and_adds_stricter_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(['git','init','-q'],cwd=repo,check=True)
            old = {'version':1,'verification':{'commands':[{'name':'project','argv':['echo','ok'],'cwd':'.'}],
                                                     'autodetect':False,'require_project_checks':True},
                   'tdd':{'enabled':True,'red_commands':[{'name':'red','argv':['echo','RED'],'cwd':'.'}]},
                   'routing':{'always_security_review':True},
                   'safety':{'blocked_paths':['private/'],'protected_basenames':['conftest.py']}}
            (repo/'nest.config.json').write_text(json.dumps(old))
            result = subprocess.run([sys.executable,str(ROOT/'install.py'),str(repo),'--update-code'],
                                    cwd=repo,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            updated = json.loads((repo/'nest.config.json').read_text())
            self.assertEqual(updated['version'],2)
            self.assertEqual(updated['verification']['commands'],old['verification']['commands'])
            self.assertTrue(updated['routing']['always_security_review'])
            self.assertIn('private/',updated['safety']['blocked_paths'])
            self.assertIn('package.json',updated['safety']['protected_basenames'])
            self.assertTrue(updated['safety']['test_path_globs'])
            self.assertTrue(list((repo/'.ai-nest/config-backups').glob('nest.config.*.json')))


class V2SafetyMigrationTests(unittest.TestCase):
    def test_existing_v2_policy_is_backed_up_and_hardened(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
            old = {'version': 2, 'policy_version': '2026-11',
                   'safety': {'blocked_paths': ['custom/'],
                              'protected_basenames': ['package.json'],
                              'test_path_markers': ['test_'],
                              'test_path_globs': ['**/*.spec.*', 'tests/**']},
                   'tdd': {'protected_tests': True},
                   'verification': {'commands': [{'name': 'custom', 'argv': ['echo', 'hello'], 'cwd': '.'}]}}
            (repo/'nest.config.json').write_text(json.dumps(old))
            p = subprocess.run([sys.executable, str(ROOT/'install.py'), str(repo), '--update-code'],
                               cwd=repo, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            new = json.loads((repo/'nest.config.json').read_text())
            self.assertEqual(new['verification']['commands'], old['verification']['commands'])
            self.assertFalse(new['tdd']['protected_tests'])  # fail closed without isolated tests
            self.assertIn('WARNING: disabling protected_tests=true', p.stdout)
            self.assertIn('requirements*.txt', new['safety']['protected_basenames'])
            self.assertNotIn('test_path_markers', new['safety'])
            self.assertNotIn('**/*.spec.*', new['safety']['test_path_globs'])
            self.assertTrue(list((repo/'.ai-nest/config-backups').glob('nest.config.*.json')))
