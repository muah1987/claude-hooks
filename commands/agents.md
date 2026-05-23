---
description: Inspect the agent registry — list recent agents, active agents, results, and session trees
argument-hint: "[list | active | results | session | tree | clear]"
allowed-tools: Bash, Read
---

Use `uv run ~/.claude/scripts/agents.py <command>` to inspect the agent registry.

Available commands:

- `uv run ~/.claude/scripts/agents.py list` — show the last 20 agent events (start / stop) in a table with timestamp, event, agent_id, agent_type, session, and result_summary.
- `uv run ~/.claude/scripts/agents.py active` — show agents that have a `start` event but no matching `stop`, with **elapsed time** since launch.
- `uv run ~/.claude/scripts/agents.py results` — show the last 10 `stop` events with `status` (from stored result or `## RESULT` block) and result_summary.
- `uv run ~/.claude/scripts/agents.py session [<session_id>]` — show all agents **grouped by session**, with start/stop pairs, duration, backend, and status. Defaults to the 5 most recent sessions.
- `uv run ~/.claude/scripts/agents.py tree [<session_id>]` — show the agent hierarchy tree for a session: each sub-agent with type, backend, duration, and result summary. Defaults to the most recent session.
- `uv run ~/.claude/scripts/agents.py clear` — truncate the registry file at `~/.claude/data/agent_registry.jsonl`.

The registry file is a JSON Lines log at `~/.claude/data/agent_registry.jsonl`. It is populated by the SubagentStart and SubagentStop hooks.

## Structured results (`agent_results.py`)

The `SubagentStop` hook also persists each sub-agent's final summary as a structured JSON record under `~/.claude/data/results/<agent_id>.json`. Use the `agent_results.py` CLI to inspect these:

- `uv run ~/.claude/scripts/agent_results.py list` — see the last 10 recent results (timestamp, agent_id, status, summary).
- `uv run ~/.claude/scripts/agent_results.py get <id>` — print the full stored result for a specific agent as JSON.
- `uv run ~/.claude/scripts/agent_results.py wait <id>` — block until a `stop` event for the given agent appears in the registry, then print its `result_summary` (use `--timeout <seconds>`, default 60).
- `uv run ~/.claude/scripts/agent_results.py store <id> <status> <summary>` — manually store a result (used by non-Claude backends such as Ollama).

### Wait for multiple agents in parallel

```bash
uv run ~/.claude/scripts/agent_results.py wait-all <id1> <id2> <id3> --timeout 120
```

Polls until all agents complete. Prints one JSON line per agent as it finishes. Exit 1 on timeout.

## Typical inspection flow

```bash
# Check which agents are still running (with elapsed time):
uv run ~/.claude/scripts/agents.py active

# See the current session's agent tree:
uv run ~/.claude/scripts/agents.py tree

# See grouped view across sessions:
uv run ~/.claude/scripts/agents.py session

# Check a specific agent's result:
uv run ~/.claude/scripts/agent_results.py get <agent_id>
```
