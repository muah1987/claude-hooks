#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
pr_prep.py — Pre-PR checklist: lint, tests, diff summary, commit quality check.

Run before opening a PR to catch issues. Generates a PR description draft.

Usage:
  uv run ~/.claude/scripts/pr_prep.py                  # check current branch vs main
  uv run ~/.claude/scripts/pr_prep.py --base develop   # diff against develop
  uv run ~/.claude/scripts/pr_prep.py --draft          # print PR description draft
  uv run ~/.claude/scripts/pr_prep.py --skip-tests     # skip test execution
"""
__version__ = "2026.04.20.1"

import argparse
import subprocess
import sys
from pathlib import Path

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _run(cmd: str, cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, (r.stdout + r.stderr).strip()


def _ok(label: str, detail: str = "") -> None:
    print(f"  {GREEN}✓{RESET}  {label:<32} {DIM}{detail}{RESET}")


def _warn(label: str, detail: str = "") -> None:
    print(f"  {YELLOW}⚠{RESET}  {label:<32} {YELLOW}{detail}{RESET}")


def _fail(label: str, detail: str = "") -> None:
    print(f"  {RED}✗{RESET}  {label:<32} {RED}{detail}{RESET}")


def check_git(base: str) -> tuple[bool, dict]:
    rc, branch = _run("git rev-parse --abbrev-ref HEAD")
    if rc != 0:
        return False, {}

    rc, log = _run(f"git log --oneline {base}..HEAD")
    commits = [l for l in log.splitlines() if l.strip()]

    rc, stat = _run(f"git diff --stat {base}..HEAD")
    rc, files_changed = _run(f"git diff --name-only {base}..HEAD")
    changed = [f for f in files_changed.splitlines() if f.strip()]

    # Check commit message quality
    rc, raw_msgs = _run(f"git log --format='%s' {base}..HEAD")
    messages = [m for m in raw_msgs.splitlines() if m.strip()]
    bad_msgs = [m for m in messages if len(m) < 10 or m.lower() in ("wip", "fix", "update", "changes")]

    return True, {
        "branch": branch,
        "commits": commits,
        "changed_files": changed,
        "stat_summary": stat.splitlines()[-1] if stat else "",
        "bad_messages": bad_msgs,
    }


def run_linters(root: Path, changed_files: list[str]) -> list[tuple[str, bool, str]]:
    results = []
    py_files = [f for f in changed_files if f.endswith(".py")]
    ts_files = [f for f in changed_files if f.endswith((".ts", ".tsx", ".js", ".jsx"))]

    if py_files:
        rc, out = _run(f"python -m ruff check {' '.join(py_files[:20])} 2>&1 | head -20", cwd=root)
        results.append(("ruff (Python)", rc == 0, out[:200] if rc != 0 else ""))

    if ts_files and (root / "package.json").exists():
        rc, out = _run("npx tsc --noEmit 2>&1 | tail -10", cwd=root)
        results.append(("tsc (TypeScript)", rc == 0, out[:200] if rc != 0 else ""))

    sh_files = [f for f in changed_files if f.endswith(".sh")]
    if sh_files:
        rc, out = _run(f"shellcheck {' '.join(sh_files[:10])}", cwd=root)
        results.append(("shellcheck", rc == 0, out[:200] if rc != 0 else ""))

    return results


def run_tests(root: Path) -> tuple[bool, str]:
    for cmd in ["python -m pytest --tb=line -q 2>&1 | tail -10",
                "npm test -- --passWithNoTests 2>&1 | tail -10",
                "cargo test 2>&1 | tail -10",
                "go test ./... 2>&1 | tail -10"]:
        tool = cmd.split()[0]
        rc_check, _ = _run(f"which {tool}")
        if rc_check != 0:
            continue
        rc, out = _run(cmd, cwd=root)
        return rc == 0, out
    return True, "(no test runner detected)"


def generate_draft(git_info: dict, base: str) -> str:
    branch = git_info["branch"]
    commits = git_info["commits"]
    changed = git_info["changed_files"]

    lines = [
        "## Summary",
        "",
        "<!-- Describe what this PR does and why -->",
        "",
    ]
    if commits:
        lines += ["**Changes:**", ""]
        for c in commits[:8]:
            lines.append(f"- {c[8:]}")  # skip hash
        lines.append("")

    lines += [
        "## Files Changed",
        "",
    ]
    for f in changed[:15]:
        lines.append(f"- `{f}`")
    if len(changed) > 15:
        lines.append(f"- ... {len(changed) - 15} more files")
    lines += [
        "",
        "## Test Plan",
        "",
        "- [ ] Unit tests pass",
        "- [ ] Manual testing done",
        "- [ ] No regressions",
        "",
        f"🤖 Generated with `pr_prep.py` from branch `{branch}` vs `{base}`",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-PR checklist and draft generator")
    parser.add_argument("--base",       default="main", help="Base branch to diff against (default: main)")
    parser.add_argument("--draft",      action="store_true", help="Print PR description draft and exit")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests")
    args = parser.parse_args()

    root = Path.cwd()
    ok_git, git_info = check_git(args.base)

    if not ok_git:
        print(f"{RED}Not a git repository or git failed{RESET}"); sys.exit(1)

    if args.draft:
        print(generate_draft(git_info, args.base))
        return

    print(f"\n{BOLD}PR Prep Checklist{RESET}  {DIM}{git_info['branch']} → {args.base}{RESET}\n")

    failures = 0

    # Git checks
    commits = git_info["commits"]
    if not commits:
        _warn("Commits", f"no commits ahead of {args.base}")
    else:
        _ok("Commits", f"{len(commits)} commit(s) — {git_info['stat_summary']}")

    if git_info["bad_messages"]:
        _warn("Commit messages", f"{len(git_info['bad_messages'])} vague: {git_info['bad_messages'][0]}")
    else:
        _ok("Commit messages", "all descriptive")

    changed = git_info["changed_files"]
    if len(changed) > 50:
        _warn("Files changed", f"{len(changed)} files — consider splitting PR")
    else:
        _ok("Files changed", str(len(changed)))

    # Linting
    lint_results = run_linters(root, changed)
    for tool, passed, detail in lint_results:
        if passed:
            _ok(f"Lint: {tool}")
        else:
            _fail(f"Lint: {tool}", detail[:80])
            failures += 1

    if not lint_results:
        _warn("Linting", "no applicable linters found")

    # Tests
    if not args.skip_tests:
        test_ok, test_out = run_tests(root)
        last = test_out.splitlines()[-1] if test_out else ""
        if test_ok:
            _ok("Tests", last[:60])
        else:
            _fail("Tests", last[:60])
            failures += 1
    else:
        _warn("Tests", "skipped")

    # Uncommitted changes warning
    rc, uncommitted = _run("git status --porcelain")
    if uncommitted.strip():
        _warn("Uncommitted changes", "stash or commit before PR")
    else:
        _ok("Working tree", "clean")

    print()
    if failures == 0:
        print(f"  {GREEN}✓ Ready for PR{RESET}  Run with --draft for PR description\n")
    else:
        print(f"  {RED}✗ {failures} check(s) failed — fix before opening PR{RESET}\n")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
