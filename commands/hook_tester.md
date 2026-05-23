---
description: Fire any hook locally with a synthetic payload to test behavior
argument-hint: --event <EventName> [--prompt "text"] [--file path]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Hook Tester

Invoke any Claude Code hook locally with a synthetic payload. Useful for developing, debugging, and regression-testing hooks without round-tripping through a real session.

## Usage
`uv run ~/.claude/scripts/hook_tester.py --event <EventName> [--prompt "text"] [--file path]`

Supported events: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `SubagentStart`, `SubagentStop`, `Stop`, `Notification`.

Flags:
- `--event` — required, event name to simulate
- `--prompt` — text to inject for prompt-related events
- `--file` — file path to simulate a tool-use payload against

## What it does
- Builds a realistic JSON payload matching the event schema
- Invokes the configured hook script with stdin piped
- Captures stdout, stderr, and exit code
- Pretty-prints the result, flagging non-zero exits

## When to use
- Debugging hook behavior after editing a hook script
- Reproducing a hook failure seen in the wild
- Adding a new hook and wanting a tight feedback loop
- Writing tests or CI coverage for hooks
