---
description: Show LOC breakdown, language chart, and largest / most-changed files
argument-hint: [path] [--top N] [--json]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Project Stats

Codebase overview: lines of code per language, largest files, and most-churned files.

## Usage
`uv run ~/.claude/scripts/project_stats.py [path] [--top N] [--json]`

Flags:
- `path` — directory to analyse (default: current project)
- `--top N` — show the N largest and most-changed files (default 10)
- `--json` — machine-readable output

## What it does
- Walks the tree, skipping vendored, build, and VCS directories
- Classifies files by language and counts LOC, SLOC, and comment ratio
- Renders a bar chart of language distribution
- Uses git history (if available) to find most-churned files
- Lists the largest files by LOC

## When to use
- User asks "how big is this codebase", "what languages are used"
- Onboarding someone new to a repo
- Identifying the biggest and busiest files before a refactor
- Tracking codebase growth over time via `--json`
