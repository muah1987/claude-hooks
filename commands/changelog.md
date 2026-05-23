---
description: Generate a changelog from git history between two points
argument-hint: [from..to or 'last-release' or number of commits]
allowed-tools: Bash, Read, Write
---

# Changelog

Generate a structured changelog from git history for the specified `RANGE`.

## Variables

RANGE: $ARGUMENTS

## Instructions

- If no `RANGE` is provided, generate changelog since the last tag (`git describe --tags --abbrev=0`).
- If `RANGE` is a number, use the last N commits.
- If `RANGE` is in `from..to` format, use that git range.
- Group changes by conventional commit type.

## Workflow

1. **Gather Commits** - Get git log for the specified range
2. **Parse** - Extract conventional commit types, scopes, and descriptions
3. **Group** - Organize by category (Features, Fixes, Docs, etc.)
4. **Format** - Generate markdown changelog

## Categories

Map conventional commit prefixes:
- `feat` -> **Features**
- `fix` -> **Bug Fixes**
- `perf` -> **Performance**
- `refactor` -> **Refactoring**
- `docs` -> **Documentation**
- `test` -> **Tests**
- `chore` -> **Maintenance**
- `ci` -> **CI/CD**
- Breaking changes (any commit with `BREAKING CHANGE` or `!`) -> **Breaking Changes** (at top)

## Report

```
## Changelog [version or date range]

### Breaking Changes
- [description] ([commit hash])

### Features
- **[scope]**: [description] ([commit hash])

### Bug Fixes
- **[scope]**: [description] ([commit hash])

### Documentation
- [description] ([commit hash])

### Maintenance
- [description] ([commit hash])

---
**[N] commits** | **[N] files changed** | **[date range]**
```
