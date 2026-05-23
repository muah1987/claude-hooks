---
description: Refactor code with safety checks -- preserving behavior while improving structure
argument-hint: [file-path or description of what to refactor]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Refactor

Refactor the specified `TARGET` to improve code quality while preserving behavior.

## Variables

TARGET: $ARGUMENTS

## Instructions

- If no `TARGET` is provided, stop and ask the user what to refactor.
- NEVER change behavior. Refactoring means same inputs produce same outputs.
- Run tests before AND after to verify behavior is preserved.
- Make changes incrementally -- one refactoring step at a time.

## Workflow

1. **Understand** - Read the target code and its tests thoroughly
2. **Baseline** - Run existing tests to establish a passing baseline
3. **Plan** - Identify specific refactoring opportunities (list them before acting)
4. **Execute** - Apply refactorings one at a time
5. **Verify** - Re-run tests after each change to catch regressions immediately
6. **Report** - Summarize what changed and why

## Refactoring Patterns

Apply only what's needed:
- **Extract function** -- long function into smaller, named pieces
- **Rename** -- unclear names to descriptive ones
- **Remove duplication** -- consolidate repeated code
- **Simplify conditionals** -- flatten nested if/else, use early returns
- **Reduce parameters** -- group related params into structs/objects
- **Split file** -- large files into focused modules
- **Remove dead code** -- unused functions, unreachable branches

## Constraints

- Do NOT add features
- Do NOT change public APIs unless explicitly requested
- Do NOT refactor code that has no tests (flag it and ask first)
- Keep changes minimal and focused

## Report

```
## Refactor Report

**Target**: [what was refactored]
**Baseline Tests**: [pass/fail before changes]
**Final Tests**: [pass/fail after changes]

**Changes Made**:
- [refactoring 1]: [file] - [description]
- [refactoring 2]: [file] - [description]

**Behavior Preserved**: Yes/No
**Files Changed**: [count]
```
