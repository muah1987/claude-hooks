Here is an improved version of the specification. The core architecture and decisions are unchanged—only clarity, consistency, and edge cases have been tightened.

---

# Build a Token‑Efficient Hook Automation System for Claude Code

## Executive Summary

This document specifies a **user‑level automation layer** (`~/.claude/`) for Claude Code that intercepts deterministic tasks—formatting, linting, validation, indexing—and executes them via local scripts instead of LLM tool calls. It is token‑efficient, injecting only compact structured reports (≤500 tokens) back into the model’s context.

The system is designed for a **single installation that must serve every project**, regardless of language, stack, or deployment target. All project‑specific behaviour is resolved at runtime through a layered configuration mechanism (global defaults + per‑project overlays). Success is measured by fewer round trips, smaller context injections, and zero regressions across all projects—including those that do not yet exist.

---

## 1. Ground Rules (Read Before Implementing)

1.  **Native Hook System**: Use Claude Code’s official hook system exclusively. Hooks reside in `~/.claude/settings.json` (user‑level). All scripts live under `~/.claude/hooks/`. **Do not** invent a custom event bus or place hook logic inside individual repositories.
2.  **Official Reference**: Consult the [hooks documentation](https://code.claude.com/docs/en/hooks) for the current event list, stdin JSON schema, and output protocol before building. The event set may change between versions—do not rely on memory.
3.  **Script Invocation**: Every hook entry must invoke a script in `~/.claude/hooks/`. No inline logic in `settings.json` beyond the script path. Scripts are the unit of testing and reuse.
4.  **Hook Protocol Compliance**:
    - Scripts read a single JSON object from stdin (`hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`, etc.).
    - **Exit codes**: `0` = proceed; `2` = block (stderr is surfaced as the reason). Other codes = non‑blocking error.
    - **Structured control**: Use JSON on stdout (`hookSpecificOutput` with `permissionDecision` for `PreToolUse`; `decision`/`reason` for `Stop`; `additionalContext` to inject context). **Note**: `Stop` hooks block via JSON (`decision: "block"`), **not** via exit code 2. For all other hooks, `exit 2` is the blocking mechanism.
5.  **Token Discipline**:
    - Scripts **must never** dump raw logs, diffs, or test output into `additionalContext` or stderr.
    - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`.
    - Only a summary report (see Report Contract) is returned to the model, **capped at 500 tokens** (~2 000 characters). If results exceed that, summarize counts and include the log file path for on‑demand retrieval.
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
        - **Merge Rules**: Scalars are replaced by the overlay. Lists are **replaced** unless the overlay uses a key ending in `_append` (e.g., `protected_paths_append`), in which case they are concatenated and deduplicated.
        - **Versioning**: Both configs must include a `"version"` field. Scripts check compatibility and fall back gracefully if versions mismatch (log warning, use global defaults).
    - **Per‑Project State**: All state/logs are namespaced under `~/.claude/hooks/{state,logs,trash}/<project-key>/`.
        - **Project‑Key Derivation**: `slugify(basename($cwd)) + '-' + (echo -n $cwd | sha1sum | cut -c1-8)`. (e.g., `my-app-a1b2c3d4`).
    - **Secrets**: Read from the project’s `.env` at runtime. Global config stores variable *names*, never values.

---

## 2. System Architecture

The following diagram illustrates the data flow. The implementation must match this wiring exactly.

```
                        ┌─────────────────────────── Claude Code (any project) ───────────────────────────┐
                        │                                                                                  │
 EVENTS                 │  SessionStart   UserPromptSubmit   PreToolUse   PostToolUse   Stop/SessionEnd    │
                        └───────┬───────────────┬────────────────┬─────────────┬──────────────┬───────────┘
                                │ stdin JSON    │                │             │              │
                                ▼               ▼                ▼             ▼              ▼
                        ┌──────────────────────── ~/.claude/hooks/ (user level, all projects) ────────────┐
 HOOK SCRIPTS           │  context.sh      limit-bridge.sh   guards.sh     format.sh      finish.sh       │
                        │  janitor.sh ◄─┐  (reads state,     (bash guard,  index.sh       (tests +        │
                        │  (async,      │   injects tier     protected     (async)        validators +    │
                        │   retention)  │   directives)      paths)        manifest.sh    repo-tidy →     │
                        │               │                                  (track writes) quarantine)     │
                        └───────┬───────┼──────────┬──────────────┬─────────────┬──────────────┬──────────┘
                                │       │          │              │             │              │
                                ▼       │          ▼              ▼             ▼              ▼
 SHARED LIB             ┌  lib/: config-loader (global ⊕ project overlay) · report.sh (contract + 500-tok cap)
                        │        project-key derivation · restore (un-quarantine) · timing/logging helpers
                        └───────┬──────────────────────────────────────────────────────────────┬──────────┘
                                │                                                              │
                                ▼                                                              ▼
 CONFIG (read-only)     global: ~/.claude/hooks/config.json          overlay: $PROJECT/.claude/hooks/config.json
                        (defaults: tiers, retention, patterns)       (validation.targets, keep-list, overrides)
                                │                        secrets: $PROJECT/.env (names in config, values here)
                                ▼
 STATE & OUTPUT         ~/.claude/hooks/state/<project-key>/   logs/<project-key>/   trash/<project-key>/
                                ▲          │                          ▲                      ▲
                                │          │ read                     │ full output          │ scratch files
                                │          ▼                          │                      │ (7-day purge)
 STATUSLINE             statusline.sh ── writes limits.json ─────────┘   ← sole producer of limit metrics
 (bridge + display)     displays: model · branch · last report status · 3 limit gauges (🟡🟠🔴)
                                │
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / headless browser / HTTP)
 (Stop hook, per        activated per project overlay by validation.targets; fixtures mock targets for --test
  touched target)
                                │
                                ▼
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

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
- Gracefully handle missing tools (e.g., no linter installed) by logging a warning and exiting `0`.

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
- **`restore.sh`**: Helper to restore quarantined session files (moves them back preserving paths; handles conflicts by renaming with a `.conflict` suffix).
- **`logging.sh`**: Standardized JSONL logging with timestamps, durations, and error handling.

---

## 6. Statusline & Limit Monitoring

The statusline is the sole producer of limit metrics; the bridge hook is the sole consumer.

### 6.1 Statusline (`statusline.sh`)
- Reads the statusline JSON from stdin (verify schema against official docs).
- Writes current **Context %**, **Session 5‑hour %**, and **Weekly %** to `state/<project-key>/limits.json` on every refresh.
- Displays (to stderr): current model, branch + dirty count, last report status, and the three percentages with tiered colour coding (🟡 / 🟠 / 🔴).
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
- **Auto‑compact**: As a safety net, users should ensure Claude’s built‑in auto‑compact is enabled and set to 85 % context usage (via environment variables or configuration). The hook system does not control this directly; document the recommended setting in the README.
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
  1. If `validation.file_map` exists, determine which targets are linked to files changed in this session. If no mapping is defined, run all configured targets. If a mapping exists but no touched files correspond to any target, skip remote validation entirely (only code‑level checks).
  2. Execute triggered validators **in parallel**, each with a timeout (from config).
  3. Wait for all to finish or time out. A timeout is treated as a failure.
  4. If any validator fails, block stop via JSON `decision: "block"` and name the failed probe(s).
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
- Orphan sweep: removes namespaces for projects that no longer exist on disk (after `state_days`).
- Injects nothing into context; writes one summary line to its own log.

### 8.2 Repo Tidiness (Scratch Files, Higher Risk)
- **Track**: `manifest.sh` records every file *created* by Claude this session (`PostToolUse` Write). Only files in this manifest are candidates.
- **Classify at session end** (`finish.sh`): Entries matching scratch patterns (from config) and **not** committed, not in the `keep` list, and not in protected paths are classified as scratch.
  - *Git‑tracked check*: Use `git ls-files`; tracked files are never touched (even if they later match a scratch pattern).
- **Quarantine**: Move scratch files to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths.
- **Report**: Include `details.scratch_quarantined: N` in the Stop report.
- **Restore**: `restore.sh` moves a quarantined session back to its original location.
- **Purge**: Janitor purges quarantine after `retention.trash_days`.

---

## 9. Deliverables

All files reside under `~/.claude/`—nothing is written into repositories.

1. **`settings.json`** — Hook configuration with narrow matchers.
2. **`hooks/`** — Executable scripts per hook, each with stdin parsing, error handling, timing, `--test` mode.
3. **`hooks/lib/`** — Shared library (config, report, project‑key, restore, logging).
4. **`hooks/config.json`** — Global defaults with a `"version"` field.
5. **`hooks/config.overlay.example.json`** — Documented example for project overlays.
6. **`hooks/README.md`** — Table of hooks, config layering, how to add an overlay, auto‑compact recommendation.
7. **`hooks/fixtures/`** — Sample stdin JSON for each hook (including malformed JSON).
8. **`hooks/MIGRATION.md`** — Inventory of pre‑existing hooks/scripts (upgraded or retired, with justification) and flagged project‑level duplicates. Only produced if something existed before.
9. **`hooks/statusline.sh`** — Upgraded statusline script.
10. **`hooks/validators/`** — Context‑aware validator scripts per target type.
11. **`hooks/test/harness.bats`** (optional but recommended) — BATS test harness to run all `--test` modes.

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
- [ ] Janitor removes aged files, respects size cap, runs ≤ once per `janitor_interval_hours`.
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