---
description: Smart git operations — status, diff, log, commit, branches, cleanup, uncommitted
argument-hint: <status|diff|log|commit|branches|cleanup|uncommitted>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Git Smart

Rich git operations that go beyond raw porcelain. Complements `/git_status` by offering focused subcommands.

## Usage
`uv run ~/.claude/scripts/git_smart.py <status|diff|log|commit|branches|cleanup|uncommitted>`

Subcommands:
- `status` — concise repo state with ahead/behind and stash summary
- `diff` — summary diff with per-file hunk counts and renames
- `log` — annotated log with authors, dates, and file counts
- `commit` — interactive commit with generated message
- `branches` — list local and remote branches with last-touched timestamps
- `cleanup` — identify merged / stale branches safe to delete
- `uncommitted` — list every repo on disk with uncommitted changes

## What it does
- Wraps git porcelain commands, enriching output with color, alignment, and context
- Detects merged branches against `main`/`master` for safe cleanup
- Walks configured project roots to find dirty working trees

## When to use
- User wants more detail than `git status` gives
- Auditing branches before a cleanup sweep
- Locating every unfinished change across all repos
- Preparing a commit interactively with a generated message
