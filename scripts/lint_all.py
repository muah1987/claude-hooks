#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
lint_all.py — Run all applicable linters against a project in parallel.

Auto-detects languages and runs: ruff, mypy, eslint, tsc, shellcheck,
yamllint, markdownlint, cargo clippy, go vet. Shows unified summary.

Usage:
  uv run ~/.claude/scripts/lint_all.py                 # current directory
  uv run ~/.claude/scripts/lint_all.py /path/to/project
  uv run ~/.claude/scripts/lint_all.py --fix           # auto-fix where possible
  uv run ~/.claude/scripts/lint_all.py --only py ts    # run only Python and TS
  uv run ~/.claude/scripts/lint_all.py --changed       # only lint git-changed files
"""
__version__ = "2026.04.20.1"

import argparse
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target"}


def _run(cmd: str, cwd: Path) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=cwd)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "TIMEOUT after 60s"
    except Exception as e:
        return 1, str(e)


def _tool_available(tool: str) -> bool:
    r = subprocess.run(f"which {tool}", shell=True, capture_output=True)
    return r.returncode == 0


def _has_files(root: Path, exts: set[str]) -> bool:
    for p in root.rglob("*"):
        if any(skip in p.parts for skip in SKIP_DIRS):
            continue
        if p.suffix.lower() in exts:
            return True
    return False


def _changed_files(root: Path, ext: str) -> list[str]:
    r = subprocess.run("git diff --name-only HEAD", shell=True,
                       capture_output=True, text=True, cwd=root)
    return [f for f in r.stdout.splitlines() if f.endswith(ext)]


def build_linters(root: Path, fix: bool, only: list[str], changed_only: bool) -> list[dict]:
    linters = []

    def add(key, name, cmd, exts, detect_file=None, detect_tool=None):
        if only and key not in only:
            return
        if detect_file and not (root / detect_file).exists():
            return
        if detect_tool and not _tool_available(detect_tool):
            return
        if not _has_files(root, exts):
            return
        linters.append({"key": key, "name": name, "cmd": cmd})

    fix_flag = "--fix" if fix else ""

    add("py",   "ruff",           f"ruff check . {fix_flag} 2>&1 | head -30",
        {".py"}, detect_tool="ruff")
    add("py",   "mypy",           "python -m mypy . --ignore-missing-imports 2>&1 | tail -20",
        {".py"}, detect_file="mypy.ini" if (root / "mypy.ini").exists() else None,
        detect_tool="mypy")
    add("ts",   "tsc",            "npx tsc --noEmit 2>&1 | tail -20",
        {".ts", ".tsx"}, detect_file="tsconfig.json")
    add("ts",   "eslint",         f"npx eslint . {fix_flag} 2>&1 | tail -20",
        {".ts", ".tsx", ".js", ".jsx"},
        detect_file=".eslintrc.js" if (root / ".eslintrc.js").exists() else
                    ".eslintrc.json" if (root / ".eslintrc.json").exists() else None)
    add("sh",   "shellcheck",     "find . -name '*.sh' | xargs shellcheck --severity=style 2>&1 | head -30",
        {".sh"}, detect_tool="shellcheck")
    add("yml",  "yamllint",       "yamllint . 2>&1 | head -30",
        {".yml", ".yaml"}, detect_tool="yamllint")
    add("md",   "markdownlint",   "markdownlint '**/*.md' --disable MD013 2>&1 | head -20",
        {".md"}, detect_tool="markdownlint")
    add("rs",   "cargo clippy",   f"cargo clippy {'--fix --allow-dirty' if fix else ''} 2>&1 | tail -20",
        {".rs"}, detect_file="Cargo.toml", detect_tool="cargo")
    add("go",   "go vet",         "go vet ./... 2>&1",
        {".go"}, detect_file="go.mod", detect_tool="go")

    return linters


def run_linter(linter: dict, root: Path) -> dict:
    rc, output = _run(linter["cmd"], root)
    issue_lines = [l for l in output.splitlines() if l.strip() and
                   any(w in l.lower() for w in ("error", "warning", "warn:", "note:", "fixme"))]
    return {
        "name": linter["name"],
        "key": linter["key"],
        "passed": rc == 0,
        "rc": rc,
        "issues": len(issue_lines),
        "output": output,
        "summary": issue_lines[:3],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all linters in parallel")
    parser.add_argument("path",    nargs="?", default=".", help="Project root")
    parser.add_argument("--fix",   action="store_true", help="Auto-fix where possible")
    parser.add_argument("--only",  nargs="+", help="Run only these linter keys (py ts sh yml md rs go)")
    parser.add_argument("--changed", action="store_true", help="Only lint git-changed files")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Path not found: {root}"); sys.exit(1)

    linters = build_linters(root, args.fix, args.only or [], args.changed)
    if not linters:
        print(f"{YELLOW}No applicable linters found for {root}{RESET}")
        sys.exit(0)

    print(f"\n{BOLD}Running {len(linters)} linter(s){RESET}  {DIM}{root}{RESET}\n")

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(run_linter, l, root): l for l in linters}
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            status = f"{GREEN}✓{RESET}" if r["passed"] else f"{RED}✗{RESET}"
            issues = f"  {YELLOW}{r['issues']} issues{RESET}" if r["issues"] else ""
            print(f"  {status}  {r['name']:<20}{issues}")

    print()

    failures = [r for r in results if not r["passed"]]
    if failures:
        for r in failures:
            print(f"  {RED}{r['name']}:{RESET}")
            for line in r["summary"]:
                print(f"    {line}")
            print()

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"  {GREEN}{passed}/{total} passed{RESET}"
          + (f"  {RED}{total - passed} failed{RESET}" if total != passed else "")
          + "\n")

    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
