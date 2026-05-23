---
description: Smart code search — find definitions, usages, imports, anti-patterns, dead code
argument-hint: <find|uses|imports|anti|dead> <name> [--path .]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Code Search

Semantic code search across the codebase. Goes beyond grep by understanding definitions, call sites, import graphs, anti-patterns, and dead code.

## Usage
`uv run ~/.claude/scripts/code_search.py <find|uses|imports|anti|dead> <name> [--path .]`

Modes:
- `find <name>` — locate the primary definition of a symbol
- `uses <name>` — every call site / reference
- `imports <name>` — every file that imports the module or symbol
- `anti <pattern>` — scan for known anti-patterns (e.g. bare except, any)
- `dead <name>` — symbols defined but never referenced

## What it does
- Indexes source files, honoring language-specific rules (Python, TS, Go, Rust)
- Filters noise (node_modules, .venv, dist, build)
- Produces a ranked list of hits with file:line and short context
- Supports scoping via `--path` to a subtree

## When to use
- User asks "where is X defined" or "find all uses of Y"
- Planning a refactor and need the full call graph for a symbol
- Auditing for anti-patterns before a review or release
- Hunting dead code prior to cleanup
- Investigating an import cycle or an unexpected dependency
