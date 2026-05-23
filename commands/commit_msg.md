---
description: Generate a conventional commit message from the staged git diff
argument-hint: [--all] [--commit] [--amend]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Commit Message

Generate a Conventional Commits message by reading the staged diff (or all changes with `--all`). Optionally commit directly.

## Usage
`uv run ~/.claude/scripts/commit_msg.py [--all] [--commit] [--amend]`

Flags:
- `--all` — include unstaged changes in the analysis
- `--commit` — run `git commit` with the generated message
- `--amend` — amend the previous commit instead

## What it does
- Reads `git diff --cached` (or `git diff HEAD` with `--all`)
- Classifies change type: feat, fix, refactor, docs, test, chore, perf, ci, build, style
- Derives a scope from the touched paths
- Produces a one-line subject plus a short body summarising the "why"
- Prints the message; with `--commit`, performs the commit

## When to use
- Before committing when no message was specified
- User says "commit this", "write a commit message", "conventional commit"
- Cleaning up a series of WIP commits into one well-described commit
- Automating commit messages in a multi-step workflow
