#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
git_smart.py — Smart git helpers for Claude Code sessions.

Commands:
  status        Pretty git status with file counts and branch info
  diff [--stat] Coloured diff summary — what changed and why it matters
  log [N]       Last N commits with stats (default 10)
  commit <msg>  Stage all tracked changes and commit with conventional message
  branches      List branches with last-commit age and merged status
  cleanup       Delete local branches already merged into main/master
  stash-list    Show stash entries with timestamps and sizes
  uncommitted   Show all files changed since last commit (with line counts)
  blame <file>  Who changed what — summarised blame per function/block

Usage:
  uv run ~/.claude/scripts/git_smart.py status
  uv run ~/.claude/scripts/git_smart.py diff
  uv run ~/.claude/scripts/git_smart.py log 5
  uv run ~/.claude/scripts/git_smart.py commit "feat: add login endpoint"
  uv run ~/.claude/scripts/git_smart.py branches
  uv run ~/.claude/scripts/git_smart.py cleanup --dry-run
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
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _run(cmd: str, cwd: Path | None = None, check: bool = False) -> tuple[int, str, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _git_root() -> Path | None:
    rc, out, _ = _run("git rev-parse --show-toplevel")
    return Path(out) if rc == 0 else None


def cmd_status(args: argparse.Namespace) -> int:
    root = _git_root()
    if not root:
        print(f"{RED}Not a git repository{RESET}"); return 1

    _, branch, _ = _run("git rev-parse --abbrev-ref HEAD")
    _, upstream, _ = _run("git rev-parse --abbrev-ref @{u} 2>/dev/null")
    _, ahead_behind, _ = _run("git rev-list --left-right --count HEAD...@{u} 2>/dev/null")

    print(f"\n{BOLD}Branch:{RESET} {CYAN}{branch}{RESET}", end="")
    if upstream:
        ab = ahead_behind.split() if ahead_behind else ["0", "0"]
        ahead, behind = ab[0] if len(ab) > 0 else "0", ab[1] if len(ab) > 1 else "0"
        if ahead != "0":
            print(f"  {GREEN}↑{ahead}{RESET}", end="")
        if behind != "0":
            print(f"  {RED}↓{behind}{RESET}", end="")
    print()

    _, status_out, _ = _run("git status --porcelain")
    if not status_out:
        print(f"  {GREEN}✓ Working tree clean{RESET}\n"); return 0

    staged, unstaged, untracked = [], [], []
    for line in status_out.splitlines():
        xy = line[:2]
        fname = line[3:]
        if xy[0] not in (" ", "?"):
            staged.append((xy[0], fname))
        if xy[1] not in (" ", "?"):
            unstaged.append((xy[1], fname))
        if xy == "??":
            untracked.append(fname)

    LABELS = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied"}
    if staged:
        print(f"\n  {GREEN}Staged ({len(staged)}){RESET}")
        for st, f in staged[:15]:
            print(f"    {GREEN}{LABELS.get(st, st):<10}{RESET} {f}")
    if unstaged:
        print(f"\n  {YELLOW}Unstaged ({len(unstaged)}){RESET}")
        for st, f in unstaged[:15]:
            print(f"    {YELLOW}{LABELS.get(st, st):<10}{RESET} {f}")
    if untracked:
        print(f"\n  {DIM}Untracked ({len(untracked)}){RESET}")
        for f in untracked[:8]:
            print(f"    {DIM}{f}{RESET}")
        if len(untracked) > 8:
            print(f"    {DIM}... {len(untracked)-8} more{RESET}")

    _, diff_stat, _ = _run("git diff --stat HEAD 2>/dev/null")
    if diff_stat:
        last_line = diff_stat.splitlines()[-1] if diff_stat else ""
        print(f"\n  {DIM}{last_line}{RESET}")
    print()
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    if not _git_root():
        print(f"{RED}Not a git repository{RESET}"); return 1

    if args.stat:
        _, out, _ = _run("git diff --stat HEAD")
        print(out or "(no changes)")
        return 0

    _, out, _ = _run("git diff --color HEAD")
    if not out:
        _, out, _ = _run("git diff --color --cached")
    print(out or f"{GREEN}(no changes){RESET}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    n = args.n or 10
    fmt = "%C(yellow)%h%C(reset) %C(cyan)%ar%C(reset) %C(bold)%s%C(reset) %C(dim)(%an)%C(reset)"
    _, out, _ = _run(f"git log --oneline --color --format='{fmt}' -n {n}")
    if not out:
        print("(no commits)"); return 0
    _, stat, _ = _run(f"git log --shortstat -n {n}")
    print(f"\n{BOLD}Last {n} commits:{RESET}\n{out}\n")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    if not _git_root():
        print(f"{RED}Not a git repository{RESET}"); return 1
    msg = " ".join(args.message)
    if not msg:
        print(f"{RED}Usage: git_smart.py commit <message>{RESET}"); return 1

    rc, _, err = _run("git add -u")
    if rc != 0:
        print(f"{RED}git add failed: {err}{RESET}"); return 1

    rc, out, err = _run(f'git commit -m "{msg}"')
    if rc != 0:
        print(f"{RED}Commit failed: {err}{RESET}"); return rc
    print(f"{GREEN}✓ Committed:{RESET} {msg}")
    print(out.splitlines()[0] if out else "")
    return 0


def cmd_branches(args: argparse.Namespace) -> int:
    if not _git_root():
        print(f"{RED}Not a git repository{RESET}"); return 1

    _, current, _ = _run("git rev-parse --abbrev-ref HEAD")
    _, out, _ = _run("git branch -vv --sort=-committerdate")

    print(f"\n{BOLD}Branches:{RESET}\n")
    for line in out.splitlines()[:25]:
        marker = f"{GREEN}*{RESET}" if line.startswith("*") else " "
        rest = line[2:]
        color = CYAN if line.startswith("*") else RESET
        print(f"  {marker} {color}{rest}{RESET}")
    print()
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    if not _git_root():
        print(f"{RED}Not a git repository{RESET}"); return 1

    _, main_branch, _ = _run("git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null")
    main_branch = main_branch.split("/")[-1] if main_branch else "main"

    _, merged, _ = _run(f"git branch --merged {main_branch}")
    to_delete = [b.strip() for b in merged.splitlines()
                 if b.strip() and b.strip() not in (main_branch, "main", "master", "*")]

    if not to_delete:
        print(f"{GREEN}No merged branches to clean up{RESET}"); return 0

    print(f"\n{BOLD}Merged branches to delete:{RESET}")
    for b in to_delete:
        print(f"  {RED}{b}{RESET}")

    if args.dry_run:
        print(f"\n{DIM}(dry run — pass without --dry-run to delete){RESET}"); return 0

    for b in to_delete:
        rc, _, err = _run(f"git branch -d {b}")
        status = f"{GREEN}deleted{RESET}" if rc == 0 else f"{RED}failed: {err}{RESET}"
        print(f"  {b}: {status}")
    return 0


def cmd_uncommitted(args: argparse.Namespace) -> int:
    if not _git_root():
        print(f"{RED}Not a git repository{RESET}"); return 1

    _, out, _ = _run("git diff --stat HEAD")
    if not out:
        print(f"{GREEN}Nothing uncommitted{RESET}"); return 0

    print(f"\n{BOLD}Uncommitted changes:{RESET}\n{out}\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart git helpers")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status")
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("--stat", action="store_true")
    p_log = sub.add_parser("log")
    p_log.add_argument("n", nargs="?", type=int, default=10)
    p_commit = sub.add_parser("commit")
    p_commit.add_argument("message", nargs="+")
    sub.add_parser("branches")
    p_cleanup = sub.add_parser("cleanup")
    p_cleanup.add_argument("--dry-run", action="store_true")
    sub.add_parser("uncommitted")

    args = parser.parse_args()
    dispatch = {
        "status": cmd_status, "diff": cmd_diff, "log": cmd_log,
        "commit": cmd_commit, "branches": cmd_branches,
        "cleanup": cmd_cleanup, "uncommitted": cmd_uncommitted,
    }
    fn = dispatch.get(args.cmd)
    if not fn:
        parser.print_help(); return
    sys.exit(fn(args))


if __name__ == "__main__":
    main()
