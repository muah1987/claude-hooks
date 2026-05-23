---
description: Write comprehensive tests for specified code, functions, or modules
argument-hint: [file-path or module name to test]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Test

Write comprehensive tests for the specified `TARGET`.

## Variables

TARGET: $ARGUMENTS

## Instructions

- If no `TARGET` is provided, stop and ask the user what code to test.
- Analyze the target code to understand all functions, branches, and edge cases.
- Write tests that cover: happy path, error cases, edge cases, boundary conditions.
- Follow the project's existing test patterns and framework.

## Workflow

1. **Analyze Target** - Read the target file/module to understand all public functions and their contracts
2. **Identify Test Framework** - Look at existing tests to match the project's testing patterns
3. **Plan Coverage** - List every function, branch, and edge case that needs testing
4. **Write Tests** - Create test file(s) following existing conventions
5. **Verify** - Run the tests to ensure they compile/pass

## Test Design Principles

- Each test should test ONE behavior
- Test names should describe the expected behavior
- Use descriptive assertion messages
- Test boundary values (0, 1, MAX, empty, null)
- Test error conditions and invalid inputs
- Test state transitions (before/after)
- Avoid testing implementation details -- test the interface

## Report

```
## Test Report

**Target**: [what was tested]
**Test File**: [path to new test file]
**Coverage**:
- [N] test functions written
- [N] assertions total
- Functions covered: [list]
- Edge cases covered: [list]

**Run Command**: [how to execute the tests]
```
