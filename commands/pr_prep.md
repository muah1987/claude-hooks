---
description: Pre-PR checklist — lint, tests, commit quality, and generated PR description draft
argument-hint: [--base main] [--draft] [--skip-tests]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# PR Prep

Run the full pre-PR checklist: lint, tests, commit-message quality, and generate a PR description draft.

## Usage
`uv run ~/.claude/scripts/pr_prep.py [--base main] [--draft] [--skip-tests]`

Flags:
- `--base main` — base branch for diff and description (default: main)
- `--draft` — emit only the PR description draft, skip checks
- `--skip-tests` — skip the test run (lint still runs)

## What it does
- Runs lint, type checks, and tests scoped to changed files
- Reviews commit messages on the branch and flags non-conventional ones
- Computes a summary of changes vs. the base branch
- Generates a PR title and body draft (summary + test plan)
- Returns a single GO / NO-GO verdict

## When to use
- Before creating any pull request
- When the user says "prepare a PR", "draft a PR description"
- As a pre-push hook equivalent
- To double-check a branch you've not touched in a while
