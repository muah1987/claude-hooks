---
description: Parallel command executor — run N shell commands concurrently with retry, isolation, and zero cascade failures. Works with any AI model.
argument-hint: "<cmd1>" "<cmd2>" "<cmd3>" [--limit N] [--retry N] [--timeout N] [--cwd /path]
allowed-tools: Bash, Read, Write, Agent
---

# /parallel — Universal Parallel Command Executor

Runs multiple shell commands **concurrently**, fully isolated so one failure
never cancels the others. Works identically on Claude, Gemini, GPT, or any
AI that can invoke a Bash tool.

---

## Quick Start

```bash
# CLI — inline commands
python3 ~/.claude/hooks/utils/parallel_runner.py "cmd1" "cmd2" "cmd3"

# CLI — with options
python3 ~/.claude/hooks/utils/parallel_runner.py \
  "cd /my/project && go build ./... 2>&1" \
  "git -C /my/project status" \
  --limit 3 --retry 2 --timeout 60

# JSON stdin — best for AI agents (structured, no shell escaping issues)
echo '[
  {"cmd": "go build ./...", "cwd": "/my/project/server"},
  {"cmd": "git status",     "cwd": "/my/project"},
  {"cmd": "npm test",       "cwd": "/my/project/frontend"}
]' | python3 ~/.claude/hooks/utils/parallel_runner.py --stdin --allow-failures
```

**Output** — always valid JSON array, one entry per command:
```json
[
  {"cmd": "...", "exit": 0, "output": "...", "attempts": 1, "ok": true},
  {"cmd": "...", "exit": 1, "output": "error text", "attempts": 3, "ok": false}
]
```

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | 4 | Max concurrent commands |
| `--retry N` | 3 | Max retries per failed command |
| `--timeout N` | 120 | Seconds before a command is killed |
| `--cwd /path` | none | Working directory applied to all commands |
| `--stdin` | off | Read `[{cmd, cwd?}]` JSON from stdin |
| `--json-input FILE` | none | Read from a JSON file |
| `--allow-failures` | off | Exit 0 even if some commands fail |
| `--quiet` | off | Suppress human-readable output, JSON only |

---

## All Failure Modes & Fixes

### ❌ Mode 1 — Cascade cancellation (most common)

```
Cancelled: parallel tool call Bash(go build ...) errored
```

**Cause:** One Bash tool call errors → Claude Code cancels sibling calls.

**Fix A — Use the parallel runner script (recommended):**
```bash
# One Bash call, all commands run in isolation
python3 ~/.claude/hooks/utils/parallel_runner.py \
  "cd /project/server && go build ./... 2>&1" \
  "git -C /project status" \
  "npm test --prefix /project/frontend"
```

**Fix B — Defensive inline pattern:**
```bash
# Append ; echo EXIT:$? to every command so non-zero exit becomes output, not failure
(cd /project/server && go build ./... 2>&1); echo "BUILD_EXIT:$?"
```

**Fix C — Explicit || true on read-only commands:**
```bash
git -C /project status || true
git -C /project log --oneline -5 || true
```

---

### ❌ Mode 2 — Wrong working directory

```
pattern ./server/...: directory prefix does not contain main module
```

**Cause:** Each parallel Bash call gets a fresh shell. CWD is NOT shared.

**Fix:** Use explicit `cd` or `-C` / `--prefix` flags in every command:

| Language | Correct pattern |
|----------|----------------|
| Go | `cd /abs/path/server && go build ./...` |
| Git | `git -C /abs/path status` |
| npm | `npm test --prefix /abs/path/frontend` |
| Python | `python3 /abs/path/script.py` |
| Make | `make -C /abs/path target` |
| Docker | always uses absolute paths already |

---

### ❌ Mode 3 — stderr not captured

**Cause:** Build errors go to stderr which gets swallowed.

**Fix:** Always merge stderr into stdout for build/test commands:
```bash
go build ./... 2>&1
npm run build 2>&1
cargo build 2>&1
```

---

### ❌ Mode 4 — Timeout / hung command blocks everything

**Cause:** A slow network fetch or hanging test blocks the parallel queue.

**Fix:** Use the runner's `--timeout` flag, or wrap manually:
```bash
timeout 30 slow-command 2>&1 || echo "TIMED OUT"
```
The parallel runner kills commands that exceed `--timeout` and marks them `exit: 124`.

---

### ❌ Mode 5 — API rate limit (HTTP 500 / 429)

**Cause:** Too many concurrent Bash calls hit Claude/Anthropic API limits.

**Fix:** Lower `--limit`:
```bash
python3 ~/.claude/hooks/utils/parallel_runner.py "cmd1" ... --limit 2
```
Default limit is 4, which is safe for most sessions.

---

### ❌ Mode 6 — Command not found (PATH differences)

**Cause:** Tools like `go`, `node`, `docker` may not be on PATH in a fresh shell.

**Fix:** Use absolute binary paths:
```bash
# Discover paths once:
which go node npm docker gh 2>/dev/null

# Then use them:
/usr/local/go/bin/go build ./...
/usr/bin/node script.js
```

Discover binary paths once:
```bash
which go node npm docker gh python3 2>/dev/null
```

Then use absolute paths in commands to avoid PATH issues in fresh shells.

---

## JSON Stdin Mode (Recommended for AI Agents)

Avoids shell escaping issues entirely. Any AI can generate this:

```bash
echo '[
  {"cmd": "/usr/local/go/bin/go build ./...", "cwd": "/mnt/d/Projects/zyratv/server"},
  {"cmd": "git status",                       "cwd": "/mnt/d/Projects/zyratv"},
  {"cmd": "git log --oneline -5",             "cwd": "/mnt/d/Projects/zyratv"},
  {"cmd": "node scripts/audit.js",            "cwd": "/mnt/d/Projects/zyratv"}
]' | python3 ~/.claude/hooks/utils/parallel_runner.py --stdin --allow-failures
```

The `cwd` per-command means **no `cd` needed** — the runner handles directory switching.

---

## Parsing Results in AI Code

The runner always outputs valid JSON. AI agents can parse and act on it:

```python
import subprocess, json

result = subprocess.run(
    ["python3", f"{Path.home()}/.claude/hooks/utils/parallel_runner.py", "--stdin", "--allow-failures", "--quiet"],
    input=json.dumps([
        {"cmd": "go build ./...", "cwd": "/project/server"},
        {"cmd": "git status",    "cwd": "/project"},
    ]),
    capture_output=True, text=True
)

results = json.loads(result.stdout)
for r in results:
    if not r["ok"]:
        print(f"FAILED: {r['cmd']}\n{r['output']}")
```

---

## Decision Tree: When to Use This Script

```
Need to run multiple commands?
│
├─ Are they independent (no output dependency)?
│   ├─ YES → use parallel_runner.py
│   └─ NO  → run sequentially with &&
│
├─ Could any of them fail non-critically?
│   ├─ YES → add --allow-failures
│   └─ NO  → default (exit 1 if any fail)
│
└─ Worried about hitting API rate limits?
    ├─ YES → --limit 2
    └─ NO  → default --limit 4
```

---

## Golden Rules (apply to ALL AI models)

1. **Never assume CWD** — always use absolute paths or `cwd` per command
2. **Always capture stderr** — append `2>&1` to builds/tests
3. **Use `--allow-failures` for diagnostic runs** — don't let one bad check abort others
4. **Use the JSON stdin mode** for 4+ commands — cleaner than shell escaping
5. **Set `--retry 1` for build commands** — fast feedback; don't retry compile errors
6. **Set `--retry 3` for network commands** — retries are useful for flaky APIs
