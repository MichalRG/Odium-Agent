import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str((Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'selftests' else Path(__file__).resolve().parents[1]) / 'ai_nest'))
import cli as nest


def git(cwd, *args):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout


class NestTests(unittest.TestCase):
    def test_disallow_protected_paths(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        self.assertTrue(nest.is_blocked_file('.github/workflows/ci.yml', cfg))
        self.assertTrue(nest.is_blocked_file('AGENTS.md', cfg))
        self.assertFalse(nest.is_blocked_file('src/app.py', cfg))
        self.assertTrue(nest.is_test_file('frontend/src/app.component.spec.ts', cfg))

    def test_test_file_classification_avoids_substrings(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        for filename in ('src/latest_version.py', 'src/contest/model.py', 'app/attest_signature.ts', 'docs/openapi.spec.yaml', 'src/test_utils/config.py'):
            self.assertFalse(nest.is_test_file(filename, cfg), filename)
        for filename in ('tests/test_api.py', 'src/a.spec.ts', 'unit/__tests__/a.js'):
            self.assertTrue(nest.is_test_file(filename, cfg), filename)

    def test_recursive_test_path_globs_protect_nested_support_files(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        for name in ('tests/unit/__init__.py', 'tests/unit/conftest.py',
                     'tests/unit/helpers.py', 'backend/tests/integration/fixtures/data.json',
                     'frontend/src/__tests__/helpers/index.ts', 'backend/tests/unit/test_project.py'):
            self.assertTrue(nest.is_test_file(name, cfg), name)
        for name in ('src/latest_version.py', 'src/contest/model.py',
                     'src/test_utils/config.py', 'docs/openapi.spec.yaml', 'app/attest_signature.ts'):
            self.assertFalse(nest.is_test_file(name, cfg), name)

    def test_path_globs_match_zero_or_more_directory_segments(self):
        cfg = {'safety': {'test_path_globs': ['**/tests/**', '**/*.spec.ts']}}
        for name in ('tests/helper.py', 'tests/unit/a.py',
                     'backend/tests/integration/data/fixture.json', 'a.spec.ts',
                     'frontend/src/deep/a.spec.ts'):
            self.assertTrue(nest.is_test_file(name, cfg), name)
        for name in ('frontend/contest/index.ts', 'src/unittest_utils/index.ts'):
            self.assertFalse(nest.is_test_file(name, cfg), name)

    def test_deny_unsafe_relative_test_paths(self):
        cfg = {'safety': {'test_path_globs': ['**/tests/**']}}
        for name in ('../tests/a.py', '/tests/a.py'):
            with self.assertRaises(nest.Blocked):
                nest.is_test_file(name, cfg)

    def test_sensitive_gate_files_are_protected(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        for filename in ('backend/conftest.py', 'backend/requirements.txt', 'backend/requirements-dev.txt', 'backend/Dockerfile', 'backend/Makefile', 'frontend/package.json',
                         'backend/pytest.ini', 'frontend/angular.json',
                         'scripts/verify.py', 'scripts/verify.config.json'):
            self.assertTrue(nest.is_blocked_file(filename, cfg), filename)

    def test_red_requires_real_test_name_and_rejects_environment_errors(self):
        result = {'checks': [{'name': 'unit', 'exit_code': 1,
                              'stdout_tail': 'test_add (tests.TestFeature) ... FAIL\nAssertionError', 'stderr_tail': ''}]}
        self.assertEqual(nest.validate_red_result(result, ['test_add']), 'expected_red')
        with self.assertRaisesRegex(nest.Blocked, 'does not mention'):
            nest.validate_red_result(result, ['test_another'])
        result['checks'][0]['stderr_tail'] = 'ModuleNotFoundError: broken_fixture'
        with self.assertRaisesRegex(nest.Blocked, 'infrastructure'):
            nest.validate_red_result(result, ['test_add'])

    def test_sanitized_feedback_never_contains_protected_assertions(self):
        raw = {'checks': [{'name': 'verify-all', 'exit_code': 1,
                           'stderr_tail': 'assert secret_value == 42', 'stdout_tail': 'PRIVATE_TEST'}]}
        feedback = nest.safe_failure_feedback(raw)
        self.assertNotIn('secret_value', json.dumps(feedback))
        self.assertNotIn('PRIVATE_TEST', json.dumps(feedback))

    def test_review_severity_policy(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        review = {'findings': [{'severity': 'low'}, {'severity': 'high'}]}
        self.assertEqual(len(nest.blocking_findings(review, cfg)), 1)
        self.assertEqual(nest.blocking_findings(review, cfg)[0]['severity'], 'high')

    def test_routing_final_diff(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        self.assertFalse(nest.needs_security_review(['src/button.css'], cfg)[0])
        self.assertTrue(nest.needs_security_review(['src/auth.py'], cfg)[0])
        self.assertTrue(nest.needs_security_review(['infra/main.tf'], cfg)[0])

    def test_codex_provider_uses_stdin_and_supported_flag_order(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'limits': {'agent_timeout_seconds': 20}}
            payload = []
            def fake_call(argv, cwd, timeout, input_text=None):
                payload.append((argv, input_text))
                final_index = argv.index('--output-last-message') + 1
                Path(argv[final_index]).write_text(json.dumps({
                    'summary':'ok','relevant_files':[],'risks':[],'observations':[]}))
                return subprocess.CompletedProcess(argv, 0, '', '')
            with patch.object(nest.shutil, 'which', return_value='/usr/bin/codex'), patch.object(nest, 'call', side_effect=fake_call):
                agent = nest.CLIProvider('codex', cfg, Path(tmp))
                agent.run('explore', Path(tmp), {'x':'a'*150000})
            self.assertEqual(payload[0][0][:2], ['codex', 'exec'])
            self.assertEqual(payload[0][0][-1], '-')
            self.assertGreater(len(payload[0][1]), 128000)
            self.assertNotIn('--ask-for-approval', payload[0][0])

    def test_no_checks_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'verification': {'autodetect': False, 'commands': [], 'require_project_checks': True}}
            with self.assertRaises(nest.Blocked):
                nest.effective_checks(Path(tmp), cfg)

    def test_cli_provider_schemas_required(self):
        with self.assertRaises(nest.Blocked):
            nest.parse_result('review', {'approved': True, 'summary': 'fine'})

    def test_existing_protected_tests_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.email', 'tester@example.test')
            git(repo, 'config', 'user.name', 'Test')
            (repo / 'tests').mkdir()
            (repo / 'tests' / 'test_existing.py').write_text('assert True\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'base')
            cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
            (repo / 'tests' / 'test_existing.py').write_text('assert False\n')
            with self.assertRaisesRegex(nest.Blocked, 'only add new test files'):
                nest.get_patch(repo, repo / 'test.patch', cfg, test_only=True)
            with self.assertRaisesRegex(nest.Blocked, 'Coding agent may not modify test'):
                nest.get_patch(repo, repo / 'code.patch', cfg, forbid_tests=True)


    def test_test_engineer_may_create_new_conftest_but_not_edit_existing_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.email', 'tester@example.test')
            git(repo, 'config', 'user.name', 'Test')
            (repo/'tests').mkdir()
            (repo/'calc.py').write_text('def f(): return True\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'base')
            cfg = json.loads((nest.ROOT/'nest.config.json').read_text())
            (repo/'tests/conftest.py').write_text('import pytest\n')
            output = repo/'new-tests.patch'
            changed = nest.get_patch(repo, output, cfg, test_only=True)
            self.assertEqual(changed, ['tests/conftest.py'])
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'fixture')
            (repo/'tests/conftest.py').write_text('import pytest\npytest_plugins = []\n')
            with self.assertRaises(nest.Blocked):
                nest.get_patch(repo, repo/'changed.patch', cfg, test_only=True)
            with self.assertRaises(nest.Blocked):
                nest.get_patch(repo, repo/'coder.patch', cfg, forbid_tests=True)

    def test_new_missing_modules_only_accept_planned_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo/'tests').mkdir()
            (repo/'tests/test_add.py').write_text('from calcx import add\ndef test_add(): assert add(1,2)==3\n')
            result = {'checks':[{'name':'pytest','exit_code':2, 'stdout_tail':'ERROR collecting tests/test_add.py',
                                 'stderr_tail':"tests/test_add.py:1: ModuleNotFoundError: No module named 'calcx'"}]}
            kwargs = dict(public_tree=repo, public_files=['tests/test_add.py'])
            self.assertEqual(nest.validate_red_result(result, ['test_add'], planned_files=['calcx.py'], **kwargs), 'expected_red')
            with self.assertRaises(nest.Blocked):
                nest.validate_red_result(result, ['test_add'], planned_files=['calc.py'], **kwargs)
            (repo/'tests/test_add.py').write_text("import totally_missing_dependency_123\ndef test_add(): pass\n")
            result['checks'][0]['stderr_tail'] = "tests/test_add.py:1: ModuleNotFoundError: No module named 'totally_missing_dependency_123'"
            with self.assertRaises(nest.Blocked):
                nest.validate_red_result(result, ['test_add'], planned_files=['calcx.py'], **kwargs)

    def test_red_accepts_runner_style_names_and_reads_output_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo/'tests').mkdir()
            (repo/'tests/test_wf.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_count(self):\n        import app.wordfreq\n')
            kwargs = dict(public_tree=repo, public_files=['tests/test_wf.py'], planned_files=['app/wordfreq.py'])
            result = {'checks': [{'name': 'unit', 'exit_code': 1, 'stderr_tail': '',
                                  'stdout_tail': "tests/test_wf.py\nModuleNotFoundError: No module named 'app.wordfreq'"}]}
            for name in ('test_count (test_wf.T)', 'test_count (test_wf.T.test_count)', 'tests/test_wf.py::T::test_count',
                         'test_wf.T.test_count', 'demo.T#test_count', 'tests/test_wf.py::T::test_count[1.5]'):
                self.assertEqual(nest.validate_red_result(result, [name], **kwargs), 'expected_red')
            with self.assertRaisesRegex(nest.Blocked, 'not found in the generated test files'):
                nest.validate_red_result(result, ['test_missing (test_wf.T)'], **kwargs)
        # unittest -v prints names first; with many tracebacks they survive only in the head
        result = {'checks': [{'name': 'unit', 'exit_code': 1, 'stdout_head': 'test_add (tests.T.test_add) ... FAIL',
                              'stdout_tail': 'AssertionError: 1 != 2', 'stderr_tail': ''}]}
        self.assertEqual(nest.validate_red_result(result, ['test_add (tests.T)']), 'expected_red')

    def test_red_accepts_new_symbol_errors_from_java_go_and_csharp(self):
        cases = [('src/test/java/CalcTest.java', 'class CalcTest { @Test void testAdd() { new Calc(); } }', 'testAdd',
                  '[ERROR] /x/src/test/java/CalcTest.java:[1,40] cannot find symbol\n[ERROR]   symbol:   class Calc'),
                 ('calc_test.go', 'func TestAdd(t *testing.T) { Add(1, 2) }', 'TestAdd', './calc_test.go:1:31: undefined: Add'),
                 ('Calc.Tests/CalcTests.cs', 'public void TestAdd() { Calc.Add(1, 2); }', 'TestAdd',
                  "Calc.Tests/CalcTests.cs(1,25): error CS0103: The name 'Calc' does not exist in the current context")]
        for name, source, test, log in cases:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / name).write_text(source)
                kwargs = dict(public_tree=Path(tmp), public_files=[name])
                result = {'checks': [{'name': 'unit', 'exit_code': 1, 'stdout_tail': log, 'stderr_tail': ''}]}
                self.assertEqual(nest.validate_red_result(result, [test], **kwargs), 'expected_red', name)
                result['checks'][0]['stdout_tail'] = log.replace('Add', 'Unrelated').replace('Calc', 'Unrelated')
                with self.assertRaises(nest.Blocked, msg=name):
                    nest.validate_red_result(result, [test], **kwargs)

    def test_typescript_new_module_allowed_only_if_planned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            test = repo/'src/app/new-widget.spec.ts'
            test.parent.mkdir(parents=True)
            test.write_text("import { NewWidget } from './new-widget';\nit('test_widget', () => { expect(NewWidget).toBeDefined(); });\n")
            result = {'checks':[{'name':'tsc','exit_code':2, 'stdout_tail':'src/app/new-widget.spec.ts',
                                 'stderr_tail':"src/app/new-widget.spec.ts:1: Cannot find module './new-widget'"}]}
            kwargs = dict(public_tree=repo, public_files=['src/app/new-widget.spec.ts'])
            self.assertEqual(nest.validate_red_result(result, ['test_widget'], planned_files=['src/app/new-widget.ts'], **kwargs), 'expected_red')
            with self.assertRaises(nest.Blocked):
                nest.validate_red_result(result, ['test_widget'], planned_files=['src/app/other.ts'], **kwargs)

    def test_schema_has_typed_nested_items(self):
        s = nest.schema_for('review')
        item = s['properties']['findings']['items']
        self.assertEqual(item['type'], 'object')
        self.assertIn('severity', item['required'])
        observations = s['properties']['observations']['items']
        self.assertIn('suggested_action', observations['required'])

    def test_mocked_agent_end_to_end_and_test_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.email', 'tester@example.test')
            git(repo, 'config', 'user.name', 'Test')
            (repo / 'tests').mkdir()
            (repo / 'calc.py').write_text('def add(a, b):\n    return 0\n')
            (repo / 'tests' / 'test_existing.py').write_text(
                'import unittest\nfrom calc import add\n'
                'class TestExisting(unittest.TestCase):\n'
                '    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n')
            cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
            cfg['routing']['always_security_review'] = True
            cfg['tdd']['protected_tests'] = True  # explicitly exercise protected branch in mocked test
            cfg['tdd']['red_commands'] = [{'name': 'red', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 'cwd': '.'}]
            cfg['verification'] = {'autodetect': False, 'require_project_checks': True,
                                   'commands': [{'name': 'unittest',
                                                 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                                 'cwd': '.'}]}
            nest.write_json(repo / 'nest.config.json', cfg)
            (repo / '.gitignore').write_text('.ai-nest/\n__pycache__/\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'initial')
            seen_historical = []

            class MockProvider:
                def __init__(self, name, cfg, output):
                    pass

                def run(self, stage, cwd, context, write=False):
                    session = context['nest_session']
                    if stage == 'specify':
                        assert any(h['stage'] == 'explore' for h in session['current_run_handoffs'])
                        seen_historical.append(len(session['prior_run_handoffs']) > 0)
                    if stage in ('implement', 'repair'):
                        assert all(h['stage'] != 'protected_tests' for h in session['current_run_handoffs'])
                        assert all(h['stage'] != 'protected_tests' for h in session['prior_run_handoffs'])
                        assert (cwd / 'tests' / 'test_feature.py').exists()
                        assert not (cwd / 'tests' / 'test_hidden.py').exists()
                    note = {'kind': 'potential_issue', 'severity': 'low',
                            'summary': f'{stage} detected an issue', 'evidence': 'calc.py',
                            'file': 'calc.py', 'suggested_action': 'Check arithmetic'}
                    if stage == 'explore':
                        return {'summary': 'calc.add returns zero', 'relevant_files': ['calc.py'], 'risks': [],
                                'observations': [note]}
                    if stage == 'specify':
                        return {'goal': 'add correctly', 'acceptance_criteria': ['add(1,2)==3'],
                                'constraints': [], 'open_questions': [], 'observations': [note]}
                    if stage == 'plan':
                        return {'tasks': [{'id': 't1', 'description': 'fix add', 'files': ['calc.py']}],
                                'testing_strategy': 'unit tests', 'risks': [], 'observations': [note]}
                    if stage == 'tests':
                        self_ref = cwd / 'tests' / 'test_feature.py'
                        self_ref.write_text('import unittest\nfrom calc import add\n'
                                            'class TestFeature(unittest.TestCase):\n'
                                            '    def test_add(self):\n        self.assertEqual(add(1,2),3)\n')
                        return {'summary': 'public acceptance test', 'files_modified': ['tests/test_feature.py'],
                                'expected_red_tests': ['test_add'], 'coder_guidance': ['make add(1,2) == 3'],
                                'test_strategy': {'unit': ['test_add'], 'integration': [], 'contract': [], 'e2e': [], 'smoke': []},
                                'observations': [note]}
                    if stage == 'protected_tests':
                        (cwd / 'tests' / 'test_hidden.py').write_text(
                            'import unittest\nfrom calc import add\n'
                            'class TestHidden(unittest.TestCase):\n'
                            '    def test_negative(self):\n        self.assertEqual(add(-3,1),-2)\n')
                        return {'summary': 'protected acceptance test', 'files_modified': ['tests/test_hidden.py'],
                                'observations': [note]}
                    if stage == 'implement':
                        # Public TDD tests are available, hidden tests are not in this worktree.
                        assert (cwd / 'tests' / 'test_feature.py').exists()
                        assert not (cwd / 'tests' / 'test_hidden.py').exists()
                        (cwd / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
                        return {'summary': 'fixed addition', 'files_modified': ['calc.py'], 'observations': [note]}
                    if stage in ('review', 'security_review'):
                        assert not (cwd / 'tests' / 'test_hidden.py').exists()
                        return {'approved': True, 'findings': [], 'summary': 'reviewed', 'observations': [note]}
                    raise AssertionError(stage)

            with patch.object(nest, 'CLIProvider', MockProvider):
                exit_code = nest.run_feature(repo, 'Fix addition', 'codex', True, 'arithmetic')
            self.assertEqual(exit_code, 0)
            reports = list((repo / '.ai-nest' / 'runs').glob('*/report.json'))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['status'], 'verified')
            self.assertEqual(report['session'], 'arithmetic')
            self.assertEqual(seen_historical, [False])
            code = Path(report['worktree'])
            self.assertTrue((code / 'tests' / 'test_feature.py').exists())
            self.assertIn('return a + b', (code / 'calc.py').read_text())
            git(repo, 'worktree', 'remove', '--force', str(code))
            handoff_dir = Path(report['session_workspace']) / 'runs' / report['run_id'] / 'handoffs'
            self.assertTrue((handoff_dir / 'explore_01.json').is_file())
            self.assertTrue((handoff_dir / 'tests_01.json').is_file())
            self.assertEqual(nest.list_sessions(repo)[0]['name'], 'arithmetic')
            self.assertEqual(len(nest.inspect_session(repo, 'arithmetic')['handoffs']), 8)
            self.assertTrue(nest.inspect_session(repo, 'arithmetic')['routing'][0]['decisions'][0]['invoked'])

            # Run another feature in the same named session: earlier notes survive,
            # but protected test notes are not exposed to the coding agent.
            with patch.object(nest, 'CLIProvider', MockProvider):
                code2 = nest.run_feature(repo, 'Fix addition again', 'codex', True, 'arithmetic')
            self.assertEqual(code2, 0)
            self.assertEqual(seen_historical, [False, True])
            self.assertEqual(len(nest.inspect_session(repo, 'arithmetic')['handoffs']), 16)
            new_reports = [json.loads(path.read_text()) for path in
                           (repo / '.ai-nest' / 'runs').glob('*/report.json')]
            for other in new_reports:
                if other['run_id'] != report['run_id']:
                    git(repo, 'worktree', 'remove', '--force', other['worktree'])

    def test_session_name_cannot_escape_workspace(self):
        from memory import session_slug
        self.assertEqual(session_slug('My Task'), session_slug('My Task'))
        self.assertNotIn('/', session_slug('../../my task'))
        with self.assertRaises(ValueError):
            session_slug('bad\nname')

    def test_session_store_scopes_history_to_same_session(self):
        from memory import SessionStore
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            a = SessionStore(repo, 'api', '20261108-120000-abc', 'sha1')
            a.record('explore', {'summary': 'api route', 'observations': []})
            b = SessionStore(repo, 'frontend', '20261108-120001-def', 'sha1')
            self.assertEqual(b.handoff_context('plan')['prior_run_handoffs'], [])
            c = SessionStore(repo, 'api', '20261108-120002-ghi', 'sha2')
            history = c.handoff_context('plan')['prior_run_handoffs']
            self.assertEqual(len(history), 1)
            self.assertFalse(history[0]['same_base_commit'])

    def test_upgrade_preserves_configuration_and_existing_instructions(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('nest_installer', nest.ROOT / 'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            (repo / 'AGENTS.md').write_text('Custom instructions\n')
            (repo / 'nest.config.json').write_text('{"custom": true}\n')
            (repo / 'ai_nest').mkdir()
            (repo / 'ai_nest' / 'cli.py').write_text('old code\n')
            installer.install(repo, update_code=True)
            self.assertEqual((repo / 'AGENTS.md').read_text().splitlines()[0],
                             'Custom instructions')
            self.assertEqual((repo / 'nest.config.json').read_text(), '{"custom": true}\n')
            self.assertIn('SessionStore', (repo / 'ai_nest' / 'cli.py').read_text())
            self.assertTrue((repo / 'ai_nest' / 'memory.py').is_file())
            self.assertIn('sessions/<session-slug>', (repo / 'AI_NEST_README.md').read_text())

    def test_reject_malformed_observations(self):
        result = {'summary': 'test', 'relevant_files': [], 'risks': [],
                  'observations': [{'kind': 'risk'}]}
        with self.assertRaisesRegex(nest.Blocked, 'invalid observation'):
            nest.parse_result('explore', result)

    def test_static_failure_of_public_tests_ignores_expected_missing_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / 'scripts').mkdir()
            manifest = tree / 'scripts/verify.config.json'
            manifest.write_text(json.dumps({'checks': [{'name': 'unit', 'suite': 'unit'}]}))
            with patch.object(nest, 'run_checks') as run:
                self.assertEqual(nest.public_tests_static_failure(tree, {}, tree / 'out.json'), '')
                run.assert_not_called()  # no static suite configured
            manifest.write_text(json.dumps({'checks': [{'name': 'lint', 'suite': 'static'}]}))
            def failed(log):
                return {'passed': False, 'checks': [{'stdout_tail': log, 'stderr_tail': ''}]}
            with patch.object(nest, 'run_checks', return_value=failed('t.py:1:1: I001 Import block is un-sorted')):
                self.assertIn('I001', nest.public_tests_static_failure(tree, {}, tree / 'out.json'))
            with patch.object(nest, 'run_checks', return_value=failed(
                    "t.spec.ts(1,10): error TS2305: Module '\"./calc\"' has no exported member 'multiply'.")):
                self.assertEqual(nest.public_tests_static_failure(tree, {}, tree / 'out.json'), '')

    def test_extra_observations_keep_the_most_severe_instead_of_blocking(self):
        def obs(severity, n):
            return {'kind': 'fact', 'severity': severity, 'summary': f'{severity}{n}', 'evidence': 'e',
                    'file': '', 'suggested_action': ''}
        listed = [obs('info', n) for n in range(16)] + [obs('high', 0), obs('critical', 0)]
        kept = nest.parse_result('explore', {'summary': 's', 'relevant_files': [], 'risks': [],
                                             'observations': listed})['observations']
        self.assertEqual(len(kept), 16)
        self.assertEqual([o['summary'] for o in kept[:3]], ['critical0', 'high0', 'info0'])
        self.assertNotIn('info15', [o['summary'] for o in kept])


if __name__ == '__main__':
    unittest.main()

class V41PolicyTests(unittest.TestCase):
    def test_custom_test_globs_are_enforced(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        cfg['safety']['test_path_globs'] = ['specs/**']
        self.assertTrue(nest.is_test_file('specs/a.py',cfg))
        self.assertFalse(nest.is_test_file('tests/test_a.py',cfg))

    def test_public_failure_feedback_includes_log_tail(self):
        raw = {'checks':[{'name':'unit','exit_code':1,'stdout_tail':'PUBLIC FAIL','stderr_tail':'Traceback'}]}
        self.assertIn('PUBLIC FAIL',json.dumps(nest.safe_failure_feedback(raw,protected=False)))
        self.assertNotIn('PUBLIC FAIL',json.dumps(nest.safe_failure_feedback(raw,protected=True)))

    def test_red_already_green_policy_is_explicit(self):
        result = {'checks':[{'name':'unit','exit_code':0,'stdout_tail':'test_new PASSED','stderr_tail':''}]}
        with self.assertRaises(nest.Blocked):
            nest.validate_red_result(result,['test_new'])
        self.assertEqual(nest.validate_red_result(result,['test_new'],cfg={'tdd':{'already_green_policy':'allow'}}),'already_green')

    def test_red_rejects_unexpected_exit_code(self):
        result = {'checks':[{'name':'unit','exit_code':137,'stdout_tail':'test_new FAIL','stderr_tail':''}]}
        with self.assertRaises(nest.Blocked):
            nest.validate_red_result(result,['test_new'],cfg={'tdd':{'accepted_red_exit_codes':[1,2]}})

class BootstrapPolicyTests(unittest.TestCase):
    """Greenfield scaffolds may ADD build files and smoke tests; existing ones and Nest gates stay immutable."""
    def check(self, writes, role='bootstrap'):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            for name in ('pyproject.toml', 'tests/test_old.py', 'README.md'):
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text('old\n')
            git(repo, 'add', '.')
            git(repo, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', 'commit', '-qm', 'base')
            for name in writes:
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text('new\n')
            return nest.assert_authorized_changes(repo, cfg, role)

    def test_new_build_files_lockfiles_and_smoke_tests_are_allowed(self):
        writes = ['app/pyproject.toml', 'app/uv.lock', 'app/.gitignore', 'app/src/odium/__init__.py',
                  'app/tests/test_smoke.py', 'frontend/package.json', 'frontend/package-lock.json',
                  'frontend/angular.json', 'frontend/src/app/app.spec.ts', 'README.md']
        self.assertEqual(sorted(self.check(writes)), sorted(writes))

    def test_existing_build_and_test_files_and_gates_stay_blocked(self):
        for name in ('pyproject.toml', 'tests/test_old.py', 'scripts/setup.sh', 'nest.config.json',
                     '.github/workflows/ci.yml', 'ai_nest/cli.py', 'AGENTS.md', '.claude/settings.json'):
            with self.assertRaises(nest.Blocked, msg=name):
                self.check([name])

    def test_dependency_output_is_rejected(self):
        with self.assertRaisesRegex(nest.Blocked, 'gitignore'):
            self.check(['frontend/node_modules/x/index.js'])

    def test_feature_coder_still_cannot_create_build_files(self):
        with self.assertRaises(nest.Blocked):
            self.check(['app/pyproject.toml'], role='coder')


class V41TimeoutTests(unittest.TestCase):
    def test_outer_verify_timeout_must_cover_inner_check_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)
            (repo/'scripts').mkdir()
            (repo/'scripts/verify.config.json').write_text(json.dumps({
                'version':1, 'default_timeout_seconds':60,
                'checks':[{'name':'a'},{'name':'b'}]}))
            cfg={'verification':{'commands':[{'name':'verify-all','argv':['bash','scripts/verify.sh'],'cwd':'.'}]},
                 'limits':{'check_timeout_seconds':140}}
            with self.assertRaisesRegex(nest.Blocked, 'too short'):
                nest.validate_outer_verify_timeout(repo,cfg)
            cfg['limits']['check_timeout_seconds']=151
            nest.validate_outer_verify_timeout(repo,cfg)
