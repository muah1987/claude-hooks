---
description: Pretty-print agent registry, session transcripts, or hook logs
argument-hint: [agents|session|hooks] [--last N] [--no-follow]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Log Tail

Pretty-print recent entries from the agent registry, active session transcript, or hook logs.

## Usage
`uv run ~/.claude/scripts/log_tail.py [agents|session|hooks] [--last N] [--no-follow]`

Targets:
- `agents` — recent sub-agent runs with status and duration
- `session` — current session transcript messages
- `hooks` — recent hook invocations with exit codes

Flags:
- `--last N` — show the last N entries (default 20)
- `--no-follow` — print once and exit; default follows live

## What it does
- Reads JSONL logs under `~/.claude/` and pretty-prints them
- Colorises by severity and event type
- Optionally follows in real time like `tail -f`

## When to use
- User asks "what did the agents do", "show recent hook runs"
- Debugging a hook that seems to misfire
- Watching a background agent as it progresses
- Auditing a session after the fact
