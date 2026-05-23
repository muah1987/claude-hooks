---
description: Inspect stored sub-agent results — list, get by ID, wait for completion
argument-hint: <list|get <id>|wait <id>|wait-all <id1> <id2>>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Agent Results

Inspect results from sub-agents stored in the agent registry. Complements `/agents` by focusing on structured result retrieval.

## Usage
`uv run ~/.claude/scripts/agent_results.py <list|get <id>|wait <id>|wait-all <id1> <id2>>`

Subcommands:
- `list` — recent agent runs with id, status, and duration
- `get <id>` — full stored result for a specific agent
- `wait <id>` — block until an agent completes, then print the result
- `wait-all <id1> <id2> ...` — block until every listed agent completes

## What it does
- Reads the agent registry JSONL store
- Parses each run's `## RESULT` block into structured fields
- Polls at a short interval for wait commands, with a sensible timeout
- Emits compact output suitable for orchestrator consumption

## When to use
- Checking results of background agents you spawned earlier
- Orchestrator code that needs to synchronise multiple parallel agents
- Debugging why a particular sub-agent's output was unusable
- Auditing the agent run history for a session
