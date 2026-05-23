---
description: Scan codebase for TODO/FIXME/BUG/HACK markers with severity grouping
argument-hint: [path] [--type FIXME] [--json] [--by-file]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# TODO Scanner

Find every TODO, FIXME, BUG, HACK, XXX, and NOTE marker in the codebase, grouped by severity.

## Usage
`uv run ~/.claude/scripts/todo_scanner.py [path] [--type FIXME] [--json] [--by-file]`

Flags:
- `path` — directory to scan (default: current project)
- `--type FIXME` — restrict to a single marker type
- `--by-file` — group results by file instead of by type
- `--json` — machine-readable output

## What it does
- Scans source files for well-known markers
- Classifies by severity: BUG/FIXME (high), HACK/XXX (medium), TODO/NOTE (low)
- Extracts the author (git blame) and age for each marker
- Renders a summary table plus per-marker context lines

## When to use
- User asks "what's left to do", "what are the known issues"
- Reviewing a codebase you're about to inherit or refactor
- Preparing a release and sweeping for unresolved HACKs
- Tracking technical debt over time via `--json`
