---
name: cook
description: Parallel task launcher — decompose any goal into N independent tasks and run them simultaneously with the right specialist agents. Use for research, builds, audits, or any multi-track work that can proceed concurrently.
argument-hint: "<task1>" "<task2>" ... | or describe a multi-part goal
allowed-tools: Bash, Read, Agent
---

# /cook — Parallel Task Launcher

Run any number of independent tasks simultaneously. Each task gets the right specialist sub-agent. Results are collected and synthesised into one report.

## Variables

GOAL: $ARGUMENTS

---

## How to invoke

### Explicit tasks (quoted, run as-is)
```
/cook "audit auth code for secrets" "write missing tests for invoice module" "research best practices for rate limiting"
```

### Multi-part description (auto-decomposed)
```
/cook research AI frameworks, benchmark our API endpoints, and scan deps for CVEs
```

### Research-only mode (append --research)
```
/cook --research qwen3-coder architecture kimi-k2-thinking capabilities deepseek-v3.2 benchmarks
```

---

## Step 1 — Parse GOAL

Read `$ARGUMENTS`. Determine the input form:

1. **Quoted tasks** — each `"..."` is an independent task. Take them as-is.
2. **Comma/and-separated** — split on `, ` and ` and ` to get the task list.
3. **Single description** — decompose into the smallest independent units (max 7).
4. **`--research` flag** — strip the flag; each remaining token/phrase is a research query.

Output a numbered list of tasks before proceeding.

---

## Step 2 — Map Tasks to Specialists

For each task, choose the best agent type:

| Task nature | Specialist | Model hint |
|-------------|-----------|------------|
| Write / modify code | `builder` | sonnet / qwen3-coder:480b |
| Run tests, verify output | `validator` | haiku / ministral-3:14b |
| Web research, doc lookup | `general-purpose` | kimi-k2:1t / deepseek-v3.2 |
| Security scan / audit | `security-privacy-engineer` | opus / gpt-oss:120b |
| Test writing | `qa-test-lead` | sonnet |
| Architecture / design | `backend-systems-architect` | opus / kimi-k2-thinking |
| Data / SQL | `data-analytics-engineer` | sonnet |
| Frontend / UI | `web-developer` | sonnet |
| AI / LLM research | `llm-ai-agents-and-eng-research` | kimi-k2:1t |
| Crypto market | `crypto-coin-analyzer-sonnet` | sonnet |
| General analysis | `general-purpose` | sonnet |

---

## Step 3 — Check Rate Limit

```bash
cat ~/.claude/data/usage_status.json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('RATE_LIMITED' if d.get('rate_limited') else 'AVAILABLE')
print('model_override:', d.get('model_override','none'))
"
```

If `RATE_LIMITED`:
- Route all tasks through Ollama cloud instead of Claude sub-agents.
- Use `uv run ~/.claude/scripts/ollama_cloud.py chat <model> "<task>"` for each.
- Run Ollama tasks in background with `&` and `wait` for them all.

If `AVAILABLE`: proceed with Claude sub-agents (Agent tool).

---

## Step 4 — Dispatch All Tasks in Parallel

**Claude path** — spawn all agents in a single message with `run_in_background: true`.

Brief each sub-agent with:
- Their specialist role
- The exact task
- Project cwd (absolute path from `pwd`)
- Instruction: end final message with `## RESULT\n- Status: ...\n- Output: ...\n- Files: ...\n- Next: ...`

Capture each `agent_id`.

**Ollama path** — run each in background:
```bash
uv run ~/.claude/scripts/ollama_cloud.py chat <model> "<task>" &
# ... repeat for each task
wait
```

---

## Step 5 — Collect Results

```bash
# Wait for all agents to complete
uv run ~/.claude/scripts/agent_results.py wait-all <id1> <id2> <id3> --timeout 180

# List results
uv run ~/.claude/scripts/agent_results.py list

# Fetch specific result if needed
uv run ~/.claude/scripts/agent_results.py get <agent_id>
```

---

## Step 6 — Synthesise

Present one concise report:

```
## Cook Results — <N> tasks completed in parallel

### Task 1: <name>
Status: ✓ | ✗ | ~
<2-3 sentence summary>

### Task 2: <name>
...

### Files changed
<list of absolute paths>

### Open items
<anything partial or blocked>
```

---

## Examples

```bash
# Run 3 independent research tasks
/cook "latest Claude Code hooks API changes" "best practices for Python hook exit codes" "Ollama cloud model benchmarks 2025"

# Parallel build + test + audit
/cook "implement rate limiting middleware in auth-service" "write integration tests for rate limiter" "audit auth-service for hardcoded secrets"

# Auto-decompose a multi-part goal
/cook research options for WebSocket scaling, benchmark current WS handler, and implement connection pooling

# Research-only: analyze multiple AI models
/cook --research nemotron-3-super capabilities qwen3-coder-480b code quality kimi-k2-thinking reasoning depth
```
