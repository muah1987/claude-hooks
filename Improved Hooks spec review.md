# Review Report — "Token-Efficient Hook Automation System" Specification (base, v10, v11, v12)

**Reviewed:** `Improved_Hooks_.md` (base), `Improved_Hooks_v10.md`, `Improved_Hooks_V11.md`, `Improved_Hooks_V12.md`
**Date:** 14 July 2026
**Method:** Full read of all four documents, cross-checked against the official Claude Code hooks reference (code.claude.com/docs/en/hooks) and statusline documentation as of July 2026.

---

## 1. Context and purpose

These four files are successive iterations of a *specification / implementation prompt* — not code. The document instructs Claude Code to build a user-level (`~/.claude/`) hook automation layer that offloads deterministic work (formatting, linting, testing, validation, cleanup, limit monitoring) from the LLM to shell scripts, with strict token discipline (≤500-token reports back to the model), layered configuration (global defaults + per-project overlay + a dynamic `validator_context.md`), per-project state/log/trash namespacing, context-aware validators (VPS/email/web/API/DB), a quarantine-based repo-tidiness system, and an upgraded statusline with tiered limit monitoring.

The evolution is: the base file is a compact prose spec; v10 restructured it into a formal specification with "official" schemas; v11 and v12 are incremental refinement passes, each with a change table. v12 declares itself "fully aligned with official Claude Code hooks documentation … ready for implementation."

The overall design intent is sound and the later versions genuinely fixed real problems (manifest tracking now covers edits, atomic state writes, the dynamic-context merge restricted to the `validation` subtree, `awk` instead of `perl`, faster default-branch detection). However, verification against the official documentation shows that v12's central limit-monitoring architecture is built on a factually inverted claim, that two of its "clarifications" are regressions relative to earlier versions, and that several internal contradictions remain. These are detailed below, most severe first.

---

## 2. Critical findings (would break the implementation)

### 2.1 The limit-collector architecture is inverted — the base file had it right

v12 §1.1 claims the *hook* stdin JSON contains `context_window` and `rate_limits`, and §1.2 claims as a "critical difference" that the *statusline* does **not** receive these fields. The official documentation says exactly the opposite. The documented common hook input fields are `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `effort`, and `hook_event_name` plus event-specific fields — there is no `context_window` or `rate_limits` in hook input. Meanwhile the statusline stdin payload *does* include `context_window` (with `used_percentage`, `context_window_size`, `current_usage`, etc.), `exceeds_200k_tokens`, and — for Pro/Max subscribers on recent versions — `rate_limits.five_hour` and `rate_limits.seven_day`.

The consequence is severe: `limit-collector.sh` (a PostToolUse hook, §6.2) would find nothing to extract, `limits.json` would forever contain nulls, the statusline gauges would show "n/a" permanently, and `limit-bridge.sh` would never fire a tier directive. The entire Section 6 data flow, plus the wiring-integrity acceptance criteria ("`limit-collector.sh` is the ONLY producer of `limits.json`"), is unimplementable as written.

Notably, the **base file** (`Improved_Hooks_.md`, statusline section) described the correct architecture: "non-statusline hooks do not receive context/usage metrics. Use the statusline-bridge pattern: the statusline script (which receives `context_window.*` and … `rate_limits` … on stdin) writes current percentages to the per-project state directory; a UserPromptSubmit and/or PreToolUse hook reads that state file and acts on it." v10's "Revised Architecture" inverted this based on a hallucinated schema, and v11/v12 carried the inversion forward. The fix is to restore the base file's design: statusline = collector + display; bridge hook = reader + injector.

Related: the claim that `rate_limits` was added to hook input "from Claude Code v2.1.80" is unverifiable and appears fabricated (the field belongs to statusline input, and a documented regression around v2.1.96 even removed it from statusline input temporarily — GitHub issue #45133). Defensive reading remains good advice, but the version claim should be removed.

### 2.2 The `if` field is not a regex — v11 introduced a regression that v12 "clarified" further in the wrong direction

v10 had the correct syntax: `"if": "Bash(rm *)"`. The official docs confirm `if` uses **permission-rule syntax** (`Bash(git *)`, `Edit(*.ts)`), evaluated only on tool events, with documented subcommand/`$()`/backtick matching semantics, and it fails *open* when the command can't be parsed. v11's change table replaced this with "`if` is a regex pattern matched against the full tool call string," and v12 doubled down ("case-sensitive regex … anchor with `^…$`"). The v12 `settings.json` example uses `"if": "rm -rf|push --force"`, which is not a valid permission rule; depending on parser tolerance the guard hook either never spawns or always spawns — either way, not what the spec intends.

Two secondary problems ride along: hardcoding the dangerous-pattern list inside `settings.json` violates the spec's own rules 3 (no inline logic) and 11 (no hardcoded tunables outside config); and because the docs state the `if` filter is best-effort and fails open, a security guard must not rely on it — the spec should say the guard script itself re-checks, and that hard denies belong in the permission system.

### 2.3 `format.sh` is registered on the wrong event in the settings.json example (all of v10–v12)

The hook-set table (§4.2) correctly places `format.sh` on `PostToolUse` — you can only format a file *after* it has been written. But the `settings.json` example (§3.3) in v10, v11, and v12 registers it under **`PreToolUse`** with `matcher: "Edit|Write"` and a 30-second timeout. On PreToolUse the file change hasn't happened yet, so the hook formats stale content (or nothing), and a 30 s synchronous PreToolUse hook also violates the spec's own rule 6 (PreToolUse < 500 ms). Since the deliverable instructs the implementer to follow "this exact structure," the example must be corrected to `PostToolUse`.

### 2.4 `limit-bridge.sh` is specified but never wired

Section 6.4 and the architecture diagram give `limit-bridge.sh` the job of injecting Warning/Action tier directives "on `UserPromptSubmit` or `PreToolUse`," and §5.2 step 6 additionally makes it the injector of async validator results "on the next UserPromptSubmit." Yet it appears in neither the initial hook set table (§4.2) nor the `settings.json` example — and no `UserPromptSubmit` entry exists anywhere in the configuration. Three acceptance criteria (bridge tier behavior, async-result injection, wiring integrity) test a component that the deliverable configuration never registers. Add a `UserPromptSubmit` (and optionally `PreToolUse`) entry for it.

---

## 3. High-severity findings (contradictions and doc mismatches)

### 3.1 Malformed dynamic context: skip or block? The spec contradicts itself

Section 5.2 step 1: if `<validator-targets>` extraction fails → "skip remote validation (log warning)." Section 3.2 and acceptance criterion A: "missing or malformed `<validator-targets>` block is caught and **blocks Stop** with a clear error." Step 2 blocks only on jq-invalid JSON. These three statements cannot all be true. A sensible resolution: file absent → skip (already specified); file present but tags missing or JSON invalid → block with the fix-it message. Pick one and state it once.

### 3.2 Stop-hook blocking mechanism described incorrectly

v12 rule 4 states: "`Stop` hooks block via JSON (`decision: "block"`), **not** via exit code 2." Per the official exit-code table, exit 2 on `Stop` *does* block ("Prevents Claude from stopping, continues the conversation"); JSON `decision: "block"` is the alternative on exit 0. The claim is harmless if the implementer uses JSON, but it is presented as an official-protocol fact and is wrong. Also worth adding (currently absent from the spec): JSON output is **only processed on exit 0** — a script must choose exit-code signaling or JSON, never both, or its report JSON will be silently discarded.

### 3.3 Rule 8 miscasts PostToolUse as blocking

"Blocking `PreToolUse` and `PostToolUse` hooks use `exit 2`." PostToolUse cannot block — the tool already ran; exit 2 there only surfaces stderr to Claude (docs: "Shows stderr to Claude; the tool already ran"). PostToolUse *can* return top-level `decision: "block"` to prompt Claude with feedback, but nothing is undone. The wording will mislead the implementer about what the guard on `Read|Edit|Write` protects (that guard is correctly on PreToolUse in the table; the rule text is what's wrong).

### 3.4 PermissionDenied retry shape

v12 §1.5 says print `{ "retry": true }` to stdout. The documented shape is `hookSpecificOutput.retry: true` (decision-control table: "PermissionDenied | hookSpecificOutput | retry: true"). The bare top-level form will likely be ignored. The "v2.1.88+" version claim is also unverifiable and should be softened to "recent versions; consult the docs."

### 3.5 `limits.json` stores the wrong quantity

Section 1.8 defines `five_hour` as `rate_limits.five_hour.used` and the tier logic (§6.4) compares against percentage thresholds (60/75/90 %). The real field (in statusline input, where this data actually lives) is `used_percentage`; the spec's own §1.1 example uses `{used, limit}` pairs instead. As written, `used` is only a percentage by accident when `limit` happens to be 100. Define the file to store `used_percentage` (and ideally `resets_at`), sourced from the statusline payload per finding 2.1.

---

## 4. Medium findings

**Manifest path inconsistency.** §5.2 step 4 reads the session manifest at `state/<project-key>/manifest-<session-id>.json`; §8.1 has the janitor cleaning `state/<project-key>/manifests/` (a subdirectory). One canonical path is needed or the janitor cleans nothing and the state dir accumulates manifests forever.

**Async validators launched from inside a script misuse `asyncRewake`.** §5.2 step 6 says slow validators are launched in the background "(with `asyncRewake` if desired)." `asyncRewake` is a *hook-entry field* in settings.json, not something a script can attach to a child process it spawns. Background children of a synchronous Stop hook also risk being orphaned or killed when the hook exits; and because the Stop has already been allowed, an async validator failure can no longer block completion — it only surfaces on the *next* prompt, which may never come (session ends). The spec should acknowledge this weakened guarantee and route async results through a real wired hook (see finding 2.4).

**`limit-collector` matcher too narrow (moot after 2.1 but structurally telling).** Even under the spec's own (incorrect) premise, attaching the collector to `PostToolUse` with `matcher: Write|Edit` means a session doing only Bash/Read/Grep work never refreshes `limits.json`, so the statusline shows stale numbers precisely during long non-editing stretches.

**Secrets loading executes repo-controlled code.** §3.4's `set -a; source "$CLAUDE_PROJECT_DIR/.env"` runs arbitrary shell from the project directory with full user permissions — the exact threat rule 13 warns about ("hooks run with zero sandboxing"). A hostile or compromised repo's `.env` becomes code execution on `Stop`. Safer: parse `.env` as `KEY=VALUE` lines (reject anything containing `$(`, backticks, or `;`) and export explicitly, or only export the variable names whitelisted in config.

**Blocking on the missing-tags case vs. projects that never need remote validation.** Because §3.2/acceptance blocks Stop when the block is "missing," a project that legitimately has a `validator_context.md` without the tags (or a stale directive) would be unable to finish. Tie the block condition to "project declares validation targets in config" rather than mere file presence.

**FileChanged note is wrong and dead weight.** §3.3 says the FileChanged matcher is a glob like `src//*.ts` (typo aside, docs say it is a *literal filename watch list*, not a glob/regex), and the event is excluded from the system anyway (§4.3). Delete or correct the note.

---

## 5. Minor findings

The report contract example uses hook name `post-edit-format` while §1.7's `last_status.json` example uses `format` — pick one naming scheme. The acceptance criterion "blocks `git push --force origin main`" hardcodes `main` in a spec whose rule 11 forbids assuming the default branch (acceptable as a test fixture, but say so). §4.1's hook-type table says MCP tool hooks cost "tokens per response" — per docs the tool's text output is treated like command stdout with no per-call LLM cost (prompt/agent hooks are the LLM-cost types). `PermissionRequest` does not fire in headless (`-p`) mode, worth a note next to the optional `permission-helper.sh`. The `log` path in report JSON uses a literal `~` — scripts should emit expanded paths so the model can pass them to Read directly. The spec's ≤500-token injection cap is fine and comfortably inside the documented 10,000-character hook-output cap, but the README deliverable could state both numbers. Finally, `git symbolic-ref refs/remotes/origin/HEAD` fails on clones where `origin/HEAD` was never set; the fallback to `git remote show origin` is specified — good — but a second local fallback (`git symbolic-ref --short HEAD`) would avoid a network call when offline.

---

## 6. What v12 got right (verified)

The 30-event lifecycle used in the architecture diagram matches the current official event list, including `StopFailure`, `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `PermissionDenied`, `PostCompact`, and `MessageDisplay`. The `hookSpecificOutput`/`additionalContext` injection format is correct. `async`, `asyncRewake` (implies async; wakes on exit 2), `args` exec form, `shell`, `timeout` in seconds, and `statusMessage` all exist as described. `stop_hook_active` loop-guarding, exit-1-only-warns, matcher regex semantics for `Edit|Write`, statusline output on stdout, the ~300 ms statusline debounce, and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` are all consistent with current documentation and community-verified behavior. The v12 fixes over v11 (manifest `Write|Edit`, `validation`-subtree-only dynamic merge, atomic `.tmp`+`mv` writes, POSIX `awk` extraction, explicit `limits.json` definition, test-command discovery) are genuine improvements.

---

## 7. Recommended fix list for a v13

Restore the base file's statusline-bridge architecture (statusline writes `limits.json` from its own stdin; `limit-bridge.sh` on `UserPromptSubmit`/`PreToolUse` reads it) and delete `limit-collector.sh`, or keep the name but attach it to the statusline path. Rewrite §1.1 and §1.2 with the actual documented schemas and drop the fabricated version numbers. Revert §1.6 to permission-rule syntax and move the guard patterns into `config.json`. Move `format.sh` to `PostToolUse` in the settings example. Wire `limit-bridge.sh` (and async-validator result injection) into §4.2 and the settings example under `UserPromptSubmit`. Resolve the skip-vs-block contradiction for malformed dynamic context with a single rule. Correct the Stop/PostToolUse blocking statements and add the "JSON only on exit 0" rule. Fix the PermissionDenied retry shape, the `limits.json` field definitions (`used_percentage`), the manifest path, and the secrets-loading mechanism. After those changes, the specification's architecture is coherent and implementable.