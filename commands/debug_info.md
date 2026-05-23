---
description: Capture a full system + project debug snapshot (OS, tools, git, recent errors)
argument-hint: [--project /path] [--env] [--json] [--errors]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Debug Info

Produce a comprehensive debug snapshot for troubleshooting. Captures OS details, installed tool versions, project state, and recent errors.

## Usage
`uv run ~/.claude/scripts/debug_info.py [--project /path] [--env] [--json] [--errors]`

Flags:
- `--project /path` — scope project-specific checks to a directory
- `--env` — include environment variables (secrets are redacted)
- `--errors` — include recent errors from hook and session logs
- `--json` — machine-readable output

## What it does
- Collects OS, kernel, shell, locale, and arch
- Reports versions of `uv`, `bun`, `node`, `python`, `git`, `gh`, `ruff`, `ty`, `rustc`, `go`
- Dumps git status, branch, and last commits for the project
- Summarises hook configuration and recent hook failures
- Redacts secrets when `--env` is used

## When to use
- Automatically at the start of any debugging session
- When something breaks and the first question is "what's the setup"
- Filing a bug report or asking for help
- Before and after a major tooling change, for comparison
