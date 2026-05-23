---
description: Pre-flight intelligence check — audit capabilities, self-repair any broken config, then execute TASK with maximum tools and optimal model routing
argument-hint: <task or goal>
allowed-tools: Bash, Read, Write, Edit, Agent, ToolSearch
---

# Intelligence — Capability Maximiser

TASK: $ARGUMENTS

## Phase 1 — Fast Capability Scan (run all at once)

```bash
# Project context + memory + crons in one call
uv run ~/.claude/scripts/skill_runner.py context --brief

# Available skills count
uv run ~/.claude/scripts/skill_runner.py skills 2>/dev/null | wc -l

# Active cron jobs
uv run ~/.claude/scripts/skill_runner.py crons

# MCP servers
cat ~/.claude.json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); [print(k,'-',v.get('command','')[:60]) for k,v in d.get('mcpServers',{}).items()]" 2>/dev/null || echo "none"

# Active agents
uv run ~/.claude/scripts/agents.py active 2>/dev/null | head -10

# Rate limit status
cat ~/.claude/data/usage_status.json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('LIMITED' if d.get('rate_limited') else 'OK', d.get('model_override',''))" 2>/dev/null

# Project anchor
uv run ~/.claude/scripts/project_anchor.py resolve 2>/dev/null || echo "no anchor"
```

## Phase 2 — Self-Repair (if needed)

Check for broken or missing capabilities that TASK requires:

- **Missing skill**: If a skill referenced in TASK doesn't exist in `~/.claude/commands/`, create it with the Write tool before proceeding.
- **Missing hook**: If TASK needs a hook that isn't registered in `~/.claude.json`, note it and ask user to register (don't silently skip).
- **No project anchor**: If cwd has no `.claude-project.json`, run `uv run ~/.claude/scripts/project_anchor.py anchor` to create one.
- **Stale memory**: If memory files are >7 days old for an active project, run `/mem` to refresh.
- **Rate-limited**: If `usage_status.json` shows `rate_limited=true`, switch to Ollama cloud model from `model_override` field.

Only repair if the gap blocks TASK. Don't fix things that aren't broken.

## Phase 3 — Intelligence Report (under 150 words)

```
TASK: <task>
STATUS: <available|rate-limited — model=<model>>
PROJECT: <name> | <anchor uuid[:8]>
MCP: <useful servers for this task>
SKILLS: <most relevant 3-5 skills with /<name>>
MODEL: <sonnet|opus|haiku> + <ollama model if needed>
AGENTS: <parallel sub-tasks if any>
REPAIRED: <any self-repair actions taken, or "none">
PLAN:
  1. <action using tool/skill>
  2. ...
```

## Skills to specifically look for

Prefer these over manual work whenever the situation matches:

- `/build` — implement a plan, then validate
- `/test` — write tests for code
- `/review` — review code quality & bugs
- `/debug` — systematically diagnose errors
- `/audit` — security / compliance audit
- `/deploy` — pre-deploy checklist + guided deploy
- `/orchestrate` — multi-agent decomposition
- `/cook` — parallel independent tasks
- `/plan` — concise implementation plan
- `/prime` — load context for a cold session
- `/mem` — read/write project memory
- `/vault` — fetch secrets, never hardcode
- `/model` / `/inference` — route to best model
- `/ollama` — Ollama cloud chat
- `/code_search` — find definitions, usages, imports, anti-patterns
- `/commit_msg` — generate conventional commit messages
- `/context_stats` — context window usage and cache hits
- `/cost_tracker` — USD spend tracking
- `/debug_info` — system + git + error snapshot
- `/git_smart` — rich git operations
- `/health_check` — full setup health check
- `/hook_tester` — fire a hook with synthetic payload
- `/lint_all` — run all linters in parallel
- `/log_tail` — view agent/session/hook logs
- `/pr_prep` — pre-PR checklist + draft
- `/project_stats` — LOC and file stats
- `/skill_audit` — audit skill quality
- `/test_runner` — auto-detect and run tests
- `/todo_scanner` — find TODO/FIXME/BUG
- `/agent_results` — collect sub-agent results

## Phase 4 — Execute

Immediately execute TASK using the optimal capability set. Rules:
- **Discover deferred tools first**: before using any tool from the `<available-deferred-tools>` list (LSP, TeamCreate, AskUserQuestion, etc.), call `ToolSearch("select:<ToolName>")` to load its schema — otherwise the call will fail with InputValidationError
- **LSP for code nav**: use LSP `definition`/`references`/`call_hierarchy` instead of grep when working in TypeScript/Rust/Python — it's faster and respects type boundaries
- **AskUserQuestion** when task is ambiguous and has 2+ clear options — don't guess, present choices
- **EnterPlanMode** before exploring a large unfamiliar codebase — it enforces read-only exploration
- **Skills first**: prefer `/build`, `/test`, `/review`, `/deploy`, `/audit`, `/orchestrate`, `/cook` over manual steps
- **Parallel when independent**: use `/cook` or multiple Agent calls in one message for 3+ independent sub-tasks
- **Ollama when limited**: use `model_override` from usage_status.json; route via `uv run ~/.claude/scripts/ollama_cloud.py chat <model> "<prompt>"`
- **Memory last**: after completion, save key findings via `/mem write` or `uv run ~/.claude/scripts/project_anchor.py st-set`
- **Verify**: always run at least one check (test, lint, or read-back) before reporting success

## Model Selection Guide

| TASK complexity | Model |
|----------------|-------|
| Quick lookups, routing | haiku or ministral-3:14b |
| Code, features, fixes | sonnet or qwen3-coder:480b |
| Architecture, deep analysis | opus or kimi-k2-thinking |
| Long context, research | kimi-k2:1t or deepseek-v3.2 |

## Self-Improvement

After each run:
- If a new skill/hook/MCP was useful → add it to this file's scan.
- If a repair was needed → save a feedback memory via Write tool.
- Save key findings: `uv run ~/.claude/scripts/project_anchor.py st-set <key> "<value>"`.
