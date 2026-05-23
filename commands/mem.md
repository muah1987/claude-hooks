---
allowed-tools: Bash, Read, Write
description: Read or write project memory (short-term session memory or long-term persistent)
argument-hint: "[read|write|short|anchor] [key] [value]"
---

# Memory

Manage short-term (session) and long-term (persistent) project memory.

## Quick operations

```bash
# Read long-term memory index for current project
uv run ~/.claude/scripts/skill_runner.py memory long --index

# Read all short-term memory for this session
uv run ~/.claude/scripts/skill_runner.py memory short "$CLAUDE_SESSION_ID"

# Write a short-term memory key
uv run ~/.claude/scripts/skill_runner.py st-set "$CLAUDE_SESSION_ID" "key" "value"

# Read a short-term memory key
uv run ~/.claude/scripts/skill_runner.py st-get "$CLAUDE_SESSION_ID" "key"

# Ensure current project is anchored with a UUID
uv run ~/.claude/scripts/project_anchor.py anchor

# List all registered projects
uv run ~/.claude/scripts/project_anchor.py list
```

## Task: $ARGUMENTS

Execute the memory operation specified. If no argument, show both short-term and long-term memory summaries for the current project.

Rules:
- Short-term memory disappears when the session ends — use for temporary working state, in-progress task notes, intermediate results
- Long-term memory persists across sessions — use for facts, decisions, architecture notes, user preferences
- When writing long-term memory, write to `~/.claude/projects/<project>/memory/<topic>.md` with YAML frontmatter (`type: user|feedback|project|reference`)
- Project anchor UUID links memory to the project regardless of directory renames
