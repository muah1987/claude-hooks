---
description: Review code changes, PRs, or specific files for quality, bugs, and best practices
argument-hint: [file-path, PR-number, or 'staged' for staged changes]
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Code Review

Perform a thorough code review on the specified `TARGET`. Analyze for correctness, security, performance, and maintainability.

## Variables

TARGET: $ARGUMENTS

## Instructions

- If no `TARGET` is provided, review staged git changes (`git diff --cached`). If nothing is staged, review unstaged changes (`git diff`).
- If `TARGET` is a number, treat it as a PR number and use `gh pr diff TARGET` to get the diff.
- If `TARGET` is a file path, review that specific file.
- If `TARGET` is a directory, review all modified files in that directory.

## Workflow

1. **Gather Changes** - Get the diff or file contents based on TARGET
2. **Understand Context** - Read surrounding code to understand the change in context
3. **Analyze** - Review each change against the checklist below
4. **Report** - Provide findings organized by severity

## Review Checklist

### Correctness
- Logic errors, off-by-one, null/undefined handling
- Edge cases not covered
- Error handling gaps
- Race conditions or concurrency issues

### Security
- Input validation (SQL injection, XSS, command injection)
- Authentication/authorization gaps
- Sensitive data exposure (secrets, PII in logs)
- OWASP Top 10 violations

### Performance
- N+1 queries, unnecessary loops
- Missing indexes, unoptimized queries
- Memory leaks, unbounded growth
- Missing caching opportunities

### Maintainability
- Code clarity and naming
- Dead code or unused imports
- Missing or misleading comments
- Overly complex logic that could be simplified

### Testing
- Test coverage for new/changed code
- Edge cases in tests
- Test quality (not just line coverage)

## Report

```
## Code Review

**Target**: [what was reviewed]
**Verdict**: ✅ Approve | ⚠️ Approve with suggestions | ❌ Changes requested

### Critical Issues (must fix)
- [issue]: [file:line] - [description]

### Warnings (should fix)
- [issue]: [file:line] - [description]

### Suggestions (nice to have)
- [suggestion]: [file:line] - [description]

### Positive Notes
- [what's done well]
```
