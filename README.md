# Build a Token‑Efficient Hook Automation System for Claude Code (v13)

## Summary of Changes from v12

| Area | v12 | v13 |
|------|-----|-----|
| **Limit‑data source** | Claimed hook stdin contains `context_window`/`rate_limits`; `limit-collector.sh` wrote `limits.json` | **Corrected**: statusline receives these fields; `statusline.sh` writes `limits.json`; `limit-collector.sh` removed |
| **`if` condition syntax** | Described as regex matching tool call string | Reverted to **permission‑rule syntax** (official format, e.g., `Bash(git *)`, `Edit(*.ts)`) |
| **`format.sh` registration** | Placed on `PreToolUse` in `settings.json` example | Moved to **`PostToolUse`** (format after write) |
| **`limit-bridge.sh` wiring** | Specified but never registered | Added to **`UserPromptSubmit`** to inject tier directives and async validator results |
| **Stop‑hook blocking mechanism** | Claimed `Stop` hooks block only via JSON `decision: "block"` | Corrected: `exit 2` also blocks; clarified JSON processed only on `exit 0` |
| **PostToolUse blocking** | Claimed `exit 2` blocks (contradicts docs) | Corrected: `PostToolUse` cannot block tool execution; `decision: "block"` can prompt Claude |
| **PermissionDenied retry shape** | Bare `{"retry":true}` | Changed to **official shape**: `{"hookSpecificOutput":{"retry":true}}` |
| **`limits.json` values** | Stored `used` counts (only percentages if limit=100) | Store **`used_percentage`** directly (sourced from statusline input) |
| **Manifest path** | Inconsistent: `state/.../manifest-...json` vs `state/.../manifests/` | Unified to **`state/<project-key>/manifests/`** |
| **Dynamic‑context validation** | Contradictory: skip vs block on missing/malformed block | Clarified: file **absent** → skip; file present but extraction fails or JSON invalid → **block** |
| **Secrets loading** | `source .env` (runs arbitrary shell) | Safer: parse `KEY=VALUE` lines, reject dangerous patterns, export only whitelisted names |
| **Async validator execution** | Launched via `asyncRewake` from script (invalid) | Background processes write results; `limit-bridge.sh` injects them on next `UserPromptSubmit` |

---

# Full v13 Specification

## Executive Summary

This document specifies a **user‑level automation layer** (`~/.claude/`) for Claude Code that intercepts deterministic tasks—formatting, linting, validation, indexing—and executes them via local scripts instead of LLM tool calls. It is token‑efficient, injecting only compact structured reports (≤500 tokens) back into the model's context.

The system is designed for a **single installation that must serve every project**, regardless of language, stack, or deployment target. All project‑specific behaviour is resolved at runtime through a layered configuration mechanism (global defaults + per‑project overlays) and **dynamic, LLM-maintained context files**. Success is measured by fewer round trips, smaller context injections, and zero regressions across all projects—including those that do not yet exist.

---

## 1. Ground Rules (Read Before Implementing)

1.  **Native Hook System**: Use Claude Code's official hook system exclusively. Hooks reside in `~/.claude/settings.json` (user‑level). All scripts live under `~/.claude/hooks/`. **Do not** invent a custom event bus or place hook logic inside individual repositories.
2.  **Official Reference**: Consult the hooks documentation for the current event list, stdin JSON schema, and output protocol before building. The event set may change between versions—do not rely on memory.
3.  **Script Invocation**: Every hook entry must invoke a script in `~/.claude/hooks/`. No inline logic in `settings.json` beyond the script path. Scripts are the unit of testing and reuse.
4.  **Hook Protocol Compliance**:
    - Scripts read a single JSON object from stdin.
    - **Exit codes**:
      - `0` = proceed; any JSON on stdout is processed.
      - `1` = non‑blocking error (stderr shown as warning).
      - `2` = block (for most events). For `Stop`, `exit 2` also blocks. For `PostToolUse`, `exit 2` only shows stderr (tool already ran).
    - **Structured control**: Use JSON on stdout.
      - For `PreToolUse`, use `permissionDecision` with `decision`/`reason`.
      - For `Stop`, use `decision`/`reason` with `"block"`.
      - For `additionalContext`, use the `hookSpecificOutput` wrapper.
      - **Important**: JSON is **only processed when the script exits with 0**. If you set `exit 2`, any JSON you printed is discarded. Choose one signalling method per hook.
5.  **Token Discipline**:
    - Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr.
    - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`.
    - Only a summary report is returned to the model, **capped at 500 tokens** (~2 000 characters). If results exceed that, summarize counts and include the log file path for on‑demand retrieval.
6.  **Performance**: `PreToolUse` hooks gate matched tool calls—target **< 500 ms**. Slower operations (test suites, indexing) belong on `PostToolUse`, `Stop`, or run with `"async": true`.
7.  **Chaining**: Chaining is not native. Implement it inside a script (Script A calls Script B) or via a shared state file. Document each chain explicitly.
8.  **Safety**: Never auto‑approve destructive operations. `PreToolUse` may auto‑allow **only** an explicit allowlist of read‑only or idempotent commands.
9.  **Loop Guard**: Any `Stop` hook must check the `stop_hook_active` field in the stdin JSON and `exit 0` when `true`.
10. **Audit Before Build**: Inventory existing hooks/scripts in `~/.claude/settings.json`, `~/.claude/hooks/`, and project‑level `.claude/settings.json`. **Upgrade or retire** every existing user‑level item to meet these standards. Document each in `MIGRATION.md`. Do not run old and new conventions side‑by‑side.
11. **Zero Hardcoded Values**:
    - **Paths**: Derive everything from stdin (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`. The only permitted absolute anchor is `$HOME/.claude/...`. Never use literal `/home/<user>/`.
    - **Project specifics**: Discover at runtime (e.g., from `package.json`, `Makefile`, `pyproject.toml`). Formatters/linters are detected per project; if none exist, the hook no‑ops silently. Default branch is read from `git symbolic-ref refs/remotes/origin/HEAD` (fallback to `git remote show origin` then `git symbolic-ref --short HEAD`)—never assumed to be `main`.
    - **Tunables**: Every threshold, cap, timeout, and allowlist lives in config—scripts read config, never embed numbers.
    - **Dynamic API**: Field names are read defensively. Missing/renamed fields degrade gracefully rather than crashing.
    - **Portability**: All scripts must run on macOS and Linux (and Windows via WSL/Git Bash) without modification. Use POSIX‑compliant constructs or `#!/usr/bin/env bash`.
12. **Layered Configuration**:
    - **Global Defaults**: `~/.claude/hooks/config.json`.
    - **Project Overlay**: `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json`. Deep-merged over global defaults for static lists/thresholds.
        - **Merge Rules**: Scalars replaced; lists replaced unless `_append` suffix (then concatenated and deduplicated); nested objects recursively merged (overlay subtree replaces global subtree for that key).
    - **Dynamic Context**: Changing project data (DOM selectors, API endpoints) lives in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md` (see Section 3.2). **Dynamic overrides are strictly limited to the `"validation"` subtree** of the merged config for security reasons. If this file or its parent directory does not exist, the system falls back to global defaults and skips remote validation (code‑level checks only).
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
    - **Secrets**: Stored in the project's `.env`; load safely by parsing `KEY=VALUE` lines, rejecting anything containing `$()`, backticks, or `;`, and exporting only the variable names whitelisted in `config.json`. Never logged, never injected.
13. **Security & Sandboxing**: Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. Mandatory practices:
    - Quote all shell variables (`"$VAR"`).
    - Use the `args` field (exec form) to avoid shell injection when handling user‑provided paths.
    - Validate JSON inputs with `jq --exit-status` before parsing.
    - Sanitize inputs (strip `..`, `~`, control characters).
    - Use `if` conditions to pre‑filter hooks (permission‑rule syntax).
    - Set a `timeout` on every hook.
    - All state file writes must be atomic: write to a temporary file (e.g., `file.tmp`) then `mv` to the final name.

---

### 1.1 Input JSON Schema (from Claude Code – Hook Events)

Hook scripts receive a JSON object with at least the following fields (additional fields may exist). The exact schema varies by event and Claude Code version.

**Important**: Hook input **does not** include `context_window` or `rate_limits` fields. Those are only provided to the **statusline** command (see Section 1.2). This specification corrects a widespread misconception.

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "git push --force" },
  "cwd": "/home/user/project",
  "session_id": "abc-123",
  "transcript_path": "/path/to/transcript.jsonl",
  "stop_hook_active": false
  // No context_window or rate_limits here
}
```

**Note on `cwd` vs `$CLAUDE_PROJECT_DIR`**:
- `cwd` is the current working directory **where the tool was invoked** (may be a subdirectory).
- `$CLAUDE_PROJECT_DIR` is an environment variable set by Claude Code to the **project root** (the directory containing `.claude/`).
Use `$CLAUDE_PROJECT_DIR` for project‑relative configuration and state locations; use `cwd` for operations that depend on the user's current location.

---

### 1.2 Statusline Input Schema (Official)

The statusline command receives a **different JSON schema** than hook scripts. It **does** include usage metrics.

```json
{
  "hook_event_name": "Status",
  "session_id": "abc123...",
  "transcript_path": "/path/to/transcript.json",
  "cwd": "/current/working/directory",
  "model": { "id": "claude-opus-4-1", "display_name": "Opus" },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/path/to/project"
  },
  "version": "1.0.80",
  "output_style": { "name": "default" },
  "cost": { "total_cost_usd": 0.01234 },
  "context_window": {
    "used_percentage": 42,
    "context_window_size": 200000,
    "current_usage": 84000
  },
  "exceeds_200k_tokens": false,
  "rate_limits": {
    "five_hour": { "used_percentage": 30, "resets_at": "2026-07-14T15:00:00Z" },
    "seven_day": { "used_percentage": 45, "resets_at": "2026-07-18T00:00:00Z" }
  }
}
```

**Version notes**:
- `rate_limits` may be absent for non‑Pro/Max plans or older versions.
- The schema is subject to change; scripts must handle missing fields gracefully (show "n/a").

---

### 1.3 Report Contract (Summary)

Every script that returns information to the model emits JSON with exactly these fields:

```json
{
  "hook": "post-edit-format",
  "status": "ok | warn | blocked | error",
  "summary": "One sentence, human-readable.",
  "details": { "files_changed": 3, "errors": 0 },
  "log": "~/.claude/hooks/logs/myproject-a1b2c3/post-edit-format-2026-07-14T10:22:03.jsonl",
  "duration_ms": 142
}
```

`details` holds counts and short identifiers only—never file contents, stack traces, or diffs. The total token count of the entire JSON must not exceed 500 tokens.

**Which hooks produce a report and update `last_status.json`**: `format.sh`, `finish.sh` (on `Stop`), and any additional hooks that emit a summary JSON. Hooks that only block via exit code (e.g., `guards.sh`) or that are purely logging (`error-recovery.sh`, `compact-monitor.sh`) do **not** produce a report and therefore do **not** update `last_status.json`.

---

### 1.4 `additionalContext` Injection Format (Official)

To inject context into the model, output the following JSON to stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "Your context text here (≤500 tokens)"
  }
}
```

The `hookEventName` must match the event that triggered the hook. This is the **official format** documented in the hooks reference.

---

### 1.5 PermissionDenied Retry Protocol (Official)

For the `PermissionDenied` event specifically, to trigger a retry for a denied tool call, the hook must print:

```json
{
  "hookSpecificOutput": {
    "retry": true
  }
}
```

to stdout. This is the **only control surface** for retrying denied tool calls. **Version note**: This requires Claude Code **v2.1.88 or later**. On earlier versions, the `PermissionDenied` event and retry response are not available.

---

### 1.6 `if` Condition Syntax

The `if` field in a hook entry uses **permission‑rule syntax** as documented in the official hooks reference. It is **not** a regex. Valid examples:

- `Bash(git *)` – matches Bash commands starting with `git`
- `Edit(*.ts)` – matches edits on `.ts` files
- `Write(*.env)` – matches writes to `.env` files
- `Bash(git push --force)` – matches exact command

The rule is evaluated by Claude Code's permission system; if the rule cannot be parsed, the hook **fails open** (the hook does not run). Therefore, a security guard script **must re‑check** the full command and cannot rely solely on `if` for protection.

---

### 1.7 Last Report Status State File

Every hook script that produces a report (per the list in Section 1.3) **must** also write its `status` and `summary` to a shared state file:

`~/.claude/hooks/state/<project-key>/last_status.json`

Content:

```json
{
  "hook": "format",
  "status": "ok",
  "summary": "Formatted 3 files",
  "timestamp": "2026-07-14T10:22:03Z"
}
```

This file is read by the statusline to display the last report status.

---

### 1.8 `limits.json` Format

The **statusline script** writes to `state/<project-key>/limits.json` with the following structure (sourced from its own stdin):

```json
{
  "context_used_percentage": 42,
  "five_hour_used_percentage": 30,
  "seven_day_used_percentage": 45,
  "five_hour_resets_at": "2026-07-14T15:00:00Z",
  "seven_day_resets_at": "2026-07-18T00:00:00Z",
  "timestamp": "2026-07-14T10:22:03Z"
}
```

- `context_used_percentage`: integer from `context_window.used_percentage`
- `five_hour_used_percentage`: from `rate_limits.five_hour.used_percentage` (or `null`/`"n/a"` if unavailable)
- `seven_day_used_percentage`: same for seven‑day
- Resets timestamps if available
- `timestamp`: ISO‑8601 timestamp of the write

All writes must be atomic (write to `limits.tmp` then `mv`).

---

## 2. System Architecture

The following diagram illustrates the data flow. The implementation must match this wiring exactly.

```
                        ┌─────────────────────────── Claude Code (any project) ───────────────────────────┐
                        │                                                                                  │
 EVENTS                 │  SessionStart · Setup · UserPromptSubmit · PreToolUse · PostToolUse · Stop       │
                        │  + StopFailure · PostToolUseFailure · PostToolBatch · PreCompact · PostCompact  │
                        │  + PermissionRequest · PermissionDenied · MessageDisplay                         │
                        │  + SubagentStart/Stop · TaskCreated/Completed · TeammateIdle                     │
                        │  + InstructionsLoaded · ConfigChange · CwdChanged · FileChanged                  │
                        │  + WorktreeCreate/Remove · Elicitation/ElicitationResult                        │
                        └───────┬───────────────┬────────────────┬─────────────┬──────────────┬───────────┘
                                │ stdin JSON    │                │             │              │
                                ▼               ▼                ▼             ▼              ▼
                        ┌──────────────────────── ~/.claude/hooks/ (user level, all projects) ────────────┐
 HOOK SCRIPTS           │  context.sh      limit-bridge.sh   guards.sh     format.sh      finish.sh       │
                        │  (Injects     ◄─┐ (reads state,    (bash guard,  (PostToolUse:  (tests +        │
                        │   directive to  │  injects tier    protected     format after   dynamic         │
                        │   update        │  directives,     paths)        write)         validators +   │
                        │   context.md)   │  and async       (PreToolUse)   index.sh      repo-tidy,      │
                        │                 │   results)                      (async)        branches on     │
                        │                 │  (UserPromptSubmit)             manifest.sh    hook_event_name)│
                        │                 │  + async results injection)    (track writes  (async support) │
                        │                 │                                 & edits)                       │
                        └───────┬───────┼──────────┬──────────────┬─────────────┬──────────────┬──────────┘
                                │       │          │              │             │              │
                                ▼       │          ▼              ▼             ▼              ▼
 SHARED LIB             ┌  lib/: config-loader · context-extractor.sh · report.sh · logging helpers       │
                        └───────┬──────────────────────────────────────────────────────────────┬──────────┘
                                │                                                              │
                                ▼                                                              ▼
 CONFIG & CONTEXT       global: ~/.claude/hooks/config.json          overlay: $PROJECT/.claude/hooks/config.json
                        (defaults: tiers, retention, patterns,      (static overrides, keep-list,
                         test_command, test_timeout,                validation.file_map)
                         validator_async_threshold_seconds)
                                │                        secrets: $PROJECT/.env
                                │                        DYNAMIC: $PROJECT/.claude/validator_context.md
                                ▼
 STATE & OUTPUT         ~/.claude/hooks/state/<project-key>/   logs/<project-key>/   trash/<project-key>/
                                ▲          │                          ▲                      ▲
                                │          │ read                     │ full output          │ scratch files
                                │          ▼                          │                      │ (7-day purge)
 STATUSLINE             statusline.sh ── writes limits.json from its own stdin ──┐
                        (also reads last_status.json for display)                │
                        **Output to stdout** (per official protocol)             │
                                │          ▲                                     │
                                │          │ reads                                │
                                ▼          │                                     │
 LIMIT BRIDGE           limit-bridge.sh ──┘ (reads limits.json, last_status)     │
 (UserPromptSubmit)      injects tier warnings/directives; also injects pending  │
                         async validator results from state file                 │
                                                                                 │
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets    │
 (Stop hook, using      parameters extracted from `<validator-targets>` JSON     │
  filtered by validation.file_map and changed files, with async support)         │
                         (slow validators run in background; write results to    │
                          state/pending_validator_results.json)                  │
                                │                                                 │
                                ▼                                                 │
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

**Key architecture notes**:
- `statusline.sh` **writes** `limits.json` from its stdin and **reads** `last_status.json` for display.
- `limit-bridge.sh` (on `UserPromptSubmit`) **reads** `limits.json` to know when to inject tier directives, and also reads `pending_validator_results.json` to inject async validator results.
- `finish.sh` branches on `hook_event_name`: on `Stop` it runs tests+validators; on `SessionEnd` it runs repo tidiness.
- Validators are filtered by `validation.file_map` (static overlay) against the list of changed files from the session manifest.
- Slow validators (estimated runtime > `validator_async_threshold_seconds`, default 15) run as background processes; their results are written to `state/<project-key>/pending_validator_results.json` and injected on the next `UserPromptSubmit` by `limit-bridge.sh`.

---

## 3. Configuration & Project Layering

### 3.1 Global Defaults & Static Overlay (`config.json`)

Contains defaults for all tunables:
- **Limits**: Context window (60 %/75 %/85 %), Session (60 %/75 %/90 %), Weekly (70 %/85 %/95 %).
- **Retention**: `logs_days` (14), `state_days` (60), `screenshots_days` (7), `trash_days` (7), size cap per namespace (100 MB).
- **Protected paths**: `.env*`, `*.pem`, `/etc/passwd`, etc.
- **Scratch patterns**: `*.tmp`, `scratch*`, `debug_*`, `test_output*`, `*.bak`, `tmp_*`.
- **Validator timeouts**: e.g., 30 s for VPS, 15 s for HTTP.
- **Janitor interval**: `janitor_interval_hours` (24).
- **Auto‑approve list** (for `PermissionRequest`): read‑only commands, idempotent operations (e.g., `git status`, `ls`, `cat` on non‑sensitive files).
- **`validation.file_map`**: Optional object mapping glob patterns to target names (e.g., `{ "src/**/*.js": "web", "api/**/*.py": "api" }`). If present, validators run only for targets whose glob matches at least one changed file in the session. If absent, all configured targets run.
- **`test_command`**: Optional string (e.g., `"npm test"`, `"pytest"`, `"make test"`). If not set, the system attempts discovery via heuristics (check `package.json` for `"test"` script, look for `pytest.ini`, `Makefile` with `test` target). If no command is found, tests are skipped.
- **`test_timeout`**: Timeout in seconds for the test command (default 60).
- **`validator_async_threshold_seconds`**: If a validator's estimated runtime exceeds this value (default 15), it runs asynchronously. Estimation can be based on the target type (e.g., VPS/SSH may be slower) or a static config override.
- **`secrets_whitelist`**: Array of environment variable names that may be exported from `.env` (e.g., `["DB_PASSWORD", "API_KEY"]`). Only these are exported; all others are ignored.

A complete example `config.json` with all keys and comments is provided in the deliverables.

---

### 3.2 Dynamic Context: The Living Document

Because a project grows dynamically, validators cannot rely on static endpoints or DOM selectors. If a project requires external validation, Claude will be instructed to maintain a living document at `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.

**The Hybrid Format:**
This document acts as a scratchpad for Claude to document architectural logic, but it **must** contain a strictly formatted JSON block enclosed in `<validator-targets>` tags for the automation scripts to parse.

**Extraction Logic**: Use a POSIX‑compliant `awk` state machine to extract content between the opening and closing tags (avoid `perl` for portability). The extracted text must be validated with `jq`.

**Validation and Blocking Rules**:
- If the file **does not exist** or the `<validator-targets>` block is missing → **skip remote validation** (log warning, continue).
- If the block exists but extraction fails or `jq` rejects it → **block the Stop** with a clear error message instructing Claude to fix the syntax.
- If the file exists and JSON is valid → merge and proceed.

**Merge Rules for Dynamic Context**:
The extracted JSON is **only merged into the `"validation"` subtree** of the merged static configuration. This prevents Claude from overriding security‑critical keys like `protected_paths`. Within that subtree, the merge follows the standard rules: scalars replaced, lists replaced (unless `_append` suffix), nested objects recursively merged.

**Example `$PROJECT/.claude/validator_context.md`:**

```markdown
# Project Validation Context
This document tracks the current live targets for the validation hooks.

* The login button was changed to `#auth-submit` on Tuesday.
* The API health check moved to `/api/v2/health`.

<validator-targets>
{
  "web": {
    "login_selector": "#auth-submit",
    "health_endpoint": "/api/v2/health"
  },
  "api": {
    "base_url": "http://localhost:3000",
    "schema_path": "./docs/openapi.yaml"
  }
}
</validator-targets>
```

---

### 3.3 Official `settings.json` Structure

The user‑level `~/.claude/settings.json` follows this exact structure:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/guards.sh",
            "timeout": 5,
            "if": "Bash(rm -rf) || Bash(git push --force)"
          }
        ]
      },
      {
        "matcher": "Read|Edit|Write",
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/guards.sh", "timeout": 5 }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/format.sh", "timeout": 30 },
          { "type": "command", "command": "~/.claude/hooks/manifest.sh", "async": true, "timeout": 5 },
          { "type": "command", "command": "~/.claude/hooks/index.sh", "async": true, "asyncRewake": true, "timeout": 30 }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/limit-bridge.sh", "timeout": 5 }
        ]
      }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/finish.sh", "timeout": 120 }] }
    ],
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/context.sh", "timeout": 10 },
          { "type": "command", "command": "~/.claude/hooks/janitor.sh", "async": true, "timeout": 60 }
        ]
      }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/finish.sh", "timeout": 30 }] }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "~/.claude/hooks/statusline.sh"
  }
}
```

**Key points**:
- `matcher` supports regular expressions (e.g., `Edit|Write`, `Read|Edit|Write`)
- Events without matchers (`Stop`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`) omit the `matcher` field
- `timeout` is specified in **seconds** on each hook entry
- `async: true` runs the hook in the background without blocking Claude
- `asyncRewake: true` (implies `async`) wakes Claude on exit code 2, showing stderr as a system reminder
- `if` condition: **permission‑rule syntax** (official) – see Section 1.6
- **Exec form** (no shell): use `args` field to avoid injection risks (e.g., `"args": [".", "/path/to/file.json"]`)

---

### 3.4 Secrets Loading

For scripts that need environment variables (validators), load the project’s `.env` safely:

```bash
# Load only whitelisted variables, reject dangerous content
load_env() {
  local env_file="$CLAUDE_PROJECT_DIR/.env"
  [[ -f "$env_file" ]] || return 0
  while IFS='=' read -r key value; do
    [[ -z "$key" ]] && continue
    # Reject lines containing command substitution or semicolons
    if [[ "$value" =~ \$\( ]] || [[ "$value" =~ \` ]] || [[ "$value" =~ ; ]]; then
      echo "Warning: .env line contains dangerous pattern, skipped: $key" >&2
      continue
    fi
    # Export only if in whitelist
    if [[ " ${SECRETS_WHITELIST[@]} " =~ " ${key} " ]]; then
      export "$key=$value"
    fi
  done < "$env_file"
}
```

The whitelist is read from `config.json` (`secrets_whitelist`). This prevents arbitrary code execution from a compromised repo.

---

## 4. Hook Script Specifications

### 4.1 Hook Type Comparison (Official)

| Type | Description | LLM Cost | Use Case |
|------|-------------|----------|----------|
| **Command** | Shell script execution | None | Deterministic tasks (formatting, guards, validation) |
| **HTTP** | HTTP endpoint call with event data | None | Remote orchestration, webhooks |
| **MCP Tool** | Call a tool on an MCP server | Tokens per response | Providing additional external contextual state |
| **Prompt** | LLM evaluates a prompt to decide | LLM tokens per call | Complex decision‑making requiring understanding |
| **Agent** | Multi-turn verification with tool access (experimental) | High LLM compute | Complex multi-step task delegation |

**This system uses Command hooks exclusively**—they are deterministic, have no LLM cost, and are the most predictable for automation.

---

### 4.2 Initial Hook Set (v13)

| Event | Matcher | Script | Purpose | Blocking | Timeout (s) | Notes |
|---|---|---|---|---|---|---|
| `PostToolUse` | `Write\|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain. | No (tool already ran) | 30 | **Corrected**: placed on PostToolUse |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to default branch). | Yes (`exit 2`) | 5 | Use `if` to reduce spawns |
| `PreToolUse` | `Read\|Edit\|Write` | `guards.sh` | Deny access to `.env*`, keys, and protected paths. | Yes (`exit 2`) | 5 | |
| `UserPromptSubmit` | — | `limit-bridge.sh` | Reads `limits.json`; injects tier warnings/directives; injects async validator results. | No | 5 | **Newly wired** |
| `Stop` | — | `finish.sh` | Run tests + dynamic validators (filtered by `validation.file_map` and changed files). Block if failures. Slow validators run async. | Yes (`exit 2` or JSON) | 120 | Branches on `hook_event_name` |
| `StopFailure` | — | `error-recovery.sh` | Log API error details; no blocking. | No | 5 | |
| `PostToolUseFailure` | `Write\|Edit` | `error-recovery.sh` | Log write failure. | No | 5 | |
| `PostToolBatch` | — | `error-recovery.sh` | Log batch completion. | No | 5 | |
| `PreCompact` | — | `compact-monitor.sh` | Update state with pre‑compact percentages. | No | 5 | |
| `PostCompact` | — | `compact-monitor.sh` | Update state after compaction; log token savings. | No | 5 | |
| `SessionStart` | — | `context.sh` | Inject compact project context AND directive to update `.claude/validator_context.md`. | No | 10 | |
| `SessionStart` (async) | — | `janitor.sh` | Retention‑based cleanup of own logs/state/trash. | No | 60 | |
| `PostToolUse` (async) | `Write\|Edit` | `manifest.sh` | Record files *created* or *modified* by Claude this session. Newly created files are candidates for quarantine; edits are not. | No | 5 | Matcher fixed to `Write\|Edit` |
| `SessionEnd` | — | `finish.sh` | **Repo tidiness**: classify manifest entries as scratch, quarantine, report count. | No | 30 | Branches on `hook_event_name` |
| `PostToolUse` (async) | `Write\|Edit` | `index.sh` | Update project index/dependency graph in background. | No | 30 | `asyncRewake: true` |
| **Optional** `PermissionRequest` | `Bash` | `permission-helper.sh` | Auto‑allow read‑only/idempotent commands from allowlist. | Yes (`permissionDecision`) | 5 | |
| **Optional** `PermissionDenied` | `Bash\|Write\|Edit` | `retry-handler.sh` | If denied, optionally retry (via `hookSpecificOutput.retry: true`). Requires v2.1.88+. | No (output ignored) | 5 | |

**Statusline** (not a hook) configured as `statusLine` entry.

---

### 4.3 Events Not Included in This System

| Event | Justification for Exclusion |
|-------|----------------------------|
| `Setup` | Single-use init only; not needed. |
| `UserPromptExpansion` | Too early; adds latency. |
| `MessageDisplay` | Fires per message; excessive overhead. |
| `SubagentStart` / `SubagentStop` | Subagent workflows out of scope for v1. |
| `TaskCreated` / `TaskCompleted` | Task lifecycle managed separately. |
| `TeammateIdle` | Agent Team not used. |
| `InstructionsLoaded` | Already handled by `SessionStart`. |
| `ConfigChange` / `CwdChanged` / `FileChanged` | Complexity; file changes tracked via `manifest.sh`. |
| `WorktreeCreate` / `WorktreeRemove` | Not used. |
| `Elicitation` / `ElicitationResult` | MCP elicitation out of scope. |

**Plugin hooks**: Coexist without modification; they are auto‑merged.

**MCP tool hooks**: Out of scope for v1.

---

## 5. Context‑Aware Validation (Dynamic)

Code‑level checks are insufficient—validation must extend to the running system (VPS, email, web app, etc.).

### 5.1 The `SessionStart` Directive

The `context.sh` hook must inject the following strict directive via `additionalContext` when a session starts:

> *"If you modify core architectural elements, API endpoints, or UI selectors during this session, you MUST update the JSON block inside the `<validator-targets>` tags in `.claude/validator_context.md` before stopping. The JSON must be valid and enclosed exactly as shown. Only the `validation` subtree of the configuration can be overridden."*

### 5.2 Validator Execution (`finish.sh` Stop Hook)

When Claude attempts to stop, the `finish.sh` script handles dynamic validation via these steps:

1. **Extract**: Use a POSIX `awk` state machine to extract the JSON block between `<validator-targets>` and `</validator-targets>`.
   - If the file does not exist or the block is missing → **skip remote validation** (log warning, continue to code‑level tests only).
   - If extraction fails (e.g., no closing tag) → **block** with message: *"validator_context.md missing closing </validator-targets> – please fix."*
2. **Validate**: Pipe extracted text through `jq --exit-status .`; if invalid → **block Stop** with message: *"validator_context.md contains malformed JSON – please fix and try again."*
3. **Merge**: Deep‑merge the dynamic JSON **only into the `"validation"` subtree** of the static config (per merge rules). This yields the final validation configuration.
4. **Filter targets**:
   - Read the session manifest (`state/<project-key>/manifests/manifest-<session-id>.json`) to get the list of files created or modified.
   - If `validation.file_map` exists in the merged config, for each target, check if any changed file matches its glob pattern. Only those targets are run.
   - If no `file_map` exists, run all targets that have keys in the dynamic JSON.
   - If no targets remain, skip remote validation entirely (only code‑level checks).
5. **Execute tests** (if a test command is found, run it with timeout; if it fails, block with failure reason).
6. **Execute validators**:
   - For each target, estimate runtime. If > `validator_async_threshold_seconds`, launch in background and store a pending state in `state/<project-key>/pending_validator_results.json` (with `status: "pending"`). Otherwise, run synchronously in parallel with timeouts.
   - Wait for synchronous validators. If any fail, block stop.
   - For async validators, the background process writes its result (status, summary) to `pending_validator_results.json` when complete. On the next `UserPromptSubmit`, `limit-bridge.sh` will read this file, inject the results as `additionalContext`, and clear the entry.
7. **Block** if any synchronous validator fails: return JSON `decision: "block"` or `exit 2` with a summary of failures. Both work; choose one.

---

### 5.3 Validator Scripts (`~/.claude/hooks/validators/`)

- One script per target type (`vps.sh`, `email.sh`, `web.sh`, `api.sh`, `db.sh`).
- **Safety**: Read‑only against production by default; mutating probes target sandbox resources exclusively. Secrets from `.env` never logged.
- **`--test` mode**: Accepts mocked responses (fixtures) to test offline, including a "target unreachable" fixture (reports `error`, does not hang, respects timeout).

### 5.4 Validator Target Types (Implement Once)

- **VPS/Server**: SSH to verify artifact version/checksum, service status, ports, disk/memory, recent logs for errors.
- **Email**: Send probe to test recipient; verify delivery, SPF/DKIM/DMARC, no unintended recipients.
- **Web**: Headless browser (Playwright) to check key pages, console errors, network requests, critical flows; screenshots saved to logs.
- **API**: Probe endpoints for status, schema, auth behaviour.
- **Database**: Read‑only connectivity, migration version, row‑count sanity.

---

## 6. Statusline & Limit Monitoring (Correct Architecture)

The statusline is **not a hook** – it is a separate `statusLine` command configured in `~/.claude/settings.json`. It receives `context_window` and `rate_limits` in its stdin and is the **sole producer** of `limits.json`.

### 6.1 Limit Data Flow (Correct Architecture)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  statusline.sh  │ ──► │ writes limits   │ ──► │ limits.json     │
│  (receives      │     │ .json (atomic,  │     │ (state file,    │
│   context_window│     │  from its stdin)│     │  read by others)│
│   + rate_limits)│     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
       │                                                   │
       │ display to stdout                                 │
       ▼                                                   ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Terminal       │     │  limit-bridge   │ ──► │ reads limits    │
│  output         │     │  .sh (on        │     │ .json, injects  │
└─────────────────┘     │  UserPromptSubmit)     │ tier directives │
                        └─────────────────┘     └─────────────────┘
```

### 6.2 `statusline.sh` – Collector and Display

- Invoked by Claude Code on every refresh. Refresh triggers:
  - After each assistant message
  - After `/compact` completes
  - When permission mode changes
  - Claude applies a built‑in **300 ms debounce** – you cannot control this.
- Reads the statusline JSON from stdin (official schema: `model`, `workspace`, `cost`, `context_window`, `rate_limits`).
- **Writes** `state/<project-key>/limits.json` with the values from its stdin (atomic write, throttled? Not needed because statusline is called frequently but we can still throttle to avoid excessive writes; but the spec says "write throttle" is not required for statusline because it's not as frequent? Actually it's every refresh, which may be often; we can still throttle to ≤ once per 5s to reduce I/O. We'll add that.)
- **Reads** `state/<project-key>/last_status.json` for the last report status.
- Derives branch and dirty count from `git` using `cwd` (fallback to `n/a`). Use `git symbolic-ref --short HEAD` for branch, `git status --porcelain` for dirty count.
- Prints its display to **stdout** (per official protocol). The display should include:
  - Current model name
  - Branch + dirty‑file count (e.g., `main*`)
  - Last report status with colour (green/ok, yellow/warn, red/error)
  - Three percentages with tiered colour coding (🟡 / 🟠 / 🔴)
- **Performance**: Target < 100 ms. If state files are missing/stale, display placeholders (`n/a`). Never throw errors.

### 6.3 Limit Tiers & Bridge Hook (`limit-bridge.sh`)

| Limit | Notice (🟡) | Warning (🟠) | Action (🔴) |
|---|---|---|---|
| Context window | 60 % | 75 % | 85 % |
| Session (5‑hour) usage | 60 % | 75 % | 90 % |
| Weekly usage | 70 % | 85 % | 95 % |

- **Notice**: Statusline colour change only.
- **Warning**: Statusline change + **one‑time** `additionalContext` line (≤50 tokens) from `limit-bridge.sh` (triggered on `UserPromptSubmit`). Dedupe via `state/<project-key>/limit_alerts.json`.
- **Action**: `limit-bridge.sh` injects a high‑priority wind‑down directive via `additionalContext`; logs the event; statusline turns red. For plan limits, instructs Claude to reach a clean stopping point.
- **Auto‑compact**: The hook system does **not** set this; users should set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in their environment. The README will recommend this.
- **Fallback**: If `rate_limits` data is unavailable (older Claude Code version or plan without it), degrade to context‑only monitoring; show "n/a" for others; never crash or block.

### 6.4 Async Validator Result Injection

Async validators (launched from `finish.sh`) write their results to `state/<project-key>/pending_validator_results.json`. `limit-bridge.sh`, on each `UserPromptSubmit`, checks this file; if it contains pending results, it injects them via `additionalContext` (≤500 tokens) and clears the file. This ensures that even if the session ends before the next prompt, the results are visible on the next interaction.

---

## 7. Shared Library (`lib/`)

Implement the following as shared modules:

- **`config.sh`**: Loads global config, checks for overlay, deep‑merges per merge rules, validates schema/version.
- **`context_extractor.sh`**: Robust `awk`‑based extraction and `jq`‑validation of the XML‑fenced JSON from `.claude/validator_context.md`. Returns extracted JSON or exits with error.
- **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary, and updates `last_status.json` (atomic write) if the hook produces a report.
- **`project_key.sh`**: Derives the project key from `cwd` (deterministic slug + short hash).
- **`restore.sh`**: Helper to restore quarantined session files. Usage: `restore.sh <project-key> <session-id>`. It moves files from `trash/<project-key>/<session-id>/` back to their original relative paths. If a file already exists, rename the restored file with a `.conflict` suffix.
- **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.

**Security requirement**: All library functions must quote all variables and sanitize JSON inputs before passing to `jq` or other tools. All file writes must be atomic.

---

## 8. Cleanup & Tidiness

Two distinct responsibilities, two risk levels.

### 8.1 Housekeeping (Own Files, Low Risk)

- `janitor.sh` runs on `SessionStart`, rate‑limited to once per `janitor_interval_hours` (global config).
- Enforces retention from global config (logs, state, screenshots, trash).
- Also cleans up session manifest files (under `state/<project-key>/manifests/`) after `state_days`.
- Orphan sweep: removes namespaces for projects that no longer exist on disk (after `state_days`).
- Injects nothing into context; writes one summary line to its own log.

### 8.2 Repo Tidiness (Scratch Files, Higher Risk)

- **Track**: `manifest.sh` records every file *created* or *modified* by Claude this session (`PostToolUse` Write|Edit). It stores a flag `created: true/false` for each entry. Only newly created files are candidates for quarantine; edits to existing files are never touched.
- **Classify at session end** (`finish.sh` on `SessionEnd`): Entries where `created: true` that match scratch patterns (from config) and **not** committed, not in the `keep` list, and not in protected paths are classified as scratch.
  - *Git‑tracked check*: Use `git ls-files --error-unmatch <file> >/dev/null 2>&1`; if it returns 0, the file is tracked and **must never** be touched.
- **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths.
- **Report**: Include `details.scratch_quarantined: N` in the Stop report.
- **Restore**: `restore.sh` moves a quarantined session back to its original location.
- **Purge**: Janitor purges quarantine after `retention.trash_days`.

---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration with narrow matchers, explicit `timeout` fields, `if` conditions (permission‑rule syntax), and `statusLine` entry.
2. **`hooks/`** — Executable scripts per hook, each with stdin parsing, error handling, timing, `--test` mode.
3. **`hooks/lib/`** — Shared library (config, report, context extractor, project‑key, restore, logging).
4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented, including `test_command`, `test_timeout`, `validator_async_threshold_seconds`, `validation.file_map`, and `secrets_whitelist`.
5. **`hooks/config.overlay.example.json`** — Documented example for project overlays, showing static overrides and `validation.file_map`.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, explanation of the dynamic markdown validation logic, correct output channel (**stdout**), statusline architecture (statusline writes limits, limit-bridge reads), `if`/`args`/`shell`/`asyncRewake` usage, version requirements, and atomic write guidance.
7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification).
9. **`hooks/statusline.sh`** — Upgraded statusline script: reads stdin, writes `limits.json` (atomic, throttled), reads `last_status.json`, derives git info, outputs to **stdout**.
10. **`hooks/limit-bridge.sh`** — Reads `limits.json` and `pending_validator_results.json` on `UserPromptSubmit`; injects tier warnings/directives and async results.
11. **`hooks/validators/`** — Context‑aware validator scripts per target type, with async support.
12. **`hooks/test/run.sh`** — A simple test runner that invokes each script with `--test` and verifies exit codes and JSON validity. BATS is optional but recommended.

---

## 10. Acceptance Criteria

### A. Functionality

- [ ] `claude --debug` shows each hook firing on its intended event and no others.
- [ ] Every script passes its `--test` mode against fixtures (including malformed JSON).
- [ ] Bash guard blocks `rm -rf /` and `git push --force origin main` (exit 2) and allows `ls`, `git status`.
- [ ] Stop hook blocks completion when a test is broken, allows when fixed—without looping.
- [ ] Bridge hook: silent below Notice tier; ≤50‑token advisory exactly once at Warning tier; wind‑down directive at Action tier. Dedupe works.
- [ ] `rate_limits` fallback: missing data degrades to context‑only, shows "n/a", never crashes.
- [ ] Statusline renders correctly from state (limits, last status, git info), updates after hooks fire, degrades gracefully on missing state (<100 ms). Output is sent to **stdout**.
- [ ] Statusline writes `limits.json` from its stdin, with throttle, atomic.
- [ ] Validators catch deliberately introduced faults and block Stop; after fix, Stop allowed.
- [ ] Session touching only unmapped files (when `validation.file_map` is present) triggers no remote probes.
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up session manifests from `state/<project-key>/manifests/`.
- [ ] Repo tidiness (on `SessionEnd`): quarantines only scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.
- [ ] Multi‑project: two different stacks (Node/Python/no toolchain) each adapt, no‑toolchain no‑ops cleanly, state/logs namespaced with no cross‑contamination.
- [ ] Project with no config overlay runs safely on pure global defaults.
- [ ] Project without `.claude/` directory or `validator_context.md` skips remote validation cleanly.
- [ ] `StopFailure` and `PostToolUseFailure` hooks fire on errors and log without blocking.
- [ ] `PermissionRequest` hook (if enabled) auto‑approves allowlisted commands and denies others; `PermissionDenied` hook logs and optionally retries (v2.1.88+) with correct `hookSpecificOutput.retry`.
- [ ] `finish.sh` branches correctly on `hook_event_name`: runs validators on `Stop` and repo‑tidiness on `SessionEnd`.
- [ ] Dynamic context extraction: file absent → skip; file present with malformed JSON → blocks Stop with clear error.
- [ ] Test suite runs when `test_command` is set/discovered; fails block stop.
- [ ] Slow validators (> threshold) run asynchronously; results are written to `pending_validator_results.json` and injected by `limit-bridge.sh` on next `UserPromptSubmit`.

### B. Performance & Token Discipline

- [ ] No hook output injected exceeds 500 tokens (verify from debug transcript).
- [ ] Formatting hook completes < 2 s on largest file; PreToolUse guards < 500 ms.
- [ ] Compaction completes successfully at 85 % context threshold (headroom proven).
- [ ] Statusline < 100 ms; state file writes (statusline) throttled to ≤ once per 5 s; atomic writes do not cause corruption.

### C. Portability & Maintainability

- [ ] `grep -rn` across `~/.claude/hooks/` finds no absolute user paths (outside `$HOME`‑derived), no hardcoded branch/model/tool‑command strings outside config, no threshold numbers outside config.
- [ ] All scripts pass `--test` from a different working directory.
- [ ] All scripts run on both macOS and Linux (and Windows WSL/Git Bash) without modification.
- [ ] Config loader handles malformed overlay JSON by falling back to defaults and logging (not crashing).
- [ ] No secret value from any `.env` appears in reports, logs, or debug transcript.
- [ ] Removing hooks from `settings.json` restores stock behaviour—no side effects outside intended formatting and `~/.claude/hooks/` state/logs.
- [ ] Every pre‑existing hook/script is upgraded or retired; `MIGRATION.md` accounts for each item.
- [ ] Missing external tools (e.g., `jq`, `ssh`, `playwright`) cause a logged warning and `exit 0` – they do not break the session.
- [ ] `$CLAUDE_PROJECT_DIR` is used for project‑relative paths; `cwd` is used for operations depending on current location.

### D. Safety & Validation

- [ ] No hook auto‑approves write/network operations beyond the explicit allowlist.
- [ ] Validator probes are read‑only against production; mutating probes target designated sandboxes and clean up.
- [ ] Validator handles target unreachable (reports `error`, respects timeout, does not hang).
- [ ] Quarantine never touches git‑tracked files or files under protected paths.
- [ ] All shell variables are quoted (`"$VAR"`). All inputs are sanitized. `args` field is used where applicable.
- [ ] Dynamic context merges are restricted to the `validation` subtree; security‑critical keys cannot be overridden.
- [ ] Secrets loading uses whitelist and rejects dangerous patterns; no `.env` line is ever executed as code.

### E. Wiring Integrity

- [ ] The implemented wiring matches the system schema: every hook resolves config/reports through `lib/`, all state/log/trash writes are namespaced.
- [ ] `statusline.sh` is the ONLY producer of `limits.json`; `limit-bridge.sh` is the ONLY consumer for directives and async results; statusline is the ONLY display.
- [ ] `validation.file_map` filtering works: validators run only for targets whose glob matches changed files; if no map, all run.

---

## 11. Out of Scope

- **HTTP, Prompt, MCP, and Agent hook types**: This system uses `command` hooks exclusively.
- **MCP tool hooks**: MCP tool interaction is not covered.
- **Project‑level hook logic**: Repositories carry at most an optional config overlay (`.claude/hooks/config.json`), never scripts or hook entries.
- **Any hook that auto‑approves write or network operations** beyond the defined allowlist.
- **Retrying on `PostToolUseFailure`**: We only log.
- **Subagent, Task, Teammate, Worktree, Elicitation, and configuration change events**: These are out of scope for v1.

---

## 12. Version History

| Version | Changes |
|---------|---------|
| **v1 – v10** | Earlier iterations (see previous records). |
| **v11** | Re‑introduced `validation.file_map`; added `last_status.json`; defined dynamic context merge rules; improved extraction method; clarified `if`; added git info; documented secrets loading; added fallback for missing `.claude/`; added `asyncRewake`. |
| **v12** | Manifest tracking `Write\|Edit`; dynamic merge restricted to `validation`; re‑introduced async validators; added test config; replaced `perl` with `awk`; defined `limits.json` format; atomic writes; updated `settings.json`; clarified `if` regex; faster default branch detection. |
| **v13** | **Critical corrections**: Restored correct limit‑data architecture (statusline writes `limits.json`); reverted `if` to permission‑rule syntax; moved `format.sh` to `PostToolUse`; wired `limit-bridge.sh` on `UserPromptSubmit`; corrected Stop/PostToolUse blocking statements; fixed PermissionDenied retry shape; changed `limits.json` to store `used_percentage`; unified manifest path; resolved skip/block contradiction; improved secrets loading; clarified async validator result injection via bridge. Fully aligned with official documentation. |

---

**This v13 specification is fully aligned with official Claude Code hooks documentation, addresses all identified issues from the review, and is ready for implementation.**
