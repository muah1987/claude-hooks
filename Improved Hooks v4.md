## 1. Evolution Summary (v1 → v3)

| Area | v1 | v2 | v3 |
|------|----|----|----|
| **Stop hook blocking** | Unclear (exit 2 vs JSON) | Clarified: Stop uses JSON `decision: "block"` | Same, now explicitly highlighted |
| **Config merge rules** | Not specified | Defined scalar replacement, list replacement, and `_append` for concatenation | Same, more precise |
| **Project‑key derivation** | Mentioned but not detailed | Added `slugify(basename)+short-hash` | Same, with example |
| **Validation target mapping** | Not present | Not present | Added `validation.file_map` to limit validators by changed files |
| **Statusline role** | Vague | Clarified as sole producer of limit metrics | Explicitly states `statusline.sh` writes `limits.json` and `limit-bridge.sh` reads it |
| **Auto‑compact control** | Mentioned environment variable | Same | Clarified that the hook system does **not** set it; user must configure separately |
| **Portability** | Mentioned | Added POSIX compliance requirement | Same, with explicit macOS/Linux/WSL support |
| **Malformed overlay** | Not specified | Added fallback to defaults with logging | Same |

**Verdict:** v3 is the best starting point because it handles the most edge cases and gives clear implementation guidance.

---

## 2. What v3 Still Lacks (Opportunities for v4)

Based on a thorough review, the following areas would benefit from further specification:

1. **Explicit input JSON schema** – no sample payload is given; scripts need to know exactly which fields to expect.
2. **Concrete report contract example** – the JSON structure is described but no full example is shown.
3. **Statusline script behaviour** – it is not stated that `statusline.sh` is **not** a hook but a separate `statusLine` command, and that it prints to stderr per Claude’s protocol.
4. **Validation – how to obtain changed files** – the Stop hook must read the session manifest to know which files were touched; this is implied but not spelled out.
5. **Git‑tracked check command** – the exact command to test if a file is tracked is missing.
6. **Merge rules for nested objects** – only list merging is detailed; nested object merging should be explicitly defined.
7. **Sample config and overlay files** – no fully documented example with all default values.
8. **Handling missing external tools** – scripts should gracefully no‑op if `jq`, `curl`, `ssh`, etc. are not installed.
9. **Janitor – session manifests cleanup** – manifests are not mentioned in retention policy.
10. **Restore script usage** – no example invocation or conflict handling details.
11. **Test harness recommendation** – BATS mentioned but no simple runner example.
12. **Auto‑compact environment variable** – should be explicitly recommended in README.

These items are addressed in the following **v4 specification**.

---

## 3. v4 – Full Improved Specification

I have taken v3 and applied all the above improvements. The result is a more complete and implementable document. Below is the full v4 text (with changes highlighted in the summary, but presented as a complete document for direct use).

---

# Build a Token‑Efficient Hook Automation System for Claude Code (v4)

## Executive Summary

This document specifies a **user‑level automation layer** (`~/.claude/`) for Claude Code that intercepts deterministic tasks—formatting, linting, validation, indexing—and executes them via local scripts instead of LLM tool calls. It is token‑efficient, injecting only compact structured reports (≤500 tokens) back into the model’s context.

The system is designed for a **single installation that must serve every project**, regardless of language, stack, or deployment target. All project‑specific behaviour is resolved at runtime through a layered configuration mechanism (global defaults + per‑project overlays). Success is measured by fewer round trips, smaller context injections, and zero regressions across all projects—including those that do not yet exist.

---

## 1. Ground Rules (Read Before Implementing)

1.  **Native Hook System**: Use Claude Code’s official hook system exclusively. Hooks reside in `~/.claude/settings.json` (user‑level). All scripts live under `~/.claude/hooks/`. **Do not** invent a custom event bus or place hook logic inside individual repositories.
2.  **Official Reference**: Consult the [hooks documentation](https://code.claude.com/docs/en/hooks) for the current event list, stdin JSON schema, and output protocol before building. The event set may change between versions—do not rely on memory.
3.  **Script Invocation**: Every hook entry must invoke a script in `~/.claude/hooks/`. No inline logic in `settings.json` beyond the script path. Scripts are the unit of testing and reuse.
4.  **Hook Protocol Compliance**:
    - Scripts read a single JSON object from stdin. The expected fields are defined in Section 1.1 (Input JSON Schema).
    - **Exit codes**: `0` = proceed; `2` = block (stderr is surfaced as the reason). Other codes = non‑blocking error.
    - **Structured control**: Use JSON on stdout (`hookSpecificOutput` with `permissionDecision` for `PreToolUse`; `decision`/`reason` for `Stop`; `additionalContext` to inject context). **Note**: `Stop` hooks block via JSON (`decision: "block"`), **not** via exit code 2. For all other hooks, `exit 2` is the blocking mechanism.
5.  **Token Discipline**:
    - Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr.
    - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`.
    - Only a summary report (see Report Contract in Section 1.2) is returned to the model, **capped at 500 tokens** (~2 000 characters). If results exceed that, summarize counts and include the log file path for on‑demand retrieval.
6.  **Performance**: `PreToolUse` hooks gate matched tool calls—target **< 500 ms**. Slower operations (test suites, indexing) belong on `PostToolUse`, `Stop`, or run with `"async": true`.
7.  **Chaining**: Chaining is not native. Implement it inside a script (Script A calls Script B) or via a shared state file. Document each chain explicitly.
8.  **Safety**: Never auto‑approve destructive operations. `PreToolUse` may auto‑allow **only** an explicit allowlist of read‑only or idempotent commands. Blocking `PreToolUse` and `PostToolUse` hooks use `exit 2`; `Stop` hooks use JSON `decision: "block"`. Exit code `1` only warns.
9.  **Loop Guard**: Any `Stop` hook must check the `stop_hook_active` field in the stdin JSON and `exit 0` when `true`.
10. **Audit Before Build**: Inventory existing hooks/scripts in `~/.claude/settings.json`, `~/.claude/hooks/`, and project‑level `.claude/settings.json`. **Upgrade or retire** every existing user‑level item to meet these standards. Document each in `MIGRATION.md`. Do not run old and new conventions side‑by‑side.
11. **Zero Hardcoded Values**:
    - **Paths**: Derive everything from stdin (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`. The only permitted absolute anchor is `$HOME/.claude/...`. Never use literal `/home/<user>/`.
    - **Project specifics**: Discover at runtime (e.g., from `package.json`, `Makefile`, `pyproject.toml`). Formatters/linters are detected per project; if none exist, the hook no‑ops silently. Default branch is read from `git remote show origin` (or equivalent)—never assumed to be `main`.
    - **Tunables**: Every threshold, cap, timeout, and allowlist lives in config—scripts read config, never embed numbers.
    - **Dynamic API**: Field names are read defensively. Missing/renamed fields degrade gracefully (e.g., `rate_limits` fallback) rather than crashing.
    - **Portability**: All scripts must run on macOS and Linux (and Windows via WSL/Git Bash) without modification. Use POSIX‑compliant constructs or `#!/usr/bin/env bash`.
12. **Layered Configuration**:
    - **Global Defaults**: `~/.claude/hooks/config.json`
    - **Project Overlay**: If `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json` exists, it is deep‑merged over the global defaults.
        - **Merge Rules**:
          - Scalars are replaced by the overlay.
          - Lists are **replaced** unless the overlay uses a key ending in `_append` (e.g., `protected_paths_append`), in which case they are concatenated and deduplicated.
          - Nested objects are merged recursively (overlay subtree replaces global subtree for that key).
        - **Versioning**: Both configs must include a `"version"` field. Scripts check compatibility and fall back gracefully if versions mismatch (log warning, use global defaults).
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
        - **Project‑Key Derivation**: `slugify(basename($cwd)) + '-' + (echo -n $cwd | sha1sum | cut -c1-8)`. (e.g., `my-app-a1b2c3d4`).
    - **Secrets**: Read from the project’s `.env` at runtime. Global config stores variable *names*, never values.

### 1.1 Input JSON Schema (from Claude Code)
Hook scripts receive a JSON object with at least the following fields (additional fields may exist):
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
- `context_window` and `rate_limits` may be absent; scripts must handle missing fields gracefully.
- The `tool_input` structure varies by `tool_name`.

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
`details` holds counts and short identifiers only—never file contents, stack traces, or diffs.

---

## 2. System Architecture

[Same diagram as v3 – omitted here for brevity but retained in full document.]

*Note:* `statusline.sh` writes current usage percentages to `state/<project-key>/limits.json`. `limit-bridge.sh` reads that file to know when to inject tier directives.

---

## 3. Configuration & Project Layering

### 3.1 Global Defaults (`~/.claude/hooks/config.json`)
Contains defaults for all tunables:
- **Limits**: Context window (60 %/75 %/85 %), Session (60 %/75 %/90 %), Weekly (70 %/85 %/95 %).
- **Retention**: `logs_days` (14), `state_days` (60), `screenshots_days` (7), `trash_days` (7), size cap per namespace (100 MB).
- **Protected paths**: `.env*`, `*.pem`, `/etc/passwd`, etc.
- **Scratch patterns**: `*.tmp`, `scratch*`, `debug_*`, `test_output*`, `*.bak`, `tmp_*`.
- **Validator timeouts**: e.g., 30 s for VPS, 15 s for HTTP.
- **Janitor interval**: `janitor_interval_hours` (24).

A complete example `config.json` with all keys and comments is provided in the deliverables.

### 3.2 Project Overlay (`$PROJECT/.claude/hooks/config.json`)
Optional. Deep‑merged over global defaults for that project only. Common uses:
- `validation.targets` array (VPS, Email, Web, API, DB).
- `validation.file_map` (optional mapping from glob patterns to target names, so validators run only when relevant files change).
- Project‑specific `protected_paths_append`.
- `keep` list for files that should never be quarantined.
- Overrides for thresholds (must be justified in a comment).

If the overlay is **malformed**, the config loader falls back to global defaults, logs an error to the hook’s log, and continues—never crashing the session.

### 3.3 Secrets
Stored in the project’s `.env`. Read at runtime. Never logged, never injected.

---

## 4. Hook Script Specifications

All scripts follow a **standard boilerplate**:
- Parse stdin JSON gracefully (if invalid → `exit 0` + log error).
- Source `lib/config.sh` and `lib/report.sh`.
- Implement `--test` mode (reads a fixture file or sample JSON from stdin).
- Write structured logs to the per‑project log directory.
- Respect the report contract.
- Gracefully handle missing tools (e.g., no linter installed, `jq` missing) by logging a warning and exiting `0` (no‑op). This prevents failure on machines without optional dependencies.

### Initial Hook Set

| Event | Matcher | Script | Purpose | Blocking |
|---|---|---|---|---|
| `PostToolUse` | `Write\|Edit` | `format.sh` | Auto‑format + lint‑fix using project toolchain; report only if changes or errors. | No |
| `PreToolUse` | `Bash` | `guards.sh` | Block dangerous patterns (recursive deletes outside tmp, force‑push to default branch, credential file access). Patterns in config. | Yes (`exit 2`) |
| `PreToolUse` | `Read\|Edit\|Write` | `guards.sh` | Deny access to `.env*`, keys, and protected paths (global + overlay). | Yes (`exit 2`) |
| `Stop` | — | `finish.sh` | Run test suite + context‑aware validators for targets touched. Block stop if failures occur. | Yes (JSON `decision: "block"`) |
| `SessionStart` | — | `context.sh` | Inject compact project context (branch, dirty count, last 5 commits, TODO count) ≤300 tokens. | No |
| `SessionStart` (async) | — | `janitor.sh` | Retention‑based cleanup of own logs/state/trash; rate‑limited via state timestamp (`janitor_interval_hours`). | No |
| `PostToolUse` (async) | `Write` | `manifest.sh` | Record files *created* by Claude this session (feeds repo tidiness). | No |
| `Stop` / `SessionEnd` | — | `finish.sh` | Repo tidiness: classify manifest entries as scratch, quarantine, report count. | No |
| `PostToolUse` (async) | `Write\|Edit` | `index.sh` | Update project index/dependency graph in background; write to state file; inject nothing. | No |

Extend beyond this set only where a repetitive task is observed across projects—justify each addition in the README.

---

## 5. Shared Library (`lib/`)

Implement the following as shared modules:
- **`config.sh`**: Loads global config, checks for overlay, deep‑merges per merge rules, validates schema/version.
- **`report.sh`**: Enforces the report contract (≤500 tokens), writes full logs, returns JSON summary.
- **`project_key.sh`**: Derives the project key from `cwd` (deterministic slug + short hash).
- **`restore.sh`**: Helper to restore quarantined session files. Usage: `restore.sh <project-key> <session-id>`. It moves files from `trash/<project-key>/<session-id>/` back to their original relative paths. If a file already exists, rename the restored file with a `.conflict` suffix.
- **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.

---

## 6. Statusline & Limit Monitoring

The statusline is **not a hook** – it is a separate `statusLine` command configured in `~/.claude/settings.json`. It is the sole producer of limit metrics; the bridge hook (`limit-bridge.sh`) is the sole consumer.

### 6.1 Statusline (`statusline.sh`)
- Invoked by Claude Code on every refresh (via `statusLine` setting).
- Reads the statusline JSON from stdin (same schema as hooks, including `context_window` and `rate_limits`).
- Writes current **Context %**, **Session 5‑hour %**, and **Weekly %** to `state/<project-key>/limits.json` on every refresh.
- Prints its display to **stderr** (per Claude’s statusline protocol): current model, branch + dirty count, last report status, and the three percentages with tiered colour coding (🟡 / 🟠 / 🔴).
- **Performance**: Target < 100 ms. No writes except its own log line. Stale/missing state degrades to placeholders (`n/a`).
- **Refresh throttle**: Writes to `limits.json` no more than once every 5 seconds to avoid IO thrashing.

### 6.2 Limit Tiers & Bridge Hook (`limit-bridge.sh`)

| Limit | Notice (🟡) | Warning (🟠) | Action (🔴) |
|---|---|---|---|
| Context window | 60 % | 75 % | 85 % |
| Session (5‑hour) usage | 60 % | 75 % | 90 % |
| Weekly usage | 70 % | 85 % | 95 % |

- **Notice**: Statusline colour change only.
- **Warning**: Statusline change + **one‑time** `additionalContext` line (≤50 tokens) from `limit-bridge.sh` (triggered on `UserPromptSubmit` or `PreToolUse`). Dedupe via `state/<project-key>/limit_alerts.json`.
- **Action**: `limit-bridge.sh` injects a high‑priority wind‑down directive via `additionalContext`; logs the event; statusline turns red. For plan limits, instructs Claude to reach a clean stopping point.
- **Auto‑compact**: The hook system does **not** set this; users should set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85` in their environment. The README will recommend this.
- **Fallback**: If `rate_limits` data is unavailable, degrade to context‑only monitoring; show "n/a" for others; never crash or block.

---

## 7. Context‑Aware Validation

Code‑level checks are insufficient—validation must extend to the running system (VPS, email, web app, etc.).

### 7.1 Validation Profile
- Defined per project in `validation.targets` (overlay).
- Each target has a `type`, connection parameters as environment variable references, and a list of probes.
- An optional `validation.file_map` object maps glob patterns to target names. This limits which validators run based on the files touched in the session.
- **No overlay** = code‑level checks only. Validators never guess at remote targets.

### 7.2 Validator Scripts (`~/.claude/hooks/validators/`)
- One script per target type (`vps.sh`, `email.sh`, `web.sh`, `api.sh`, `db.sh`).
- **Safety**: Read‑only against production by default; mutating probes target sandbox resources exclusively. Secrets from `.env` never logged.
- **Execution in Stop Hook**:
  1. The Stop hook (`finish.sh`) reads the session manifest (from `state/<project-key>/manifest-<session-id>.json`) to obtain the list of files created or modified during the session.
  2. If `validation.file_map` exists, determine which targets are linked to those changed files. If no mapping is defined, run all configured targets. If a mapping exists but no touched files correspond to any target, skip remote validation entirely (only code‑level checks).
  3. Execute triggered validators **in parallel**, each with a timeout (from config).
  4. Wait for all to finish or time out. A timeout is treated as a failure.
  5. If any validator fails, block stop via JSON `decision: "block"` and name the failed probe(s).
- **`--test` mode**: Accepts mocked responses (fixtures) to test offline, including a "target unreachable" fixture (reports `error`, does not hang, respects timeout).

### 7.3 Validator Target Types (Implement Once)

- **VPS/Server**: SSH to verify artifact version/checksum, service status, ports, disk/memory, recent logs for errors.
- **Email**: Send probe to test recipient; verify delivery, SPF/DKIM/DMARC, no unintended recipients.
- **Web**: Headless browser (Playwright) to check key pages, console errors, network requests, critical flows; screenshots saved to logs.
- **API**: Probe endpoints for status, schema, auth behaviour.
- **Database**: Read‑only connectivity, migration version, row‑count sanity.

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
- **Classify at session end** (`finish.sh`): Entries matching scratch patterns (from config) and **not** committed, not in the `keep` list, and not in protected paths are classified as scratch.
  - *Git‑tracked check*: Use `git ls-files --error-unmatch <file> >/dev/null 2>&1`; if it returns 0, the file is tracked and **must never** be touched.
- **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths.
- **Report**: Include `details.scratch_quarantined: N` in the Stop report.
- **Restore**: `restore.sh` moves a quarantined session back to its original location (see Section 5).
- **Purge**: Janitor purges quarantine after `retention.trash_days`.

---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration with narrow matchers.
2. **`hooks/`** — Executable scripts per hook, each with stdin parsing, error handling, timing, `--test` mode.
3. **`hooks/lib/`** — Shared library (config, report, project‑key, restore, logging).
4. **`hooks/config.json`** — Global defaults with a `"version"` field and all keys documented.
5. **`hooks/config.overlay.example.json`** — Documented example for project overlays, showing how to override thresholds, add validation targets, use `_append`, etc.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, auto‑compact recommendation, and notes on missing tool handling.
7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification) and flagged project‑level duplicates. Only produced if something existed before.
9. **`hooks/statusline.sh`** — Upgraded statusline script.
10. **`hooks/validators/`** — Context‑aware validator scripts per target type.
11. **`hooks/test/run.sh`** — A simple test runner that invokes each script with `--test` and verifies exit codes and JSON validity (if applicable). BATS is optional but recommended.

---

## 10. Acceptance Criteria

### A. Functionality
- [ ] `claude --debug` shows each hook firing on its intended event and no others.
- [ ] Every script passes its `--test` mode against fixtures (including malformed JSON).
- [ ] Bash guard blocks `rm -rf /` and `git push --force origin main` (exit 2) and allows `ls`, `git status`.
- [ ] Stop hook blocks completion when a test is broken, allows when fixed—without looping.
- [ ] Bridge hook: silent below Notice tier; ≤50‑token advisory exactly once at Warning tier; wind‑down directive at Action tier. Dedupe works.
- [ ] `rate_limits` fallback: missing data degrades to context‑only, shows "n/a", never crashes.
- [ ] Statusline renders correctly from state, updates after hooks fire, degrades gracefully on missing state (<100 ms).
- [ ] Validators catch deliberately introduced faults and block Stop; after fix, Stop allowed.
- [ ] Session touching only unmapped files (when `validation.file_map` is present) triggers no remote probes.
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`, and cleans up session manifests.
- [ ] Repo tidiness: quarantines only scratch files; pre‑existing/git‑tracked/keep‑listed files untouched; `restore` recovers; purged after `trash_days`.
- [ ] Multi‑project: two different stacks (Node/Python/no toolchain) each adapt, no‑toolchain no‑ops cleanly, state/logs namespaced with no cross‑contamination.
- [ ] Project with no config overlay runs safely on pure global defaults.

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

### D. Safety & Validation
- [ ] No hook auto‑approves write/network operations.
- [ ] Validator probes are read‑only against production; mutating probes target designated sandboxes and clean up.
- [ ] Validator handles target unreachable (reports `error`, respects timeout, does not hang).
- [ ] Quarantine never touches git‑tracked files or files under protected paths.

### E. Wiring Integrity
- [ ] The implemented wiring matches the system schema: every hook resolves config/reports through `lib/`, all state/log/trash writes are namespaced, and no component outside the statusline produces limit metrics (spot‑check via grep and debug transcript).

---

## 11. Out of Scope

- HTTP/prompt/agent hook handler types (command hooks only for v1).
- Project‑level hook logic—repositories carry at most an optional config overlay (`.claude/hooks/config.json`), never scripts or hook entries. Existing project‑level hooks are flagged in `MIGRATION.md`, not modified.
- Any hook that auto‑approves write or network operations.

