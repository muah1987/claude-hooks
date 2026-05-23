---
description: Estimate USD spend from session transcripts using current Anthropic pricing
argument-hint: [--today] [--top N] [--json]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Cost Tracker

Estimate token spend in USD from local session transcripts. Applies per-model pricing and accounts for prompt caching.

## Usage
`uv run ~/.claude/scripts/cost_tracker.py [--today] [--top N] [--json]`

Flags:
- `--today` — restrict to sessions modified today
- `--top N` — show the N most expensive sessions
- `--json` — machine-readable output

## What it does
- Walks `~/.claude/projects/*/` for session transcripts
- Sums input, output, cache-read, and cache-write tokens per model
- Applies current Anthropic pricing (Opus, Sonnet, Haiku tiers)
- Prints a per-session and per-model cost breakdown with a grand total

## When to use
- User asks "how much did this cost", "what's my spend today"
- Monthly / weekly billing reconciliation
- Comparing the cost of different models for the same kind of work
- Feeding a cost dashboard via `--json`
