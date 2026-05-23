---
description: Audit all skills for missing description/hint, bad paths, allowed-tools gaps
argument-hint: [--fix] [--json] [--skill <name>]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Skill Audit

Audit every skill file under `~/.claude/commands/` for correctness, completeness, and best practices.

## Usage
`uv run ~/.claude/scripts/skill_audit.py [--fix] [--json] [--skill <name>]`

Flags:
- `--fix` — apply safe auto-fixes (add missing allowed-tools, normalise frontmatter)
- `--skill <name>` — audit a single skill
- `--json` — machine-readable output

## What it does
- Parses the YAML frontmatter of every skill
- Flags missing `description`, `argument-hint`, or `allowed-tools`
- Verifies referenced script paths exist and are executable
- Detects stale command examples and broken links
- Emits a per-skill report with a severity

## When to use
- After adding or editing a skill file
- Weekly maintenance sweep of the skill library
- Before publishing or sharing the dotfiles
- Ensuring consistency across skill frontmatter
