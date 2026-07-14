# Build a Token‑Efficient Hook Automation System for Claude Code (v10)

## Evolution Summary (v9 → v10)

| Area | v9 | v10 |
|------|----|-----|
| **Statusline input schema** | Assumed `context_window`/`rate_limits` fields | Updated to match official schema (`model`, `workspace`, `cost`) with fallback mechanism |
| **Statusline as "sole producer"** | Claimed statusline is sole producer of limit metrics | Clarified: statusline reads from state file; limits are sourced via a dedicated hook when available |
| **additionalContext format** | Not fully specified | Added exact output format with `hookSpecificOutput` wrapper |
| **Hook event list** | Missing several official events | Added `Setup`, `UserPromptExpansion`, `MessageDisplay`, `SubagentStart/Stop`, `TaskCreated/Completed`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `FileChanged`, `WorktreeCreate/Remove`, `Elicitation/ElicitationResult` with explicit handling |
| **Hook type comparison** | Incomplete (missing MCP, Agent) | Added full table with all five types |
| **`if` condition** | Not mentioned | Added `if` field for conditional hook execution |
| **`args` field** | Not mentioned | Added `args` for exec form (no shell) to reduce injection risk |
| **`shell` field** | Not mentioned | Added `shell` for cross-platform compatibility |
| **`asyncRewake`** | Not mentioned | Added `asyncRewake` for background hooks that wake Claude on failure |
| **`PermissionDenied` version** | Mentioned | Added explicit version requirement (v2.1.88+) |
| **Security/Sandboxing** | Brief mention | Expanded with concrete quoting and validation requirements |

---

# Full v10 Specification

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
    - **Dynamic Context (NEW)**: Changing project data (DOM selectors, API endpoints) lives in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
    - **Secrets**: Read from the project's `.env` at runtime. Global config stores variable *names*, never values.
13. **Security & Sandboxing**: Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. You must aggressively validate/sanitize JSON inputs and quote all shell variables (e.g., `"$FILE_PATH"` instead of `$FILE_PATH`) to prevent shell injection from the model's output. **Use the `args` field (exec form) for hooks that handle user-provided paths to avoid shell injection entirely.**

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
- Instead, a separate **hook** (e.g., `PostToolUse` or `UserPromptSubmit`) MUST write limit data to `state/<project-key>/limits.json`.
- The statusline reads `limits.json` and displays it. This maintains the separation of concerns while working within the official API constraints.

**Implementation**: A dedicated `PostToolUse` or `UserPromptSubmit` hook (`limit-collector.sh`) extracts `context_window` and `rate_limits` from its stdin and writes them to `limits.json`. The statusline reads this file. This is the **correct architecture** per the official API.

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

`details` holds counts and short identifiers only—never file contents, stack traces, or diffs.

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
                        │   directive to  │  injects tier    protected     (async)        dynamic         │
                        │   update        │  directives)     paths)        manifest.sh    validators +    │
                        │   context.md)   │  + limit-        (Read|Write|  (track writes) (on Stop)       │
                        │                 │   collector)     Edit)                                        │
                        │                 │  (writes limits)                                            │
                        └───────┬───────┼──────────┬──────────────┬─────────────┬──────────────┬──────────┘
                                │       │          │              │             │              │
                                ▼       │          ▼              ▼             ▼              ▼
 SHARED LIB             ┌  lib/: config-loader · context-extractor.sh · report.sh · logging helpers       │
                        └───────┬──────────────────────────────────────────────────────────────┬──────────┘
                                │                                                              │
                                ▼                                                              ▼
 CONFIG & CONTEXT       global: ~/.claude/hooks/config.json          overlay: $PROJECT/.claude/hooks/config.json
                        (defaults: tiers, retention, patterns)       (static overrides, keep-list)
                                │                        secrets: $PROJECT/.env
                                │                        DYNAMIC: $PROJECT/.claude/validator_context.md
                                ▼
 STATE & OUTPUT         ~/.claude/hooks/state/<project-key>/   logs/<project-key>/   trash/<project-key>/
                                ▲          │                          ▲                      ▲
                                │          │ read                     │ full output          │ scratch files
                                │          ▼                          │                      │ (7-day purge)
 STATUSLINE             statusline.sh ── reads limits.json ──────────┘   ← reads from state file
 (display only)          displays: model · branch · last report status · 3 limit gauges (🟡🟠🔴)
                                │  **Output to stdout** (per official protocol)
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / browser / HTTP)
 (Stop hook, using      parameters extracted from `<validator-targets>` JSON in validator_context.md
  dynamic context)
                                │
                                ▼
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

**Key architecture notes**:
- `statusline.sh` **reads** `limits.json` from the state directory; it does **not** write it (except for its own display).
- A dedicated `limit-collector.sh` hook (e.g., on `PostToolUse` or `UserPromptSubmit`) **writes** `limits.json` from stdin data.
- This separation respects the official API: the statusline receives a different schema than hooks.
- The `limit-bridge.sh` hook **reads** `limits.json` to know when to inject tier directives.

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

A complete example `config.json` with all keys and comments is provided in the deliverables.

---

### 3.2 Dynamic Context: The Living Document

Because a project grows dynamically, validators cannot rely on static endpoints or DOM selectors. If a project requires external validation, Claude will be instructed to maintain a living document at `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.

**The Hybrid Format:**
This document acts as a scratchpad for Claude to document architectural logic, but it **must** contain a strictly formatted JSON block enclosed in `<validator-targets>` tags for the automation scripts to parse.

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
            "if": "Bash(rm *)"   // Only runs on rm commands
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "~/.claude/hooks/manifest.sh", "async": true, "timeout": 5 },
          { "type": "command", "command": "~/.claude/hooks/limit-collector.sh", "async": true, "timeout": 5 }
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
- `matcher` supports **regular expressions** (e.g., `Edit|Write`, `Read|Edit|Write`)
- Events without matchers (`Stop`, `SessionStart`, `SessionEnd`) omit the `matcher` field
- `timeout` is specified in **seconds** on each hook entry
- `async: true` runs the hook in the background without blocking Claude
- `if` condition: only runs the hook if the tool call matches the pattern
- For the `FileChanged` event specifically, the `matcher` field is used to specify *which filenames to watch on disk* (e.g., `src//*.ts`), rather than matching a tool name.
- Plugin hooks are auto‑merged; use `${CLAUDE_PLUGIN_ROOT}` to reference plugin files
- **Exec form** (no shell): use the `args` field to avoid injection risks:
  ```json
  { "type": "command", "command": "/usr/bin/jq", "args": [".", "/path/to/file.json"] }
  ```

### 3.4 `args` Field (Exec Form)

When `args` is present, `command` is resolved as an executable and spawned directly with `args` as the argument vector, **with no shell involved**. This eliminates shell injection risks entirely.

**Security recommendation**: Always use `args` for hooks that handle user-provided paths or commands from the model.

### 3.5 `shell` Field (Cross-Platform)

Accepts `"bash"` or `"powershell"`. Defaults to `"bash"`, or to `"powershell"` on Windows when Git Bash isn't installed. Use this for better Windows compatibility:

```json
{ "type": "command", "command": "script.sh", "shell": "bash" }
```

### 3.6 `asyncRewake` Field

If `true`, runs in the background and wakes Claude on exit code 2. Implies `async`. The hook's stderr, or stdout if stderr is empty, is shown to Claude as a system reminder.

```json
{ "type": "command", "command": "long-running-validator.sh", "async": true, "asyncRewake": true }
```

---

### 3.7 Secrets

Stored in the project's `.env`. Read at runtime. Never logged, never injected.

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

### 4.2 Initial Hook Set (v10)

| Event | Matcher | Script | Purpose | Blocking | Timeout (s) | Notes |
|---|---|---|---|---|---|---|
| `PostToolUse` | `Write\|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain. | No | 30 | |
| `PostToolUse` | `Write\|Edit` | `limit-collector.sh` | Extract `context_window` and `rate_limits` from stdin, write to `limits.json`. | No | 5 | **NEW** |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to default branch). | Yes (`exit 2`) | 5 | Use `if: Bash(rm * | push --force)` to reduce spawns |
| `PreToolUse` | `Read\|Edit\|Write` | `guards.sh` | Deny access to `.env*`, keys, and protected paths. | Yes (`exit 2`) | 5 | |
| `Stop` | — | `finish.sh` | Extract JSON from `validator_context.md`, run context‑aware validators. Block stop if failures occur. | Yes (`decision: "block"`) | 120 | |
| `StopFailure` | — | `error-recovery.sh` | Log API error details; no blocking (output ignored). | No | 5 | |
| `PostToolUseFailure` | `Write\|Edit` | `error-recovery.sh` | Log write failure; just log. | No | 5 | |
| `PostToolBatch` | — | `error-recovery.sh` | Log batch completion; optional summary. | No | 5 | |
| `PreCompact` | — | `compact-monitor.sh` | Update state with pre‑compact percentages. | No | 5 | |
| `PostCompact` | — | `compact-monitor.sh` | Update state after compaction; log token savings. | No | 5 | |
| `SessionStart` | — | `context.sh` | Inject compact project context AND the directive to update `.claude/validator_context.md` if architecture changes. | No | 10 | |
| `SessionStart` (async) | — | `janitor.sh` | Retention‑based cleanup of own logs/state/trash. | No | 60 | |
| `PostToolUse` (async) | `Write` | `manifest.sh` | Record files *created* by Claude this session. | No | 5 | |
| `SessionEnd` | — | `finish.sh` | **Repo tidiness**: classify manifest entries as scratch, quarantine, report count. | No | 30 | |
| `PostToolUse` (async) | `Write\|Edit` | `index.sh` | Update project index/dependency graph in background. | No | 30 | |
| **Optional** `PermissionRequest` | `Bash` | `permission-helper.sh` | Auto‑allow read‑only/idempotent commands from allowlist. | Yes (`permissionDecision`) | 5 | |
| **Optional** `PermissionDenied` | `Bash\|Write\|Edit` | `retry-handler.sh` | If a command was denied, optionally retry (via `{"retry": true}`). Requires v2.1.88+. | No (output ignored) | 5 | |

---

### 4.3 Events Not Included in This System

| Event | Justification for Exclusion |
|-------|----------------------------|
| `Setup` | Single-use init only; not needed for ongoing automation. |
| `UserPromptExpansion` | Too early in the flow; would add latency without benefit. |
| `MessageDisplay` | Fires per message; excessive overhead for automation. |
| `SubagentStart` / `SubagentStop` | Subagent workflows are out of scope for v1. |
| `TaskCreated` / `TaskCompleted` | Task lifecycle is managed separately by Claude. |
| `TeammateIdle` | Agent Team feature is not used in this setup. |
| `InstructionsLoaded` | Already handled by `SessionStart` context injection. |
| `ConfigChange` / `CwdChanged` / `FileChanged` | Configuration changes add complexity; file changes are tracked via `manifest.sh`. |
| `WorktreeCreate` / `WorktreeRemove` | Worktree operations are not used in this setup. |
| `Elicitation` / `ElicitationResult` | MCP elicitation is out of scope for v1. |

**Plugin hooks**: If plugins are installed, they may add their own hook entries. This system will coexist with them; we do not modify plugin hooks. Plugin hooks are auto‑merged and use `${CLAUDE_PLUGIN_ROOT}` to reference plugin files.

**MCP tool hooks**: MCP tool interaction is out of scope for v1. This system focuses on Claude Code's native tool calls (`Bash`, `Read`, `Write`, `Edit`).

---

## 5. Context‑Aware Validation (Dynamic)

Code‑level checks are insufficient—validation must extend to the running system (VPS, email, web app, etc.).

### 5.1 The `SessionStart` Directive

The `context.sh` hook must inject the following strict directive via `additionalContext` when a session starts:

> *"If you modify core architectural elements, API endpoints, or UI selectors during this session, you MUST update the JSON block inside the `<validator-targets>` tags in `.claude/validator_context.md` before stopping."*

### 5.2 Validator Execution (`finish.sh` Stop Hook)

When Claude attempts to stop, the `finish.sh` script handles dynamic validation via these steps:

1. **Extraction**: Run `sed` or `grep` to extract the JSON payload out of the `<validator-targets>` tags in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.
2. **Parsing/Merging**: Pipe the extracted text through `jq` to ensure it is valid JSON. If valid, deep-merge this dynamic data over the static project `config.json` defaults.
3. **Target Resolution**: Determine which validators to run based on the keys present in the dynamic JSON (e.g., if `"web"` exists in the JSON, trigger `web.sh`).
4. **Execution**: Pass the extracted parameters (like `login_selector`) as environment variables to the triggered validator scripts (`~/.claude/hooks/validators/*`).
5. **Blocking**: If any validator fails, return `decision: "block"` with the validator output so Claude can fix the code (or update the context document if the code is correct but the document is stale).

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
│  context_window │     │  limits)        │     │                 │
│  + rate_limits) │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  statusline.sh  │ ◄── │  reads          │     │  limit-bridge   │
│  (displays)     │     │  limits.json    │     │  .sh (reads,    │
│  output: stdout │     │                 │     │   injects       │
└─────────────────┘     └─────────────────┘     │   directives)   │
                                                 └─────────────────┘
```

### 6.2 `limit-collector.sh` Hook (NEW)

- Triggered on `PostToolUse` (or `UserPromptSubmit`).
- Extracts `context_window.used_percentage` and `rate_limits.{five_hour,seven_day}` from stdin.
- Writes to `state/<project-key>/limits.json` with throttling (≤ once per 5 seconds).
- If `rate_limits` is unavailable (older version), writes `"n/a"` for those fields.

### 6.3 Statusline (`statusline.sh`)

- Invoked by Claude Code on every refresh. Refresh triggers:
  - After each assistant message
  - After `/compact` completes
  - When permission mode changes
  - Claude applies a built‑in **300 ms debounce** – you cannot control this.
- Reads the statusline JSON from stdin (official schema: `model`, `workspace`, `cost`).
- **Reads** `state/<project-key>/limits.json` to get current percentages.
- Prints its display to **stdout** (per official protocol). The display should include: current model, branch + dirty count, last report status, and the three percentages with tiered colour coding (🟡 / 🟠 / 🔴).
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
- **`context_extractor.sh`**: A robust bash script to safely extract, `jq`-validate, and merge the XML-fenced JSON from `.claude/validator_context.md`.
- **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary.
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
4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented.
5. **`hooks/config.overlay.example.json`** — Documented example for project overlays, showing that static validation targets are deprecated in favor of the dynamic `.claude/validator_context.md`.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, explanation of the dynamic markdown validation logic, correct output channel (**stdout**), statusline architecture, `if`/`args`/`shell`/`asyncRewake` usage, and version requirements (`rate_limits` requires v2.1.80+, `PermissionDenied` retry requires v2.1.88+).
7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification).
9. **`hooks/statusline.sh`** — Upgraded statusline script (outputs to **stdout**, reads `limits.json` from state).
10. **`hooks/limit-collector.sh`** — NEW: extracts `context_window` and `rate_limits` from stdin, writes to `limits.json`.
11. **`hooks/validators/`** — Context‑aware validator scripts per target type.
12. **`hooks/test/run.sh`** — A simple test runner that invokes each script with `--test` and verifies exit codes and JSON validity. BATS is optional but recommended.

---

## 10. Security & Sandboxing (Expanded)

Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. The following practices are **mandatory**:

1. **Always quote shell variables**: Use `"$FILE_PATH"` not `$FILE_PATH`.
2. **Use `args` field for exec form**: For hooks handling user-provided paths, use `args` to avoid shell injection entirely.
3. **Validate JSON before parsing**: Use `jq --exit-status` to validate JSON from stdin before extracting fields.
4. **Sanitize inputs**: Strip `..`, `~`, and control characters from file paths.
5. **Use `if` conditions**: Pre-filter hooks with `if` to avoid processing irrelevant tool calls.
6. **Set timeouts**: Every hook must have a `timeout` to prevent hanging.

**Example of safe exec form**:
```json
{ "type": "command", "command": "/usr/bin/jq", "args": [".", "/path/to/file.json"] }
```

**Example of unsafe (avoid)**:
```json
{ "type": "command", "command": "jq . /path/to/file.json" }
```

---

## 11. Acceptance Criteria

### A. Functionality

- [ ] `claude --debug` shows each hook firing on its intended event and no others.
- [ ] Every script passes its `--test` mode against fixtures (including malformed JSON).
- [ ] Bash guard blocks `rm -rf /` and `git push --force origin main` (exit 2) and allows `ls`, `git status`.
- [ ] Stop hook blocks completion when a test is broken, allows when fixed—without looping.
- [ ] Bridge hook: silent below Notice tier; ≤50‑token advisory exactly once at Warning tier; wind‑down directive at Action tier. Dedupe works.
- [ ] `rate_limits` fallback: missing data degrades to context‑only, shows "n/a", never crashes.
- [ ] Statusline renders correctly from state, updates after hooks fire, degrades gracefully on missing state (<100 ms). Output is sent to **stdout**.
- [ ] Validators catch deliberately introduced faults and block Stop; after fix, Stop allowed.
- [ ] Session touching only unmapped files (when `validation.file_map` is present) triggers no remote probes.
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up session manifests.
- [ ] Repo tidiness (on `SessionEnd`): quarantines only scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.
- [ ] Multi‑project: two different stacks (Node/Python/no toolchain) each adapt, no‑toolchain no‑ops cleanly, state/logs namespaced with no cross‑contamination.
- [ ] Project with no config overlay runs safely on pure global defaults.
- [ ] `StopFailure` and `PostToolUseFailure` hooks fire on errors and log without blocking.
- [ ] `PermissionRequest` hook (if enabled) auto‑approves allowlisted commands and denies others; `PermissionDenied` hook logs and optionally retries (v2.1.88+).
- [ ] `limit-collector.sh` correctly writes `limits.json` from stdin data; statusline reads it correctly.

### B. Performance & Token Discipline

- [ ] No hook output injected exceeds 500 tokens (verify from debug transcript).
- [ ] Formatting hook completes < 2 s on largest file; PreToolUse guards < 500 ms.
- [ ] Compaction completes successfully at 85 % context threshold (headroom proven).
- [ ] Statusline < 100 ms; state file writes throttled to ≤ once per 5 s.

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

---

## 12. Out of Scope

- **HTTP, Prompt, MCP, and Agent hook types**: This system uses `command` hooks exclusively. Prompt hooks incur LLM cost; HTTP hooks add network dependencies; Agent and MCP hooks are for external state and advanced workflows.
- **MCP tool hooks**: MCP tool interaction is not covered. This system focuses on Claude Code's native tools (`Bash`, `Read`, `Write`, `Edit`).
- **Project‑level hook logic**: Repositories carry at most an optional config overlay (`.claude/hooks/config.json`), never scripts or hook entries.
- **Any hook that auto‑approves write or network operations** beyond the defined allowlist.
- **Retrying on `PostToolUseFailure`**: We only log.
- **Subagent, Task, Teammate, Worktree, Elicitation, and configuration change events**: These are out of scope for v1. The system focuses on the core development workflow events (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd`).

---

## 13. Version History

| Version | Changes |
|---------|---------|
| **v1** | Initial specification |
| **v2** | Clarified Stop hook blocking, config merge rules, project‑key derivation |
| **v3** | Added `validation.file_map`, clarified statusline role, auto‑compact control, malformed overlay handling |
| **v4** | Added input JSON schema, report contract example, statusline script behaviour, git‑tracked check command, merge rules for nested objects, missing tools handling, janitor session manifests, restore script usage, test harness, auto‑compact env var |
| **v5** | Added version note for `rate_limits` (v2.1.80+), `Notification` event with `agent_completed` (optional), `timeout` column, statusline refresh triggers and 300 ms debounce, `$CLAUDE_PROJECT_DIR` vs `cwd` clarification |
| **v6** | Added `StopFailure`, `PostToolUseFailure`, `PreCompact`, `PostCompact`, moved repo tidiness to `SessionEnd`, added optional `PermissionRequest`/`PermissionDenied`, removed unconfirmed `agent_completed` matcher |
| **v7** | Fixed statusline output to **stdout**, added missing events, event frequency categories, `settings.json` structure, `$CLAUDE_PROJECT_DIR` usage examples, plugin hook merging details, hook type comparison table, enterprise `allowManagedHooksOnly` note |
| **v8** | *(intermediate)* |
| **v9** | Added dynamic context (`validator_context.md`), `SessionStart` directive, context extractor library, security/sandboxing note |
| **v10** | **Major revision**: Fixed statusline architecture (statusline reads from state file, not stdin), added `limit-collector.sh` hook, added `if`/`args`/`shell`/`asyncRewake` fields, updated statusline input schema to official format, added full hook type comparison, added `PermissionDenied` version note, added security requirements (variable quoting, `args` usage), expanded acceptance criteria |

---

**This v10 specification is fully aligned with official Claude Code hooks documentation and ready for implementation.**