# Build a Token‑Efficient Hook Automation System for Claude Code (v9)

## Executive Summary

This document specifies a **user‑level automation layer** (`~/.claude/`) for Claude Code that intercepts deterministic tasks—formatting, linting, validation, indexing—and executes them via local scripts instead of LLM tool calls[cite: 7]. It is token‑efficient, injecting only compact structured reports (≤500 tokens) back into the model's context[cite: 7].

The system is designed for a **single installation that must serve every project**, regardless of language, stack, or deployment target[cite: 7]. All project‑specific behaviour is resolved at runtime through a layered configuration mechanism (global defaults + per‑project overlays) and **dynamic, LLM-maintained context files**[cite: 7]. Success is measured by fewer round trips, smaller context injections, and zero regressions across all projects—including those that do not yet exist[cite: 7].

---

## 1. Ground Rules (Read Before Implementing)

1.  **Native Hook System**: Use Claude Code's official hook system exclusively[cite: 7]. Hooks reside in `~/.claude/settings.json` (user‑level)[cite: 7]. All scripts live under `~/.claude/hooks/`[cite: 7]. **Do not** invent a custom event bus or place hook logic inside individual repositories[cite: 7].
2.  **Official Reference**: Consult the hooks documentation for the current event list, stdin JSON schema, and output protocol before building[cite: 7]. The event set may change between versions—do not rely on memory[cite: 7].
3.  **Script Invocation**: Every hook entry must invoke a script in `~/.claude/hooks/`[cite: 7]. No inline logic in `settings.json` beyond the script path[cite: 7]. Scripts are the unit of testing and reuse[cite: 7].
4.  **Hook Protocol Compliance**:
    *   Scripts read a single JSON object from stdin[cite: 7].
    *   **Exit codes**: `0` = proceed; `2` = block (stderr is surfaced as the reason)[cite: 7]. Other codes = non‑blocking error[cite: 7].
    *   **Structured control**: Use JSON on stdout (`hookSpecificOutput` with `permissionDecision` for `PreToolUse`; `decision`/`reason` for `Stop`; `additionalContext` to inject context)[cite: 7]. **Note**: `Stop` hooks block via JSON (`decision: "block"`), **not** via exit code 2[cite: 7]. For all other hooks, `exit 2` is the blocking mechanism[cite: 7].
5.  **Token Discipline**:
    *   Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr[cite: 7].
    *   Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`[cite: 7].
    *   Only a summary report is returned to the model, **capped at 500 tokens** (~2 000 characters)[cite: 7]. If results exceed that, summarize counts and include the log file path for on‑demand retrieval[cite: 7].
6.  **Performance**: `PreToolUse` hooks gate matched tool calls—target **< 500 ms**[cite: 7]. Slower operations (test suites, indexing) belong on `PostToolUse`, `Stop`, or run with `"async": true`[cite: 7].
7.  **Chaining**: Chaining is not native[cite: 7]. Implement it inside a script (Script A calls Script B) or via a shared state file[cite: 7]. Document each chain explicitly[cite: 7].
8.  **Safety**: Never auto‑approve destructive operations[cite: 7]. `PreToolUse` may auto‑allow **only** an explicit allowlist of read‑only or idempotent commands[cite: 7]. Blocking `PreToolUse` and `PostToolUse` hooks use `exit 2`; `Stop` hooks use JSON `decision: "block"`[cite: 7]. Exit code `1` only warns[cite: 7].
9.  **Loop Guard**: Any `Stop` hook must check the `stop_hook_active` field in the stdin JSON and `exit 0` when `true`[cite: 7].
10. **Audit Before Build**: Inventory existing hooks/scripts in `~/.claude/settings.json`, `~/.claude/hooks/`, and project‑level `.claude/settings.json`[cite: 7]. **Upgrade or retire** every existing user‑level item to meet these standards[cite: 7]. Document each in `MIGRATION.md`[cite: 7]. Do not run old and new conventions side‑by‑side[cite: 7].
11. **Zero Hardcoded Values**:
    *   **Paths**: Derive everything from stdin (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`[cite: 7]. The only permitted absolute anchor is `$HOME/.claude/...`[cite: 7]. Never use literal `/home/<user>/`[cite: 7].
    *   **Project specifics**: Discover at runtime (e.g., from `package.json`, `Makefile`, `pyproject.toml`)[cite: 7]. Formatters/linters are detected per project; if none exist, the hook no‑ops silently[cite: 7]. Default branch is read from `git remote show origin` (or equivalent)—never assumed to be `main`[cite: 7].
    *   **Tunables**: Every threshold, cap, timeout, and allowlist lives in config—scripts read config, never embed numbers[cite: 7].
    *   **Dynamic API**: Field names are read defensively[cite: 7]. Missing/renamed fields degrade gracefully (e.g., `rate_limits` fallback) rather than crashing[cite: 7].
    *   **Portability**: All scripts must run on macOS and Linux (and Windows via WSL/Git Bash) without modification[cite: 7]. Use POSIX‑compliant constructs or `#!/usr/bin/env bash`[cite: 7].
12. **Layered Configuration**:
    *   **Global Defaults**: `~/.claude/hooks/config.json`[cite: 7].
    *   **Project Overlay**: `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json`[cite: 7]. Deep-merged over global defaults for static lists/thresholds.
    *   **Dynamic Context (NEW)**: Changing project data (DOM selectors, API endpoints) lives in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.
    *   **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`[cite: 7].
    *   **Secrets**: Read from the project's `.env` at runtime[cite: 7]. Global config stores variable *names*, never values[cite: 7].
13. **Security & Sandboxing**: Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. You must aggressively validate/sanitize JSON inputs and quote all shell variables (e.g., `"$FILE_PATH"` instead of `$FILE_PATH`) to prevent shell injection from the model's output.

### 1.1 Input JSON Schema (from Claude Code)

Hook scripts receive a JSON object with at least the following fields (additional fields may exist)[cite: 7]. 
*Note: The `rate_limits` field is available from **Claude Code v2.1.80** onward. If you are on an older version, it will be absent; scripts must handle this gracefully.*[cite: 7]

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

**Note on `cwd` vs `$CLAUDE_PROJECT_DIR**`:

* `cwd` is the current working directory **where the tool was invoked** (may be a subdirectory).


* `$CLAUDE_PROJECT_DIR` is an environment variable set by Claude Code to the **project root** (the directory containing `.claude/`).



### 1.2 Report Contract (Summary)

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

**Retry Protocol:** For the `PermissionDenied` event specifically, to trigger a retry for a denied tool call, the hook must print `{"retry": true}` to stdout.

---

## 2. System Architecture

The following diagram illustrates the data flow. The implementation must match this wiring exactly.

```
                        ┌─────────────────────────── Claude Code (any project) ───────────────────────────┐
                        │                                                                                  │
 EVENTS                 │  SessionStart · Setup · UserPromptSubmit · PreToolUse · PostToolUse · Stop       │
                        │  + StopFailure · PostToolUseFailure · PostToolBatch · PreCompact · PostCompact  │
                        │  + PermissionRequest · PermissionDenied (optional)                              │
                        └───────┬───────────────┬────────────────┬─────────────┬──────────────┬───────────┘
                                │ stdin JSON    │                │             │              │
                                ▼               ▼                ▼             ▼              ▼
                        ┌──────────────────────── ~/.claude/hooks/ (user level, all projects) ────────────┐
 HOOK SCRIPTS           │  context.sh      limit-bridge.sh   guards.sh     format.sh      finish.sh       │
                        │  (Injects     ◄─┐ (reads state,    (bash guard,  index.sh       (tests +        │
                        │   directive to  │  injects tier    protected     (async)        dynamic         │
                        │   update        │  directives)     paths)        manifest.sh    validators +    │
                        │   context.md)   │                                (track writes) (on Stop)       │
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
 STATUSLINE             statusline.sh ── writes limits.json ─────────┘   ← sole producer of limit metrics
 (bridge + display)     displays: model · branch · last report status · 3 limit gauges (🟡🟠🔴)
                                │  **Output to stdout**
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / browser / HTTP)
 (Stop hook, using      parameters extracted from `<validator-targets>` JSON in validator_context.md
  dynamic context)

```

---

## 3. Configuration & Project Layering

### 3.1 Global Defaults & Static Overlay (`config.json`)

* **Limits**: Context window (60 %/75 %/85 %), Session (60 %/75 %/90 %), Weekly (70 %/85 %/95 %).


* **Retention**: `logs_days` (14), `state_days` (60), `screenshots_days` (7), `trash_days` (7).


* **Protected paths**: `.env*`, `*.pem`, `/etc/passwd`, etc.


* **Scratch patterns**: `*.tmp`, `scratch*`, `debug_*`, `test_output*`, `*.bak`.



### 3.2 Dynamic Context: The Living Document (NEW)

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

### 3.3 Official `settings.json` Structure

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
          { "type": "command", "command": "~/.claude/hooks/guards.sh", "timeout": 5 }
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
    "command": "~/.claude/hooks/statusline.sh",
    "padding": 0
  }
}

```

* **Exception**: For the `FileChanged` event specifically, the `matcher` field is used to specify *which filenames to watch on disk* (e.g., `src//*.ts`), rather than matching a tool name.
* Plugin hooks are auto‑merged; use `${CLAUDE_PLUGIN_ROOT}` to reference plugin files.



---

## 4. Hook Script Specifications

### 4.1 Hook Type Comparison (Official)

| Type | Description | LLM Cost | Use Case |
| --- | --- | --- | --- |
| **Command** | Shell script execution | None | Deterministic tasks (formatting, guards, validation)

 |
| **Prompt** | LLM evaluates a prompt to decide | LLM tokens per call | Complex decision‑making requiring understanding

 |
| **HTTP** | HTTP endpoint call | None | Remote orchestration, webhooks

 |
| **MCP** | Model Context Protocol integration | Tokens per response | Providing additional external contextual state |
| **Agent** | Sub-agent workflow execution | High LLM compute | Complex multi-step task delegation |

**This system uses Command hooks exclusively**—they are deterministic, have no LLM cost, and are the most predictable for automation.

### 4.2 Initial Hook Set (v9)

| Event | Matcher | Script | Purpose | Blocking | Timeout (s) |
| --- | --- | --- | --- | --- | --- |
| `PostToolUse` | `Write|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain.

 | No | 30 |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to default branch).

 | Yes (`exit 2`) | 5 |
| `PreToolUse` | `Read|Edit|Write` | `guards.sh` | Deny access to `.env*`, keys, and protected paths.

 | Yes (`exit 2`) | 5 |
| `Stop` | — | `finish.sh` | Extract JSON from `validator_context.md`, run context‑aware validators. Block stop if failures occur. | Yes (`decision: "block"`) | 120 |
| `StopFailure` | — | `error-recovery.sh` | Log API error details; no blocking (output ignored).

 | No | 5 |
| `PostToolUseFailure` | `Write|Edit` | `error-recovery.sh` | Log write failure; just log.

 | No | 5 |
| `PostToolBatch` | — | `error-recovery.sh` | Log batch completion; optional summary.

 | No | 5 |
| `PreCompact` | — | `compact-monitor.sh` | Update state with pre‑compact percentages.

 | No | 5 |
| `PostCompact` | — | `compact-monitor.sh` | Update state after compaction; log token savings.

 | No | 5 |
| `SessionStart` | — | `context.sh` | Inject compact project context AND the directive to update `.claude/validator_context.md` if architecture changes. | No | 10 |
| `SessionStart` (async) | — | `janitor.sh` | Retention‑based cleanup of own logs/state/trash.

 | No | 60 |
| `PostToolUse` (async) | `Write` | `manifest.sh` | Record files *created* by Claude this session.

 | No | 5 |
| `SessionEnd` | — | `finish.sh` | **Repo tidiness**: classify manifest entries as scratch, quarantine, report count.

 | No | 30 |
| `PostToolUse` (async) | `Write|Edit` | `index.sh` | Update project index/dependency graph in background.

 | No | 30 |
| **Optional** `PermissionRequest` | `Bash` | `permission-helper.sh` | Auto‑allow read‑only/idempotent commands from allowlist.

 | Yes (`permissionDecision`) | 5 |
| **Optional** `PermissionDenied` | `Bash|Write|Edit` | `retry-handler.sh` | If a command was denied, optionally retry (via `{"retry": true}`).

 | No (output ignored) | 5 |

---

## 5. Context‑Aware Validation (Dynamic)

Code‑level checks are insufficient—validation must extend to the running system (VPS, email, web app, etc.).

### 5.1 The `SessionStart` Directive

The `context.sh` hook must now inject the following strict directive via `additionalContext` when a session starts:

> *"If you modify core architectural elements, API endpoints, or UI selectors during this session, you MUST update the JSON block inside the `<validator-targets>` tags in `.claude/validator_context.md` before stopping."*

### 5.2 Validator Execution (`finish.sh` Stop Hook)

When Claude attempts to stop, the `finish.sh` script handles dynamic validation via these steps:

1. **Extraction**: Run `sed` or `grep` to extract the JSON payload out of the `<validator-targets>` tags in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.
2. **Parsing/Merging**: Pipe the extracted text through `jq` to ensure it is valid JSON. If valid, deep-merge this dynamic data over the static project `config.json` defaults.
3. **Target Resolution**: Determine which validators to run based on the keys present in the dynamic JSON (e.g., if `"web"` exists in the JSON, trigger `web.sh`).
4. **Execution**: Pass the extracted parameters (like `login_selector`) as environment variables to the triggered validator scripts (`~/.claude/hooks/validators/*`).
5. **Blocking**: If any validator fails, return `decision: "block"` with the validator output so Claude can fix the code (or update the context document if the code is correct but the document is stale).



### 5.3 Validator Scripts (`~/.claude/hooks/validators/`)

* One script per target type (`vps.sh`, `email.sh`, `web.sh`, `api.sh`, `db.sh`).


* **Safety**: Read‑only against production by default; mutating probes target sandbox resources exclusively. Secrets from `.env` never logged.



---

## 6. Cleanup & Tidiness

Two distinct responsibilities, two risk levels.

### 6.1 Housekeeping (Own Files, Low Risk)

* `janitor.sh` runs on `SessionStart`, rate‑limited to once per `janitor_interval_hours` (global config).


* Enforces retention from global config (logs, state, screenshots, trash).


* Also cleans up session manifest files (under `state/<project-key>/manifests/`) after `state_days`.


* Orphan sweep: removes namespaces for projects that no longer exist on disk (after `state_days`).



### 6.2 Repo Tidiness (Scratch Files, Higher Risk)

* **Track**: `manifest.sh` records every file *created* by Claude this session (`PostToolUse` Write). Only files in this manifest are candidates.


* **Classify at session end** (`finish.sh` on `SessionEnd`): Entries matching scratch patterns (from config) and **not** committed, not in the `keep` list, and not in protected paths are classified as scratch.


* *Git‑tracked check*: Use `git ls-files --error-unmatch <file> >/dev/null 2>&1`; if it returns 0, the file is tracked and **must never** be touched.




* **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths.


* **Report**: Include `details.scratch_quarantined: N` in the Stop report.


* **Restore**: `restore.sh` moves a quarantined session back to its original location.



---

## 7. Shared Library (`lib/`)

Implement the following as shared modules:

* **`config.sh`**: Loads global config, checks for overlay, deep‑merges per merge rules, validates schema/version.


* **`context_extractor.sh` (NEW)**: A robust bash script to safely extract, `jq`-validate, and merge the XML-fenced JSON from `.claude/validator_context.md`.
* **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary.


* **`project_key.sh`**: Derives the project key from `cwd` (deterministic slug + short hash).


* **`restore.sh`**: Helper to restore quarantined session files.


* **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.



---

## 8. Statusline & Limit Monitoring

The statusline is **not a hook** – it is a separate `statusLine` command configured in `~/.claude/settings.json`. It is the sole producer of limit metrics; the bridge hook (`limit-bridge.sh`) is the sole consumer.

### 8.1 Statusline (`statusline.sh`)

* Invoked by Claude Code on every refresh. Refresh triggers:


* After each assistant message


* After `/compact` completes


* When permission mode changes


* Claude applies a built‑in **300 ms debounce**.




* Reads the statusline JSON from stdin.


* Writes current **Context %**, **Session 5‑hour %**, and **Weekly %** to `state/<project-key>/limits.json` on every refresh.
*Important*: Implement a write throttle – do not write more than once every 5 seconds to avoid disk thrashing.


* Prints its display to **stdout**. The display should include: current model, branch + dirty count, last report status, and the three percentages with tiered colour coding (🟡 / 🟠 / 🔴).


* **Performance**: Target < 100 ms. If state files are missing/stale, display placeholders (`n/a`). Never throw errors.



### 8.2 Limit Tiers & Bridge Hook (`limit-bridge.sh`)

* **Warning (75%)**: Statusline change + **one‑time** `additionalContext` line (≤50 tokens) from `limit-bridge.sh`. Dedupe via `state/<project-key>/limit_alerts.json`.


* **Action (85-95%)**: `limit-bridge.sh` injects a high‑priority wind‑down directive via `additionalContext`; logs the event; statusline turns red.


* **Auto‑compact**: The hook system does **not** set this; users should set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in their environment.



---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration with narrow matchers, explicit `timeout` fields, and `statusLine` entry.


2. **`hooks/`** — Executable scripts per hook, each with stdin parsing, error handling, timing, `--test` mode.


3. **`hooks/lib/`** — Shared library (config, report, context extractor, project‑key, restore, logging).


4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented.


5. **`hooks/config.overlay.example.json`** — Documented example for project overlays, showing that static validation targets are deprecated in favor of the dynamic `.claude/validator_context.md`.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, explanation of the dynamic markdown validation logic, and correct output channel (**stdout**).


7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).


8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification).


9. **`hooks/statusline.sh`** — Upgraded statusline script (outputs to **stdout**).


10. **`hooks/validators/`** — Context‑aware validator scripts per target type.


11. **`hooks/test/run.sh`** — A simple test runner that invokes each script with `--test` and verifies exit codes and JSON validity.



---

## 10. Acceptance Criteria

* [ ] `SessionStart` successfully injects the markdown update directive into Claude's context.
* [ ] The Stop hook gracefully skips remote validation if `.claude/validator_context.md` does not exist or contains no `<validator-targets>` tags.
* [ ] The Stop hook strictly parses the XML-fenced JSON using `jq`. If Claude outputs malformed JSON in the document, the hook catches it and blocks the stop, instructing Claude to fix its JSON syntax.
* [ ] Extracted properties (e.g., specific DOM selectors) are successfully passed to the underlying validator scripts without breaking bash quoting rules.
* [ ] Bash guard blocks `rm -rf /` and `git push --force origin main` (exit 2) and allows `ls`, `git status`.


* [ ] Statusline renders correctly from state, updates after hooks fire, degrades gracefully on missing state (<100 ms), output sent to **stdout**.


* [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up session manifests.


* [ ] Repo tidiness (on `SessionEnd`): quarantines only scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.


* [ ] Removing hooks from `settings.json` restores stock behaviour—no side effects outside intended formatting and `~/.claude/hooks/` state/logs.


* [ ] Scripts sanitize JSON values and fully quote variables to eliminate shell injection surfaces.

---

## 11. Out of Scope

* **HTTP, Prompt, MCP, and Agent hook types**: This system uses `command` hooks exclusively. Prompt hooks incur LLM cost; HTTP hooks add network dependencies; Agent and MCP hooks are for external state and advanced workflows.


* **Project‑level hook logic**: Repositories carry at most an optional config overlay (`.claude/hooks/config.json`), never scripts or hook entries.


* **Subagent, Task, Teammate, Worktree, Elicitation, and configuration change events**: These are out of scope for v1. The system focuses on the core development workflow events (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd`).

