---
description: Auto-detect and run tests (pytest, jest, vitest, cargo, go test, bun, etc.)
argument-hint: [path] [--framework X] [--dry-run]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Test Runner

Auto-detect the test framework for a project and run it with the right flags. Portable alternative to remembering every language's runner.

## Usage
`uv run ~/.claude/scripts/test_runner.py [path] [--framework X] [--dry-run]`

Flags:
- `path` — directory to test (default: current project)
- `--framework X` — force a specific framework (pytest, jest, vitest, cargo, go, bun)
- `--dry-run` — print the command that would run without executing

## What it does
- Detects project type via manifest files (pyproject.toml, package.json, Cargo.toml, go.mod)
- Picks the right runner and invokes it with sensible defaults
- Streams output live; exits with the runner's exit code
- Supports scoping to a path for focused runs

## When to use
- User says "run the tests", "test this project"
- Working in an unfamiliar repo where the test command is non-obvious
- Chaining tests into a multi-step workflow
- Previewing the command with `--dry-run` before execution
