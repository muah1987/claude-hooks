---
description: Implement the plan, then validate the result before reporting
argument-hint: [path-to-plan]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, LSP, ToolSearch
hooks:
  Stop:
    - hooks:
        - type: command
          command: >-
            $HOME/.local/bin/uv run
            $HOME/.claude/hooks/validators/validate_build.py
---

# Build

Implement `PATH_TO_PLAN`, validate the result, then report. Validation is **not optional** — never skip it.

## Variables

PATH_TO_PLAN: $ARGUMENTS

## Workflow

### 1. Load Plan
- If no `PATH_TO_PLAN` is provided, STOP and ask the user (AskUserQuestion).
- Read the full plan at `PATH_TO_PLAN`. Understand every step, acceptance criteria, and validation commands.
- Use **ToolSearch** to load schemas for deferred tools you'll need (e.g. `ToolSearch("select:LSP,AskUserQuestion")`).
- Seed **TodoWrite** with all tasks from the plan's "Step by Step Tasks" section. Mark each `in_progress` when starting, `completed` when done.

### 2. Implement
- Execute each step in order. Use **LSP** for code navigation in typed codebases (definitions, references, diagnostics) — faster and more accurate than grep.
- Use absolute file paths in all tool calls.
- Do not skip steps or merge unrelated changes.

### 3. Validate (MANDATORY — always run before reporting)

Run all of the following that apply to this project. Never skip a check just because "it probably works":

#### a) Plan Validation Commands
Run every command listed in the plan's `## Validation Commands` section. If the plan has none, note this and proceed to auto-detection.

#### b) Auto-detect and run checks

```bash
# Detect tech stack and run appropriate checks
CWD=$(pwd)

# Python
if ls "$CWD"/*.py "$CWD"/src/**/*.py 2>/dev/null | head -1 | grep -q py; then
  echo "=== Python: ruff/pyflakes ==="
  ruff check "$CWD" 2>/dev/null || python3 -m py_compile $(git diff --name-only HEAD | grep '\.py$') 2>&1 | head -20
fi

# TypeScript / JavaScript
if ls "$CWD"/package.json 2>/dev/null | head -1 | grep -q json; then
  echo "=== Node: lint + type-check ==="
  npm run lint --if-present 2>&1 | tail -20
  npm run type-check --if-present 2>&1 | tail -20 || npx tsc --noEmit 2>&1 | tail -20
fi

# Rust
if ls "$CWD"/Cargo.toml 2>/dev/null | grep -q toml; then
  echo "=== Rust: cargo check ==="
  cargo check 2>&1 | tail -30
fi

# Go
if ls "$CWD"/go.mod 2>/dev/null | grep -q mod; then
  echo "=== Go: build + vet ==="
  go build ./... 2>&1 | tail -20
  go vet ./... 2>&1 | tail -20
fi

# Tests (any language)
echo "=== Tests ==="
npm test --if-present 2>&1 | tail -30 || \
  python3 -m pytest --tb=short -q 2>&1 | tail -30 || \
  cargo test 2>&1 | tail -30 || \
  go test ./... 2>&1 | tail -30 || \
  true
```

#### c) LSP Diagnostics (typed codebases)

After edits, check for type errors and undeclared symbols:
```typescript
// Load LSP schema first
ToolSearch({ query: "select:LSP" })

// Check workspace diagnostics
LSP({ operation: "workspace_diagnostics" })
```

If diagnostics report errors, fix them before proceeding.

#### d) Acceptance Criteria Check
Read every item in the plan's `## Acceptance Criteria` section. For each one:
- State whether it is met: ✓ or ✗
- If ✗: fix the issue, re-run the relevant check, then re-verify

**Do not report success if any acceptance criterion is unmet.**

### 4. If Validation Fails
- Fix the issue in-place — do not skip or mark as "follow-up".
- Re-run the specific failing check(s).
- Only proceed to Report once all checks pass.
- If a check is broken (not your code, e.g. pre-existing test failure): document it explicitly in the Report as a pre-existing issue.

## Report

Present the plan's `## Report` section, then append:

```
## Validation Summary
- Checks run: <list of checks executed>
- Acceptance criteria: <N/N met>
- Test results: <pass/fail/skipped>
- Lint/type-check: <pass/fail/skipped>
- LSP diagnostics: <N errors, N warnings — or "clean">
- Pre-existing issues: <any failures that existed before this build, or "none">
```
