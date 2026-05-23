---
name: model
description: Model switching and auto-routing. Switch to any Claude or Ollama cloud model by name, check current rate-limit status, inspect the routing table, start the background watcher, or manually select the best model for a task by type and complexity.
argument-hint: "<model-name> | status | list | watch | select <score> <type>"
allowed-tools: Bash, Read
---

# /model — Model Switching & Auto-Routing

Switch to any AI model, check rate-limit status, or let the router pick the best model for a task.

## Variables

TASK: $ARGUMENTS

---

## Commands

### Switch to a Claude model
If `TASK` is `haiku`, `sonnet`, `opus`, or starts with `claude-`:
→ Reply: "Use the built-in `/model <name>` command. Available: `haiku` (claude-haiku-4-5), `sonnet` (claude-sonnet-4-6), `opus` (claude-opus-4-7)"

### Switch to an Ollama cloud model
For any other model name (e.g. `qwen3-coder:480b-cloud`, `kimi-k2-thinking:cloud`):
1. Confirm: "Routing to **<model-name>** via Ollama for this session."
2. Use API key from `OLLAMA_API_KEY` env var (set in settings.json).
3. Execute via Ollama API:
   ```bash
   curl -s https://ollama.com/api/chat \
     -H "Authorization: Bearer $OLLAMA_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model":"<model>","messages":[{"role":"user","content":"<prompt>"}],"stream":false}'
   ```
4. Return the model's response directly.

### Check current status
If `TASK` is `status` or empty:
```bash
cat ~/.claude/data/usage_status.json 2>/dev/null || echo "No status file yet"
uv run ~/.claude/scripts/usage_monitor.py check
```
Prints `available` or `rate_limited`.

### Start background watcher
If `TASK` is `watch`:
```bash
nohup uv run ~/.claude/scripts/usage_monitor.py watch >/dev/null 2>&1 &
echo "Watcher started (PID $!). Polls every 60s when limited, 300s when available."
```

### List all models by tier
If `TASK` is `list`:
```bash
uv run ~/.claude/scripts/model_selector.py list
```

### Auto-select best model for a task
If `TASK` starts with `select`:
```bash
# Usage: select <score 0-100> <coding|thinking|general|fast>
uv run ~/.claude/scripts/model_selector.py select <score> <type>
```
Example: `select 85 coding` → `qwen3-coder:480b`

---

## How auto-routing works

All components share `~/.claude/data/usage_status.json` as the single source of truth:

1. **`usage_monitor.py`** probes `https://api.claude.ai/api/auth/me` and writes status.
2. **`model_selector.py`** maps `(task_type, complexity)` → Ollama model id.
3. **`model_router.py`** (UserPromptSubmit hook) reads the status file and injects Ollama routing context when `rate_limited=true`.
4. **`session_start.py`** runs `usage_monitor.py check` in the background on every session start.
5. On state transitions (available↔limited) a Telegram notification is sent.

---

## Routing table (from `model_selector.py select <score> <type>`)

| Task type | Score | Model |
|-----------|-------|-------|
| coding | ≥70 | `qwen3-coder:480b` |
| coding | ≥40 | `qwen3-coder-next` |
| coding | <40 | `devstral-small-2:24b` |
| thinking | ≥60 | `kimi-k2-thinking` |
| thinking | <60 | `deepseek-v3.1:671b` |
| general | ≥80 | `kimi-k2:1t` |
| general | ≥50 | `mistral-large-3:675b` |
| general | <50 | `qwen3-next:80b` |
| fast | any | `ministral-3:14b` |

---

## Available Ollama cloud models

**Tier 1 — Heavy (frontier reasoning & coding)**
| Model | Best for |
|-------|----------|
| `kimi-k2:1t` | Long context, frontier reasoning |
| `kimi-k2.5` | Fast frontier, balanced |
| `qwen3-coder:480b` | Hard coding (Rust, TypeScript, Python) |
| `deepseek-v3.1:671b` | Research-grade synthesis |
| `gpt-oss:120b` | Strong general reasoning |
| `mistral-large-3:675b` | General heavy tasks |
| `cogito-2.1:671b` | Advanced reasoning |
| `devstral-2:123b` | Large-scale code generation |

**Tier 2 — Medium (everyday)**
| Model | Best for |
|-------|----------|
| `kimi-k2-thinking` | Chain-of-thought, multi-step planning |
| `nemotron-3-super` | NVIDIA reasoning |
| `qwen3-coder-next` | Balanced code quality |
| `deepseek-v3.2` | General coding + analysis |
| `qwen3-next:80b` | Balanced quality/speed |
| `gemma4:31b` | Google general reasoning |
| `devstral-small-2:24b` | Everyday coding |

**Tier 3 — Fast (routing, short tasks)**
| Model | Best for |
|-------|----------|
| `gemini-3-flash-preview` | Fast, cheap, good for routing |
| `ministral-3:14b` | Quickest responses |
| `glm-5.1` | Multilingual (Arabic, Dutch, Japanese) |
| `minimax-m2.7` | Long context, available locally |

---

## Examples

```bash
/model qwen3-coder:480b-cloud      # route current task to best code model
/model kimi-k2-thinking:cloud      # route to chain-of-thought model
/model status                      # check if Claude is rate-limited
/model list                        # see all models and tiers
/model select 85 coding            # auto-pick: score=85, type=coding
/model watch                       # start background rate-limit watcher
/model sonnet                      # reminder to use built-in /model command
```
