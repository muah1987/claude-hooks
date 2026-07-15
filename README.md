# Build a Token‑Efficient Hook Automation System for Claude Code (v13)

## Summary of Changes from v12

| Area | v12 (broken/wrong) | v13 (fixed) |
|------|-----|-----|
| **Limit data flow** | Claimed hook stdin carries `context_window`/`rate_limits`; statusline "does NOT receive" them; `limit-collector.sh` on PostToolUse | **Inverted back to the correct architecture** (as in the original spec): the *statusline* stdin carries `context_window`, `exceeds_200k_tokens`, and (Pro/Max, recent versions) `rate_limits`. The statusline writes `limits.json`; `limit-collector.sh` is **deleted** |
| **`limit-bridge.sh` wiring** | Specified but registered nowhere; no `UserPromptSubmit` entry existed | Wired on `UserPromptSubmit` in the hook table and `settings.json`; also injects async validator results |
| **Hook input schema (§1.1)** | Fabricated fields and a fabricated "v2.1.80" version claim | Replaced with the officially documented common fields; version claims removed |
| **`if` condition (§1.6)** | Described as case‑sensitive regex; example `"if": "rm -rf\|push --force"` | Corrected to **permission‑rule syntax** (`Bash(rm *)`), tool events only, best‑effort/fails‑open; guard patterns moved to config; the script always re‑checks |
| **`format.sh` event** | Registered under `PreToolUse` in the settings example (file not yet written; violates own <500 ms rule) | Registered under `PostToolUse`, matching the hook table |
| **Stop blocking** | "Stop hooks block via JSON, **not** exit 2" | Both work: exit 2 blocks Stop, or exit 0 + JSON `decision:"block"`. New rule: **JSON is only processed on exit 0** — one channel per script |
| **PostToolUse blocking** | Rule 8 called PostToolUse "blocking via exit 2" | PostToolUse cannot block (tool already ran); exit 2 only surfaces stderr to Claude; JSON `decision:"block"` prompts feedback without undoing |
| **PermissionDenied retry** | Bare `{ "retry": true }` | Correct shape: `hookSpecificOutput.retry: true`; version claim softened |
| **`limits.json` fields** | Stored `rate_limits.*.used` (not a percentage) while tiers compare percentages | Stores `used_percentage` (+ `resets_at`) directly from the statusline payload |
| **Malformed dynamic context** | §5.2 said "skip", §3.2 and acceptance said "block" — contradiction | One rule: block only when the project *declares* validation targets; otherwise skip |
| **Manifest path** | `manifest-<sid>.json` in one section, `manifests/` dir in another | Canonical: `state/<project-key>/manifests/<session-id>.json` everywhere |
| **Async validators** | "Launch with `asyncRewake`" (a settings field, not applicable to script‑spawned children); results injector unwired | Detached background jobs + pending‑state file; results injected by the (now wired) `limit-bridge.sh` on next `UserPromptSubmit`; weakened‑guarantee caveat documented |
| **Secrets loading** | `source $PROJECT/.env` (executes repo‑controlled shell code) | Safe line‑by‑line `KEY=VALUE` parser with an allowlist of variable names from config; never `source` |
| **FileChanged note** | Wrong (glob `src//*.ts`); event unused anyway | Removed |
| **Minor** | Naming drift (`format` vs `post-edit-format`), `~` in log paths, MCP‑tool cost row wrong, hardcoded `main` in acceptance test unlabeled | Unified hook names, expanded absolute log paths, hook‑type table corrected, test fixture labeled as fixture |

---

# Full v13 Specification

## Executive Summary

This document specifies a **user‑level automation layer** (`~/.claude/`) for Claude Code that intercepts deterministic tasks—formatting, linting, validation, indexing—and executes them via local scripts instead of LLM tool calls. It is token‑efficient, injecting only compact structured reports (≤500 tokens) back into the model's context.

The system is designed for a **single installation that must serve every project**, regardless of language, stack, or deployment target. All project‑specific behaviour is resolved at runtime through a layered configuration mechanism (global defaults + per‑project overlays) and **dynamic, LLM‑maintained context files**. Success is measured by fewer round trips, smaller context injections, and zero regressions across all projects—including those that do not yet exist.

---

## 1. Ground Rules (Read Before Implementing)

1.  **Native Hook System**: Use Claude Code's official hook system exclusively. Hooks reside in `~/.claude/settings.json` (user‑level). All scripts live under `~/.claude/hooks/`. **Do not** invent a custom event bus or place hook logic inside individual repositories.
2.  **Official Reference**: Consult the hooks documentation (https://code.claude.com/docs/en/hooks) and the statusline documentation for the current event list, stdin JSON schemas, and output protocol before building. The event set and field names change between versions—**do not rely on memory, and do not rely on this document's schema excerpts either**: re‑verify against the live docs at implementation time.
3.  **Script Invocation**: Every hook entry must invoke a script in `~/.claude/hooks/`. No inline logic in `settings.json` beyond the script path. Scripts are the unit of testing and reuse. Pattern lists (dangerous commands, protected paths) live in config (rule 12), never in `settings.json`.
4.  **Hook Protocol Compliance**:
    - Scripts read a single JSON object from stdin.
    - **Exit codes**: `0` = proceed; `2` = block **on events that support blocking** (stderr is surfaced as the reason). Exit `1` and other non‑zero codes = non‑blocking error (exit 1 does **not** block—this is the single biggest hook footgun).
    - **Structured control**: exit `0` and print JSON to stdout. For `PreToolUse`, use `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`) with `permissionDecisionReason`. For `Stop`, use top‑level `decision: "block"` with `reason`. For context injection, use `hookSpecificOutput.additionalContext` with the matching `hookEventName`.
    - **One channel per script**: JSON on stdout is **only processed on exit code 0**. If a script exits 2, any JSON it printed is discarded and only stderr is used. A script must therefore choose: exit‑code signaling *or* exit‑0‑plus‑JSON—never both in the same code path.
    - **Blocking semantics per event** (verify against the docs' exit‑code table): `PreToolUse` blocks the tool; `Stop` blocks completion (via exit 2 *or* JSON `decision:"block"`—both are valid; this system standardizes on JSON so the block can carry a structured report); `PostToolUse` **cannot block**—the tool already ran; exit 2 there only feeds stderr to Claude, and JSON `decision:"block"` prompts Claude with feedback without undoing anything; `SessionEnd`, `SessionStart`, `PostCompact`, `StopFailure` cannot block at all.
5.  **Token Discipline**:
    - Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr.
    - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`.
    - Only a summary report is returned to the model, **capped at 500 tokens** (~2 000 characters; well inside the platform's 10 000‑character hook‑output cap). If results exceed that, summarize counts and include the log file path for on‑demand retrieval.
6.  **Performance**: `PreToolUse` hooks gate matched tool calls—target **< 500 ms**. Slower operations (formatting, test suites, indexing) belong on `PostToolUse`, `Stop`, or run with `"async": true`.
7.  **Chaining**: Chaining is not native. Implement it inside a script (Script A calls Script B) or via a shared state file. Document each chain explicitly.
8.  **Safety**: Never auto‑approve destructive operations. `PreToolUse` may auto‑allow **only** an explicit allowlist of read‑only or idempotent commands. Enforcement guards live on `PreToolUse` (the only tool event that can prevent execution). The `if` pre‑filter is best‑effort and **fails open** (see §1.6), so the guard script itself always re‑validates against config; for hard, non‑negotiable denies, prefer the native permission system (`permissions.deny` rules) over hooks and note this in the README.
9.  **Loop Guard**: Any `Stop` hook must check the `stop_hook_active` field in the stdin JSON and `exit 0` when `true`.
10. **Audit Before Build**: Inventory existing hooks/scripts in `~/.claude/settings.json`, `~/.claude/hooks/`, and project‑level `.claude/settings.json`. **Upgrade or retire** every existing user‑level item to meet these standards. Document each in `MIGRATION.md`. Do not run old and new conventions side‑by‑side.
11. **Zero Hardcoded Values**:
    - **Paths**: Derive everything from stdin (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`. The only permitted absolute anchor is `$HOME/.claude/...`. Never use literal `/home/<user>/`. All paths emitted in reports (e.g. the `log` field) are **expanded absolute paths**, never `~`‑prefixed, so the model can pass them directly to file tools.
    - **Project specifics**: Discover at runtime (e.g., from `package.json`, `Makefile`, `pyproject.toml`). Formatters/linters are detected per project; if none exist, the hook no‑ops silently. Default branch resolution order: `git symbolic-ref refs/remotes/origin/HEAD` → `git remote show origin` (network) → `git symbolic-ref --short HEAD` (offline local fallback)—never assumed to be `main`.
    - **Tunables**: Every threshold, cap, timeout, allowlist, denylist, and guard pattern lives in config—scripts read config, never embed numbers or patterns.
    - **Dynamic API**: Field names are read defensively with `jq '// empty'`‑style fallbacks. Missing/renamed fields degrade gracefully rather than crashing. Do not gate behaviour on specific Claude Code version numbers; probe for field presence instead.
    - **Portability**: All scripts must run on macOS and Linux (and Windows via WSL/Git Bash) without modification. Use POSIX‑compliant constructs or `#!/usr/bin/env bash`.
12. **Layered Configuration**:
    - **Global Defaults**: `~/.claude/hooks/config.json`.
    - **Project Overlay**: `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json`. Deep‑merged over global defaults for static lists/thresholds.
        - **Merge Rules**: Scalars replaced; lists replaced unless `_append` suffix (then concatenated and deduplicated); nested objects recursively merged (overlay subtree replaces global subtree for that key).
    - **Dynamic Context**: Changing project data (DOM selectors, API endpoints) lives in `$CLAUDE_PROJECT_DIR/.claude/validator_context.md` (see Section 3.2). **Dynamic overrides are strictly limited to the `"validation"` subtree** of the merged config for security reasons. If this file or its parent directory does not exist, the system falls back to global defaults and skips remote validation (code‑level checks only).
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
    - **Secrets**: Read from the project's `.env` via the **safe parser in §3.4**—never `source`d. Global config stores variable *names* only, never values.
13. **Security & Sandboxing**: Claude Code hooks run with **full user permissions and absolutely zero sandboxing**. Mandatory practices:
    - Quote all shell variables (`"$VAR"`).
    - Use the `args` field (exec form) to avoid shell injection when a hook entry passes paths or arguments; exec form spawns the executable directly with no shell tokenization.
    - Validate JSON inputs with `jq --exit-status` before parsing.
    - Sanitize inputs (strip `..`, `~`, control characters).
    - Use `if` conditions (§1.6) to reduce process spawns—as an optimization only, never as the security boundary.
    - Set a `timeout` (seconds) on every hook entry.
    - All state file writes must be atomic: write to a temporary file (e.g., `file.tmp`) then `mv` to the final name.
    - Never execute repo‑controlled content (`.env`, scripts inside the project) from user‑level hooks; parse data files as data (§3.4).

---

### 1.1 Hook Input JSON Schema (from Claude Code)

Hook scripts receive a JSON object on stdin. Per the official reference, the **common fields** present on (nearly) all events are:

```json
{
  "session_id": "abc-123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/project/src",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "effort": { "level": "high" }
}
```

Event‑specific fields are added per event, e.g. `tool_name`, `tool_input`, `tool_use_id` on `PreToolUse`; `tool_response` on `PostToolUse`; `stop_hook_active` and `last_assistant_message` on `Stop`; `source` on `SessionStart`. `prompt_id` and `effort` may be absent on older versions or certain events—read all fields defensively.

**Hook stdin does NOT contain `context_window` or `rate_limits`.** Those fields are delivered only to the **statusline** command (§1.2). Any design that expects usage metrics inside a hook must read them from the state file the statusline maintains (§6). Do not "correct" this at implementation time based on remembered schemas—verify against the live docs; this exact inversion was the critical defect of the previous spec version.

**Note on `cwd` vs `$CLAUDE_PROJECT_DIR`**:
- `cwd` is the current working directory **where the hook was invoked** (may be a subdirectory).
- `$CLAUDE_PROJECT_DIR` is an environment variable set by Claude Code to the **project root**.
Use `$CLAUDE_PROJECT_DIR` for project‑relative configuration; use `cwd` for operations that depend on the current location. Derive the project key (§7) from the project root.

---

### 1.2 Statusline Input Schema (Official)

The statusline command receives a **richer JSON schema** than hook scripts. Representative shape (verify current fields in the statusline docs):

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "model": { "id": "claude-opus-4-6", "display_name": "Opus" },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/path/to/project"
  },
  "version": "2.1.x",
  "output_style": { "name": "default" },
  "cost": { "total_cost_usd": 0.01234 },
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "used_percentage": 8,
    "remaining_percentage": 92,
    "current_usage": { "input_tokens": 8500, "output_tokens": 1200 }
  },
  "exceeds_200k_tokens": false,
  "rate_limits": {
    "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
    "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
  }
}
```

**Critical facts (the exact opposite of what v10–v12 claimed):**
- The statusline **does** receive `context_window` (with `used_percentage` computed from *input tokens only*: input + cache‑creation + cache‑read; output tokens are excluded).
- The statusline **does** receive `rate_limits.five_hour` / `rate_limits.seven_day` (each with `used_percentage` and `resets_at`) on subscription plans and recent versions. The field can be **absent**: on API‑key billing, on some versions (there has been at least one regression that dropped it), and in the first renders after `/clear`. Handle absence gracefully.
- `context_window.current_usage` is `null` before the first API call and immediately after `/compact`.

**Consequence for the architecture**: the statusline is the **only** component that receives live usage metrics, and hooks receive none. Therefore the statusline is both the *display* and the *sole producer* of `limits.json` (§6). There is no separate collector hook.

---

### 1.3 Report Contract (Summary)

Every script that returns information to the model emits JSON with exactly these fields:

```json
{
  "hook": "format",
  "status": "ok | warn | blocked | error",
  "summary": "One sentence, human-readable.",
  "details": { "files_changed": 3, "errors": 0 },
  "log": "/home/user/.claude/hooks/logs/myproject-a1b2c3/format-2026-07-14T10:22:03.jsonl",
  "duration_ms": 142
}
```

- `hook` is the script's canonical short name (the filename without `.sh`)—one naming scheme everywhere (report, `last_status.json`, log filenames).
- `log` is an **expanded absolute path** (no `~`).
- `details` holds counts and short identifiers only—never file contents, stack traces, or diffs. The total token count of the entire JSON must not exceed 500 tokens.

**Which hooks produce a report and update `last_status.json`**: `format.sh` and `finish.sh` (on `Stop`), plus any additional hooks that emit a summary JSON. Hooks that only block via exit code (`guards.sh`) or that are purely logging (`error-recovery.sh`, `compact-monitor.sh`, `manifest.sh`, `janitor.sh`) do **not** produce a report and do **not** update `last_status.json`.

Remember rule 4: a report JSON is only read by Claude Code when the script exits 0. A blocking `Stop` report is therefore delivered as exit 0 + JSON `decision:"block"` + `reason` (the report summary embedded in `reason`), never as exit 2 + JSON.

---

### 1.4 `additionalContext` Injection Format (Official)

To inject context into the model, output the following JSON to stdout (exit 0):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Your context text here (≤500 tokens)"
  }
}
```

The `hookEventName` must match the event that triggered the hook. Write injected text as **factual statements** ("Weekly usage is at 87%"), not imperative out‑of‑band commands—text framed as system commands can trip Claude's prompt‑injection defenses and get surfaced to the user instead of read as context. Injected context is saved in the transcript and is replayed (not re‑generated) on `--resume`, so avoid volatile values where staleness would mislead.

---

### 1.5 PermissionDenied Retry Protocol (Official)

For the `PermissionDenied` event, exit code and stderr are ignored (the denial already happened). The only control surface is JSON on stdout, in the `hookSpecificOutput` wrapper:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionDenied",
    "retry": true
  }
}
```

This tells the model it may retry the denied tool call. The event is comparatively recent—probe for support rather than pinning a version number; on versions without it, the hook simply never fires.

---

### 1.6 `if` Condition Syntax

The `if` field on a hook handler uses **permission‑rule syntax**, the same syntax as Claude Code permission rules—**not** a regular expression. Examples: `"if": "Bash(rm *)"` (any Bash subcommand matching `rm *`), `"if": "Bash(git push *)"`, `"if": "Edit(*.ts)"`. Exactly one rule per `if`; there is no `&&`/`||`—use separate handlers for multiple conditions.

Semantics to respect:
- Only evaluated on **tool events** (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`). On other events a handler with `if` set never runs.
- For Bash, each **subcommand** is checked (so `npm test && git push` matches `Bash(git *)`), leading `VAR=value` assignments are stripped, and commands inside `$()`/backticks are inspected.
- The filter is **best‑effort and fails open**: unparseable commands run the hook anyway, and patterns more specific than the command name run on `$()`/backtick/`$VAR` constructs regardless.

Therefore: use `if` purely as a **spawn‑count optimization**. The guard script must always re‑validate the full command against the configured patterns, and hard denies belong in the native permission system.

---

### 1.7 Last Report Status State File

Every hook script that produces a report (per the list in §1.3) **must** also write its `status` and `summary` to a shared state file:

`~/.claude/hooks/state/<project-key>/last_status.json`

```json
{
  "hook": "format",
  "status": "ok",
  "summary": "Formatted 3 files",
  "timestamp": "2026-07-14T10:22:03Z"
}
```

Written atomically (`.tmp` + `mv`). This file is read by the statusline to display the last report status.

---

### 1.8 `limits.json` Format

Written by **`statusline.sh`** (the sole producer—see §6) to `state/<project-key>/limits.json`:

```json
{
  "context_pct": 42,
  "five_hour_pct": 23.5,
  "five_hour_resets_at": 1738425600,
  "seven_day_pct": 41.2,
  "seven_day_resets_at": 1738857600,
  "timestamp": "2026-07-14T10:22:03Z"
}
```

- `context_pct`: `context_window.used_percentage` (number), or `null` if absent.
- `five_hour_pct` / `seven_day_pct`: `rate_limits.<window>.used_percentage` (number), or `null` if `rate_limits` is unavailable (API billing, older/regressed versions, first renders of a session).
- `*_resets_at`: epoch seconds passthrough, or `null`.
- `timestamp`: ISO‑8601 time of the write, used by consumers to detect staleness.

All writes atomic (`limits.json.tmp` → `mv`), throttled to ≤ once per 5 seconds via a timestamp/mtime check so the ~300 ms statusline refresh cadence doesn't hammer the disk.

---

## 2. System Architecture

The following diagram illustrates the data flow. The implementation must match this wiring exactly.

```
                        ┌─────────────────────────── Claude Code (any project) ───────────────────────────┐
                        │                                                                                  │
 EVENTS                 │  SessionStart · UserPromptSubmit · PreToolUse · PostToolUse · Stop · SessionEnd  │
                        │  + StopFailure · PostToolUseFailure · PreCompact · PostCompact                   │
                        │  (other documented events exist — see §4.3 for deliberate exclusions)            │
                        └───────┬───────────────┬────────────────┬─────────────┬──────────────┬───────────┘
                                │ stdin JSON    │                │             │              │
                                ▼               ▼                ▼             ▼              ▼
                        ┌──────────────────────── ~/.claude/hooks/ (user level, all projects) ────────────┐
 HOOK SCRIPTS           │  context.sh      limit-bridge.sh    guards.sh     format.sh      finish.sh      │
                        │  (SessionStart:  (UserPromptSubmit: (PreToolUse:  (PostToolUse:  (Stop: tests + │
                        │   inject project  reads limits.json  bash guard +  format+lint    validators;   │
                        │   context +       → tier directives; protected     after write)   SessionEnd:   │
                        │   validator       injects pending    paths;        manifest.sh    repo-tidy —   │
                        │   directive)      async validator    Read|Edit|    (PostToolUse:  branches on   │
                        │   janitor.sh      results)           Write)        track writes)  hook_event_   │
                        │   (SessionStart,                                   index.sh       name)         │
                        │    async)                                          (async index)                │
                        └───────┬───────────────┬──────────────┬─────────────┬──────────────┬─────────────┘
                                │               │              │             │              │
                                ▼               ▼              ▼             ▼              ▼
 SHARED LIB             ┌  lib/: config.sh · context_extractor.sh · report.sh · project_key.sh ·          ┐
                        └  env_reader.sh · restore.sh · logging.sh ─────────────────────────┬─────────────┘
                                │                                                           │
                                ▼                                                           ▼
 CONFIG & CONTEXT       global: ~/.claude/hooks/config.json          overlay: $PROJECT/.claude/hooks/config.json
                        (defaults: tiers, retention, patterns,      (static overrides, keep-list,
                         guard patterns, test_command,               validation.file_map)
                         validator_async_threshold_seconds)
                                │                        secrets: $PROJECT/.env  (parsed, never sourced)
                                │                        DYNAMIC: $PROJECT/.claude/validator_context.md
                                ▼
 STATE & OUTPUT         ~/.claude/hooks/state/<project-key>/   logs/<project-key>/   trash/<project-key>/
                                ▲          │                          ▲                      ▲
                                │ writes   │ read                     │ full output          │ scratch files
                                │ limits   ▼                          │                      │ (trash_days purge)
 STATUSLINE             statusline.sh ── reads own stdin (context_window, rate_limits) ──────┘
 (collector + display)   WRITES limits.json (throttled, atomic) · READS last_status.json
                         displays: model · branch+dirty · last report status · 3 limit gauges (🟡🟠🔴)
                                │  **Output to stdout** (per official protocol)
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / browser / HTTP)
 (run by finish.sh on   parameters extracted from `<validator-targets>` JSON in validator_context.md,
  Stop; filtered by     filtered by validation.file_map and changed files; slow ones detached to
  file_map)             background with results → pending_validator_results.json → limit-bridge injects
                                │
                                ▼
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

**Key architecture notes**:
- `statusline.sh` is **both** the display and the sole producer of `limits.json`: it is the only component that receives `context_window`/`rate_limits` on stdin (§1.2). It writes `limits.json` (atomic, throttled ≤ once/5 s) and reads `last_status.json`. There is **no** `limit-collector.sh`.
- `limit-bridge.sh` (on `UserPromptSubmit`) **reads** `limits.json` to decide when to inject tier directives, and also injects any pending async validator results.
- `finish.sh` branches on `hook_event_name`: on `Stop` it runs tests + validators; on `SessionEnd` it runs repo tidiness.
- Validators are filtered by `validation.file_map` (static overlay) against the list of changed files from the session manifest.
- Slow validators (estimated runtime > `validator_async_threshold_seconds`, default 15) run as **detached background jobs**; their results are written to state and injected by `limit-bridge.sh` on the next `UserPromptSubmit` (see §5.2 for the guarantee this weakens).

---

## 3. Configuration & Project Layering

### 3.1 Global Defaults & Static Overlay (`config.json`)

Contains defaults for all tunables:
- **Limits**: Context window (60 %/75 %/85 %), Session/5‑hour (60 %/75 %/90 %), Weekly (70 %/85 %/95 %).
- **Retention**: `logs_days` (14), `state_days` (60), `screenshots_days` (7), `trash_days` (7), size cap per namespace (100 MB).
- **Protected paths**: `.env*`, `*.pem`, `id_rsa*`, `.git/objects/**`, etc.
- **Guard patterns** (`guards.bash_deny`): dangerous Bash patterns (recursive delete outside tmp, force‑push to the detected default branch, `chmod 777`, writes to `/dev/`...). These live **here**, not in `settings.json`.
- **Scratch patterns**: `*.tmp`, `scratch*`, `debug_*`, `test_output*`, `*.bak`, `tmp_*`.
- **Validator timeouts**: e.g., 30 s for VPS, 15 s for HTTP.
- **Janitor interval**: `janitor_interval_hours` (24).
- **Auto‑approve list** (for the optional `PermissionRequest` helper): read‑only commands, idempotent operations (e.g., `git status`, `ls`).
- **`validation.file_map`**: Optional object mapping glob patterns to target names (e.g., `{ "src/**/*.js": "web", "api/**/*.py": "api" }`). If present, validators run only for targets whose glob matches at least one changed file in the session. If absent, all configured targets run.
- **`validation.declared`**: Boolean (or implied by a non‑empty `validation.targets`/`file_map` in the project overlay). Controls the block‑vs‑skip decision for malformed dynamic context (§5.2).
- **`env_allowlist`**: variable *names* that `env_reader.sh` may export from a project `.env` (§3.4).
- **`test_command`**: Optional string (e.g., `"npm test"`, `"pytest"`, `"make test"`). If not set, discovery heuristics apply (check `package.json` for a `"test"` script, look for `pytest.ini`, `Makefile` with a `test` target). If no command is found, tests are skipped.
- **`test_timeout`**: Timeout in seconds for the test command (default 60).
- **`validator_async_threshold_seconds`**: If a validator's estimated runtime exceeds this value (default 15), it runs asynchronously. Estimation can be based on target type (e.g., VPS/SSH slower) or a static config override.
- **`limits_staleness_minutes`**: how old `limits.json` may be before `limit-bridge.sh` treats it as unknown (default 10).

A complete example `config.json` with all keys and comments is provided in the deliverables.

---

### 3.2 Dynamic Context: The Living Document

Because a project grows dynamically, validators cannot rely on static endpoints or DOM selectors. If a project requires external validation, Claude will be instructed to maintain a living document at `$CLAUDE_PROJECT_DIR/.claude/validator_context.md`.

**The Hybrid Format:**
This document acts as a scratchpad for Claude to document architectural logic, but it **must** contain a strictly formatted JSON block enclosed in `<validator-targets>` tags for the automation scripts to parse.

**Extraction Logic**: Use a POSIX‑compliant `awk` state machine to extract content between the opening and closing tags (avoid `perl` for portability). The extracted text must be validated with `jq --exit-status`.

**Failure handling — one rule (resolves the v12 contradiction)**:
- Project **declares** validation (overlay defines `validation.targets` or `validation.file_map`, or `validation.declared: true`) **and** the file is missing, the tags are missing, or the JSON is invalid → `finish.sh` **blocks Stop** with: *"validator_context.md is missing or contains a malformed `<validator-targets>` block — please fix and try again."*
- Project does **not** declare validation → any absence or malformation is silently **skipped** (log only, code‑level checks still run). A project that never needs remote validation can therefore always finish, even with a stray `validator_context.md` lying around.

**Merge Rules for Dynamic Context**:
The extracted JSON is **only merged into the `"validation"` subtree** of the merged static configuration. This prevents Claude from overriding security‑critical keys like `protected_paths` or `guards.bash_deny`. Within that subtree, the merge follows the standard rules: scalars replaced, lists replaced (unless `_append` suffix), nested objects recursively merged.

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
            "if": "Bash(rm *)"
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/guards.sh",
            "timeout": 5,
            "if": "Bash(git push *)"
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
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/finish.sh", "timeout": 60 }] }
    ],
    "StopFailure": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/error-recovery.sh", "async": true, "timeout": 5 }] }
    ],
    "PostToolUseFailure": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/error-recovery.sh", "async": true, "timeout": 5 }]
      }
    ],
    "PreCompact": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/compact-monitor.sh", "timeout": 5 }] }
    ],
    "PostCompact": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/compact-monitor.sh", "timeout": 5 }] }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "~/.claude/hooks/statusline.sh"
  }
}
```

**Key points**:
- `format.sh` is on **`PostToolUse`** (the file must exist before formatting). Nothing heavy sits on `PreToolUse`.
- `matcher` supports exact names and `|`‑lists (`Edit|Write`); other characters switch it to unanchored regex — anchor with `^…$` when needed.
- Events without matchers (`Stop`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`) omit the `matcher` field; a matcher on them is silently ignored.
- `timeout` is in **seconds** per hook entry (platform defaults are long — 600 s for command hooks, 30 s for `UserPromptSubmit` — so always set tighter explicit values).
- `async: true` runs the hook in the background; `asyncRewake: true` (implies async) wakes Claude with stderr as a system reminder if the background hook exits 2.
- `if` uses **permission‑rule syntax** (§1.6). The two `Bash(...)` filters above are spawn optimizations; `guards.sh` re‑checks every command against `config.json → guards.bash_deny`. Note the `Read|Edit|Write` protected‑path guard runs unconditionally (no `if`).
- **Exec form**: when passing arguments, prefer `"args": [...]` so no shell is involved and no quoting bugs are possible.
- Plugin hooks are auto‑merged and coexist; identical handlers across settings layers are deduplicated automatically.

---

### 3.4 Secrets Loading (Safe Parser — never `source`)

`source`‑ing a project `.env` executes arbitrary repo‑controlled shell code with full user permissions — exactly the threat rule 13 exists to prevent. Instead, `lib/env_reader.sh` parses `.env` as **data**:

```bash
# lib/env_reader.sh — export allowlisted KEY=VALUE pairs from a project .env
# Usage: env_read "$CLAUDE_PROJECT_DIR/.env" "${ENV_ALLOWLIST[@]}"
env_read() {
  local file="$1"; shift
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    # KEY=VALUE only; reject command substitution, backticks, semicolons
    if printf '%s' "$line" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*=[^;`]*$' \
       && ! printf '%s' "$line" | grep -q '\$('; then
      local key="${line%%=*}" val="${line#*=}"
      # strip optional surrounding quotes
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      for allowed in "$@"; do
        [ "$key" = "$allowed" ] && export "$key=$val"
      done
    fi
  done < "$file"
}
```

The allowlist of variable names comes from `config.json → env_allowlist` (global) merged with the project overlay. Values are never logged, never injected, never echoed. Lines with `$(`, backticks, or `;` are ignored (and logged as a warning count only).

---

## 4. Hook Script Specifications

### 4.1 Hook Handler Type Comparison (Official)

| Type | Description | LLM Cost | Use Case |
|------|-------------|----------|----------|
| **command** | Shell script execution | None | Deterministic tasks (formatting, guards, validation) |
| **http** | POST the event JSON to a URL; response body = JSON output | None | Remote orchestration, webhooks |
| **mcp_tool** | Call a tool on a connected MCP server; text output treated like command stdout | None (the MCP call itself is not an LLM call) | External integrations |
| **prompt** | LLM single‑turn yes/no evaluation | LLM tokens per call | Judgment calls a script can't make |
| **agent** | Subagent with tool access verifies a condition (experimental) | High LLM compute | Complex multi‑step verification |

**This system uses command hooks exclusively**—deterministic, zero LLM cost, most predictable.

---

### 4.2 Initial Hook Set (v13)

| Event | Matcher | Script | Purpose | Blocking | Timeout (s) | Notes |
|---|---|---|---|---|---|---|
| `PostToolUse` | `Write\|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain, after the write. | No | 30 | Produces report |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to detected default branch). Patterns from config. | Yes (`exit 2`) | 5 | `if: "Bash(rm *)"` / `"Bash(git push *)"` as spawn filters only; script re‑checks |
| `PreToolUse` | `Read\|Edit\|Write` | `guards.sh` | Deny access to `.env*`, keys, protected paths (from config). | Yes (`exit 2`) | 5 | No `if` — runs on every matched call |
| `UserPromptSubmit` | — | `limit-bridge.sh` | Read `limits.json`; inject one‑time tier directives; inject pending async validator results. | No (context only) | 5 | The **only** consumer of `limits.json` for directives |
| `Stop` | — | `finish.sh` | Run tests + dynamic validators (filtered by `validation.file_map` + changed files). Block on failures via exit 0 + JSON `decision:"block"`. Slow validators detached. | Yes (JSON) | 120 | Checks `stop_hook_active`; branches on `hook_event_name` |
| `SessionEnd` | — | `finish.sh` | **Repo tidiness**: classify manifest entries, quarantine scratch, log count. | No (SessionEnd cannot block) | 60 | Branches on `hook_event_name` |
| `StopFailure` | — | `error-recovery.sh` | Log API‑error turn endings. Output/exit code ignored by Claude Code — logging only. | No | 5 | async |
| `PostToolUseFailure` | `Write\|Edit` | `error-recovery.sh` | Log write failure. | No | 5 | async |
| `PreCompact` | — | `compact-monitor.sh` | Snapshot pre‑compact percentages (from `limits.json`) to state. | No | 5 | |
| `PostCompact` | — | `compact-monitor.sh` | Snapshot post‑compact state; log token savings. | No | 5 | |
| `SessionStart` | — | `context.sh` | Inject compact project context AND the validator‑context directive (§5.1). | No | 10 | stdout/`additionalContext` becomes context on this event |
| `SessionStart` | — | `janitor.sh` | Retention cleanup of own logs/state/trash. | No | 60 | async |
| `PostToolUse` | `Write\|Edit` | `manifest.sh` | Record files *created* or *modified* this session; `created` flag from pre‑existence check or `tool_response` (see §8.2). | No | 5 | async |
| `PostToolUse` | `Write\|Edit` | `index.sh` | Update project index/dependency graph in background. | No | 30 | async + `asyncRewake` |
| **Optional** `PermissionRequest` | `Bash` | `permission-helper.sh` | Auto‑allow read‑only/idempotent commands from config allowlist via `hookSpecificOutput.decision.behavior`. | Yes | 5 | Does **not** fire in headless (`-p`) mode — use PreToolUse `permissionDecision` if headless matters |
| **Optional** `PermissionDenied` | `Bash\|Write\|Edit` | `retry-handler.sh` | Optionally signal retry via `hookSpecificOutput.retry: true` (§1.5). | No (exit code ignored) | 5 | Probe for event support |

---

### 4.3 Events Not Included in This System

| Event | Justification for Exclusion |
|-------|----------------------------|
| `Setup` | Fires only with `--init-only`/`--init`/`--maintenance`; not needed. |
| `UserPromptExpansion` | Adds latency to every slash command; nothing to gate. |
| `MessageDisplay` | Fires per displayed batch; excessive overhead; display‑only anyway. |
| `PostToolBatch` | Per‑batch gating not needed; Stop covers turn‑level checks. |
| `Notification` | No automation attached to notifications in v1. |
| `SubagentStart` / `SubagentStop` | Subagent workflows out of scope for v1. |
| `TaskCreated` / `TaskCompleted` / `TeammateIdle` | Task/team lifecycle managed separately. |
| `InstructionsLoaded` | Observability only; SessionStart covers our needs. |
| `ConfigChange` / `CwdChanged` / `FileChanged` | Complexity; session file changes tracked via `manifest.sh`. |
| `WorktreeCreate` / `WorktreeRemove` | Worktrees not used. |
| `Elicitation` / `ElicitationResult` | MCP elicitation out of scope. |

**Plugin hooks**: coexist without modification; they are auto‑merged. **MCP tool hooks**: out of scope for v1.

---

## 5. Context‑Aware Validation (Dynamic)

Code‑level checks are insufficient—validation must extend to the running system (VPS, email, web app, etc.).

### 5.1 The `SessionStart` Directive

The `context.sh` hook injects the following directive via `additionalContext` when a session starts (phrased as project information, per §1.4):

> *"This project uses external validation. If core architectural elements, API endpoints, or UI selectors change during this session, the JSON block inside the `<validator-targets>` tags in `.claude/validator_context.md` must be updated before stopping. The JSON must be valid and enclosed exactly as shown. Only the `validation` subtree of the configuration can be overridden."*

The directive is injected **only** for projects that declare validation (§3.2 rule); other projects get project context without it.

### 5.2 Validator Execution (`finish.sh` Stop Hook)

When Claude attempts to stop, `finish.sh` (after the `stop_hook_active` loop guard) handles dynamic validation:

1. **Declared?** If the merged static config does not declare validation (§3.2), skip to step 5 (tests only).
2. **Extract**: POSIX `awk` state machine pulls the block between `<validator-targets>` and `</validator-targets>`.
3. **Validate**: Pipe through `jq --exit-status .`. If the file, the tags, or valid JSON are missing → **block** (exit 0 + JSON `decision:"block"`, reason: *"validator_context.md is missing or contains a malformed `<validator-targets>` block — please fix and try again."*). This is the single failure rule; there is no separate "skip on extraction failure" path for declared projects.
4. **Merge**: Deep‑merge the dynamic JSON **only into the `"validation"` subtree** of the static config (per merge rules).
5. **Execute tests**: If a test command is set/discovered, run it with `test_timeout`. On failure → block with the failure summary (counts + log path, ≤500 tokens).
6. **Filter targets**: Read the session manifest (`state/<project-key>/manifests/<session-id>.json`) for changed files. If `validation.file_map` exists, run only targets whose glob matches a changed file; else run all targets present in the dynamic JSON. No targets → skip remote validation.
7. **Execute validators**:
   - Estimate runtime per target. Fast targets run synchronously in parallel, each with its configured timeout. If any fails → block (exit 0 + JSON `decision:"block"` + summary).
   - Slow targets (> `validator_async_threshold_seconds`) are **detached** (`nohup … &` with stdio redirected to the log; `disown`) so they survive the hook's exit, and a pending record is written to `state/<project-key>/pending_validator_results.json` (atomic). `asyncRewake` is a settings‑level field for *hook entries* and does not apply to children a script spawns — do not attempt to use it here.
   - On the next `UserPromptSubmit`, `limit-bridge.sh` checks `pending_validator_results.json`; completed results are injected as `additionalContext` (≤500 tokens) and the pending record is cleared.
8. **Documented caveat**: an async validator failure **cannot retroactively block** the Stop that already completed, and if the session ends before the next prompt, the failure surfaces only in logs and in `last_status.json` (which `context.sh` summarizes at the next `SessionStart`). Projects that need a hard gate must keep their validators under the async threshold or raise the threshold so they run synchronously.

### 5.3 Validator Scripts (`~/.claude/hooks/validators/`)

- One script per target type (`vps.sh`, `email.sh`, `web.sh`, `api.sh`, `db.sh`).
- **Safety**: Read‑only against production by default; mutating probes target sandbox resources exclusively and clean up. Secrets via `env_reader.sh` (§3.4), never logged.
- **`--test` mode**: Accepts mocked responses (fixtures) to test offline, including a "target unreachable" fixture (reports `error`, does not hang, respects timeout).

### 5.4 Validator Target Types (Implement Once)

- **VPS/Server**: SSH to verify artifact version/checksum, service status, ports, disk/memory, recent logs for errors.
- **Email**: Send probe to test recipient; verify delivery, SPF/DKIM/DMARC, no unintended recipients.
- **Web**: Headless browser (Playwright) to check key pages, console errors, network requests, critical flows; screenshots saved to logs.
- **API**: Probe endpoints for status, schema, auth behaviour.
- **Database**: Read‑only connectivity, migration version, row‑count sanity.

---

## 6. Statusline & Limit Monitoring

The statusline is **not a hook**—it is a separate `statusLine` command in `~/.claude/settings.json`. Because it is the only component that receives live usage metrics on stdin (§1.2), it plays a **dual role**: display *and* sole producer of `limits.json`. This is the original "statusline‑bridge" pattern; v10–v12's separate collector hook was based on an inverted schema claim and is removed.

### 6.1 Limit Data Flow (Correct Architecture)

```
┌───────────────────────┐    stdin: context_window,     ┌─────────────────┐
│  Claude Code UI       │    rate_limits, model, cost   │ statusline.sh   │
│  (every refresh,      │ ────────────────────────────► │  1. render line │
│   ~300 ms debounce)   │                               │  2. write       │
└───────────────────────┘                               │     limits.json │
                                                        │  (atomic,       │
                                                        │   ≤ once/5 s)   │
                                                        └───────┬─────────┘
                                                                │
                              ┌─────────────────────────────────┤ reads
                              ▼                                 ▼
                    ┌─────────────────┐               ┌────────────────────┐
                    │ limit-bridge.sh │               │ compact-monitor.sh │
                    │ (UserPrompt-    │               │ (Pre/PostCompact   │
                    │  Submit: tier   │               │  snapshots)        │
                    │  directives +   │               └────────────────────┘
                    │  async validator│
                    │  results)       │
                    └─────────────────┘
```

### 6.2 Statusline (`statusline.sh`)

- Invoked by Claude Code on every refresh (after each assistant message, after `/compact`, on permission‑mode change; a built‑in ~300 ms debounce applies and cannot be configured).
- Reads the statusline JSON from stdin (§1.2), defensively: every field via `// empty` fallbacks.
- **Writes** `state/<project-key>/limits.json` (§1.8) — atomic, throttled to ≤ once per 5 s via mtime check. This is its "collector" duty and the only write it performs besides its own log.
- **Reads** `state/<project-key>/last_status.json` for the last report status.
- Derives branch and dirty count with `git --no-optional-locks` from `workspace.current_dir` (fallback `n/a`): `git symbolic-ref --short HEAD` for branch, `git status --porcelain | wc -l` for dirty count.
- Prints its display to **stdout**:
  - Current model name
  - Branch + dirty‑file count (e.g., `main*3`)
  - Last report status with colour (green/ok, yellow/warn, red/error)
  - Three percentages with tiered colour coding (🟡 / 🟠 / 🔴); `n/a` for any null
- **Performance**: < 100 ms. Missing/stale state → placeholders, never errors, never a blank line (a blank/erroring statusline disappears from the UI).

### 6.3 Limit Tiers & Bridge Hook (`limit-bridge.sh`)

| Limit | Notice (🟡) | Warning (🟠) | Action (🔴) |
|---|---|---|---|
| Context window | 60 % | 75 % | 85 % |
| Session (5‑hour) usage | 60 % | 75 % | 90 % |
| Weekly usage | 70 % | 85 % | 95 % |

- Runs on **`UserPromptSubmit`** (wired in §3.3). Reads `limits.json`; if its `timestamp` is older than `limits_staleness_minutes` (default 10), treats values as unknown (`n/a` behaviour, no directives).
- **Notice**: statusline colour change only — zero token cost, no injection.
- **Warning**: **one‑time** `additionalContext` line (≤50 tokens) advising Claude to avoid starting large multi‑file work. Dedupe per tier crossing per session via `state/<project-key>/limit_alerts.json` (atomic).
- **Action**: inject a high‑priority wind‑down directive: persist working state (current goal, changed files, next step) to a handoff file, prefer compact‑friendly stopping points; for plan limits, note that compaction reduces future consumption but does not restore quota. Log the event; statusline shows red.
- **Second duty**: check `pending_validator_results.json` and inject completed async validator results (§5.2 step 7), then clear them.
- **Auto‑compact**: the hook system does **not** set this; the README recommends `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in the user's environment, and notes that both that setting and `context_window.used_percentage` measure input‑tokens‑only, so displayed and acted‑on numbers agree.
- **Fallback**: if `rate_limits` data is unavailable (API billing, version without it, early renders), degrade to context‑only monitoring; show `n/a` for the others; never crash or block.

---

## 7. Shared Library (`lib/`)

Implement the following as shared modules:

- **`config.sh`**: Loads global config, checks for overlay, deep‑merges per merge rules, validates schema/version. Malformed overlay → fall back to defaults + log a warning (never crash).
- **`context_extractor.sh`**: `awk`‑based extraction and `jq` validation of the tag‑fenced JSON from `.claude/validator_context.md`. Returns extracted JSON, or a distinct exit code for "missing file", "missing tags", "invalid JSON" so `finish.sh` can apply the §3.2 rule.
- **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary, and updates `last_status.json` (atomic) for report‑producing hooks. Emits expanded absolute paths.
- **`project_key.sh`**: Derives the project key from the project root (deterministic slug + short hash of the absolute path).
- **`env_reader.sh`**: Safe `.env` parser (§3.4).
- **`restore.sh`**: Restores quarantined session files. Usage: `restore.sh <project-key> <session-id>`. Moves files from `trash/<project-key>/<session-id>/` back to their original relative paths; on conflict, the restored file gets a `.conflict` suffix.
- **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.

**Security requirement**: All library functions quote all variables and sanitize JSON inputs before passing to `jq` or other tools. All file writes are atomic. Missing external tools (`jq`, `ssh`, `playwright`) → logged warning + `exit 0`, never a broken session.

---

## 8. Cleanup & Tidiness

Two distinct responsibilities, two risk levels.

### 8.1 Housekeeping (Own Files, Low Risk)

- `janitor.sh` runs on `SessionStart` (async), rate‑limited to once per `janitor_interval_hours`.
- Enforces retention from global config (logs, state, screenshots, trash).
- Cleans session manifest files under `state/<project-key>/manifests/` after `state_days` (this is the **canonical manifest location**, used identically in §5.2).
- Orphan sweep: removes namespaces for projects that no longer exist on disk (after `state_days`).
- Injects nothing into context; writes one summary line to its own log.

### 8.2 Repo Tidiness (Scratch Files, Higher Risk)

- **Track**: `manifest.sh` records every file *created* or *modified* by Claude this session (`PostToolUse`, `Write|Edit`) into `state/<project-key>/manifests/<session-id>.json` (atomic append‑rewrite). Each entry carries `created: true/false`, determined by: check `tool_response` for a creation indicator when present, otherwise compare against a first‑seen snapshot the hook keeps per session (a path not previously seen *and* absent from `git ls-files` at first touch → created). Only `created: true` files are quarantine candidates; edits to pre‑existing files are never touched.
- **Classify at session end** (`finish.sh` on `SessionEnd`): entries with `created: true` matching scratch patterns (config), **not** git‑tracked, not in the `keep` list, not under protected paths → scratch.
  - *Git‑tracked check*: `git ls-files --error-unmatch <file> >/dev/null 2>&1`; returns 0 → tracked → **never touched**.
- **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/`, preserving relative paths.
- **Log**: write `scratch_quarantined: N` to the SessionEnd log (SessionEnd cannot inject or block; the count also lands in `last_status.json` only if a Stop report already exists — otherwise `context.sh` surfaces it at the next `SessionStart`).
- **Restore**: `restore.sh` moves a quarantined session back.
- **Purge**: Janitor purges quarantine after `retention.trash_days`.

---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration exactly as §3.3: narrow matchers, explicit `timeout` on every entry, permission‑rule `if` filters on the Bash guards, `UserPromptSubmit` → `limit-bridge.sh`, `statusLine` entry.
2. **`hooks/`** — Executable scripts per hook, each with stdin parsing (malformed input → exit 0 + log, never crash the session), error handling, timing, `--test` mode.
3. **`hooks/lib/`** — Shared library (config, report, context extractor, project‑key, env reader, restore, logging).
4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented, including `guards.bash_deny`, `env_allowlist`, `test_command`, `test_timeout`, `validator_async_threshold_seconds`, `validation.file_map`, and `limits_staleness_minutes`.
5. **`hooks/config.overlay.example.json`** — Documented example project overlay, showing static overrides, `keep` list, and `validation.file_map`.
6. **`hooks/README.md`** — Table of hooks; config layering; how to add an overlay; the dynamic markdown validation logic and its single block/skip rule; statusline dual role (collector + display, stdout output); `if` permission‑rule syntax with the fails‑open caveat and the permission‑system recommendation for hard denies; `args` exec form; `async`/`asyncRewake` semantics (settings‑level fields); the "JSON only on exit 0" rule; atomic write guidance; `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` recommendation; note that `PermissionRequest` does not fire in headless mode.
7. **`hooks/fixtures/`** — Sample stdin JSON per hook (including malformed JSON, a statusline payload **without** `rate_limits`, and a Stop payload with `stop_hook_active: true`).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification). If a previous version of *this* system is installed, `limit-collector.sh` and its `PostToolUse` entries are retired here with the reason "architecture inverted; statusline is the collector".
9. **`hooks/statusline.sh`** — Dual‑role statusline (renders to stdout; writes `limits.json` atomically/throttled; reads `last_status.json`; derives git info; <100 ms; never blank).
10. **`hooks/limit-bridge.sh`** — Tier directives + async validator result injection on `UserPromptSubmit`, with per‑tier dedupe and staleness handling.
11. **`hooks/validators/`** — Context‑aware validator scripts per target type, with detached‑async support and unreachable‑target fixtures.
12. **`hooks/test/run.sh`** — Simple test runner invoking each script with `--test`, verifying exit codes and JSON validity (including that no script emits JSON alongside exit 2). BATS optional but recommended.

---

## 10. Acceptance Criteria

### A. Functionality

- [ ] `claude --debug` shows each hook firing on its intended event and no others; no hook fires on events it isn't registered for.
- [ ] Every script passes its `--test` mode against fixtures (including malformed JSON and the no‑`rate_limits` statusline fixture).
- [ ] Bash guard blocks `rm -rf /` and a force‑push to the *detected* default branch (test fixture uses a repo whose default branch is deliberately named something other than `main`), exit 2 with reason on stderr; allows `ls`, `git status`.
- [ ] Guard re‑check works when the `if` filter fails open: a crafted command that bypasses the `if` pattern but matches a configured deny pattern is still blocked by the script.
- [ ] Stop hook blocks completion via exit 0 + JSON `decision:"block"` when a test is broken; allows when fixed; never loops (`stop_hook_active` honoured).
- [ ] Bridge hook: silent below Notice tier; ≤50‑token advisory exactly once at Warning tier; wind‑down directive at Action tier; dedupe persists across prompts; stale `limits.json` (> `limits_staleness_minutes`) → no directives.
- [ ] `rate_limits` absent from statusline stdin → `limits.json` gets nulls, statusline shows `n/a`, bridge degrades to context‑only; nothing crashes.
- [ ] Statusline renders from state (<100 ms), writes `limits.json` atomically and no more than once per 5 s, outputs to **stdout**, and never renders blank on missing state.
- [ ] Validators catch deliberately introduced faults and block Stop; after fix, Stop allowed.
- [ ] For a **declared‑validation** project: missing file / missing tags / invalid JSON in `validator_context.md` each block Stop with the fix‑it message. For an **undeclared** project: the same conditions are skipped silently and Stop proceeds.
- [ ] Session touching only unmapped files (when `validation.file_map` is present) triggers no remote probes.
- [ ] Slow validators (> threshold) detach, survive the hook's exit, write `pending_validator_results.json`; results are injected by `limit-bridge.sh` on the next prompt and the pending record is cleared.
- [ ] Test suite runs when `test_command` is set/discovered; failures block Stop.
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up `state/<project-key>/manifests/`.
- [ ] Repo tidiness (`SessionEnd`): quarantines only `created:true` scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.
- [ ] Multi‑project: two different stacks (Node/Python/no toolchain) each adapt; no‑toolchain no‑ops cleanly; state/logs namespaced with no cross‑contamination.
- [ ] Project with no config overlay runs safely on pure global defaults; project without `.claude/` skips remote validation cleanly.
- [ ] `StopFailure` and `PostToolUseFailure` hooks log without blocking (and the implementation does not attempt to block on them).
- [ ] Optional `PermissionRequest` helper auto‑approves allowlisted commands and stays silent otherwise; documented as inactive in headless mode. Optional `PermissionDenied` handler emits `hookSpecificOutput.retry: true` and degrades silently on versions without the event.

### B. Performance & Token Discipline

- [ ] No hook output injected exceeds 500 tokens (verify from debug transcript).
- [ ] Formatting hook completes < 2 s on the largest file; PreToolUse guards < 500 ms.
- [ ] Compaction completes successfully at the 85 % context threshold (headroom proven).
- [ ] Statusline < 100 ms; `limits.json` writes throttled to ≤ once per 5 s; atomic writes cause no corruption under rapid refresh.

### C. Portability & Maintainability

- [ ] `grep -rn` across `~/.claude/hooks/` finds no absolute user paths (outside `$HOME`‑derived), no hardcoded branch/model/tool‑command strings outside config, no threshold numbers or guard patterns outside config, **and no occurrence of `source .*\.env`**.
- [ ] All scripts pass `--test` from a different working directory.
- [ ] All scripts run on macOS and Linux (and Windows WSL/Git Bash) without modification.
- [ ] Config loader handles malformed overlay JSON by falling back to defaults and logging (not crashing).
- [ ] No secret value from any `.env` appears in reports, logs, or debug transcript; only allowlisted variable names are exported.
- [ ] Removing hooks from `settings.json` restores stock behaviour—no side effects outside intended formatting and `~/.claude/hooks/` state/logs.
- [ ] Every pre‑existing hook/script is upgraded or retired; `MIGRATION.md` accounts for each item.
- [ ] Missing external tools (`jq`, `ssh`, `playwright`) cause a logged warning and `exit 0`—they do not break the session.
- [ ] `$CLAUDE_PROJECT_DIR` is used for project‑relative paths; `cwd` for location‑dependent operations; the project key is derived from the project root.

### D. Safety & Validation

- [ ] No hook auto‑approves write/network operations beyond the explicit allowlist.
- [ ] Validator probes are read‑only against production; mutating probes target designated sandboxes and clean up.
- [ ] Validator handles target unreachable (reports `error`, respects timeout, does not hang).
- [ ] Quarantine never touches git‑tracked files or files under protected paths.
- [ ] All shell variables are quoted (`"$VAR"`). All inputs sanitized. `args` exec form used where arguments are passed.
- [ ] Dynamic context merges are restricted to the `validation` subtree; security‑critical keys (`protected_paths`, `guards.*`, `env_allowlist`) cannot be overridden from the repo.
- [ ] A hostile `.env` containing `$(command)`, backticks, or `;` payloads exports nothing and executes nothing (fixture test).

### E. Wiring Integrity

- [ ] The implemented wiring matches the system schema: every hook resolves config/reports through `lib/`; all state/log/trash writes namespaced.
- [ ] `statusline.sh` is the **only** producer of `limits.json`; `limit-bridge.sh` is the **only** injector of tier directives and async validator results; no `limit-collector.sh` exists.
- [ ] `limit-bridge.sh` is actually registered under `UserPromptSubmit` in `settings.json` (a `grep` of the shipped settings proves it).
- [ ] `validation.file_map` filtering works: validators run only for targets whose glob matches changed files; if no map, all run.
- [ ] `finish.sh` branches correctly on `hook_event_name` (`Stop` → tests+validators, `SessionEnd` → repo tidiness) and the manifest path in §5.2 and §8 is one and the same.

---

## 11. Out of Scope

- **HTTP, MCP‑tool, Prompt, and Agent hook handler types**: command hooks exclusively.
- **MCP tool interaction hooks**.
- **Project‑level hook logic**: repositories carry at most an optional config overlay (`.claude/hooks/config.json`) and the validator context document — never scripts or hook entries.
- **Any hook that auto‑approves write or network operations** beyond the defined allowlist.
- **Retrying on `PostToolUseFailure`**: log only.
- **Subagent, Task, Teammate, Worktree, Elicitation, and configuration‑change events**: out of scope for v1.

---

## 12. Version History

| Version | Changes |
|---------|---------|
| **v1** – **v10** | Earlier iterations (see previous records). v10 introduced the formal spec structure — and the inverted limit architecture. |
| **v11** | Re‑introduced `validation.file_map`; added `last_status.json`; dynamic merge rules; extraction improvements; **regressed `if` from permission‑rule syntax to "regex"**; added git info; documented (unsafe) secrets loading; `.claude/` fallback; `asyncRewake`. |
| **v12** | Manifest `Write\|Edit`; dynamic merge restricted to `validation` subtree; async validators; test config; `awk` extraction; `limits.json` defined; atomic writes; carried forward the inverted limit architecture, the regex `if`, the PreToolUse `format.sh`, and the unwired bridge. |
| **v13** | **Correctness pass against official docs**: limit architecture restored to statusline‑bridge (statusline = collector + display; `limit-collector.sh` deleted); `limit-bridge.sh` wired on `UserPromptSubmit`; hook‑input schema corrected (no `context_window`/`rate_limits` in hook stdin) and fabricated version claims removed; `if` restored to permission‑rule syntax with fails‑open caveat and patterns moved to config; `format.sh` moved to `PostToolUse`; Stop/PostToolUse blocking semantics corrected + "JSON only on exit 0" rule; `PermissionDenied` retry shape fixed; `limits.json` stores `used_percentage`; single block/skip rule for malformed dynamic context keyed on declared validation; canonical manifest path; detached async validators with documented weakened guarantee; safe `.env` parser replacing `source`; FileChanged note removed; naming, path, and table corrections. |

---

**This v13 specification corrects all defects identified in the v12 review (inverted limit architecture, invalid `if` syntax, misplaced `format.sh`, unwired bridge, skip/block contradiction, protocol misstatements, unsafe secrets loading, and schema fabrications) and instructs the implementer to re‑verify all schema excerpts against the live official documentation before building.**
