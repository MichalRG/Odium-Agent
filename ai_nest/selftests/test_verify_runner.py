import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == 'selftests' else Path(__file__).resolve().parents[1]) / "scripts"


class VerifyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        for name in ("verify.sh", "verify.py"):
            shutil.copy2(SOURCE / name, self.root / "scripts" / name)

    def run_verify(self, config=None, *args):
        if config is not None:
            (self.root / "scripts" / "verify.config.json").write_text(json.dumps(config))
        return subprocess.run(["bash", "scripts/verify.sh", *args], cwd=self.root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=20)

    def config(self, checks, required=None):
        return {"version": 1, "required_suites": required or [], "checks": checks}

    def step(self, name, suite, script, cwd=".", timeout=10):
        return {"name": name, "suite": suite, "cwd": cwd,
                "argv": [sys.executable, "-c", script], "timeout_seconds": timeout}

    def report(self):
        reports = list((self.root / ".ai-nest" / "verification").glob("verify-*.json"))
        self.assertEqual(len(reports), 1)
        return json.loads(reports[0].read_text())

    def test_full_success_writes_report_and_logs(self):
        cfg = self.config([self.step("one", "unit", "print('ok')"),
                           self.step("two", "integration", "print('all good')")],
                          ["unit", "integration"])
        result = self.run_verify(cfg)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report()
        self.assertEqual(report["status"], "passed")
        self.assertEqual([s["exit_code"] for s in report["checks"]], [0, 0])
        self.assertIn("all good", (self.root / report["checks"][1]["log_path"]).read_text())

    def test_failure_does_not_skip_later_checks(self):
        cfg = self.config([self.step("broken", "unit", "import sys; sys.exit(7)"),
                           self.step("next", "build", "print('ran')")])
        result = self.run_verify(cfg)
        self.assertEqual(result.returncode, 1)
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual([s["exit_code"] for s in report["checks"]], [7, 0])

    def test_missing_config_fails_closed(self):
        result = self.run_verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Verification config missing", result.stderr)

    def test_missing_required_suite_fails_closed(self):
        result = self.run_verify(self.config([self.step("one", "unit", "print(1)")],
                                                    ["unit", "security"]))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing required suites", result.stderr)

    def test_targeted_suite_runs_only_selected(self):
        cfg = self.config([self.step("fail", "integration", "import sys;sys.exit(5)"),
                           self.step("good", "unit", "print('ok')")],
                          ["unit", "integration"])
        result = self.run_verify(cfg, "--suite", "unit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([s["name"] for s in self.report()["checks"]], ["good"])

    def test_unknown_suite_has_no_silent_success(self):
        cfg = self.config([self.step("good", "unit", "print('ok')")])
        result = self.run_verify(cfg, "--suite", "e2e")
        self.assertEqual(result.returncode, 2)
        self.assertIn("No checks configured", result.stderr)

    def test_prevent_outside_repo_cwd(self):
        cfg = self.config([self.step("outside", "unit", "print('oops')", cwd="..")])
        result = self.run_verify(cfg)
        self.assertEqual(result.returncode, 2)
        self.assertIn("inside repository", result.stderr)

    def test_command_not_found_fails_and_is_reported(self):
        cfg = self.config([{ "name": "missing", "suite": "unit", "cwd": ".",
                             "argv": ["this-command-does-not-exist-123"]}])
        result = self.run_verify(cfg)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.report()["checks"][0]["status"], "error")

    def test_timeout_is_failure(self):
        cfg = self.config([self.step("slow", "unit", "import time; time.sleep(3)", timeout=1)])
        result = self.run_verify(cfg)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.report()["checks"][0]["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
