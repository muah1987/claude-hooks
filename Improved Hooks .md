# Build a Token-Efficient Hook Automation System for Claude Code

## Objective

Implement a hook-based automation layer at the **user level** (`~/.claude/`) that applies to every project this user opens with Claude Code. It offloads deterministic work (formatting, linting, testing, validation, indexing) from the LLM to scripts. The LLM plans and decides; hooks detect events; scripts do the work; only compact structured reports flow back into the model's context.

Because one installation must serve all projects — any language, any stack, any deployment target — nothing may assume a specific project. All project-specific behavior is resolved at runtime through layered configuration (see rule 12).

Success is measured by: fewer tool-call round trips for routine tasks, smaller context injections, and zero regressions in existing workflows — across every project, including ones that don't exist yet.

## Ground rules (read before writing any code)

1. Use Claude Code's native hook system. Hooks are configured in `~/.claude/settings.json` (user-level) and all scripts live under `~/.claude/hooks/`. Do not invent a custom event bus, and do not place hook logic in individual repositories.
2. Consult the official hooks reference (https://code.claude.com/docs/en/hooks) for the current event list, stdin JSON schema, and output protocol before implementing. Do not rely on memory — the event set changes between versions.
3. Every hook entry must invoke a script in `~/.claude/hooks/` — no inline one-liner logic in settings.json beyond the script invocation itself. Scripts are the unit of testing and reuse.
4. Respect the hook protocol:
   - Scripts read a single JSON object from stdin (`hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`, etc.).
   - Exit 0 = proceed; exit 2 = block (stderr is surfaced as the reason); other codes = non-blocking error.
   - Structured control uses JSON on stdout (`hookSpecificOutput` with `permissionDecision` for PreToolUse; `decision`/`reason` for Stop-class events; `additionalContext` to inject context).
5. Token discipline is the core requirement:
   - Scripts must never dump raw logs, diffs, or test output into `additionalContext` or stderr.
   - Full output goes to `~/.claude/hooks/logs/<project-key>/<event>-<timestamp>.jsonl`, where `<project-key>` is derived from the project path (see rule 12); only a summary report (see contract below) is returned to the model.
   - Reports are capped at 500 tokens (~2,000 characters). If results exceed the cap, summarize counts and include the log file path for on-demand retrieval.
6. Performance: PreToolUse hooks gate every matched tool call — target < 500 ms. Anything slower (test suites, indexing) belongs on PostToolUse or Stop, or runs with `"async": true` when the result doesn't need to block.
7. Chaining is not a native hook feature. Where one automation should trigger another, implement it inside the script (script A calls script B) or via a shared state file that a later hook reads. Document each chain explicitly.
8. Safety: never auto-approve destructive operations. PermissionRequest/PreToolUse hooks may auto-allow only an explicit allowlist of read-only or idempotent commands. Blocking hooks must use exit 2 (exit 1 only warns).
9. Guard against loops: any Stop hook must check `stop_hook_active` in the stdin JSON and exit 0 when true.
10. Audit before building. Before implementing anything new, inventory what already exists: hook entries in `~/.claude/settings.json`, scripts under `~/.claude/hooks/`, the `statusLine` configuration, and any project-level `.claude/settings.json` hooks in currently known projects (these keep working alongside user-level hooks — note any that duplicate or conflict with the new system and recommend their removal in MIGRATION.md, but do not modify repositories). Nothing existing at user level is left as-is: every existing hook and script is either upgraded to meet all standards in this document (script-based, stdin JSON parsing, report contract, logging, timing, `--test` mode, fixtures) or explicitly retired with a one-line justification in the README. Do not run old and new conventions side by side.
11. Everything dynamic — no hardcoded values. Scripts must contain zero hardcoded absolute project paths, usernames, project names, branch names, model names, tool commands, or environment-specific values. Specifically:
    - **Paths**: derive everything from the stdin JSON (`cwd`, `transcript_path`) or `$CLAUDE_PROJECT_DIR`; script-relative paths resolve from the script's own location. The only permitted anchor is the user-level home (`~/.claude/...`), expressed via `$HOME` or equivalent — never a literal `/home/<user>/...` or `C:\...`.
    - **Project specifics**: detect at runtime, don't assume. Formatter/linter/test commands are discovered per project from its manifests (`package.json` scripts, `Makefile`, `pyproject.toml`, etc.) or read from the layered config (rule 12) — a formatting hook that hardcodes one tool breaks on every project with a different stack, and at user level that is guaranteed to happen. When a project has no matching toolchain, the hook no-ops silently (log only, inject nothing). The default branch is read from git (`origin/HEAD`), not assumed to be `main`. File-type handling dispatches on extension/detection, not on hardcoded filenames.
    - **Tunables**: every threshold, cap, timeout, tier percentage, allowlist, denylist, and protected-path pattern lives in config (rule 12), with the values in this document as shipped defaults — scripts read config, never embed the numbers. One value, one location.
    - **Dynamic API surface**: field names, event names, and env vars from the hook/statusline protocol are read defensively — missing or renamed fields degrade gracefully (see the `rate_limits` fallback) rather than crashing.
    - The test: the installation must work unmodified for any project on any machine, OS, or user account — and adapt to a specific project's needs by editing only that project's config overlay.
12. Layered configuration and per-project state — the mechanism that makes one installation serve all projects:
    - **Global defaults**: `~/.claude/hooks/config.json` holds the defaults for everything (thresholds, tiers, caps, guard patterns, validator timeouts).
    - **Project overlay**: if `$CLAUDE_PROJECT_DIR/.claude/hooks/config.json` exists, it is deep-merged over the global defaults for that project only. This is where per-project material lives: `validation.targets`, project-specific protected paths, threshold overrides, toolchain overrides. Overlays are optional — every hook must work sensibly on a project that has none.
    - **Per-project state and logs**: all state files and logs are namespaced under `~/.claude/hooks/state/<project-key>/` and `~/.claude/hooks/logs/<project-key>/`, where `<project-key>` is derived deterministically from the project path (e.g. slug + short hash). No project's automation may ever read another project's state, and nothing is written into repositories except deliverables the user asked for.
    - **Secrets**: read from the project's own `.env` (or the environment) at runtime. Global config stores variable *names*, never values.

## Deliverables

All under `~/.claude/` — nothing is written into repositories.

1. `~/.claude/settings.json` — hook configuration with matchers scoped as narrowly as possible (e.g. `Write|Edit` for formatting, `Bash` for command guards).
2. `~/.claude/hooks/` — one executable script per hook, each with:
   - stdin JSON parsing with graceful failure (malformed input → exit 0 + log, never crash the session)
   - error handling, execution timing, and structured logging to the per-project log directory (rule 12)
   - a `--test` mode that accepts sample JSON for standalone verification
3. `~/.claude/hooks/lib/` — shared library: report generator enforcing the report contract, config loader implementing the global + overlay merge, and the project-key derivation used for state/log namespacing.
4. `~/.claude/hooks/config.json` — global defaults for all tunables, plus a documented, commented example overlay file (`~/.claude/hooks/config.overlay.example.json`) the user can copy into any project.
5. `~/.claude/hooks/README.md` — one table: event, matcher, script, purpose, blocking behavior, typical runtime; plus a short section explaining the config layering and how to add a project overlay.
6. Sample stdin fixtures in `~/.claude/hooks/fixtures/` for each hook, used by `--test` mode.
7. `~/.claude/hooks/MIGRATION.md` — inventory of pre-existing user-level hooks/scripts (upgraded or retired, with justification) and any project-level hooks found that duplicate the new system (flagged with a removal recommendation). Only produced when something existed before this work.
8. Upgraded statusline (see statusline section below) — `statusLine` entry in `~/.claude/settings.json` pointing to `~/.claude/hooks/statusline.sh` (or equivalent).
9. `~/.claude/hooks/validators/` — context-aware validator scripts per the validation section. Per-project `validation.targets` profiles live in each project's config overlay (proposed to the user for confirmation when inferred).
10. Cleanup subsystem (see cleanup section): janitor script, session-manifest tracking, repo-tidy quarantine with `restore` helper, and `retention.*` defaults in global config.

## Report contract

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

`details` holds counts and short identifiers only — never file contents, stack traces, or diffs.

## Statusline upgrade

The statusline is part of this automation system and must meet the same standards as the hooks. If a `statusLine` command already exists, upgrade it in place; if not, create one.

Requirements:

- Implemented as a script in `~/.claude/hooks/` (same conventions: stdin JSON parsing, graceful failure, `--test` mode, fixture). It reads the statusline JSON from stdin — verify the current input schema in the official docs before implementing.
- Zero LLM cost: the statusline renders purely from local state and must never inject anything into the model's context.
- Reuse hook state instead of recomputing: read the per-project state files (rule 12) that the hooks already maintain (e.g. last report status, background index freshness, test pass/fail from the last Stop hook run) rather than re-running git or test commands on every refresh. The project key is derived from the stdin `cwd`/workspace fields, so the same statusline shows the right state in every project.
- Display at minimum: current model, branch + dirty-file count, the status (`ok/warn/blocked/error`) of the most recent hook report, and the three monitored percentages — context window, session (5-hour) usage, and weekly usage — with tiered color coding (see auto-compact section).
- Bridge duty: on every refresh, write the monitored percentages to the state file consumed by the limit-monitoring hooks. This is the only live source of context/usage metrics in Claude Code, so the statusline is a functional component of the automation, not just a display.
- Fast and side-effect free: target < 100 ms, no writes except its own log line, and a stale or missing state file degrades to a placeholder instead of an error.

## Auto-compact and limit monitoring

Three limits must be monitored continuously. Each has its own optimized thresholds, because the cost of acting late differs per limit — the context window hard-fails if compaction fires too late, while plan limits just burn quota faster. Flat thresholds across all three would be wrong.

| Limit | Notice (🟡) | Warning (🟠) | Action (🔴) | Rationale for action level |
|---|---|---|---|---|
| Context window | 60% | 75% | **85%** — auto-compact fires | Compaction itself consumes context; the stock buffer reserves roughly 15–20% of the window for it. 85% preserves that headroom while gaining usable space over the ~77–83% default. Above ~90%, `/compact` can fail outright and deadlock the session. |
| Session (5-hour) usage | 60% | 75% | **90%** — compact + wind-down directive | Compaction only slows future burn, it restores nothing — so acting must happen while budget remains to benefit. 10% residual is enough to compact and reach a clean stopping point; at 98% there is nothing left to save. |
| Weekly usage | 70% | 85% | **95%** — compact + wind-down directive | Weekly quota is the long-horizon budget: earlier tiers give the user days of visibility, and the action level preserves a final ~5% reserve for urgent fixes rather than letting routine work consume it. |

Behavior per tier:

- **Notice**: statusline color change only. No context injection — visibility must not cost tokens.
- **Warning**: statusline color change + a one-time `additionalContext` line (≤ 50 tokens) from the bridge hook advising Claude to avoid starting large multi-file work and to prefer compact-friendly stopping points. Fires once per tier crossing per session, not per prompt — dedupe via the state file.
- **Action**: as specified below (handoff persist, compact/wind-down, log, red indicator).

All thresholds live in the global config (`~/.claude/hooks/config.json`) with these values as defaults — overridable per project via the config overlay (rule 12) if measurement (see acceptance criteria) shows the defaults fire too early or too late for a specific project. Any override must be justified in a comment in the overlay.

Implementation constraints — verify each against the current official docs before building:

- **Context window**: use the built-in auto-compact; do not reimplement it. Ensure it is enabled and set its trigger to the action threshold via the supported mechanism (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` or its current equivalent). Confirm the configured value measures the same quantity as the statusline's `used_percentage` (input-tokens-only) so displayed and acted-on numbers agree.
- **Hooks cannot invoke `/compact`**: slash commands are not programmatically triggerable from hooks, and non-statusline hooks do not receive context/usage metrics. Use the statusline-bridge pattern: the statusline script (which receives `context_window.*` and, on supported plans/versions, `rate_limits.five_hour` and `rate_limits.seven_day` on stdin) writes current percentages to the per-project state directory (rule 12) on every refresh. A `UserPromptSubmit` (and/or `PreToolUse`) hook reads that state file and acts on it.
- **At the action tier on any monitored limit**, the bridge hook must: (a) inject a high-priority directive via `additionalContext` instructing Claude to immediately persist working state (current goal, changed files, next step) to a handoff file and initiate compaction/wind-down; (b) log the event; (c) surface a red indicator in the statusline. For plan-usage limits specifically, the directive must also warn that compaction reduces future consumption but does not restore quota, and instruct Claude to reach a clean stopping point.
- Threshold checks are pure state-file reads — no API calls or token counting inside gating hooks; all polling cost lives in the statusline path.

The statusline (see statusline section) must display all three percentages with the tiered color coding so the user sees the same numbers the automation acts on.

## Initial hook set (implement these first)

| Event | Matcher | Purpose | Blocking |
|---|---|---|---|
| PostToolUse | Write\|Edit | Auto-format + lint-fix changed file using the project's own toolchain (discovered per rule 11); report only if fixes/errors occurred | No |
| PreToolUse | Bash | Block dangerous patterns (recursive deletes outside temp paths, force-push to the repo's default branch, credential file access) — patterns defined in config.json | Yes (exit 2) |
| PreToolUse | Read\|Edit\|Write | Deny access to `.env*`, key files, and protected-path patterns from the layered config (global denylist + project overlay additions) | Yes (exit 2) |
| Stop | — | Run test suite + the context-aware validators for targets touched this session (see validation section); block stop with a failure report if either fails (respect `stop_hook_active`) | Yes (decision: block) |
| SessionStart | — | Inject compact project context: branch, dirty-file count, last 5 commits, open TODO count (≤ 300 tokens) | No |
| SessionStart (async) | — | Janitor: retention-based cleanup of own logs/state/screenshots/trash, rate-limited via state timestamp (see cleanup section) | No |
| PostToolUse (async) | Write | Session manifest: record files created by Claude this session (feeds repo tidiness) | No |
| Stop / SessionEnd | — | Repo tidiness: classify manifest entries as scratch per config patterns, quarantine to trash namespace, report count (see cleanup section) | No |
| PostToolUse (async) | Write\|Edit | Update project index/dependency graph in background; write to state file, inject nothing | No |

Extend beyond this set only where a repetitive task is observed across the user's projects — justify each addition in the README.

## Context-aware validation (validate against the real target)

Code-level checks (lint, unit tests) are necessary but not sufficient. Validation must extend to whatever the project actually *is*: the running system, not just the source tree. "Tests pass" means nothing if the deployed VPS is serving the old version or the email never arrived. The validation logic must fit the project's domain.

### Mechanism

- **Validation profile per project**: a `validation.targets` array in the project's config overlay (rule 12) declaring what that project deploys to or produces. Each target has a `type`, connection parameters as environment-variable *references* (values live in the project's `.env`, never in config or scripts — per rule 11), and a list of enabled probes. Projects with no overlay get code-level checks only — validators must never guess at remote targets.
- **One validator script per target type** in `~/.claude/hooks/validators/` — written once, reused by every project whose overlay declares that target type — following every existing standard: report contract, full output to the per-project logs, ≤500-token summary, `--test` mode with fixtures (fixtures mock the remote responses so validators are testable offline).
- **Wired into the Stop hook**: before Claude declares work complete, the Stop hook runs the validators relevant to what changed this session (a validator only fires if the session touched files/areas mapped to its target in the overlay — no point browser-testing after a README edit). Failures block stop with a `decision: block` report naming the failed probe. Slow validators (> ~15 s) run in async mode with results written to the state file and injected on the next prompt instead of blocking.
- **Detection, not assumption**: when a project looks deployable but has no overlay, infer candidate target types from the project itself (deploy scripts, `docker-compose.yml`, SMTP config, framework manifests, an existing `mip.md`), generate a proposed overlay with a `validation.targets` block, and ask the user to confirm it once per project rather than guessing credentials or hosts.

### Validator logic per target type — implement all of the following once at user level; each activates only for projects that declare it

- **VPS / server deployments**: over SSH (key from `.env`), verify the deployed artifact matches the local state (version string, git SHA, checksum), services are `active`, ports respond, disk/memory are within thresholds, and recent service logs contain no new errors since the deploy timestamp. Report: version match yes/no, per-service status, error count — never raw logs.
- **Email systems (server, accounts, DMs/notifications)**: after a change touching mail flow, send a probe message to a designated test recipient defined in config (never a real user), then verify end-to-end via IMAP/API: delivery within timeout, correct sender/subject/body template, SPF/DKIM/DMARC pass in the received headers, and no bounce in the MTA log. For account or DM logic: verify the triggering action produced exactly the expected messages — and none to unintended recipients.
- **Websites / web apps**: browser-level verification with a headless browser (Playwright or equivalent; plain HTTP probe as fallback when unavailable): key pages return 200, render without JS console errors or failed network requests, critical elements/flows exist (configurable selectors — login form, checkout button), and a screenshot per checked page is saved to the log directory for the user. Report: pages checked, console error count, failed requests, screenshot paths — never HTML dumps.
- **APIs / services**: probe declared endpoints for status, schema-valid responses, and auth behavior (valid token accepted, missing token rejected).
- **Databases**: read-only sanity probes — connectivity, migration version matches the codebase, row-count sanity on critical tables.
- **Other project types**: follow the same pattern — identify the observable end result the user cares about, probe it programmatically, report a summary. The domain logic must fit each project; when no meaningful probe exists for a target type, document that in the README rather than shipping a vacuous validator.

### Safety rules for validators

- Probes are **read-only against production** by default. Anything that mutates state (sending a probe email, creating a test record) must target sandbox/test resources explicitly designated in config, and must clean up after itself.
- Secrets come from `.env` at runtime, are never logged, never appear in reports or `additionalContext`, and validator log files are added to the protected-paths denylist.
- A validator that cannot reach its target reports `status: error` with the reason (timeout, auth, DNS) — distinguishing "target is broken" from "couldn't check" — and never blocks indefinitely: every remote call has a timeout from config.

## Cleanup and tidiness

The automation itself produces artifacts (logs, state, screenshots) and agent sessions produce scratch material (throwaway scripts, debug files, temp outputs). Both accumulate forever unless cleanup is itself a hook. Two cleanup responsibilities, two different risk levels:

### 1. Housekeeping of the automation's own files (`~/.claude/hooks/`) — low risk, fully automatic

- An async janitor script runs on `SessionStart` (and no more than once per interval defined in config, e.g. 24h, tracked via a state timestamp — not on every session start).
- Enforces retention from global config: logs older than `retention.logs_days` (default 14) deleted; state files for project keys untouched for `retention.state_days` (default 60) deleted; validator screenshots older than `retention.screenshots_days` (default 7) deleted; hard size cap per project namespace (default 100 MB) with oldest-first eviction.
- Orphan sweep: namespaces whose project path no longer exists on disk are removed after the state retention period.
- Runs `async`, injects nothing into context; writes one summary line to its own log (files removed, bytes freed).

### 2. Repo tidiness (scratch files inside the project) — higher risk, quarantine-first

Deleting files in a user's repository must never be a guess. The mechanism:

- **Track, don't infer**: a lightweight `PostToolUse` (Write, async) addition records every file *created* by Claude this session into a session manifest in the project's state namespace. Only files in this manifest are ever cleanup candidates — a file that existed before the session is never touched, regardless of its name.
- **Classify at session end**: on `Stop`/`SessionEnd`, manifest entries matching scratch patterns from the layered config (defaults: `*.tmp`, `scratch*`, `debug_*`, `test_output*`, `*.bak`, `tmp_*` — extendable per project via the overlay) and not referenced by the final work product (not committed, not imported/required by remaining code, not listed as a deliverable) are classified as scratch.
- **Quarantine, not delete**: scratch files are *moved* to `~/.claude/hooks/trash/<project-key>/<session-id>/` preserving relative paths, and a one-line note is included in the Stop report (`details.scratch_quarantined: N`). The janitor purges quarantine after `retention.trash_days` (default 7). A `restore` helper script in `lib/` moves a quarantined session back.
- **Never touched, ever**: anything git-tracked, anything the user created, anything under the protected-paths denylist, `.env*`, and anything the user explicitly asked to keep (an overlay `keep` list). When classification is uncertain, the file stays and is merely listed in the report.

## System schema — how everything wires together

The implementation must match this wiring exactly; the README reproduces this diagram.

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
 STATUSLINE             statusline.sh ── writes ctx% / 5h% / weekly% ─┘   ← the ONLY live metrics source;
 (bridge + display)     displays: model · branch · last report status · 3 limit gauges (🟡🟠🔴)
                                │
                                ▼
 VALIDATORS             validators/{vps,email,web,api,db}.sh ──► real targets (SSH / IMAP / headless browser / HTTP)
 (Stop hook, per        activated per project by overlay's validation.targets; fixtures mock targets for --test
  touched target)
                                │
                                ▼
 BACK TO THE MODEL      ONLY: ≤500-token reports · tier directives · block reasons.   Everything else → disk.
```

Wiring rules the diagram encodes: every hook goes through `lib/` for config and reporting (no direct config parsing in hook scripts); every write of state/logs/trash goes through the project-key namespace; the statusline is the sole producer of limit metrics and the bridge hook their sole consumer; the model receives nothing except capped reports and directives.

## Acceptance criteria

- [ ] `claude --debug` shows each hook firing on its intended event and no others.
- [ ] Every script passes its `--test` mode against the fixtures, including a malformed-JSON fixture.
- [ ] The Bash guard blocks `rm -rf /` and `git push --force origin main` (exit 2, reason on stderr) and allows `ls`, `git status`.
- [ ] The Stop hook blocks completion when a test is deliberately broken, and allows it once fixed — without looping.
- [ ] No hook output injected into the model exceeds 500 tokens (verify from the debug transcript).
- [ ] Formatting hook completes in < 2 s on the largest file in the test project; PreToolUse guards complete in < 500 ms.
- [ ] Removing the hook entries from `~/.claude/settings.json` restores stock behavior — no script has side effects outside `~/.claude/hooks/` state/logs and intended file formatting.
- [ ] No pre-existing user-level hook, script, or statusline remains on the old conventions: everything is upgraded or retired, and MIGRATION.md accounts for each item (including flagged project-level duplicates).
- [ ] The statusline renders correctly from hook state, updates after a hook fires, degrades gracefully when state files are missing, and completes in < 100 ms.
- [ ] Built-in auto-compact is verified enabled at the 85% action threshold; fixture-driven tests of the bridge hook confirm, for each limit independently: nothing injected below its notice tier, the ≤50-token advisory exactly once at the warning tier, and the wind-down directive at the action tier (e.g. session limit: silent at 89%, directive at 90%).
- [ ] Compaction completes successfully in a session deliberately driven to the 85% context threshold — proving the headroom is sufficient, not assumed.
- [ ] When `rate_limits` data is unavailable (plan/version without it), the system degrades to context-window monitoring only, shows "n/a" in the statusline, and never crashes or blocks.
- [ ] Portability check: `grep -rn` across `~/.claude/hooks/` finds no absolute user paths beyond `$HOME`-derived ones, no hardcoded branch/model/tool-command strings outside config files, and no threshold numbers outside config files; all hook `--test` fixtures pass when run from a different working directory.
- [ ] Multi-project check: the system is exercised in at least two projects with different stacks (e.g. one Node, one Python, or one with no toolchain at all). Hooks adapt per project, the no-toolchain project produces clean no-ops (log only, nothing injected, nothing blocked), and each project's state/logs land in its own namespace with no cross-contamination.
- [ ] A project with no config overlay runs safely on pure global defaults: code-level checks work, no remote probes fire, nothing errors.
- [ ] Each configured validator passes `--test` offline against mocked-response fixtures, including a target-unreachable fixture (reports `error`, does not hang, respects its timeout).
- [ ] Against a real target in at least one project: a deliberately introduced fault (e.g. stopped service, broken page element, wrong mail template — whichever fits that project) is caught by the validator and blocks the Stop hook; after the fix, stop is allowed.
- [ ] A session that only touches files unmapped to any target triggers no remote probes (verified from validator logs).
- [ ] No secret value from any project's `.env` appears in any report, log summary, injected context, or the debug transcript.
- [ ] Janitor: aged fixture files beyond each retention threshold are removed on the next rate-limited run, files within retention survive, the size cap evicts oldest-first, and the janitor never runs more than once per configured interval.
- [ ] Repo tidiness: a session that creates both a scratch file (matching patterns) and a real deliverable quarantines only the scratch file; a pre-existing file with a scratch-like name is untouched; git-tracked, keep-listed, and protected-path files are untouched; the quarantined file is recoverable via `restore` and purged after `retention.trash_days`.
- [ ] The implemented wiring matches the system schema: every hook resolves config and reports through `lib/`, all state/log/trash writes are namespaced by project key, and no component outside the statusline produces limit metrics (spot-check via grep and the debug transcript).

## Out of scope

- HTTP/prompt/agent hook handler types (command hooks only for v1).
- Project-level hook logic — repositories carry at most an optional config overlay (`.claude/hooks/config.json`), never scripts or hook entries. Existing project-level hooks are flagged in MIGRATION.md, not modified.
- Any hook that auto-approves write or network operations.