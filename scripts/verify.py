#!/usr/bin/env python3
"""AI Nest verification gate: no third-party Python dependencies.

All declared checks are required. Full mode rejects absent required suites.
The runner records actual exit codes; it does not claim a failing check passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "scripts" / "verify.config.json"
SUITES = ("smoke", "static", "unit", "integration", "contract", "e2e", "security", "build")


class ConfigError(ValueError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def repo_sha() -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def resolve_workspace_path(raw: str, label: str) -> Path:
    path = (ROOT / raw).resolve()
    if not path.is_relative_to(ROOT):
        raise ConfigError(f"{label} must remain inside repository: {raw}")
    return path


def validate(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ConfigError("Expected JSON object with version: 1")
    checks = raw.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ConfigError("'checks' must be a nonempty list (fail closed)")
    required = raw.get("required_suites", [])
    if not isinstance(required, list) or any(s not in SUITES for s in required):
        raise ConfigError(f"'required_suites' must be a list from: {', '.join(SUITES)}")
    default_timeout = raw.get("default_timeout_seconds", 600)
    if type(default_timeout) is not int or not 1 <= default_timeout <= 7200:
        raise ConfigError("default_timeout_seconds must be 1..7200")

    checked = []
    names = set()
    for index, step in enumerate(checks):
        if not isinstance(step, dict):
            raise ConfigError(f"Check {index + 1}: expected object")
        name = step.get("name")
        suite = step.get("suite")
        argv = step.get("argv")
        cwd = step.get("cwd", ".")
        timeout = step.get("timeout_seconds", default_timeout)
        if not isinstance(name, str) or not name or not all(c.isalnum() or c in "_-" for c in name):
            raise ConfigError(f"Check {index + 1}: invalid name (use letters, digits, _ or -)")
        if name in names:
            raise ConfigError(f"Duplicate check: {name}")
        names.add(name)
        if suite not in SUITES:
            raise ConfigError(f"Check {name}: invalid suite {suite!r}")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise ConfigError(f"Check {name}: argv must be a nonempty list of nonempty strings")
        if not isinstance(cwd, str) or not cwd:
            raise ConfigError(f"Check {name}: cwd must be a relative directory")
        if type(timeout) is not int or not 1 <= timeout <= 7200:
            raise ConfigError(f"Check {name}: timeout_seconds must be 1..7200")
        workdir = resolve_workspace_path(cwd, f"Check {name} cwd")
        if not workdir.is_dir():
            raise ConfigError(f"Check {name}: missing directory {cwd!r}")
        checked.append({"name": name, "suite": suite, "argv": argv,
                        "cwd": cwd, "workdir": workdir, "timeout_seconds": timeout})
    return {"checks": checked, "required_suites": required}


def stream_command(argv: list[str], workdir: Path, log_file: Path, timeout: int) -> tuple[int | None, str]:
    """Execute without a shell and stream output; kill the process group on timeout."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(argv, cwd=workdir, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    errors="replace", bufsize=1,
                                    start_new_session=(os.name == "posix"))
        except OSError as exc:
            msg = f"Could not execute {argv[0]}: {exc}\n"
            print(msg, file=sys.stderr, end="", flush=True)
            log.write(msg)
            return None, "error"

        def drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            code = proc.wait(timeout=timeout)
            reader.join(timeout=5)
            return code, "passed" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT after {timeout}s: {' '.join(argv)}", file=sys.stderr, flush=True)
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()
            reader.join(timeout=5)
            log.write(f"\nTIMEOUT after {timeout}s\n")
            return None, "timeout"
        except KeyboardInterrupt:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait()
            raise


def safe_write_json(dest: Path, content: dict) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Nest deterministic verification")
    parser.add_argument("--suite", choices=("full", *SUITES), default="full",
                        help="Run all configured checks (full) or one suite")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Path to verification manifest (default: scripts/verify.config.json)")
    parser.add_argument("--report", help="Write JSON report to this path (default: unique under .ai-nest/verification/)")
    parser.add_argument("--list", action="store_true", help="List configured checks without executing")
    args = parser.parse_args()

    try:
        config_path = Path(args.config).resolve()
        if not config_path.is_file():
            raise ConfigError(f"Verification config missing: {config_path}. Copy the example and configure real checks.")
        cfg = validate(json.loads(config_path.read_text(encoding="utf-8")))
        steps = cfg["checks"]
        if args.suite == "full":
            available = {s["suite"] for s in steps}
            missing = set(cfg["required_suites"]) - available
            if missing:
                raise ConfigError("Missing required suites: " + ", ".join(sorted(missing)))
        else:
            steps = [step for step in steps if step["suite"] == args.suite]
            if not steps:
                raise ConfigError(f"No checks configured for --suite {args.suite}")
    except (ConfigError, ValueError, OSError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for step in steps:
            print(f"{step['name']:<26} [{step['suite']:<11}] {step['cwd']}: {step['argv']}")
        return 0

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
    reports_root = ROOT / ".ai-nest" / "verification"
    report_path = Path(args.report).resolve() if args.report else reports_root / f"verify-{run_id}.json"
    log_root = reports_root / "logs" / run_id
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "repository_sha": repo_sha(),
        "mode": args.suite,
        "started_at": now(),
        "status": "running",
        "checks": [],
    }
    start = time.monotonic()
    safe_write_json(report_path, report)

    try:
        for step in steps:
            log = log_root / (step["name"] + ".log")
            print(f"\n=== {step['name']} [{step['suite']}] ===", flush=True)
            print(f"$ {step['argv']} (cwd={step['cwd']})", flush=True)
            began = time.monotonic()
            code, status = stream_command(step["argv"], step["workdir"], log, step["timeout_seconds"])
            entry = {"name": step["name"], "suite": step["suite"], "cwd": step["cwd"],
                     "argv": step["argv"], "status": status, "exit_code": code,
                     "duration_seconds": round(time.monotonic() - began, 3),
                     "log_path": str(log.relative_to(ROOT))}
            report["checks"].append(entry)
            safe_write_json(report_path, report)
            print(f"=== {step['name']}: {status} ===", flush=True)
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["finished_at"] = now()
        safe_write_json(report_path, report)
        return 130

    failed = [entry for entry in report["checks"] if entry["status"] != "passed"]
    report["status"] = "failed" if failed else "passed"
    report["finished_at"] = now()
    report["duration_seconds"] = round(time.monotonic() - start, 3)
    safe_write_json(report_path, report)
    print(f"\nVerification {report['status'].upper()}: {len(steps) - len(failed)}/{len(steps)} checks passed", flush=True)
    print(f"Report: {report_path}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
