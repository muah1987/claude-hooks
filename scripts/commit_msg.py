#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
commit_msg.py — Generate conventional commit messages from git diff.

Analyses what changed (file types, additions/deletions, keywords in diff)
and proposes a conventional commit message: feat/fix/refactor/docs/test/chore.

Usage:
  uv run ~/.claude/scripts/commit_msg.py              # from staged changes
  uv run ~/.claude/scripts/commit_msg.py --all        # from all changes (staged + unstaged)
  uv run ~/.claude/scripts/commit_msg.py --commit     # generate AND commit immediately
  uv run ~/.claude/scripts/commit_msg.py --amend      # generate AND amend last commit
"""
__version__ = "2026.04.20.1"

import argparse
import re
import subprocess
import sys
from pathlib import Path
from collections import Counter

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _run(cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def analyse_diff(staged_only: bool) -> dict:
    flag = "--cached" if staged_only else "HEAD"
    _, diff = _run(f"git diff {flag}")
    _, stat = _run(f"git diff --stat {flag}")
    _, files_raw = _run(f"git diff --name-only {flag}")
    files = [f for f in files_raw.splitlines() if f.strip()]

    added_lines   = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed_lines = [l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]

    # Keyword frequency in added lines
    keywords = Counter()
    kw_map = {
        "def ": "function", "class ": "class", "function ": "function",
        "test_": "test", "describe(": "test", "it(": "test",
        "import ": "import", "require(": "import",
        "fix": "fix", "bug": "fix", "error": "fix", "exception": "fix",
        "TODO": "todo", "FIXME": "fix",
        "readme": "docs", "README": "docs", ".md": "docs",
    }
    for line in added_lines:
        for kw, cat in kw_map.items():
            if kw in line:
                keywords[cat] += 1

    return {
        "files": files,
        "added": len(added_lines),
        "removed": len(removed_lines),
        "keywords": dict(keywords),
        "stat_summary": stat.splitlines()[-1] if stat else "",
    }


def classify(data: dict) -> tuple[str, str]:
    files = data["files"]
    kw    = data["keywords"]

    # Determine type
    if kw.get("test", 0) > 2 or all(f.endswith(("_test.py", ".test.ts", "_test.go", ".spec.ts")) for f in files if files):
        commit_type = "test"
    elif kw.get("fix", 0) > kw.get("function", 0) and data["removed"] > data["added"] * 0.5:
        commit_type = "fix"
    elif all(f.endswith(".md") for f in files if files):
        commit_type = "docs"
    elif kw.get("docs", 0) > 2:
        commit_type = "docs"
    elif all(f.endswith((".json", ".yaml", ".yml", ".toml", ".env", ".cfg")) for f in files if files):
        commit_type = "chore"
    elif kw.get("function", 0) > 0 or kw.get("class", 0) > 0:
        commit_type = "feat"
    else:
        commit_type = "refactor"

    # Determine scope from common directory
    scopes = set()
    for f in files:
        parts = Path(f).parts
        if len(parts) > 1:
            scopes.add(parts[0])
    scope = list(scopes)[0] if len(scopes) == 1 else ""

    # Generate subject
    ext_types = Counter(Path(f).suffix for f in files if f)
    main_ext = ext_types.most_common(1)[0][0] if ext_types else ""
    lang_map = {".py": "Python", ".ts": "TypeScript", ".go": "Go", ".rs": "Rust",
                ".js": "JavaScript", ".md": "docs", ".sh": "shell"}
    lang = lang_map.get(main_ext, "")

    if commit_type == "fix" and files:
        subject = f"fix issue in {Path(files[0]).stem}"
    elif commit_type == "test":
        subject = f"add tests for {scope or 'module'}"
    elif commit_type == "docs":
        subject = f"update documentation"
    elif commit_type == "chore":
        subject = f"update {scope or 'config'} settings"
    elif len(files) == 1:
        subject = f"add {Path(files[0]).stem} {lang or ''}".strip()
    else:
        subject = f"update {scope or lang or 'module'} implementation"

    full = f"{commit_type}"
    if scope:
        full += f"({scope})"
    full += f": {subject}"

    return commit_type, full


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate conventional commit messages from diff")
    parser.add_argument("--all",    action="store_true", help="Include unstaged changes")
    parser.add_argument("--commit", action="store_true", help="Stage and commit with generated message")
    parser.add_argument("--amend",  action="store_true", help="Amend last commit with generated message")
    args = parser.parse_args()

    rc, _ = _run("git rev-parse --git-dir")
    if rc != 0:
        print("Not a git repository"); sys.exit(1)

    data = analyse_diff(staged_only=not args.all)

    if not data["files"]:
        print(f"{YELLOW}No changes detected{RESET}")
        if not args.all:
            print(f"{DIM}Tip: use --all to include unstaged changes{RESET}")
        sys.exit(0)

    commit_type, msg = classify(data)

    print(f"\n{BOLD}Suggested commit message:{RESET}\n")
    print(f"  {CYAN}{msg}{RESET}\n")
    print(f"  {DIM}Files: {len(data['files'])}  +{data['added']} -{data['removed']}  {data['stat_summary']}{RESET}\n")

    # Show alternatives
    alternatives = {
        "feat": "feat: add new functionality",
        "fix": "fix: resolve issue",
        "refactor": "refactor: improve code structure",
        "test": "test: add test coverage",
        "docs": "docs: update documentation",
        "chore": "chore: maintenance update",
    }
    other_types = [f"{t}: ..." for t in alternatives if t != commit_type]
    print(f"  {DIM}Other types: {', '.join(other_types)}{RESET}\n")

    if args.commit:
        _run("git add -u")
        rc, out = _run(f'git commit -m "{msg}"')
        if rc == 0:
            print(f"{GREEN}✓ Committed:{RESET} {msg}")
        else:
            print(f"Commit failed: {out}")
            sys.exit(1)

    elif args.amend:
        rc, out = _run(f'git commit --amend -m "{msg}"')
        if rc == 0:
            print(f"{GREEN}✓ Amended:{RESET} {msg}")
        else:
            print(f"Amend failed: {out}")
            sys.exit(1)


if __name__ == "__main__":
    main()
