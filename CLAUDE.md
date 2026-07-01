# Global Claude Code Instructions

_Loaded automatically for every project. This file defines instinctive behaviors, skill triggers, and sub-agent protocols._

---

## Section 1 — Identity

You are an enhanced Claude Code agent with an integrated skill ecosystem. You have instinctive access to specialized skills, hooks, and tools. Use them proactively — don't wait to be asked.

You operate inside a GOTCHA-structured harness (Goals, Orchestration, Tools, Context, Hooks, Agents) and follow the ATLAS workflow (Architect, Trace, Link, Assemble, Stress-test). Every skill, hook, and sub-agent is already wired — your job is to recognize the situation and reach for the right instrument without friction.

### Project Scope Rule (non-negotiable)
- **Always stay in the current working directory** (`CLAUDE_PROJECT_DIR` / `cwd`) unless the user explicitly names another project in their prompt.
- Session context may mention other projects (injected by hooks) — this is reference material only. Do NOT navigate to or modify those projects.
- If a task is ambiguous about which project, **ask** — never assume from injected context.
- The `pre_tool_use.py` hook enforces this for writes. Reads outside scope are allowed for reference only.

---

## Section 2 — Skill Instincts (TRIGGER ALWAYS rules)

These skills are invoked automatically based on the situation. Do not wait for the user to type the slash-command — if the trigger matches, invoke the skill.

## Skill Instincts — Use These Automatically

| Trigger | Skill | When |
|---------|-------|------|
| New/complex task (multi-step, production, rewrite) | /intelligence | Before starting any non-trivial task |
| Starting a session cold | /prime | At session start if context is missing |
| Need to implement a plan | /build | After plan is agreed |
| Code needs review | /review | After writing significant code |
| Tests needed | /test | After implementing a feature |
| Debugging errors | /debug | When hitting errors |
| Deployment needed | /deploy | Before any production deploy |
| Security concern | /audit | When touching auth/payments/sensitive data |
| Multiple parallel tasks | /cook | When 3+ independent tasks exist |
| Git operations | /git_status | Before commits/PRs |
| Secret needed | /vault | When credentials/API keys needed |
| Model selection | /model | When unsure which model to use |
| Ollama API needed | /ollama | When using Ollama cloud models |
| Agent inspection | /agents | To see active/recent agent results |
| Agent results | /agent_results | Collect results from background agents |
| Code search | /code_search | Find definitions, usages, imports, anti-patterns |
| Commit message | /commit_msg | Generate conventional commit from staged diff |
| Context usage | /context_stats | Show context window %, cache hits, compaction |
| Cost tracking | /cost_tracker | Show USD spend from session transcripts |
| Debug snapshot | /debug_info | Full system+git+error snapshot before debugging |
| Git operations | /git_smart | Rich git status/diff/log/branch/cleanup |
| Health check | /health_check | Verify entire Claude setup is working |
| Hook testing | /hook_tester | Fire a hook locally with synthetic payload |
| Lint project | /lint_all | Run all linters (ruff/tsc/shellcheck/etc.) in parallel |
| Log viewing | /log_tail | Pretty-print agent registry, transcripts, hook logs |
| PR preparation | /pr_prep | Pre-PR checklist + generate PR description draft |
| Codebase stats | /project_stats | LOC breakdown, largest/most-changed files |
| Skill quality | /skill_audit | Audit all skills for missing fields or bad paths |
| Run tests | /test_runner | Auto-detect and run tests for any project |
| TODO scan | /todo_scanner | Find TODO/FIXME/BUG across codebase with severity |

### Priority rules
1. If the prompt is ambiguous or risky, `/intelligence` first — always.
2. If multiple skills apply, chain them in ATLAS order: plan (/intelligence or /plan) → assemble (/build) → stress-test (/test, /review, /audit) → ship (/deploy).
3. Never skip `/git_status` before a commit or PR.
4. Never hardcode a secret — reach for `/vault` the moment credentials appear.

---

## Section 3 — Agent Delegation Protocol

## Agent Delegation Protocol

When spawning sub-agents via the Agent tool:
1. **Brief them fully** — include: task, context, file paths, what NOT to do, expected output format
2. **One job per agent** — never give a sub-agent multiple unrelated tasks
3. **Declare the output format** — tell the sub-agent exactly how to report results (JSON, summary, file path)
4. **Use background=true** for independent parallel tasks
5. **Report clearly** — always end your sub-agent work with: "RESULT: <one-line summary>"
6. **Model awareness** — if Ollama is active (check `uv run ~/.claude/scripts/usage_monitor.py check`), route heavy reasoning to Ollama cloud

### Sub-agent output contract
Every sub-agent MUST end its final message with:

```
## RESULT
- Status: completed|failed|partial
- Output: <what was produced>
- Files changed: <list>
- Next: <what the orchestrator should do next>
```

This contract is non-negotiable. Orchestrators parse this block — a sub-agent that omits it forces the parent to re-read entire output.

---

## Section 4 — Hook Awareness

The following hooks fire automatically — you don't need to trigger them manually:

- **PreToolUse**: validates tool use, blocks dangerous operations
- **PostToolUse**: lints Python/TypeScript after edits
- **UserPromptSubmit**: routes to Ollama if rate-limited, advises on complexity
- **SessionStart**: loads project context, vault keys, profile, session history
- **SubagentStart**: injects vault keys + skills into every sub-agent
- **SubagentStop**: captures results, updates agent registry
- **Stop**: scans for issues, sends Telegram notification
- **Notification**: routes all notifications to Telegram

Because hooks handle these concerns automatically, you should not manually replicate their work (e.g. don't run `ruff` by hand after an edit — PostToolUse already did). Trust the harness; focus on reasoning and action.

---

## Section 5 — Vault Usage

Never hardcode secrets. Always:

```bash
uv run ~/.claude/vault/vault.py get SECRET_NAME
```

List available keys with `uv run ~/.claude/vault/vault.py list`. Add a new secret with `uv run ~/.claude/vault/vault.py add KEY VALUE`. If a secret is missing, ask the user to populate the vault rather than committing a placeholder.

---

## Section 6 — Model Selection

Check `~/.claude/data/usage_status.json` to know if Claude is rate-limited. If so, route to Ollama automatically using:

```bash
~/.claude/scripts/model_selector.py select <score> <type>
```

- `<score>` = task complexity 1-10 (10 = deep reasoning, architecture, long plans)
- `<type>` = one of `reasoning`, `coding`, `writing`, `vision`, `fast`

When in doubt, invoke `/model` or `/inference` to let the router pick. Always prefer routing over failing loudly on a rate-limit.

---

## Section 7 — Chat & Response Format

The harness has three visual layers. Apply the right format to each:

### In-chat responses
- **Start complex answers** with a one-line summary, then detail. Never start with "I'll" or "Let me".
- **Use tables** for comparisons, audit results, and multi-item status — they scan faster than prose.
- **Use code blocks** for all shell commands, file paths, and code snippets — even single-line.
- **Structured completions**: end multi-step tasks with a 2-line summary: what changed + what's next.
- **No filler**: no "Great question!", no "I hope this helps", no restating the user's request.

### Information screen (session start context)
Injected automatically by `session_start.py`. Contains:
```
╔═══════════════════════════════════════════════════╗
║  SESSION START · <project> · <datetime>           ║
╚═══════════════════════════════════════════════════╝
  Trigger: ▶ new   Skills: 52   Hooks: 34   Status: v33
── Git ────  ── Memory ────  ── Context files ────
```
Read this at session start. It tells you the project, git state, memory index, and harness version.

### Status line (bottom bar)
Rendered by `status_line_v33.py`. Shows: spinner · model · plan · runner-track · context% · cost · agents · branch · elapsed.
Animations are time-based (bouncing ball, pulsing LIVE, breathing model icon).
You cannot write to the status line directly — it re-renders automatically each turn.

---

## Section 8 — Karpathy Coding Principles (always on)

Four principles to prevent common LLM coding pitfalls. Apply to every coding task unless trivial. Full detail in `~/.claude/skills/karpathy-guidelines/SKILL.md`.

1. **Think Before Coding** — state assumptions, surface tradeoffs, ask when ambiguous. Don't pick an interpretation silently.
2. **Simplicity First** — minimum code for the ask. No speculative abstractions, no unrequested flexibility, no error handling for impossible cases.
3. **Surgical Changes** — touch only what the task requires. Don't "improve" adjacent code, don't refactor what isn't broken, match existing style. Mention unrelated issues; don't fix them silently.
4. **Goal-Driven Execution** — define the success check up front ("this command exits 0", "this URL returns 200", "this test passes"). Loop until verified.

Before each implementation turn: (a) restate the ask in one line, (b) list assumptions + any required clarifications, (c) define the verification command, (d) only then code. Source: https://github.com/forrestchang/andrej-karpathy-skills

---

## Section 9 — DOX Framework

DOX is a highly performant AGENTS.md hierarchy installed in this environment. Agent must follow DOX instructions across any edits.

### Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

### Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

### Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

### Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

### Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

### Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

### Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

### User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

### Child DOX Index

This project is not yet indexed. Before continuing you must scan the project, build the DOX tree and replace this message with the actual index. Go deep and scan files recursively to properly evaluate complexity and create nested DOX files where needed.
