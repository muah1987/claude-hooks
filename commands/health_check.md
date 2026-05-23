---
description: Run a full Claude Code setup health check (hooks, vault, scripts, settings)
argument-hint: [--json]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Health Check

End-to-end sanity check of the Claude Code harness. Verifies hooks, vault, scripts, settings, and model routing.

## Usage
`uv run ~/.claude/scripts/health_check.py [--json]`

Flags:
- `--json` — machine-readable output for dashboards

## What it does
- Validates `~/.claude/settings.json` schema and referenced paths
- Confirms every hook script is executable and exits 0 on a synthetic payload
- Checks vault accessibility and key count
- Verifies that each script in `~/.claude/scripts/` is reachable and importable
- Probes model routing (Claude reachable, Ollama cloud reachable)
- Reports pass/fail per check with a short remediation hint

## When to use
- User says "is everything set up correctly" or "why is X broken"
- After upgrading Claude Code or editing settings.json
- At the start of a new machine or a fresh clone of the dotfiles
- As a CI step for dotfiles repositories
