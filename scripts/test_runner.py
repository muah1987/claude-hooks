#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
test_runner.py — Auto-detect and run tests for any project.

Detects: pytest, jest, vitest, cargo test, go test, bun test, mocha, deno test.
Shows a clean summary with pass/fail counts, timing, and failed test names.

Usage:
  uv run ~/.claude/scripts/test_runner.py              # auto-detect and run
  uv run ~/.claude/scripts/test_runner.py /path/to/project
  uv run ~/.claude/scripts/test_runner.py --framework pytest
  uv run ~/.claude/scripts/test_runner.py --dry-run    # show what would run
  uv run ~/.claude/scripts/test_runner.py -- -k "test_login"  # pass extra args
"""
__version__ = "2026.04.20.1"

import argparse
import subprocess
import sys
import time
from pathlib import Path

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

FRAMEWORKS = [
    # (name, detect_files, detect_deps, command)
    ("pytest",   ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"],
                 ["pytest"], "python -m pytest --tb=short -q"),
    ("jest",     ["jest.config.js", "jest.config.ts", "jest.config.json"],
                 ["jest"], "npx jest --passWithNoTests"),
    ("vitest",   ["vitest.config.ts", "vitest.config.js"],
                 ["vitest"], "npx vitest run"),
    ("cargo",    ["Cargo.toml"],
                 [], "cargo test"),
    ("go",       ["go.mod"],
                 [], "go test ./... -v"),
    ("bun",      ["bun.lockb"],
                 [], "bun test"),
    ("deno",     ["deno.json", "deno.jsonc"],
                 [], "deno test"),
    ("mocha",    [".mocharc.js", ".mocharc.yml", ".mocharc.json"],
                 ["mocha"], "npx mocha"),
]


def _run(cmd: str, cwd: Path, extra_args: list[str]) -> tuple[int, str, float]:
    full_cmd = cmd + (" " + " ".join(extra_args) if extra_args else "")
    start = time.time()
    r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    elapsed = time.time() - start
    return r.returncode, r.stdout + r.stderr, elapsed


def detect_framework(root: Path) -> tuple[str, str] | None:
    pkg_json = root / "package.json"
    pkg_deps: set[str] = set()
    if pkg_json.exists():
        import json
        try:
            data = json.loads(pkg_json.read_text())
            pkg_deps = set((data.get("devDependencies") or {}).keys()) | \
                       set((data.get("dependencies") or {}).keys())
        except Exception:
            pass

    for name, files, deps, cmd in FRAMEWORKS:
        if any((root / f).exists() for f in files):
            return name, cmd
        if deps and any(d in pkg_deps for d in deps):
            return name, cmd

    return None


def render_result(name: str, rc: int, output: str, elapsed: float) -> None:
    lines = output.splitlines()
    status = f"{GREEN}PASSED{RESET}" if rc == 0 else f"{RED}FAILED{RESET}"
    print(f"\n{BOLD}[{name}]{RESET}  {status}  {DIM}{elapsed:.1f}s{RESET}\n")

    # Print last 40 lines (most frameworks put summary at the end)
    relevant = [l for l in lines if l.strip()]
    for line in relevant[-40:]:
        if "FAIL" in line or "ERROR" in line or "error" in line.lower():
            print(f"  {RED}{line}{RESET}")
        elif "PASS" in line or "ok" in line or "passed" in line.lower():
            print(f"  {GREEN}{line}{RESET}")
        elif "skip" in line.lower() or "warn" in line.lower():
            print(f"  {YELLOW}{line}{RESET}")
        else:
            print(f"  {line}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-detect and run project tests")
    parser.add_argument("path", nargs="?", default=".", help="Project root")
    parser.add_argument("--framework", help="Force a specific framework")
    parser.add_argument("--dry-run", action="store_true", help="Show command without running")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args passed to test runner")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"{RED}Path not found: {root}{RESET}"); sys.exit(1)

    extra = [a for a in (args.extra or []) if a != "--"]

    if args.framework:
        fw_map = {name: cmd for name, _, _, cmd in FRAMEWORKS}
        cmd = fw_map.get(args.framework)
        if not cmd:
            print(f"{RED}Unknown framework: {args.framework}{RESET}")
            print(f"Available: {', '.join(fw_map.keys())}"); sys.exit(1)
        detected = (args.framework, cmd)
    else:
        detected = detect_framework(root)

    if not detected:
        print(f"{YELLOW}No test framework detected in {root}{RESET}")
        print(f"{DIM}Tip: use --framework to specify one{RESET}")
        sys.exit(0)

    name, cmd = detected
    print(f"{CYAN}Framework:{RESET} {name}")
    print(f"{CYAN}Command:{RESET}  {cmd}{' ' + ' '.join(extra) if extra else ''}")
    print(f"{CYAN}Root:{RESET}     {root}\n")

    if args.dry_run:
        return

    rc, output, elapsed = _run(cmd, root, extra)
    render_result(name, rc, output, elapsed)
    sys.exit(rc)


if __name__ == "__main__":
    main()
