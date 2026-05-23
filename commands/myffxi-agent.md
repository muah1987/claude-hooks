---
description: myffxi agentic development — build, test, and deploy myffxi features end-to-end
argument-hint: "<feature or task description>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# myffxi Agentic Development — /myffxi-agent

Run a multi-model agentic development cycle for the myffxi project using Ollama cloud models.
Implements MIP items, reviews code, and commits via git workflow.

## Variables

TASK: $ARGUMENTS

---

## Instructions

This skill orchestrates multiple Ollama cloud models for myffxi development tasks.

### System Prompt (used for all Ollama calls):
```
You are an expert game server developer working on myffxi — a custom FFXI-compatible
private server in Rust (tokio, sqlx, PostgreSQL 16) + cross-platform client (C++20,
Vulkan/custom RHI, PS4/PS5 homebrew). You understand FFXI game mechanics deeply.
Be concise, write production-quality Rust code, follow Rust 2021 edition conventions.
Use anyhow for binary errors, thiserror for lib errors, tracing for logging.
```

### Model Assignment:
- **Code generation / Rust implementation**: `qwen3-coder:480b-cloud`
- **Architecture / game mechanic design**: `kimi-k2-thinking:cloud`
- **Code review / analysis**: `deepseek-v3.2:cloud`
- **Quick tasks / documentation**: `minimax-m2.7:cloud`
- **Multilingual / JP content**: `glm-5.1:cloud` or `glm-5:cloud`
- **General reasoning**: `gemma4:31b-cloud`

### Agentic Git Workflow:

For each development task:
1. **Plan** (kimi-k2-thinking) — analyze MIP item, design implementation
2. **Implement** (qwen3-coder:480b) — generate Rust code
3. **Review** (deepseek-v3.2) — check for correctness, edge cases
4. **Commit** via Claude Code git workflow:
   ```bash
   git checkout -b feat/<description>
   # apply changes
   git add server/crates/myffxi-zone/src/world.rs
   git commit -m "feat(zone): MIP#NNN — <description>"
   git checkout main
   git merge --no-ff feat/<description>
   git branch -d feat/<description>
   ```

### How to call Ollama remote models:
Remote model names (no `:cloud` suffix on ollama.com API): `gemma4:31b`, `glm-5.1`, `minimax-m2.7`, `qwen3-coder:480b-cloud`, `kimi-k2-thinking:cloud`, `deepseek-v3.2:cloud`

```bash
OLLAMA_API_KEY=ed77e3e587f84d90ae33c682266c4b3e.mniXRRM13umE32FZZrTBG463
curl -s https://ollama.com/api/chat \
  -H "Authorization: Bearer $OLLAMA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:31b",
    "messages": [{"role":"system","content":"<system_prompt>"},{"role":"user","content":"<task>"}],
    "stream": false
  }' | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['message']['content'])"
```

### Workflow Steps:

Parse `TASK` and determine action:

**If TASK contains "implement MIP#NNN":**
1. Read `docs/mip.md` to find the MIP item description
2. Read `server/crates/myffxi-zone/src/world.rs` around the insertion point
3. Call `qwen3-coder:480b-cloud` to generate the implementation
4. Apply the code change
5. Call `deepseek-v3.2:cloud` to review
6. Git commit with feat(zone) prefix

**If TASK contains "review":**
1. Run `git diff HEAD` to get recent changes
2. Call `deepseek-v3.2:cloud` with the diff for review
3. Report findings

**If TASK contains "design" or "architecture":**
1. Call `kimi-k2-thinking:cloud` for deep reasoning
2. Write result to `docs/design/<topic>.md`

**If TASK contains "document":**
1. Call `glm-5.1:cloud` or `minimax-m2.7:cloud`
2. Update relevant docs

**Default (general task):**
1. Analyze with `gemma4:31b-cloud`
2. Implement if code changes needed
3. Commit if changes made

### After each cycle:
- Update `docs/mip.md` status if MIP items were completed
- Update memory at `/home/mohammed/.claude/projects/-mnt-d-projects-myffxi/memory/project_phase_state.md`
