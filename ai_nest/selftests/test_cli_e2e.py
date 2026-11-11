"""Real CLI + Git worktree tests against a deterministic stand-in Codex executable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'selftests' else Path(__file__).resolve().parents[1]


def cmd(cwd, *argv, env=None, timeout=90):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


FAKE = r'''#!PYTHON
import json, os, subprocess, sys
from pathlib import Path
base = Path.cwd()
args = sys.argv[1:]
prompt = sys.stdin.read()
scenario = os.environ.get('NEST_FAKE_SCENARIO', 'happy')
if os.environ.get('NEST_FAKE_ARGV'):
    with open(os.environ['NEST_FAKE_ARGV'], 'a') as argv_log:
        argv_log.write(json.dumps(args) + '\n')
notes = []
if '# Role: explorer' in prompt:
    result = {'summary':'explored', 'relevant_files':['calc.py'], 'risks':[]}
elif '# Role: specification writer' in prompt:
    result = {'goal':'correct add','acceptance_criteria':['add(1,2)==3'], 'constraints':[],
              'open_questions':['Should add accept floats?'] if scenario == 'questions' else []}
elif '# Role: planner' in prompt:
    result = {'tasks':[{'id':'T1','description':'correct add','files':['calcx.py' if scenario == 'red_new_module' else 'calc.py']}], 'testing_strategy':'unit','risks':[],
              'commits':[{'message':'Correct add','tasks':['T1']}]}
elif '# Role: test-engineer — PUBLIC' in prompt:
    if scenario == 'red_invalid':
        body = 'import totally_missing_dependency_123\n'
        expected = ['test_add']
    elif scenario == 'red_new_module':
        body = 'import unittest\nfrom calcx import add\nclass TestCalc(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1,2),3)\n'
        expected = ['test_add']
    elif scenario == 'red_symbol':
        body = 'import unittest\nfrom calc import multiply_new\nclass TestCalc(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(multiply_new(2,3),6)\n'
        expected = ['test_add']
    else:
        body = 'import unittest\nfrom calc import add\nclass TestCalc(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1,2),3)\n'
        expected = ['test_add']
    if scenario == 'tests_lint_stuck' or (scenario == 'tests_lint' and 'public_tests_fail_static_checks' not in prompt):
        body = 'import unittest\nimport os\n' + body.replace('import unittest\n', '', 1)  # unsorted, like ruff I001
    (base/'tests/test_feature.py').write_text(body)
    files = ['tests/test_feature.py']
    if scenario in ('new_fixture', 'new_nested_fixture', 'coder_nested_helper_edit'):
        (base/'tests/conftest.py').write_text('# newly added test-scoped fixture\n')
        files.append('tests/conftest.py')
    if scenario in ('new_nested_fixture', 'coder_nested_helper_edit'):
        (base/'tests/unit').mkdir(parents=True, exist_ok=True)
        for rel, data in [
            ('tests/unit/__init__.py', ''),
            ('tests/unit/conftest.py', '# scoped fixture\n'),
            ('tests/unit/helpers.py', 'VALUE = 1\n'),
            ('backend/tests/integration/fixtures/data.json', '{"ok":true}\n'),
        ]:
            dest = base/rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(data)
            files.append(rel)
    result = {'summary':'new public test', 'files_modified':files,
              'expected_red_tests':expected, 'coder_guidance':['make test_add pass'],
              'test_strategy':{'unit': ['test_add'], 'integration': [], 'contract': [], 'e2e': [], 'smoke': []}}
elif '# Role: coder —' in prompt:
    if 'worker_policy_or_execution_error' in prompt:
        # A retry after a block starts again from the reset tree, public tests intact.
        assert (base/'tests/test_feature.py').read_text().find('assertEqual')!=-1
        (base/'calc.py').write_text('def add(a,b):\n    return a+b\n')
    elif scenario == 'red_new_module':
        (base/'calcx.py').write_text('def add(a,b):\n    return a+b\n')
    elif scenario == 'coder_nested_helper_edit' and '# Role: coder —' in prompt:
        (base/'tests/unit/helpers.py').write_text('VALUE = 999\n')
    elif scenario == 'coder_local_gate_edit':
        # Excluded from Git, so only the orchestrator's hash check can see this.
        (base/'scripts/verify.config.json').write_text('{"version":1,"checks":[{"name":"x","suite":"unit","argv":["true"]}]}')
        (base/'calc.py').write_text('def add(a,b):\n    return a+b\n')
    elif scenario == 'coder_test_edit':
        (base/'tests/test_feature.py').write_text('assert True\n')
    elif scenario == 'coder_protected_edit':
        (base/'package.json').write_text('{"scripts":{"test":"echo fake"}}')
    elif scenario == 'coder_commit':
        (base/'calc.py').write_text('def add(a,b):\n    return a+b\n')
        # Malicious commit changes a trusted gate that must never survive repair.
        (base/'scripts/verify.sh').write_text('#!/bin/sh\nexit 0\n')
        subprocess.run(['git','add','calc.py','scripts/verify.sh'], cwd=base,check=True)
        subprocess.run(['git','commit','-qm','unauthorized'], cwd=base,check=True)
    elif scenario == 'coder_timeout':
        (base/'calc.py').write_text('def add(a,b):\n    return a  # unfinished\n')
        import time; time.sleep(60)
    else:
        (base/'calc.py').write_text('def add(a,b):\n    return a+b\n')
    result = {'summary':'attempted', 'files_modified':['calc.py']}
elif '# Role: coder repair' in prompt:
    assert (base/'tests/test_feature.py').is_file()
    assert (base/'tests/test_feature.py').read_text().find('assertEqual')!=-1
    if scenario == 'coder_timeout':
        assert 'stopped at its time limit' in prompt and 'unfinished' in (base/'calc.py').read_text()
    if scenario.startswith('review_'):
        # Fixing the findings starts from the approved code; the test-file finding is not sent.
        assert 'add repeats logic' in prompt and 'weak test' not in prompt
        assert 'a+b' in (base/'calc.py').read_text()
    if scenario == 'review_fix_breaks':
        (base/'calc.py').write_text('def add(a,b):\n    return a-b\n')
    else:
        (base/'calc.py').write_text('def add(a, b):\n    return a + b\n')
    result = {'summary':'repaired', 'files_modified':['calc.py']}
elif '# Role: bootstrapper' in prompt:
    if scenario == 'bootstrap_gate_edit' and 'worker_policy_or_execution_error' not in prompt:
        (base/'scripts/bootstrap.sh').write_text('#!/bin/sh\n')  # a Nest gate path, never creatable
    files = {'app/pyproject.toml': '[project]\nname = "app"\n', 'app/uv.lock': 'version = 1\n',
             'app/.gitignore': '__pycache__/\n', 'app/calc.py': 'def add(a,b):\n    return a+b\n',
             'app/tests/test_smoke.py': 'import unittest\nfrom calc import add\nclass TestSmoke(unittest.TestCase):\n'
                                        '    def test_add(self):\n        self.assertEqual(add(1,2),3)\n'}
    for rel, data in files.items():
        (base/rel).parent.mkdir(parents=True, exist_ok=True)
        (base/rel).write_text(data)
    result = {'summary':'scaffolded', 'files_modified':sorted(files)}
elif '# Role: code-reviewer' in prompt or '# Role: security-reviewer' in prompt:
    result = {'approved':True,'findings':[],'summary':'approved'}
    earlier_reviews = Path(args[args.index('--output-last-message') + 1]).parent.glob('review_*.answer.json')
    if '# Role: code-reviewer' in prompt and scenario.startswith('review_') and not list(earlier_reviews):
        result['findings'] = [
            {'severity':'medium','file':'calc.py','problem':'add repeats logic','evidence':'calc.py:2'},
            {'severity':'medium','file':'tests/test_feature.py','problem':'weak test','evidence':'test_feature.py:4'}]
else:
    raise SystemExit('Unrecognized stage in fake provider')
result['observations'] = notes
if scenario == 'invalid_json' and '# Role: explorer' in prompt:
    output = '{broken'
else:
    output = json.dumps(result)
Path(args[args.index('--output-last-message') + 1]).write_text(output)
'''


class EndToEndTests(unittest.TestCase):
    def feature_project(self, scenario, local=False):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        tmp = handle.name
        root = Path(tmp) / 'project'
        root.mkdir()
        self.assertEqual(cmd(root, 'git', 'init', '-q').returncode, 0)
        cmd(root, 'git', 'config', 'user.email', 'test@example.invalid')
        cmd(root, 'git', 'config', 'user.name', 'Test')
        self.assertEqual(cmd(root, sys.executable, str(ROOT / 'install.py'), str(root), *(['--local'] if local else [])).returncode, 0)
        (root / 'calc.py').write_text('def add(a,b):\n    return 0\n')
        (root / 'tests').mkdir()
        (root / 'tests/test_existing.py').write_text(
            'import unittest\nfrom calc import add\nclass TestExisting(unittest.TestCase):\n'
            '    def test_zero(self):\n        self.assertEqual(add(0,0),0)\n')
        cfg = json.loads((root / 'nest.config.json').read_text())
        cfg['tdd']['protected_tests'] = False
        cfg['tdd']['red_commands'] = [{'name': 'RED', 'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 'cwd': '.'}]
        cfg['limits']['max_repair_attempts'] = 1
        (root / 'nest.config.json').write_text(json.dumps(cfg))
        (root / 'scripts/verify.config.json').write_text(json.dumps({
            'version': 1, 'required_suites': ['unit'],
            'checks': [{'name': 'unit', 'suite': 'unit', 'cwd': '.',
                        'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']}]}))
        self.assertEqual(cmd(root,'git','add','.').returncode,0)
        self.assertEqual(cmd(root,'git','commit','-qm','base').returncode,0)
        bin_path = Path(tmp)/'bin'
        bin_path.mkdir()
        fake = bin_path/'codex'
        fake.write_text(FAKE.replace('PYTHON',sys.executable,1))
        fake.chmod(0o755)
        env = {**os.environ, 'PATH':str(bin_path)+os.pathsep+os.environ['PATH'], 'NEST_FAKE_SCENARIO':scenario}
        return root, env

    def nest(self, root, env, *argv):
        return cmd(root, sys.executable, 'ai_nest/cli.py', *argv, env=env)

    def test_plan_stops_for_approval_then_runs_the_approved_plan(self):
        root, env = self.feature_project('happy')
        p = self.nest(root, env, 'plan', '--session', 'calc', '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('PLAN READY FOR APPROVAL', p.stdout)
        self.assertIn('T1: correct add [calc.py]', p.stdout)
        plan_report = json.loads(next((root / '.ai-nest/runs').glob('*/report.json')).read_text())
        self.assertEqual(plan_report['status'], 'planned')
        # Nothing to review yet: no branch or worktree is left behind.
        self.assertFalse(Path(plan_report['worktree']).exists())
        self.assertEqual(cmd(root, 'git', 'branch', '--list', plan_report['branch']).stdout, '')
        p = self.nest(root, env, 'run', '--from-plan', plan_report['run_id'], '--allow-host-execution')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run_dir = next(d for d in (root / '.ai-nest/runs').iterdir() if d.name != plan_report['run_id'])
        report = json.loads((run_dir / 'report.json').read_text())
        self.assertEqual((report['status'], report['approved_plan'], report['session']),
                         ('verified', plan_report['run_id'], 'calc'))
        self.assertEqual(report['request'], 'Fix addition')
        stages = {f.name.split('_')[0] for f in (run_dir / 'artifacts').glob('*.schema.json')}
        self.assertFalse(stages & {'explore', 'specify', 'plan'}, stages)
        self.assertIn('implement', stages)

    def test_plan_returns_open_questions_instead_of_planning(self):
        root, env = self.feature_project('questions')
        p = self.nest(root, env, 'plan', '--session', 'calc', '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn('1. Should add accept floats?', p.stdout)
        run_dir = next((root / '.ai-nest/runs').iterdir())
        self.assertEqual(json.loads((run_dir / 'report.json').read_text())['status'], 'needs_answers')
        self.assertFalse((run_dir / 'artifacts/planning.json').exists())
        self.assertNotEqual(self.nest(root, env, 'run', '--from-plan', run_dir.name,
                                      '--allow-host-execution').returncode, 0)

    def test_each_stage_gets_its_configured_model_and_effort(self):
        root, env = self.feature_project('happy')
        argv_log = root.parent / 'argv.jsonl'
        p = self.nest(root, {**env, 'NEST_FAKE_ARGV': str(argv_log)},
                      'plan', '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        calls = [json.loads(line) for line in argv_log.read_text().splitlines()]
        explore, plan = calls[0], calls[2]  # stage order: explore, specify, plan
        self.assertEqual(explore[:5], ['exec', '-m', 'gpt-6-luna', '-c', 'model_reasoning_effort="high"'])
        self.assertEqual(plan[:3], ['exec', '-m', 'gpt-6-astra'])
        self.assertIn('[AI Nest] explore: gpt-6-luna, effort high', p.stdout)

    def lint_project(self, scenario):
        """Feature project whose static suite rejects unsorted `import` lines in tests, like ruff I001."""
        root, env = self.feature_project(scenario)
        lint = ("import pathlib, sys\n"
                "bad = [p for p in sorted(pathlib.Path('tests').glob('*.py'))\n"
                "       if (lambda i: i != sorted(i))([l for l in p.read_text().splitlines() if l.startswith('import ')])]\n"
                "print(*[f'{p}:1:1: I001 Import block is un-sorted or un-formatted' for p in bad], sep='\\n')\n"
                "sys.exit(1 if bad else 0)\n")
        manifest = json.loads((root / 'scripts/verify.config.json').read_text())
        manifest['checks'].insert(0, {'name': 'lint', 'suite': 'static', 'cwd': '.',
                                      'argv': [sys.executable, '-c', lint]})
        (root / 'scripts/verify.config.json').write_text(json.dumps(manifest))
        cmd(root, 'git', 'commit', '-qam', 'add lint')
        p = self.nest(root, env, 'run', '--session', 'lint', '--allow-host-execution', 'Fix addition')
        run_dir = next((root / '.ai-nest/runs').iterdir())
        stages = sorted(f.name.split('.')[0] for f in (run_dir / 'artifacts').glob('*.schema.json'))
        return p, json.loads((run_dir / 'report.json').read_text()), stages

    def test_public_tests_that_fail_lint_go_back_to_the_test_engineer(self):
        p, report, stages = self.lint_project('tests_lint')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((report['status'], report['attempts']), ('verified', 1))
        self.assertIn('tests_02', stages)
        self.assertEqual([s for s in stages if s.startswith('implement')], ['implement_01'])

    def test_public_tests_still_failing_lint_stop_before_the_coder(self):
        p, report, stages = self.lint_project('tests_lint_stuck')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Public tests still fail static checks', report['error'])
        self.assertIn('I001', report['error'])
        self.assertFalse([s for s in stages if s.startswith(('implement', 'repair'))], stages)

    def test_coder_stopped_at_its_time_limit_keeps_its_code_for_repair(self):
        root, env = self.feature_project('coder_timeout')
        cfg = json.loads((root / 'nest.config.json').read_text())
        cfg['limits'].update(agent_timeout_seconds=5, agent_max_seconds=5)
        (root / 'nest.config.json').write_text(json.dumps(cfg))
        self.assertEqual(cmd(root, 'git', 'commit', '-qam', 'short agent limits').returncode, 0)
        p = self.nest(root, env, 'run', '--provider', 'codex', '--session', 'calc',
                      '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('keeping its code for verification', p.stdout)
        run_dir = next((root / '.ai-nest/runs').iterdir())
        report = json.loads((run_dir / 'report.json').read_text())
        self.assertEqual((report['status'], report['attempts']), ('verified', 2))
        stages = sorted(f.name.split('.')[0] for f in (run_dir / 'artifacts').glob('*.schema.json'))
        self.assertEqual([s for s in stages if s.startswith(('implement', 'repair'))], ['implement_01', 'repair_01'])

    def test_diff_over_the_configured_review_limit_blocks_instead_of_truncating(self):
        root, env = self.feature_project('happy')
        cfg = json.loads((root / 'nest.config.json').read_text())
        cfg['limits']['review_diff_max_chars'] = 100
        (root / 'nest.config.json').write_text(json.dumps(cfg))
        self.assertEqual(cmd(root, 'git', 'commit', '-qam', 'tiny review limit').returncode, 0)
        p = self.nest(root, env, 'run', '--provider', 'codex', '--session', 'calc',
                      '--allow-host-execution', 'Fix addition')
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        run_dir = next((root / '.ai-nest/runs').iterdir())
        report = json.loads((run_dir / 'report.json').read_text())
        self.assertEqual(report['status'], 'blocked')
        self.assertRegex(report['error'], r'Diff exceeds the review limit: \d+ characters, limit 100')
        self.assertFalse(list((run_dir / 'artifacts').glob('review_*')), 'no reviewer may see a cut diff')

    def test_review_findings_go_back_to_the_coder_after_approval(self):
        root, env = self.feature_project('review_findings')
        p = self.nest(root, env, 'run', '--provider', 'codex', '--session', 'calc',
                      '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run_dir = next((root / '.ai-nest/runs').iterdir())
        report = json.loads((run_dir / 'report.json').read_text())
        self.assertEqual((report['status'], report['attempts'], report['review']['findings']), ('verified', 2, []))
        self.assertEqual(report['planned_commits'], [{'message': 'Correct add', 'tasks': ['T1']}])
        self.assertIn('a + b', (Path(report['worktree']) / 'calc.py').read_text())
        stages = sorted(f.name.split('.')[0] for f in (run_dir / 'artifacts').glob('*.schema.json'))
        self.assertEqual([s for s in stages if s.startswith(('implement', 'repair', 'review'))],
                         ['implement_01', 'repair_01', 'review_01', 'review_02'])

    def test_failed_fix_of_review_findings_keeps_the_approved_attempt(self):
        root, env = self.feature_project('review_fix_breaks')
        p = self.nest(root, env, 'run', '--provider', 'codex', '--session', 'calc',
                      '--allow-host-execution', 'Fix addition')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        report = json.loads(next((root / '.ai-nest/runs').glob('*/report.json')).read_text())
        self.assertEqual((report['status'], report['attempts']), ('verified', 1))
        self.assertIn('verification_failed', report['review_fix_failed'])
        self.assertEqual(len(report['review']['findings']), 2, 'the unfixed findings stay in the report')
        self.assertIn('a+b', (Path(report['worktree']) / 'calc.py').read_text())

    def test_approved_plan_is_refused_after_the_code_moved(self):
        root, env = self.feature_project('happy')
        self.assertEqual(self.nest(root, env, 'plan', '--allow-host-execution', 'Fix addition').returncode, 0)
        run_id = next((root / '.ai-nest/runs').iterdir()).name
        cmd(root, 'git', 'commit', '-q', '--allow-empty', '-m', 'moved on')
        p = self.nest(root, env, 'run', '--from-plan', run_id, '--allow-host-execution')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Run `plan` again', p.stderr)
        for bad in ('../../etc', 'x' * 20):
            p = self.nest(root, env, 'run', '--from-plan', bad, '--allow-host-execution')
            self.assertIn('Not a run id', p.stderr)

    def run_scenario(self, scenario, local=False):
        root, env = self.feature_project(scenario, local)
        p = cmd(root, sys.executable, 'ai_nest/cli.py', 'run', '--provider', 'codex',
                '--session', 'regression', '--allow-host-execution', 'Fix addition', env=env)
        reports = list((root/'.ai-nest/runs').glob('*/report.json'))
        self.assertEqual(len(reports), 1, p.stdout + p.stderr)
        report = json.loads(reports[0].read_text())
        if scenario in ('happy','coder_local_gate_edit','coder_test_edit','coder_protected_edit','coder_commit','coder_nested_helper_edit','red_new_module','new_fixture','new_nested_fixture','coder_nested_helper_edit'):
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            self.assertEqual(report['status'],'verified')
            self.assertEqual(report['attempts'], 2 if scenario in ('coder_local_gate_edit','coder_test_edit','coder_protected_edit','coder_commit','coder_nested_helper_edit') else 1)
            if report['attempts'] == 2:
                # Attempt 1 was blocked before verification and its tree reset, so nothing is left to repair.
                stages = sorted(f.name.split('.')[0] for f in reports[0].parent.glob('artifacts/*.schema.json'))
                self.assertEqual([s for s in stages if s.startswith(('implement', 'repair'))],
                                 ['implement_01', 'implement_02'])
            if scenario == 'happy':
                self.assertIn('verification_optimizations', report)
            if local:
                self.assertEqual(cmd(root, 'git', 'status', '--porcelain').stdout, '')
                self.assertNotIn('ai_nest/cli.py', cmd(root, 'git', 'ls-tree', '-r', '--name-only', report['branch']).stdout)
            if scenario == 'coder_commit':
                # Branch history must remain pinned to the trusted original commit.
                branch_sha = cmd(root, 'git','rev-parse', report['branch']).stdout.strip()
                self.assertEqual(branch_sha, report['base_commit'])
                committed_sh = cmd(root,'git','show',report['branch']+':scripts/verify.sh').stdout
                self.assertNotEqual(committed_sh, '#!/bin/sh\nexit 0\n')
                self.assertIn('verify.py', committed_sh)
            if scenario == 'red_new_module':
                self.assertIn('calcx.py', report['code_files'])
        else:
            self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(report['status'],'blocked')
            self.assertFalse(Path(report['worktree']).exists())
            if scenario == 'invalid_json':
                self.assertIn('invalid JSON',report['error'])
                self.assertTrue(list(reports[0].parent.glob('artifacts/explore*.stdout.log')))
            if scenario == 'red_invalid':
                self.assertIn('RED', report['error'])

    def run_bootstrap(self, scenario, greenfield=True):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        tmp = handle.name
        root = Path(tmp) / 'project'
        root.mkdir()
        cmd(root, 'git', 'init', '-q')
        cmd(root, 'git', 'config', 'user.email', 'test@example.invalid')
        cmd(root, 'git', 'config', 'user.name', 'Test')
        self.assertEqual(cmd(root, sys.executable, str(ROOT / 'install.py'), str(root), '--local').returncode, 0)
        (root / 'docs.md').write_text('Planning docs only; no code yet.\n')
        if not greenfield:
            (root / 'app/tests').mkdir(parents=True)
            (root / 'app/tests/test_ok.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n')
        (root / 'scripts/verify.config.json').write_text(json.dumps({
            'version': 1, 'required_suites': ['unit'],
            'checks': [{'name': 'unit', 'suite': 'unit', 'cwd': 'app',
                        'argv': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']}]}))
        cfg = json.loads((root / 'nest.config.json').read_text())
        cfg['limits']['max_repair_attempts'] = 1
        (root / 'nest.config.json').write_text(json.dumps(cfg))
        cmd(root, 'git', 'add', '.')
        self.assertEqual(cmd(root, 'git', 'commit', '-qm', 'base').returncode, 0)
        bin_path = Path(tmp) / 'bin'
        bin_path.mkdir()
        (bin_path / 'codex').write_text(FAKE.replace('PYTHON', sys.executable, 1))
        (bin_path / 'codex').chmod(0o755)
        env = {**os.environ, 'PATH': str(bin_path) + os.pathsep + os.environ['PATH'], 'NEST_FAKE_SCENARIO': scenario}
        p = cmd(root, sys.executable, 'ai_nest/cli.py', 'bootstrap', '--provider', 'codex',
                '--allow-host-execution', 'Scaffold the app', env=env)
        report = json.loads(next((root / '.ai-nest/runs').glob('*/report.json')).read_text())
        return p, report, root

    def test_bootstrap_creates_greenfield_skeleton(self):
        p, report, root = self.run_bootstrap('bootstrap')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((report['status'], report['mode'], report['attempts']), ('verified', 'bootstrap', 1))
        self.assertEqual(report['created_protected_files'], ['app/pyproject.toml', 'app/uv.lock'])
        self.assertIn('app/tests/test_smoke.py', report['code_files'])
        self.assertTrue(report['agent_routing'][-1]['invoked'])
        self.assertIn('bootstrap_adds_dependencies', report['agent_routing'][-1]['reason'])
        self.assertTrue((Path(report['worktree']) / 'app/pyproject.toml').is_file())
        self.assertEqual(cmd(root, 'git', 'status', '--porcelain').stdout, '')

    def test_bootstrap_gate_edit_is_blocked_then_repaired(self):
        p, report, _ = self.run_bootstrap('bootstrap_gate_edit')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report['attempts'], 2)
        self.assertNotIn('scripts/bootstrap.sh', report['code_files'])

    def test_bootstrap_refuses_when_baseline_already_passes(self):
        p, report, _ = self.run_bootstrap('bootstrap', greenfield=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Baseline already passes', report['error'])

    def test_nested_test_support_files_are_allowed(self):
        self.run_scenario('new_nested_fixture')

    def test_coder_nested_test_helper_edit_triggers_retry(self):
        self.run_scenario('coder_nested_helper_edit')

    def test_happy_path(self): self.run_scenario('happy')
    def test_local_install_happy_path(self): self.run_scenario('happy', local=True)
    def test_local_install_blocks_coder_gate_tampering(self): self.run_scenario('coder_local_gate_edit', local=True)
    def test_invalid_red_blocked(self): self.run_scenario('red_invalid')
    def test_missing_symbol_red_accepted_then_blocked_by_missing_implementation(self): self.run_scenario('red_symbol')
    def test_coder_modifies_public_test_then_repairs(self): self.run_scenario('coder_test_edit')
    def test_coder_modifies_protected_package_json_then_repairs(self): self.run_scenario('coder_protected_edit')
    def test_head_changes_detected_and_recovered_without_commit(self): self.run_scenario('coder_commit')
    def test_missing_new_python_module_accepted_when_planned(self): self.run_scenario('red_new_module')
    def test_new_test_fixture_can_pass_verification(self): self.run_scenario('new_fixture')
    def test_provider_invalid_json_reported(self): self.run_scenario('invalid_json')

if __name__ == '__main__': unittest.main()
