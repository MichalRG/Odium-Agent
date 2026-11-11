"""Run the real Python orchestration and subprocess provider adapter with a fake Codex CLI.

This is a CLI compatibility smoke test, NOT a live LLM/model test.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'selftests' else Path(__file__).resolve().parents[1]


def cmd(root, *argv, env=None):
    return subprocess.run(list(argv), cwd=root, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)


class CLISmokeTests(unittest.TestCase):
    def test_clean_install_full_tdd_with_fake_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            self.assertEqual(cmd(root, 'git', 'init', '-q').returncode, 0)
            cmd(root, 'git', 'config', 'user.name', 'Test')
            cmd(root, 'git', 'config', 'user.email', 'test@example.test')
            p = cmd(root, sys.executable, str(PACKAGE / 'install.py'), str(root))
            self.assertEqual(p.returncode, 0, p.stderr)
            (root / 'calc.py').write_text('def add(a,b):\n    return 0\n')
            (root / 'tests').mkdir()
            (root / 'tests/test_existing.py').write_text(
                'import unittest\nfrom calc import add\n'
                'class TestExisting(unittest.TestCase):\n'
                '    def test_zero(self):\n        self.assertEqual(add(0,0),0)\n')
            config = json.loads((root / 'nest.config.json').read_text())
            config['tdd']['red_commands'] = [{'name':'red','argv':['bash','scripts/verify.sh','--suite','unit'],'cwd':'.'}]
            (root / 'nest.config.json').write_text(json.dumps(config))
            # The manifest is intentionally project-specific.
            (root / 'scripts/verify.config.json').write_text(json.dumps({
                'version':1,'required_suites':['unit'],
                'checks':[{'name':'unit','suite':'unit','cwd':'.',
                           'argv':[sys.executable,'-m','unittest','discover','-s','tests','-v']}]
            }))
            (root / '.DS_Store').write_text('ignored')
            (root / 'ai_nest/__pycache__').mkdir(exist_ok=True)
            (root / 'ai_nest/__pycache__/fake.pyc').write_text('ignored')
            cmd(root, 'git', 'add', '.')
            self.assertEqual(cmd(root, 'git', 'commit', '-qm', 'base').returncode, 0)
            self.assertEqual(cmd(root, 'git', 'status', '--porcelain').stdout.strip(), '')
            fake_bin = Path(tmp) / 'bin'
            fake_bin.mkdir()
            fake = fake_bin / 'codex'
            fake.write_text('''#!''' + sys.executable + '''
import json,sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == 'exec', args
assert args[-1] == '-', args
prompt = sys.stdin.read()
base = Path.cwd()
notes = [{'kind':'fact','severity':'info','summary':'observed',
          'evidence':'calc.py','file':'calc.py','suggested_action':'none'}]
if '# Role: explorer' in prompt:
    payload={'summary':'repo mapping','relevant_files':['calc.py'],'risks':[]}
elif '# Role: specification writer' in prompt:
    payload={'goal':'fix addition','acceptance_criteria':['add(1,2) == 3'],
             'constraints':[],'open_questions':[]}
elif '# Role: planner' in prompt:
    payload={'tasks':[{'id':'T-1','description':'correct add','files':['calc.py']}],
             'testing_strategy':'unit','risks':[],'commits':[{'message':'Correct add','tasks':['T-1']}]}
elif '# Role: test-engineer — PUBLIC' in prompt:
    (base/'tests/test_feature.py').write_text(
        'import unittest\\nfrom calc import add\\nclass TestAdd(unittest.TestCase):\\n'
        '    def test_add(self):\\n        self.assertEqual(add(1,2),3)\\n')
    payload={'summary':'public TDD','files_modified':['tests/test_feature.py'],
             'expected_red_tests':['test_add'], 'coder_guidance':['pass public unit tests'],
             'test_strategy':{'unit':['test_add'],'integration':[],'contract':[],'e2e':[],'smoke':[]}}
elif '# Role: protected acceptance test-engineer' in prompt:
    (base/'tests/test_hidden.py').write_text(
        'import unittest\\nfrom calc import add\\nclass TestHidden(unittest.TestCase):\\n'
        '    def test_negative(self):\\n        self.assertEqual(add(-2,-1),-3)\\n')
    payload={'summary':'private tests','files_modified':['tests/test_hidden.py']}
elif '# Role: coder —' in prompt:
    assert (base/'tests/test_feature.py').exists()
    assert not (base/'tests/test_hidden.py').exists()
    (base/'calc.py').write_text('def add(a,b):\\n    return a+b\\n')
    payload={'summary':'implemented','files_modified':['calc.py']}
elif '# Role: code-reviewer' in prompt:
    assert not (base/'tests/test_hidden.py').exists()
    payload={'approved':True,'findings':[],'summary':'reviewed'}
else:
    raise AssertionError('Unrecognized prompt start')
payload['observations']=notes
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(payload))
''')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get('PATH', ''))
            p = cmd(root, sys.executable, 'ai_nest/cli.py', 'doctor', '--provider','codex', env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            p = cmd(root, sys.executable, 'ai_nest/cli.py', 'run', '--provider','codex',
                    '--session','fake-smoke','--allow-host-execution','Fix add',env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            reports = list((root/'.ai-nest/runs').glob('*/report.json'))
            self.assertEqual(len(reports),1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['status'],'verified')
            self.assertEqual(report['public_red_status'],'expected_red')
            self.assertTrue((root/'.ai-nest/sessions').exists())
            self.assertTrue((Path(report['worktree'])/'tests/test_feature.py').exists())
            self.assertFalse((Path(report['worktree'])/'tests/test_hidden.py').exists())
            cmd(root, 'git', 'worktree', 'remove', '--force', report['worktree'])


if __name__ == '__main__':
    unittest.main()
