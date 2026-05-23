---
description: Run all applicable linters in parallel (ruff, tsc, shellcheck, yamllint, etc.)
argument-hint: [path] [--fix] [--only py ts] [--changed]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Lint All

Auto-detect every linter relevant to the project and run them in parallel. Aggregates output into a single report.

## Usage
`uv run ~/.claude/scripts/lint_all.py [path] [--fix] [--only py ts] [--changed]`

Flags:
- `path` — directory to lint (default: current project)
- `--fix` — apply safe auto-fixes where supported
- `--only py ts` — restrict to selected languages
- `--changed` — only files changed vs. the base branch

## What it does
- Detects Python (ruff, ty), TypeScript/JavaScript (tsc, eslint), Shell (shellcheck), YAML (yamllint), Markdown, JSON
- Runs each linter in parallel with isolated output
- Normalises findings into a single summary: file, line, rule, message, severity
- Honours project configs (pyproject, tsconfig, eslintrc)

## When to use
- Before creating a PR
- User asks "lint the project" or "run all checks"
- After a large refactor or merge
- As a fast pre-commit smoke test
