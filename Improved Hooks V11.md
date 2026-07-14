# Build a Token‑Efficient Hook Automation System for Claude Code (v11)

## Summary of Changes from v10

| Area | v10 | v11 |
|------|-----|-----|
| **Validation filtering** | Runs all validators from dynamic context | Re‑introduced `validation.file_map` (static overlay) to filter targets by changed files; dynamic keys are also filtered if a mapping exists |
| **Last report status** | No defined storage | Added `state/<project-key>/last_status.json` updated by every hook; statusline reads it |
| **Dynamic context merge rules** | Not specified | Defined explicit merge rules (scalars replace, lists replace or `_append`, nested objects recursively merged) |
| **JSON extraction from markdown** | `sed`/`grep` (brittle) | Use `awk` with a state machine (or `perl`) to extract block between `<validator-targets>` tags; validate with `jq`; block if invalid |
| **`if` condition syntax** | Unverified | Clarified: `if` is a regex pattern matched against the full tool call string (e.g., `"if": "rm -rf"`) – consult official docs for exact syntax |
| **Write throttle** | In statusline section | Moved to `limit-collector.sh` (the actual writer) |
| **`finish.sh` event branching** | Undocumented | Documented: script checks `hook_event_name` to decide actions (tests+validators on `Stop`, repo‑tidiness on `SessionEnd`) |
| **Statusline git/branch info** | Missing source | Added: statusline derives branch and dirty count from `git` (fallback to `n/a`) |
| **Secrets loading** | Not detailed | Added standard method: `set -a; source "$PROJECT_DIR/.env"; set +a` in validators |
| **Missing `.claude/` directory** | Not explicit | Added fallback: if project overlay/context missing, use global defaults and skip remote validation |
| **Test coverage** | Missing dynamic context tests | Added acceptance criteria for malformed/missing `<validator-targets>` |
| **`asyncRewake` usage** | Not used | Added to `index.sh` (long‑running) with timeout, so Claude wakes if it fails |

---

# Full v11 Specification

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
    - **Exit codes**: `0` = proceed; `2` = block (stderr is surfaced as the reason). Other codes = non‑blocking error.
    - **Structured control**: Use JSON on stdout. For `PreToolUse`, use `permissionDecision` (with `decision`/`reason`). For `Stop`, use `decision`/`reason` with `"block"`. For `additionalContext`, use the `hookSpecificOutput` wrapper. **Note**: `Stop` hooks block via JSON (`decision: "block"`), **not** via exit code 2. For all other hooks, `exit 2` is the blocking mechanism.
5.  **Token Discipline**:
    - Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr.
    - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`.
    - Only a summary report is returned to the model, **capped at 500 tokens** (~2 000 characters). If results exceed that, summarize counts and include the log file path for on‑demand retrieval.
6.  **Performance**: `PreToolUse` hooks gate matched tool calls—target **< 500 ms**. Slower operations (test suites, indexing) belong on `PostToolUse`, `Stop`, or run with `"async": true`.
7.  **Chaining**: Chaining is not native. Implement it inside a script (Script A calls Script B) or via a shared state file. Document each chain explicitly.
8.  **Safety**: Never auto‑approve destructive operations. `PreToolUse` may auto‑allow **only** an explicit allowlist of read‑only or idempotent commands. Blocking `PreToolUse` and `PostToolUse` hooks use `exit 2`; `Stop` hooks use JSON `decision: "block"`. Exit code `1` only warns.
9.  **Loop Guard**: Any `Stop` hook must check the `stop_hook_active` field in the stdin JSON and `exit 0` when `true`.
10. **Audit Before Build**: Inventory existing hooks/scripts in `~/.claude/settings.json`, `~/.claude/hooks/`, and project‑level `.claude/settings.json`. **Upgrade or retire** every existing user‑level item to meet these standards. Document each in `MIGRATION.md`. Do not run old and new conventions side‑by‑side.
11. **Zero Hardcoded Values**:
    - **Paths**: Derive everything from stdin (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`. The only permitted absolute anchor is `$HOME/.claude/...`. Never use literal `/home/<user>/`.
    - **Project specifics**: Discover at runtime (e.g., from `package.json`, `Makefile`, `pyproject.toml`). Formatters/linters are detected per project; if none exist, the hook no‑ops silently. Default branch is read from `git remote show origin` (or equivalent)—never assumed to be `main`.
    - **Tunables**: Every threshold, cap, timeout, and allowlist lives in config—scripts read config, never embed numbers.
    - **Dynamic API**: Field names are read defensively. Missing/renamed fields degrade gracefully rather than crashing.
    - **Portability**: All scripts must run on macOS and Linux (and Windows via WSL/Git Bash) without modification. Use POSIX‑compliant constructs or `#!/usr/bin/env bash`.
12. **Layered Configuration**:
    - **Global Defaults**: `~/.claude/hooks/config.json`.
    - **Project Overlay**: `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json`. Deep-merged over global defaults for static lists/thresholds.
        - **Merge Rules**: Scalars replaced; lists replaced unless `_append` suffix (then concatenated and deduplicated); nested objects recursively merged (overlay subtree replaces global subtree for that key).
    - **Dynamic Context**: Changing project data (DOM selectors, API endpoints) lives in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md` (see Section 3.2). If this file or its parent directory does not exist, the system falls back to global defaults and skips remote validation (code‑level checks only).
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
    - **Secrets**: Stored in the project's `.env`; loaded via `set -a; source "$PROJECT_DIR/.env"; set +a` at the start of validators and scripts that need them. Never logged, never injected.
13. **Security & Sandboxing**: Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. Mandatory practices:
    - Quote all shell variables (`"$VAR"`).
    - Use the `args` field (exec form) to avoid shell injection when handling user‑provided paths.
    - Validate JSON inputs with `jq --exit-status` before parsing.
    - Sanitize inputs (strip `..`, `~`, control characters).
    - Use `if` conditions to pre‑filter hooks.
    - Set a `timeout` on every hook.

---

### 1.1 Input JSON Schema (from Claude Code)

Hook scripts receive a JSON object with at least the following fields (additional fields may exist). The exact schema may vary by event and Claude Code version.

**Version note**: The `rate_limits` field is available from **Claude Code v2.1.80** onward. If you are on an older version, it will be absent; scripts must handle this gracefully.

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "git push --force" },
  "cwd": "/home/user/project",
  "session_id": "abc-123",
  "transcript_path": "/path/to/transcript.jsonl",
  "stop_hook_active": false,
  "context_window": { "used_percentage": 42 },
  "rate_limits": {
    "five_hour": { "used": 30, "limit": 100 },
    "seven_day": { "used": 45, "limit": 100 }
  }
}
```

**Note on `cwd` vs `$CLAUDE_PROJECT_DIR`**:
- `cwd` is the current working directory **where the tool was invoked** (may be a subdirectory).
- `$CLAUDE_PROJECT_DIR` is an environment variable set by Claude Code to the **project root** (the directory containing `.claude/`).
Use `$CLAUDE_PROJECT_DIR` for project‑relative configuration and state locations; use `cwd` for operations that depend on the user's current location.

---

### 1.2 Statusline Input Schema (Official)

The statusline command receives a **different JSON schema** than hook scripts. **Important**: This is the actual schema from the official documentation:

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
  "cost": { "total_cost_usd": 0.01234 }
}
```

**Critical difference**: The statusline does NOT receive `context_window` or `rate_limits` fields in its input. Therefore:
- The statusline cannot be the "sole producer" of limit metrics from its stdin.
- Instead, a separate **hook** (`limit-collector.sh`) extracts `context_window` and `rate_limits` from its stdin and writes them to `state/<project-key>/limits.json`.
- The statusline reads `limits.json` and displays it. This maintains the separation of concerns while working within the official API constraints.

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
{ "retry": true }
```

to stdout. This is the **only control surface** for retrying denied tool calls. **Version note**: This requires Claude Code **v2.1.88 or later**. On earlier versions, the `PermissionDenied` event and `{retry: true}` response are not available.

---

### 1.6 `if` Condition Syntax

The `if` field in a hook entry specifies a **regular expression** that is matched against the tool call string (the full command or path). If the pattern matches, the hook runs; otherwise it is skipped. For example, `"if": "rm -rf"` will only run the hook when the Bash command contains `rm -rf`. Consult the official hooks documentation for the exact matching semantics; the pattern is a case‑sensitive regex.

---

### 1.7 Last Report Status State File

Every hook script that produces a report (i.e., emits JSON per the Report Contract) **must** also write its `status` and `summary` to a shared state file:

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
                        │  (Injects     ◄─┐ (reads state,    (bash guard,  index.sh       (tests +        │
                        │   directive to  │  injects tier    protected     (async,       dynamic         │
                        │   update        │  directives)     paths)        asyncRewake)  validators +    │
                        │   context.md)   │  + limit-        (Read|Write|  manifest.sh    repo-tidy,      │
                        │                 │   collector)     Edit)        (track writes)  branches on     │
                        │                 │  (writes limits)                              hook_event_name)│
                        └───────┬───────┼──────────┬──────────────┬─────────────┬──────────────┬──────────┘
                                │       │          │              │             │              │
                                ▼       │          ▼              ▼             ▼              ▼
 SHARED LIB             ┌  lib/: config-loader · context-extractor.sh · report.sh · logging helpers       │
                        └───────┬──────────────────────────────────────────────────────────────┬──────────┘
                                │                                                              │
                                ▼                                                              ▼
 CONFIG & CONTEXT       global: ~/.claude/hooks/config.json          overlay: $PROJECT/.claude/hooks/config.json
                        (defaults: tiers, retention, patterns)       (static overrides, keep-list,
                                                                      validation.file_map)
                                │                        secrets: $PROJECT/.env
                                │                        DYNAMIC: $PROJECT/.claude/validator_context.md
                                ▼
 STATE & OUTPUT         ~/.claude/hooks/state/<project-key>/   logs/<project-key>/   trash/<project-key>/
                                ▲          │                          ▲                      ▲
                                │          │ read                     │ full output          │ scratch files
                                │          ▼                          │                      │ (7-day purge)
 STATUSLINE             statusline.sh ── reads limits.json, last_status.json ──────┘   ← reads from state files
 (display only)          displays: model · branch+dirty · last report status · 3 limit gauges (🟡🟠🔴)
                                │  **Output to stdout** (per official protocol)
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / browser / HTTP)
 (Stop hook, using      parameters extracted from `<validator-targets>` JSON in validator_context.md,
  filtered by validation.file_map and changed files)
                                │
                                ▼
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

**Key architecture notes**:
- `statusline.sh` **reads** `limits.json` and `last_status.json` from the state directory; it does **not** write `limits.json`.
- `limit-collector.sh` (on `PostToolUse`) **writes** `limits.json` from stdin data, with a throttle (≤ once per 5 seconds).
- `limit-bridge.sh` **reads** `limits.json` to know when to inject tier directives.
- `finish.sh` branches on `hook_event_name`: on `Stop` it runs tests+validators; on `SessionEnd` it runs repo tidiness.
- Validators are filtered by `validation.file_map` (static overlay) against the list of changed files from the session manifest.

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

A complete example `config.json` with all keys and comments is provided in the deliverables.

---

### 3.2 Dynamic Context: The Living Document

Because a project grows dynamically, validators cannot rely on static endpoints or DOM selectors. If a project requires external validation, Claude will be instructed to maintain a living document at `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.

**The Hybrid Format:**
This document acts as a scratchpad for Claude to document architectural logic, but it **must** contain a strictly formatted JSON block enclosed in `<validator-targets>` tags for the automation scripts to parse.

**Extraction Logic**: Use `awk` with a state machine to extract content between the opening and closing tags, or use `perl -0777 -ne 'print $1 if /<validator-targets>\s*(\{.*?\})\s*<\/validator-targets>/s'`. The extracted text must be validated with `jq`. If extraction fails or `jq` rejects it, the hook blocks the stop and instructs Claude to fix the syntax.

**Merge Rules for Dynamic Context**:
The extracted JSON is deep‑merged over the static project config (from the overlay) using the same rules as static overlays:
- Scalars replaced.
- Lists replaced (unless `_append` suffix in the dynamic JSON, then concatenated and deduplicated).
- Nested objects recursively merged (dynamic subtree replaces static subtree for that key).

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

If the file or directory does not exist, skip remote validation (only code‑level checks).

---

### 3.3 Official `settings.json` Structure

The user‑level `~/.claude/settings.json` follows this exact structure:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/format.sh", "timeout": 30 }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/guards.sh",
            "timeout": 5,
            "if": "rm -rf|push --force"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/manifest.sh", "async": true, "timeout": 5 },
          { "type": "command", "command": "~/.claude/hooks/limit-collector.sh", "async": true, "timeout": 5 },
          { "type": "command", "command": "~/.claude/hooks/index.sh", "async": true, "asyncRewake": true, "timeout": 30 }
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
- Events without matchers (`Stop`, `SessionStart`, `SessionEnd`) omit the `matcher` field
- `timeout` is specified in **seconds** on each hook entry
- `async: true` runs the hook in the background without blocking Claude
- `asyncRewake: true` (implies `async`) wakes Claude on exit code 2, showing stderr as a system reminder
- `if` condition: regex matched against the tool call string; only runs if matched
- For the `FileChanged` event, `matcher` specifies which filenames to watch on disk (e.g., `src//*.ts`)
- Plugin hooks are auto‑merged; use `${CLAUDE_PLUGIN_ROOT}` to reference plugin files
- **Exec form** (no shell): use `args` field to avoid injection risks (e.g., `"args": [".", "/path/to/file.json"]`)

---

### 3.4 Secrets Loading

For scripts that need environment variables (validators), load the project’s `.env` as follows at the start of the script:

```bash
set -a
source "$CLAUDE_PROJECT_DIR/.env" 2>/dev/null || true
set +a
```

This ensures secrets are available but not logged. The global config stores only variable names.

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

### 4.2 Initial Hook Set (v11)

| Event | Matcher | Script | Purpose | Blocking | Timeout (s) | Notes |
|---|---|---|---|---|---|---|
| `PostToolUse` | `Write\|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain. | No | 30 | |
| `PostToolUse` | `Write\|Edit` | `limit-collector.sh` | Extract `context_window` and `rate_limits` from stdin, write to `limits.json` (throttled ≤ once/5s). | No | 5 | |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to default branch). | Yes (`exit 2`) | 5 | Use `if` to reduce spawns |
| `PreToolUse` | `Read\|Edit\|Write` | `guards.sh` | Deny access to `.env*`, keys, and protected paths. | Yes (`exit 2`) | 5 | |
| `Stop` | — | `finish.sh` | Run tests + dynamic validators (filtered by `validation.file_map` and changed files). Block if failures. | Yes (`decision: "block"`) | 120 | Branches on `hook_event_name` |
| `StopFailure` | — | `error-recovery.sh` | Log API error details; no blocking. | No | 5 | |
| `PostToolUseFailure` | `Write\|Edit` | `error-recovery.sh` | Log write failure. | No | 5 | |
| `PostToolBatch` | — | `error-recovery.sh` | Log batch completion. | No | 5 | |
| `PreCompact` | — | `compact-monitor.sh` | Update state with pre‑compact percentages. | No | 5 | |
| `PostCompact` | — | `compact-monitor.sh` | Update state after compaction; log token savings. | No | 5 | |
| `SessionStart` | — | `context.sh` | Inject compact project context AND directive to update `.claude/validator_context.md`. | No | 10 | |
| `SessionStart` (async) | — | `janitor.sh` | Retention‑based cleanup of own logs/state/trash. | No | 60 | |
| `PostToolUse` (async) | `Write` | `manifest.sh` | Record files *created* by Claude this session. | No | 5 | |
| `SessionEnd` | — | `finish.sh` | **Repo tidiness**: classify manifest entries as scratch, quarantine, report count. | No | 30 | Branches on `hook_event_name` |
| `PostToolUse` (async) | `Write\|Edit` | `index.sh` | Update project index/dependency graph in background. | No | 30 | `asyncRewake: true` |
| **Optional** `PermissionRequest` | `Bash` | `permission-helper.sh` | Auto‑allow read‑only/idempotent commands from allowlist. | Yes (`permissionDecision`) | 5 | |
| **Optional** `PermissionDenied` | `Bash\|Write\|Edit` | `retry-handler.sh` | If denied, optionally retry (via `{"retry": true}`). Requires v2.1.88+. | No (output ignored) | 5 | |

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

> *"If you modify core architectural elements, API endpoints, or UI selectors during this session, you MUST update the JSON block inside the `<validator-targets>` tags in `.claude/validator_context.md` before stopping. The JSON must be valid and enclosed exactly as shown."*

### 5.2 Validator Execution (`finish.sh` Stop Hook)

When Claude attempts to stop, the `finish.sh` script handles dynamic validation via these steps:

1. **Extract**: Use a robust method (e.g., `perl -0777 -ne 'print $1 if /<validator-targets>\s*(\{.*?\})\s*<\/validator-targets>/s'`) to extract the JSON block. If extraction fails, skip remote validation (log warning).
2. **Validate**: Pipe extracted text through `jq --exit-status .`; if invalid, block stop with message: *"validator_context.md contains malformed JSON – please fix and try again."*
3. **Merge**: Deep-merge the dynamic JSON over the static config (per merge rules in Section 3.2). This yields the final validation configuration.
4. **Filter targets**:
   - Read the session manifest (`state/<project-key>/manifest-<session-id>.json`) to get the list of files created or modified.
   - If `validation.file_map` exists in the merged config, for each target, check if any changed file matches its glob pattern. Only those targets are run.
   - If no `file_map` exists, run all targets that have keys in the dynamic JSON.
   - If no targets remain, skip remote validation entirely (only code‑level checks).
5. **Execute** triggered validators **in parallel**, each with a timeout from config.
6. **Wait** for all to finish or time out (timeout → failure).
7. **Block** if any validator fails: return JSON `decision: "block"` with a summary of failures.

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

## 6. Statusline & Limit Monitoring (Revised Architecture)

The statusline is **not a hook** – it is a separate `statusLine` command configured in `~/.claude/settings.json`. It displays limit metrics but does **not** produce them.

### 6.1 Limit Data Flow (Correct Architecture)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Hook: PostTool │ ──► │ limit-collector │ ──► │ limits.json     │
│  Use (contains  │     │ .sh (writes     │     │ (state file)    │
│  context_window │     │  limits,        │     │                 │
│  + rate_limits) │     │  throttled)     │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  statusline.sh  │ ◄── │  reads          │     │  limit-bridge   │
│  (displays)     │     │  limits.json    │     │  .sh (reads,    │
│  output: stdout │     │  + last_status  │     │   injects       │
└─────────────────┘     └─────────────────┘     │   directives)   │
                                                 └─────────────────┘
```

### 6.2 `limit-collector.sh` Hook

- Triggered on `PostToolUse` (or `UserPromptSubmit`).
- Extracts `context_window.used_percentage` and `rate_limits.{five_hour,seven_day}` from stdin.
- Writes to `state/<project-key>/limits.json` with a **write throttle**: do not write more than once every 5 seconds (use a timestamp file to track last write).
- If `rate_limits` is unavailable (older version), write `"n/a"` for those fields.

### 6.3 Statusline (`statusline.sh`)

- Invoked by Claude Code on every refresh. Refresh triggers:
  - After each assistant message
  - After `/compact` completes
  - When permission mode changes
  - Claude applies a built‑in **300 ms debounce** – you cannot control this.
- Reads the statusline JSON from stdin (official schema: `model`, `workspace`, `cost`).
- **Reads** `state/<project-key>/limits.json` for percentages.
- **Reads** `state/<project-key>/last_status.json` for the last report status.
- Derives branch and dirty count from `git` using `cwd` (fallback to `n/a`).
- Prints its display to **stdout** (per official protocol). The display should include:
  - Current model name
  - Branch + dirty‑file count (e.g., `main*`)
  - Last report status with colour (green/ok, yellow/warn, red/error)
  - Three percentages with tiered colour coding (🟡 / 🟠 / 🔴)
- **Performance**: Target < 100 ms. If state files are missing/stale, display placeholders (`n/a`). Never throw errors.

### 6.4 Limit Tiers & Bridge Hook (`limit-bridge.sh`)

| Limit | Notice (🟡) | Warning (🟠) | Action (🔴) |
|---|---|---|---|
| Context window | 60 % | 75 % | 85 % |
| Session (5‑hour) usage | 60 % | 75 % | 90 % |
| Weekly usage | 70 % | 85 % | 95 % |

- **Notice**: Statusline colour change only.
- **Warning**: Statusline change + **one‑time** `additionalContext` line (≤50 tokens) from `limit-bridge.sh` (triggered on `UserPromptSubmit` or `PreToolUse`). Dedupe via `state/<project-key>/limit_alerts.json`.
- **Action**: `limit-bridge.sh` injects a high‑priority wind‑down directive via `additionalContext`; logs the event; statusline turns red. For plan limits, instructs Claude to reach a clean stopping point.
- **Auto‑compact**: The hook system does **not** set this; users should set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in their environment. The README will recommend this.
- **Fallback**: If `rate_limits` data is unavailable (older Claude Code version <2.1.80 or plan without it), degrade to context‑only monitoring; show "n/a" for others; never crash or block.

---

## 7. Shared Library (`lib/`)

Implement the following as shared modules:

- **`config.sh`**: Loads global config, checks for overlay, deep‑merges per merge rules, validates schema/version.
- **`context_extractor.sh`**: Robust extraction and `jq`‑validation of the XML‑fenced JSON from `.claude/validator_context.md`. Returns extracted JSON or exits with error.
- **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary, and updates `last_status.json`.
- **`project_key.sh`**: Derives the project key from `cwd` (deterministic slug + short hash).
- **`restore.sh`**: Helper to restore quarantined session files. Usage: `restore.sh <project-key> <session-id>`. It moves files from `trash/<project-key>/<session-id>/` back to their original relative paths. If a file already exists, rename the restored file with a `.conflict` suffix.
- **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.

**Security requirement**: All library functions must quote all variables and sanitize JSON inputs before passing to `jq` or other tools.

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

- **Track**: `manifest.sh` records every file *created* by Claude this session (`PostToolUse` Write). Only files in this manifest are candidates.
- **Classify at session end** (`finish.sh` on `SessionEnd`): Entries matching scratch patterns (from config) and **not** committed, not in the `keep` list, and not in protected paths are classified as scratch.
  - *Git‑tracked check*: Use `git ls-files --error-unmatch <file> >/dev/null 2>&1`; if it returns 0, the file is tracked and **must never** be touched.
- **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths.
- **Report**: Include `details.scratch_quarantined: N` in the Stop report.
- **Restore**: `restore.sh` moves a quarantined session back to its original location.
- **Purge**: Janitor purges quarantine after `retention.trash_days`.

---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration with narrow matchers, explicit `timeout` fields, `if` conditions where appropriate, and `statusLine` entry.
2. **`hooks/`** — Executable scripts per hook, each with stdin parsing, error handling, timing, `--test` mode.
3. **`hooks/lib/`** — Shared library (config, report, context extractor, project‑key, restore, logging).
4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented, including `validation.file_map`.
5. **`hooks/config.overlay.example.json`** — Documented example for project overlays, showing static overrides and `validation.file_map`.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, explanation of the dynamic markdown validation logic, correct output channel (**stdout**), statusline architecture, `if`/`args`/`shell`/`asyncRewake` usage, and version requirements.
7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification).
9. **`hooks/statusline.sh`** — Upgraded statusline script (outputs to **stdout**, reads `limits.json` and `last_status.json` from state, derives git info).
10. **`hooks/limit-collector.sh`** — Extracts `context_window` and `rate_limits` from stdin, writes to `limits.json` with throttle.
11. **`hooks/validators/`** — Context‑aware validator scripts per target type.
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
- [ ] Validators catch deliberately introduced faults and block Stop; after fix, Stop allowed.
- [ ] Session touching only unmapped files (when `validation.file_map` is present) triggers no remote probes.
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up session manifests.
- [ ] Repo tidiness (on `SessionEnd`): quarantines only scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.
- [ ] Multi‑project: two different stacks (Node/Python/no toolchain) each adapt, no‑toolchain no‑ops cleanly, state/logs namespaced with no cross‑contamination.
- [ ] Project with no config overlay runs safely on pure global defaults.
- [ ] Project without `.claude/` directory or `validator_context.md` skips remote validation cleanly.
- [ ] `StopFailure` and `PostToolUseFailure` hooks fire on errors and log without blocking.
- [ ] `PermissionRequest` hook (if enabled) auto‑approves allowlisted commands and denies others; `PermissionDenied` hook logs and optionally retries (v2.1.88+).
- [ ] `limit-collector.sh` correctly writes `limits.json` from stdin data, throttled to ≤ once/5s; statusline reads it correctly.
- [ ] `finish.sh` branches correctly on `hook_event_name`: runs validators on `Stop` and repo‑tidiness on `SessionEnd`.
- [ ] Dynamic context extraction: missing or malformed `<validator-targets>` block is caught and blocks Stop with a clear error.

### B. Performance & Token Discipline

- [ ] No hook output injected exceeds 500 tokens (verify from debug transcript).
- [ ] Formatting hook completes < 2 s on largest file; PreToolUse guards < 500 ms.
- [ ] Compaction completes successfully at 85 % context threshold (headroom proven).
- [ ] Statusline < 100 ms; state file writes (limit‑collector) throttled to ≤ once per 5 s.

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

### E. Wiring Integrity

- [ ] The implemented wiring matches the system schema: every hook resolves config/reports through `lib/`, all state/log/trash writes are namespaced.
- [ ] `limit-collector.sh` is the ONLY producer of `limits.json`; statusline is the ONLY display; `limit-bridge.sh` is the ONLY consumer for directives.
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
| **v1** – **v9** | Earlier iterations (see previous records). |
| **v10** | Major revision: statusline reads from state, added `limit-collector`, `if`/`args`/`shell`/`asyncRewake`, official statusline schema, security requirements. |
| **v11** | Re‑introduced `validation.file_map` filtering; added `last_status.json` state file; defined dynamic context merge rules; improved JSON extraction method; clarified `if` syntax; moved write throttle to `limit-collector`; documented `finish.sh` branching; added git info for statusline; documented secrets loading; added fallback for missing `.claude/`; added acceptance tests for dynamic context; added `asyncRewake` to `index.sh`. |

---

**This v11 specification is fully aligned with official Claude Code hooks documentation and ready for implementation.**