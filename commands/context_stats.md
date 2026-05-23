---
description: Show context window usage, cache hit rate, and compaction events for sessions
argument-hint: [--all] [--session <id>] [--json]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Context Stats

Inspect context window usage, prompt cache hit rate, and compaction events for the current or any past session.

## Usage
`uv run ~/.claude/scripts/context_stats.py [--all] [--session <id>] [--json]`

Flags:
- `--all` — aggregate across every session found in the projects directory
- `--session <id>` — inspect a specific session id
- `--json` — machine-readable output

## What it does
- Parses session transcripts under `~/.claude/projects/`
- Computes input / output token totals, cache read vs. cache write ratios
- Counts compaction events and estimates how much context was reclaimed
- Renders a compact table, or JSON when requested

## When to use
- User asks "how much context am I using", "am I close to compaction"
- Debugging cache hit rate regressions
- Post-mortem on a long session that compacted unexpectedly
- Feeding session metrics into a dashboard via `--json`
