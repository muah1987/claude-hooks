---
name: orchestrate
description: Single entry point for complex multi-agent work. Accepts a complex multi-part goal, decomposes it into independent sub-tasks, spawns the right specialist sub-agent for each (builder, validator, researcher, qa, security, docs, etc.), runs independent tasks in parallel, collects structured results via ~/.claude/scripts/agent_results.py, and synthesises a unified deliverable. Automatically falls back to Ollama cloud routing when Claude is rate-limited.
argument-hint: [--status | --resume <uuid> | <complex multi-part goal>]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, ToolSearch
---

# Orchestrate — Unified Multi-Agent Orchestrator

You are the **Orchestrator**. Your job is to take one complex, multi-part
goal from the user and deliver it end-to-end by decomposing it into
independent sub-tasks, dispatching the right specialist for each, and
synthesising the results into one clean report.

This skill replaces the older fragmented flow (`/agent-teams`, `/cook`,
`/parallel`) with a single entry point that knows how to:

- Analyse a goal and break it into the smallest meaningful work units
- Pick the right specialist per unit (builder / validator / researcher / qa / security / docs / data / devops / frontend / backend)
- Run independent units in **parallel** via background sub-agents
- Collect structured results from `~/.claude/data/results/`
- Fall back to **Ollama cloud** when Claude is rate-limited
- Present a single synthesised answer to the user

## Variables

- **GOAL**: `$ARGUMENTS`
- **RESULTS_TOOL**: `uv run ~/.claude/scripts/agent_results.py`
- **REGISTRY_TOOL**: `uv run ~/.claude/scripts/agents.py`
- **OLLAMA_TOOL**: `uv run ~/.claude/scripts/ollama_cloud.py`
- **ROUTER_STATUS**: `uv run ~/.claude/scripts/model_selector.py` or equivalent

## Step 0 — Parse Flags

Read `$ARGUMENTS`:

- If starts with `--status` → go to **Step S** (show run history table).
- If starts with `--resume` → extract UUID and go to **Step R** (resume a failed run).
- Otherwise → treat as GOAL and continue from Step 1.

---

## Step S — Status

Find and read `~/.claude/projects/*/memory/orchestrate-log.md` for the current project (match by `pwd`). Present all runs as a table:

| UUID | Timestamp | Goal | Outcome | Specialists |
|------|-----------|------|---------|-------------|

If no log exists: "No orchestrate runs recorded for this project."

---

## Step R — Resume

1. Read `~/.claude/projects/*/memory/orchestrate-log.md` and find the entry for the provided UUID.
2. Read the original goal, outcome, artifact paths, and issue notes.
3. Check which units `failed` or `partial` via `agent_results.py get <id>`.
4. Rebuild only the failing units — do not re-run successful agents.
5. Present the recovery plan, confirm with the user, then dispatch.
6. Update the log entry with a `Resumed` sub-entry.

---

## Step 1 — Understand the Goal

Read `$ARGUMENTS` carefully. Restate the goal in 1-2 sentences and list
the concrete deliverables the user expects. Do not start work before
you know what "done" looks like.

If the goal is ambiguous or missing critical information, ask one
clarifying question and stop. Never guess.

## Step 2 — Gather Context + Git State

Before decomposing, load just enough project context **and capture git state**:

1. `pwd` to confirm the working directory.
2. Check for `CLAUDE.md` in the cwd and `~/.claude/`.
3. Skim the project structure (`ls -la`, relevant manifest files).
4. Note the tech stack in one internal sentence.
5. **Capture git baseline** (run these now, store results for Step 6):

```bash
git rev-parse --abbrev-ref HEAD           # current branch
git status --porcelain                    # uncommitted files
git log -1 --pretty="%h %s"              # last commit
git rev-list --left-right --count @{u}...HEAD 2>/dev/null  # ahead/behind
```

If the repo has uncommitted changes, note which files are dirty — these
are at risk during parallel work. Consider whether to stash them or warn
the user before dispatching agents that might touch the same files.

Keep this phase short — you are orchestrating, not building.

## Step 3 — Decompose into Sub-Tasks

Break the goal into the **smallest independent units** you can. For each
unit, capture:

| Field | Meaning |
|-------|---------|
| `id` | short slug, e.g. `api-endpoint`, `ui-form`, `unit-tests` |
| `specialist` | which role is best (see roster below) |
| `prompt` | the exact instruction for the specialist |
| `depends_on` | list of other unit ids it must wait for (empty = can run in parallel) |
| `parallel_group` | integer; units with the same group run concurrently |

Specialist roster:

| Specialist | When to pick |
|------------|-------------|
| `builder` | Write / modify code to implement a feature or fix |
| `validator` | Run tests, linters, type-checkers; verify correctness |
| `researcher` | Gather facts from the web, docs, or codebase; no code changes |
| `qa` | Write tests, design test plans, improve coverage |
| `security` | Security audit, vuln scan, secret detection (read-only) |
| `docs` | Docs / README / API reference authoring |
| `data` | Schema, migrations, data analysis, SQL |
| `devops` | CI/CD, Docker, deploys, infra |
| `frontend` | UI components, pages, styling |
| `backend` | Server-side code, APIs, business logic |

Rules for a good decomposition:

- One unit does **one thing well**. Prefer more small units over fewer large ones.
- Independent units go in the same `parallel_group`.
- Do not chain units unnecessarily — true dependencies only.
- Every unit must have a crisp success criterion the specialist can verify.

## Step 4 — Decide the Execution Backend

Before spawning anything, pick a backend for each sub-task. You have the
full model arsenal available at all times — use it deliberately.

### Available models

| Tier | Model | Best for |
|------|-------|----------|
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Default; code + reasoning |
| Claude Opus 4.7 | `claude-opus-4-7` | Complex multi-step plans |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Fast summaries, routing |
| **T1 — Heavy** | `kimi-k2:1t` | Frontier reasoning, huge context |
| **T1 — Heavy** | `qwen3-coder:480b` | Hard coding problems |
| **T1 — Heavy** | `gpt-oss:120b` | Strong general reasoning |
| **T1 — Heavy** | `deepseek-v3.1:671b` | Research-grade synthesis |
| **T2 — Code** | `kimi-k2-thinking` | Step-by-step reasoning |
| **T2 — Code** | `devstral-small-2:24b` | Everyday coding tasks |
| **T2 — Code** | `qwen3-coder-next` | Balanced code quality |
| **T3 — Fast** | `ministral-3:14b` | Quick lookups, routing |
| **T3 — Fast** | `gemma3:27b` | Low-latency responses |

**Auto-select by task type:**
```bash
uv run ~/.claude/scripts/model_selector.py select <score 0-100> <coding|thinking|general|fast>
```

### Backend decision rules

1. **Default: Claude sub-agents** — use the Task/Agent tool. Spawn each
   specialist in its own sub-agent thread. Best quality; costs tokens.

2. **Ollama cloud (rate-limited or cost-sensitive)** — route via:

   ```bash
   # Single task:
   uv run ~/.claude/scripts/ollama_cloud.py chat qwen3-coder:480b "<prompt>"

   # Multiple tasks in parallel (JSON array, returns array of results):
   echo '[
     {"id":"a","model":"qwen3-coder:480b","prompt":"task A"},
     {"id":"b","model":"kimi-k2-thinking","prompt":"task B"},
     {"id":"c","model":"ministral-3:14b","prompt":"task C"}
   ]' | uv run ~/.claude/scripts/ollama_cloud.py parallel
   ```

   Store Ollama results manually (Claude sub-agents auto-store via hook):
   ```bash
   uv run ~/.claude/scripts/agent_results.py store <unit-id> completed "<summary>"
   ```

3. **Hybrid** — assign by task nature:
   - Research / web tasks → Ollama T1 (kimi-k2:1t or deepseek-v3.1:671b)
   - Code writing → Claude Sonnet (default) or qwen3-coder:480b
   - Fast checks / routing → ministral-3:14b or Claude Haiku
   - Complex multi-step plans → Claude Opus or kimi-k2-thinking

4. **Model routing guide** by specialist:

   | Specialist | Preferred model |
   |------------|----------------|
   | builder | Claude Sonnet / qwen3-coder:480b |
   | validator | Claude Haiku / ministral-3:14b |
   | researcher | kimi-k2:1t / deepseek-v3.1:671b |
   | qa | Claude Sonnet / devstral-small-2:24b |
   | security | Claude Opus / gpt-oss:120b |
   | data | Claude Sonnet / qwen3-coder:480b |
   | docs | Claude Haiku / gemma3:27b |
   | devops | Claude Sonnet / devstral-small-2:24b |

### Advanced: Named Swarm Teams

For long-running orchestrations where agents need to communicate (not just run in parallel), use `TeamCreate` + `SendMessage`:

```typescript
// Load schemas first
ToolSearch({ query: "select:TeamCreate,SendMessage,TeamDelete" })

// Create a named team with shared task list
TeamCreate({ team_name: "auth-refactor", description: "Auth module refactor", agent_type: "builder" })

// Send work to agents by name or broadcast
SendMessage({ to: "builder-1", message: "implement login endpoint at /auth/login" })
SendMessage({ to: "*", message: "all agents: use absolute paths only" })  // broadcast

// Structured protocol messages (plan approval, shutdown)
SendMessage({ to: "validator", message: { type: "plan-approval", approved: true } })

// Clean up when done
TeamDelete({ action: "remove" })
```

Use named teams when: agents share state, need to coordinate on shared files, or the task runs >30 minutes.
Use background Agent calls when: tasks are fully independent and short-lived.

### Detecting rate-limit mid-session

Before spawning a heavy sub-agent batch, check the current usage
snapshot — the `UserPromptSubmit` hook refreshes this file regularly:

```bash
cat ~/.claude/data/usage_status.json
```

If the JSON reports the session or weekly limit as exhausted (e.g.
`session_pct >= 95` or `status == "rate_limited"`), switch remaining
units to the Ollama backend for the rest of the run instead of risking
a mid-batch 429. You can also consult the `/model-router` skill for
an interactive decision.

## Step 5 — Present the Plan

Show the user:

- The restated goal
- The list of sub-tasks (id, specialist, one-line prompt, group, deps)
- The chosen execution backend (Claude / Ollama / hybrid)
- The parallel groups (so they understand the concurrency)

Wait for confirmation unless the goal is obviously small (1-2 units).

## Step 5.5 — Git Checkpoint (before first dispatch)

Before spawning any agents, create a recovery point in git:

```bash
# Tag the pre-orchestration state so it can always be recovered
git stash push -m "orchestrate: pre-dispatch checkpoint $(date -u +%Y%m%dT%H%M%S)" 2>/dev/null || true
# If nothing to stash, create a lightweight tag instead:
git tag -f orchestrate/checkpoint 2>/dev/null || true
```

Record the HEAD commit hash now:
```bash
PRE_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
```

If the repo is clean, skip the stash and just note the `$PRE_SHA`. This
checkpoint means: if any parallel agent corrupts a shared file, you can
recover with `git checkout orchestrate/checkpoint -- <file>` or
`git stash pop`.

## Step 6 — Dispatch

For **each parallel group**, launch all of its units at the same time:

- **Claude path.** Spawn a sub-agent via the Task/Agent tool. In the
  sub-agent prompt include:

  - The specialist role as the system persona
  - The exact sub-task
  - Relevant context from Step 2
  - Absolute paths only (sub-agent `cwd` resets between bash calls)
  - Success criteria
  - Instructions to produce a concise final report — the
    `SubagentStop` hook will auto-persist the last assistant message
    to `~/.claude/data/results/<agent_id>.json` via `agent_results.py`,
    so the sub-agent only needs to make its final summary clean.

  Use `background=true` for each spawn inside a group so they run
  concurrently. Record the returned `agent_id` for each unit.

- **Ollama path.** For each unit, run the `ollama_cloud.py chat ...`
  command (in the background if multiple), capture stdout, and call
  `agent_results.py store <unit-id> completed "<stdout>"` yourself.

Wait for the whole group to finish before starting the next group.

## Step 7 — Collect Results

After each group completes:

1. List recent results:

   ```bash
   uv run ~/.claude/scripts/agent_results.py list
   ```

2. Fetch each unit's result individually when you need detail:

   ```bash
   uv run ~/.claude/scripts/agent_results.py get <agent_id>
   ```

3. If a specific sub-agent's result has not landed yet, wait for it:

   ```bash
   uv run ~/.claude/scripts/agent_results.py wait <agent_id> --timeout 120
   ```

   To block until **every** agent in a group finishes — instead of
   polling each one individually — use `wait-all`. It prints one JSON
   line per agent as soon as it completes and exits 1 on timeout:

   ```bash
   uv run ~/.claude/scripts/agent_results.py wait-all <id1> <id2> <id3> --timeout 120
   ```

4. Cross-check with the registry:

   ```bash
   uv run ~/.claude/scripts/agents.py results
   # Or see session tree with durations:
   uv run ~/.claude/scripts/agents.py tree
   ```

5. **Git diff audit** — after each group, check what actually changed:

   ```bash
   git diff --stat HEAD              # files changed vs last commit
   git status --short                # uncommitted changes
   git log --oneline -5              # recent commits by agents
   ```

   Compare against `$PRE_SHA` from Step 5.5 to see the full group impact:
   ```bash
   git diff --stat $PRE_SHA..HEAD
   ```

   If a parallel group produced conflicting file changes (two agents
   touched the same file), resolve now before starting the next group.

### Failure detection

Every stored result carries a `status` field — read it from
`agent_results.py get <id>`. Possible values:

- `completed` — the unit finished successfully.
- `failed` — the sub-agent hit a blocking error; inspect the `summary`
  / `error` fields, then retry or re-route.
- `partial` — the sub-agent made progress but did not fully satisfy
  the success criteria; usually worth re-dispatching with a tighter
  prompt or a stronger model.

Resolve failures: if a unit reports `failed` or `partial`, either retry
it with a tighter prompt, re-route it to a stronger model (or to Ollama
if Claude is rate-limited), or flag it clearly in the final report.

## Step 8 — Git Wrap-Up + Synthesise

Before synthesising, finalise the git state:

```bash
git diff --stat $PRE_SHA..HEAD     # everything changed since checkpoint
git status --short                  # any files left uncommitted
```

If there are uncommitted changes from agent work, decide:
- **Commit now** — if the changes are coherent and verified:
  ```bash
  git add -p                        # interactively stage only what's needed
  git commit -m "feat: <summary of orchestrated work>"
  ```
- **Leave uncommitted** — if the user prefers to review first (tell them).
- **Revert a bad agent** — roll back specific files to the checkpoint:
  ```bash
  git checkout $PRE_SHA -- <path/to/bad/file>
  ```

Then merge all results into one deliverable for the user:

1. **What was built / found / verified** — one tight paragraph per unit.
2. **Files changed** — `git diff --stat $PRE_SHA..HEAD` output, grouped by unit.
3. **Verifications run** — tests, lints, type-checks with their outcomes.
4. **Conflicts / overlaps** — did two units touch the same file? If so,
   explain how you reconciled it.
5. **Git state** — clean / N uncommitted / N commits ahead of origin.
6. **Open items** — anything not finished or blocked.

Keep it concise. The user wants the answer, not a transcript.

## Step 8.5 — Write Run Log

Append to `~/.claude/projects/*/memory/orchestrate-log.md` (resolve project memory dir via `uv run ~/.claude/scripts/project_anchor.py memory-path`):

```markdown
---
### Run: <UUID>
- **Timestamp**: <UTC>
- **Goal**: <one-line summary>
- **Outcome**: success | partial | failed
- **Specialists**: <comma-separated list>
- **Files changed**: <count>
- **Agent IDs**: <id1>, <id2>, ...
- **Notes**: <any issues or highlights>
```

Generate UUID: `python3 -c "import uuid; print(uuid.uuid4())"`

---

## Step 9 — Report

Present the synthesised result to the user in markdown. Include the
list of `agent_id`s so the user can run
`uv run ~/.claude/scripts/agent_results.py get <id>` on any of them if
they want the raw detail.

## Best Practices

- **Always absolute paths** in sub-agent prompts and reports.
- **Minimise sub-agent scope** — one task per agent.
- **True parallelism only** — never parallelise units that share a file
  write target; serialise them instead.
- **Fail fast** — if a unit reports a blocking issue, do not send more
  work into a broken pipeline.
- **Verify before claiming success** — run at least one validator unit
  for any code change.
- **Store everything** — rely on `agent_results.py store` (auto via the
  hook for Claude sub-agents, manual for Ollama runs) so later steps
  can re-read any result.
- **Rate-limit awareness** — if Claude returns 429s or the user is on a
  depleted tier, switch to Ollama mid-run for remaining units.
- **Git checkpoint before dispatch** — always capture `$PRE_SHA` and
  create a stash/tag before parallel agents start writing files.
- **Git diff audit per group** — run `git diff --stat $PRE_SHA..HEAD`
  after each parallel group completes; resolve conflicts before
  starting the next group.
- **Sub-agents are git-aware** — the SubagentStart hook injects branch,
  dirty file count, and last commit into every agent's context. Use
  this in sub-agent prompts: tell specialists to avoid touching files
  already marked dirty to prevent merge conflicts.
- **Post-run commit** — after a successful orchestration, always suggest
  a single coherent `git commit` that covers the entire run rather
  than leaving all changes staged-but-uncommitted.

## Example Invocations

```
/orchestrate add pagination to the mosque directory API, update the frontend to render it, write tests, and update the API docs

/orchestrate refactor the prayer times calculator, add 3 new calculation methods, write unit tests, and audit the auth code for secret leaks

/orchestrate research the top 5 AI agent frameworks from 2025, summarise each, and produce a comparison table in specs/agent-frameworks.md
```

## Quick Reference

```bash
# inspect results
uv run ~/.claude/scripts/agent_results.py list
uv run ~/.claude/scripts/agent_results.py get <agent_id>
uv run ~/.claude/scripts/agent_results.py wait <agent_id> --timeout 120
uv run ~/.claude/scripts/agent_results.py wait-all <id1> <id2> ... --timeout 120

# registry (start/stop events)
uv run ~/.claude/scripts/agents.py list
uv run ~/.claude/scripts/agents.py active
uv run ~/.claude/scripts/agents.py results

# rate-limit awareness
cat ~/.claude/data/usage_status.json

# ollama fallback — single and parallel
uv run ~/.claude/scripts/ollama_cloud.py chat qwen3-coder:480b-cloud "<subtask>"
echo '[{"model":"gpt-oss:20b","prompt":"A"},{"model":"qwen3-coder:30b","prompt":"B"}]' \
  | uv run ~/.claude/scripts/ollama_cloud.py parallel
```
