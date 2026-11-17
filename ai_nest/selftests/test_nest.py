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

    def test_red_accepts_tests_that_assert_on_error_names(self):
        for error in ("<class 'SyntaxError'>", "<class 'FileNotFoundError'> (ENOENT)"):
            log = f'FAILED tests/test_parser.py::test_rejects_bad_input - Failed: DID NOT RAISE {error}\n1 failed'
            result = {'checks': [{'name': 'unit', 'exit_code': 1, 'stdout_tail': log, 'stderr_tail': ''}]}
            self.assertEqual(nest.validate_red_result(result, ['test_rejects_bad_input']), 'expected_red', error)
        # The same words still mean a broken run when the expected test never ran.
        broken = {'checks': [{'name': 'unit', 'exit_code': 1, 'stderr_tail': '',
                              'stdout_tail': 'Test suite failed to run\nSyntaxError: Unexpected token'}]}
        with self.assertRaisesRegex(nest.Blocked, 'infrastructure'):
            nest.validate_red_result(broken, ['test_rejects_bad_input'])

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

    def test_android_tests_catalog_and_manifest_are_guarded(self):
        cfg = json.loads((nest.ROOT / 'nest.config.json').read_text())
        self.assertTrue(nest.is_test_file('app/src/androidTest/java/com/x/LoginTest.kt', cfg))
        self.assertTrue(nest.is_test_file('app/src/test/java/com/x/LoginViewModelTest.kt', cfg))
        self.assertFalse(nest.is_test_file('app/src/main/java/com/x/LoginViewModel.kt', cfg))
        self.assertTrue(nest.is_blocked_file('gradle/libs.versions.toml', cfg))
        self.assertTrue(nest.needs_security_review(['app/src/main/AndroidManifest.xml'], cfg)[0])

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
                    'summary':'ok','relevant_files':[],'risks':[],'observations':[],
                    'context_pack': {'outline': '', 'excerpts': []}}))
                return subprocess.CompletedProcess(argv, 0, '', '')
            with patch.object(nest.shutil, 'which', return_value='/usr/bin/codex'), patch.object(nest, 'call', side_effect=fake_call):
                agent = nest.CLIProvider('codex', cfg, Path(tmp))
                agent.run('explore', Path(tmp), {'x':'a'*150000})
            self.assertEqual(payload[0][0][:2], ['codex', 'exec'])
            self.assertEqual(payload[0][0][-1], '-')
            self.assertGreater(len(payload[0][1]), 128000)
            self.assertNotIn('--ask-for-approval', payload[0][0])

    def test_agent_past_its_window_keeps_running_only_while_it_makes_progress(self):
        import contextlib
        import io
        slow = [sys.executable, '-c', 'import sys, time; time.sleep(0.6); print(sys.stdin.read())']
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cwd = Path(tmp)
            with self.assertRaisesRegex(nest.Blocked, r'timed out after 0.25s: \S+$'):
                nest.call(slow, cwd, 0.25, input_text='x')
            with self.assertRaisesRegex(nest.Blocked, 'no new progress'):
                nest.call(slow, cwd, 0.25, input_text='x', progress=lambda: False, max_timeout=5)
            with self.assertRaisesRegex(nest.Blocked, 'after 0.5s.*cap'):
                nest.call(slow, cwd, 0.25, input_text='x', progress=lambda: True, max_timeout=0.5)
            done = nest.call(slow, cwd, 0.25, input_text='stdin kept', progress=lambda: True, max_timeout=5)
            self.assertEqual((done.returncode, done.stdout.strip()), (0, 'stdin kept'))

    def test_worktree_progress_counts_only_file_states_not_seen_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.email', 'tester@example.test')
            git(repo, 'config', 'user.name', 'Test')
            (repo / 'app.py').write_text('v1\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'base')
            progressed = nest.worktree_progress(repo)
            self.assertFalse(progressed())
            (repo / 'app.py').write_text('v2\n')
            self.assertTrue(progressed())
            self.assertFalse(progressed())
            (repo / 'new.py').write_text('x\n')
            self.assertTrue(progressed())
            (repo / 'new.py').unlink()
            self.assertFalse(progressed(), 'returning to an earlier state is not progress')

    def test_plan_commits_must_list_every_task_exactly_once(self):
        plan = {'tasks': [{'id': 'T1', 'description': 'a', 'files': []}, {'id': 'T2', 'description': 'b', 'files': []}],
                'testing_strategy': 'unit', 'risks': [], 'observations': []}
        for commits in ([{'message': 'A', 'tasks': ['T1']}],
                        [{'message': 'A', 'tasks': ['T1', 'T2']}, {'message': 'B', 'tasks': ['T2']}],
                        [{'message': 'A', 'tasks': ['T1', 'T2', 'T3']}]):
            with self.assertRaisesRegex(nest.Blocked, 'every task exactly once'):
                nest.parse_result('plan', {**plan, 'commits': commits})
        ok = nest.parse_result('plan', {**plan, 'commits': [{'message': 'A', 'tasks': ['T2', 'T1']}]})
        self.assertEqual(ok['commits'][0]['tasks'], ['T2', 'T1'])

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

    def test_red_accepts_new_symbol_errors_from_java_kotlin_go_and_csharp(self):
        cases = [('src/test/java/CalcTest.java', 'class CalcTest { @Test void testAdd() { new Calc(); } }', 'testAdd',
                  '[ERROR] /x/src/test/java/CalcTest.java:[1,40] cannot find symbol\n[ERROR]   symbol:   class Calc'),
                 ('app/src/test/java/CalcTest.kt', 'class CalcTest { @Test fun testAdd() { Calc().add(1, 2) } }', 'testAdd',
                  "e: file:///x/app/src/test/java/CalcTest.kt:1:40 Unresolved reference 'Calc'."),
                 ('app/src/test/java/CalcTest.kt', 'class CalcTest { @Test fun testAdd() { Calc().add(1, 2) } }', 'testAdd',
                  'e: /x/app/src/test/java/CalcTest.kt: (1, 40): Unresolved reference: Calc'),
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
                                'observations': [note], 'context_pack': {'outline': '', 'excerpts': []}}
                    if stage == 'specify':
                        return {'goal': 'add correctly', 'acceptance_criteria': ['add(1,2)==3'],
                                'constraints': [], 'open_questions': [], 'observations': [note]}
                    if stage == 'plan':
                        return {'tasks': [{'id': 't1', 'description': 'fix add', 'files': ['calc.py']}],
                                'commits': [{'message': 'Fix add', 'tasks': ['t1']}],
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

    def test_gotchas_reach_later_sessions_of_the_same_repository_only(self):
        from memory import SessionStore
        trap = {'kind': 'gotcha', 'severity': 'info', 'summary': 'Tests need TZ=UTC', 'evidence': 'test_dates.py',
                'file': 'test_dates.py', 'suggested_action': 'Set TZ'}
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            a = SessionStore(home, 'api', '20261108-120000-abc', 'sha1', project='calc')
            a.record('implement', {'summary': 's', 'observations': [trap, {**trap, 'kind': 'fact', 'summary': 'x'}]})
            a.record('protected_tests', {'summary': 's', 'observations': [{**trap, 'summary': 'hidden case'}]})
            b = SessionStore(home, 'other-feature', '20261108-120001-def', 'sha2', project='calc')
            b.record('review', {'summary': 's', 'findings': [], 'observations': [{**trap, 'summary': ' tests need  tz=utc'}]})
            later = SessionStore(home, 'third', '20261108-120002-ghi', 'sha3', project='calc').handoff_context('explore')
            self.assertEqual([(g['summary'], g['seen']) for g in later['project_gotchas']], [(' tests need  tz=utc', 2)])
            elsewhere = SessionStore(home, 'third', '20261108-120003-jkl', 'sha3', project='web')
            self.assertEqual(elsewhere.handoff_context('implement')['project_gotchas'], [])

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
        result = {'summary': 'test', 'relevant_files': [], 'risks': [], 'context_pack': {'outline': '', 'excerpts': []},
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
            # verify.sh runs every static check: the type checker's expected RED must not hide the lint error.
            suite = ('\n=== lint [static] ===\nt.py:1:1: I001 Import block is un-sorted\n=== lint: failed ===\n'
                     "\n=== tsc [static] ===\nt.spec.ts(1,10): error TS2305: Module '\"./calc\"' has no exported "
                     "member 'multiply'.\n=== tsc: failed ===\n"
                     '\n=== format [static] ===\n=== format: passed ===\n'
                     '\nVerification FAILED: 1/3 checks passed\n')
            with patch.object(nest, 'run_checks', return_value=failed(suite)):
                log = nest.public_tests_static_failure(tree, {}, tree / 'out.json')
            self.assertIn('I001', log)
            self.assertNotIn('TS2305', log)

    def test_models_per_stage_fall_back_to_default_and_reject_unsafe_values(self):
        models = {'codex': {'default': {'model': 'gpt-6.1-sol', 'effort': 'medium'},
                            'plan': {'model': 'gpt-6-astra', 'effort': 'high'}, 'review': {'effort': 'high'}},
                  'claude': {'default': {'model': 'opus'}}}
        with patch.object(nest.shutil, 'which', return_value='/bin/true'), patch('builtins.print'):
            codex = nest.CLIProvider('codex', {'models': models}, Path('.'))
            self.assertEqual(codex.model_args('plan'), ['-m', 'gpt-6-astra', '-c', 'model_reasoning_effort="high"'])
            self.assertEqual(codex.model_args('review'), ['-m', 'gpt-6.1-sol', '-c', 'model_reasoning_effort="high"'])
            self.assertEqual(codex.model_args('explore'), ['-m', 'gpt-6.1-sol', '-c', 'model_reasoning_effort="medium"'])
            self.assertEqual(nest.CLIProvider('claude', {'models': models}, Path('.')).model_args('tests'),
                             ['--model', 'opus'])
            self.assertEqual(nest.CLIProvider('codex', {}, Path('.')).model_args('plan'), [])
            for bad in ({'reveiw': {'model': 'x'}}, {'plan': {'model': '--yolo'}}, {'plan': {'model': 'x', 'temp': '1'}},
                        {'plan': {'effort': 'high"\nsandbox_mode="danger-full-access'}}, {'plan': {}}, ['plan']):
                with self.assertRaisesRegex(nest.Blocked, 'Invalid models.codex'):
                    nest.CLIProvider('codex', {'models': {'codex': bad}}, Path('.'))

    def test_copilot_provider_puts_the_schema_in_the_prompt_and_reads_the_last_answer(self):
        answer = {'summary': 'ok', 'relevant_files': [], 'risks': [], 'observations': [], 'context_pack': {'outline': '', 'excerpts': []}}
        events = [{'type': 'assistant.message', 'data': {'content': 'Looking around first.'}},
                  {'type': 'assistant.message', 'data': {'content': 'Done.\n```json\n' + json.dumps(answer) + '\n```'}},
                  {'type': 'result', 'exitCode': 0}]
        calls = []
        def fake_call(argv, cwd, timeout, input_text=None, **watch):
            calls.append((argv, input_text))
            return subprocess.CompletedProcess(argv, 0, '\n'.join(map(json.dumps, events)), '')
        models = {'copilot': {'default': {'model': 'claude-sonnet-5.5', 'effort': 'high'}}}
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'), \
                patch.object(nest.shutil, 'which', return_value='/usr/bin/copilot'), \
                patch.object(nest, 'call', side_effect=fake_call):
            agent = nest.CLIProvider('copilot', {'models': models}, Path(tmp))
            self.assertEqual(agent.run('explore', Path(tmp), {'x': 'a'}), answer)
            agent.run('explore', Path(tmp), {'x': 'a'})
            self.assertTrue((Path(tmp) / 'explore_02.json').is_file(), 'a second attempt keeps the first artifacts')
        argv, prompt = calls[0]
        self.assertEqual(argv[:5], ['copilot', '--model', 'claude-sonnet-5.5', '--reasoning-effort', 'high'])
        self.assertIn('--deny-tool=write', argv)  # read-only stage
        self.assertIn('"relevant_files"', prompt)  # the schema travels in the prompt
        events[1]['data']['content'] = 'No JSON here.'
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'), \
                patch.object(nest.shutil, 'which', return_value='/usr/bin/copilot'), \
                patch.object(nest, 'call', side_effect=fake_call):
            with self.assertRaisesRegex(nest.Blocked, 'invalid JSON'):
                nest.CLIProvider('copilot', {}, Path(tmp)).run('explore', Path(tmp), {})

    def test_workspace_repository_runs_with_its_own_checks(self):
        lint = {'name': 'lint', 'suite': 'static', 'argv': ['ruff', 'check']}
        unit = {'name': 'unit', 'suite': 'unit', 'argv': ['pytest']}
        cfg = {'tdd': {'enabled': True}, 'verification': {'commands': ['bash scripts/verify.sh']},
               'workspace': {'repos': {'api': {'checks': [lint, unit]}, 'web': {'checks': []}, 'docs': {}}}}
        home = Path('/w')
        run = nest.workspace_config(cfg, home, home / 'api')
        self.assertEqual(run['verification']['commands'], [lint, unit])
        self.assertEqual(run['tdd']['red_commands'], [unit])
        self.assertEqual(run['workspace_run'], {'workspace': '/w', 'repository': 'api',
                                                'other_repositories': ['docs', 'web']})
        for repo, error in (('web', 'No checks for web'), ('docs', 'No checks for docs'),
                            ('new', 'new is not in workspace.repos')):
            with self.assertRaisesRegex(nest.Blocked, error):
                nest.workspace_config(cfg, home, home / repo)
        cfg['workspace']['repos']['web']['checks'] = [{'name': 'lint', 'argv': ['eslint']}]
        with self.assertRaisesRegex(nest.Blocked, 'need a "suite"'):
            nest.workspace_config(cfg, home, home / 'web')
        cfg['workspace']['repos']['web']['checks'] = [lint]
        with self.assertRaisesRegex(nest.Blocked, 'no "unit" check'):
            nest.workspace_config(cfg, home, home / 'web')

    def test_workspace_static_checks_are_judged_one_by_one(self):
        checks = [{'name': 'lint', 'suite': 'static', 'argv': ['ruff']},
                  {'name': 'tsc', 'suite': 'static', 'argv': ['tsc']},
                  {'name': 'unit', 'suite': 'unit', 'argv': ['pytest']}]
        logs = {'ruff': 't.py:1:1: I001 Import block is un-sorted',
                'tsc': "t.spec.ts(1,10): error TS2305: Module '\"./calc\"' has no exported member 'multiply'."}
        def run_checks(tree, cfg, output, label):
            [check] = cfg['verification']['commands']
            return {'passed': False, 'checks': [{'stdout_tail': logs[check['argv'][0]], 'stderr_tail': ''}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(nest, 'run_checks', side_effect=run_checks) as run:
            log = nest.public_tests_static_failure(Path(tmp), {'verification': {'commands': checks}},
                                                   Path(tmp) / 'out.json')
        self.assertEqual(run.call_count, 2)  # static checks only
        self.assertIn('I001', log)
        self.assertNotIn('TS2305', log)  # the type checker's expected RED

    def test_workspace_read_only_stages_may_read_the_other_repositories(self):
        answer = {'summary': 'ok', 'relevant_files': [], 'risks': [], 'observations': [], 'context_pack': {'outline': '', 'excerpts': []}}
        calls = []
        def fake_call(argv, cwd, timeout, input_text=None, **watch):
            calls.append((argv, input_text))
            return subprocess.CompletedProcess(argv, 0, json.dumps({'structured_output': answer}), '')
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'), \
                patch.object(nest.shutil, 'which', return_value='/usr/bin/claude'), \
                patch.object(nest, 'call', side_effect=fake_call):
            (Path(tmp) / 'api').mkdir()
            (Path(tmp) / 'api/AGENTS.md').write_text('Keep handlers thin.\n')
            cfg = {'workspace_run': {'workspace': tmp, 'repository': 'api', 'other_repositories': ['web']}}
            agent = nest.CLIProvider('claude', cfg, Path(tmp))
            agent.run('explore', Path(tmp), {})
            agent.run('explore', Path(tmp), {}, write=True)
        (read_argv, prompt), (write_argv, _) = [c for c in calls if c[0][0] == 'claude']
        self.assertEqual(read_argv[read_argv.index('--add-dir') + 1], tmp)
        self.assertNotIn('--add-dir', write_argv)
        self.assertIn('Keep handlers thin.', prompt)  # the target repository's own rules

    def test_claude_stages_get_the_nest_rules_when_the_worktree_has_none(self):
        answer = {'summary': 'ok', 'relevant_files': [], 'risks': [], 'observations': [], 'context_pack': {'outline': '', 'excerpts': []}}
        calls = []
        def fake_call(argv, cwd, timeout, input_text=None, **watch):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({'structured_output': answer}), '')
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'), \
                patch.object(nest.shutil, 'which', return_value='/usr/bin/claude'), \
                patch.object(nest, 'call', side_effect=fake_call):
            agent = nest.CLIProvider('claude', {}, Path(tmp))
            agent.run('explore', Path(tmp), {})  # a workspace or home repository: no Nest files
            (Path(tmp) / '.claude').mkdir()
            (Path(tmp) / '.claude/settings.json').write_text('{}')
            agent.run('explore', Path(tmp), {})  # its own committed rules load as project settings
        bare, own = [c for c in calls if c[0] == 'claude']
        self.assertEqual(bare[bare.index('--settings') + 1], str(nest.ROOT / '.claude/settings.json'))
        self.assertNotIn('--settings', own)

    def test_claude_explorer_may_read_the_reference_docs_folder(self):
        answer = {'summary': 'ok', 'relevant_files': [], 'risks': [], 'observations': [], 'context_pack': {'outline': '', 'excerpts': []}}
        calls = []
        def fake_call(argv, cwd, timeout, input_text=None, **watch):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({'structured_output': answer}), '')
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'), \
                patch.object(nest.shutil, 'which', return_value='/usr/bin/claude'), \
                patch.object(nest, 'call', side_effect=fake_call):
            agent = nest.CLIProvider('claude', {}, Path(tmp))
            agent.run('explore', Path(tmp), {'reference_docs': {'folder': '/owner/docs', 'files': ['a.md']}})
            agent.run('explore', Path(tmp), {})
        with_docs, without = calls
        self.assertEqual(with_docs[with_docs.index('--add-dir') + 1], '/owner/docs')
        self.assertNotIn('--add-dir', without)

    def test_context_pack_copies_only_tracked_code_within_its_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            git(tree, 'init', '-q')
            (tree / 'big.py').write_text(''.join(f'line {n}\n' for n in range(1, 1001)))
            (tree / '.env').write_text('TOKEN=tracked-secret\n')
            (tree / 'local.properties').write_text('sdk.dir=/untracked\n')
            git(tree, 'add', 'big.py', '.env')
            def excerpt(file, start, end, why='w'):
                return {'file': file, 'start_line': start, 'end_line': end, 'why': why}
            pack = nest.build_context_pack(tree, {'outline': 'Flow: a -> b.', 'excerpts': [
                excerpt('.env', 1, 1), excerpt('local.properties', 1, 1), excerpt('../x.py', 1, 1),
                excerpt('', 1, 1), excerpt('big.py', 9, 3), excerpt('big.py', 5, 2000, 'all of it'),
                excerpt('big.py', 1, 3, 'header')]}, 'a' * 40)
        self.assertTrue(pack.startswith('# Context pack (base commit aaaaaaaaaaaa)\n\nFlow: a -> b.'))
        for name in ('.env', 'local.properties', '../x.py'):
            self.assertIn(f'## {name}: not included', pack)
        self.assertNotIn('tracked-secret', pack)
        self.assertNotIn('/untracked', pack)
        self.assertIn('## big.py:9-3: not included (no such lines)', pack)
        self.assertIn('## big.py:5-604 - all of it\n```\nline 5\n', pack)  # the 600-line budget
        self.assertIn('line 604\n```', pack)
        self.assertNotIn('line 605', pack)
        self.assertIn('## big.py:1-3 - header (not included: the pack is full', pack)

    def test_extra_observations_keep_the_most_severe_instead_of_blocking(self):
        def obs(severity, n):
            return {'kind': 'fact', 'severity': severity, 'summary': f'{severity}{n}', 'evidence': 'e',
                    'file': '', 'suggested_action': ''}
        listed = [obs('info', n) for n in range(16)] + [obs('high', 0), obs('critical', 0)]
        kept = nest.parse_result('explore', {'summary': 's', 'relevant_files': [], 'risks': [], 'context_pack': {'outline': '', 'excerpts': []},
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
