---
description: Systematically debug an error, failing test, or unexpected behavior
argument-hint: [error message, file:line, or description of the issue]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Debug

Systematically investigate and fix the described `ISSUE`.

## Variables

ISSUE: $ARGUMENTS

## Instructions

- If no `ISSUE` is provided, stop and ask the user to describe the problem.
- Follow the debugging workflow below methodically. Do not guess -- gather evidence first.

## Workflow

1. **Reproduce** - Understand and reproduce the issue
   - Parse the error message or description
   - Identify the failing file, function, or test
   - Run the failing command/test to confirm the error

2. **Isolate** - Narrow down the root cause
   - Read the relevant source code
   - Trace the execution path from the error backward
   - Check recent changes (`git log --oneline -10`, `git diff`) for likely culprits
   - Look for related issues in surrounding code

3. **Diagnose** - Identify the root cause
   - Distinguish between the symptom and the actual bug
   - Verify your hypothesis by reading the code path
   - Check if the bug exists in other similar code paths

4. **Fix** - Apply the minimal correct fix
   - Make the smallest change that fixes the root cause
   - Do not refactor unrelated code
   - Do not add features

5. **Verify** - Confirm the fix works
   - Re-run the failing command/test
   - Check for regressions in related functionality
   - Verify the fix doesn't introduce new warnings

## Report

```
## Debug Report

**Issue**: [description]
**Root Cause**: [what actually caused the problem]
**Fix Applied**: [what was changed and why]
**Verification**: [how the fix was confirmed]
**Files Changed**:
- [file] - [what changed]
```
