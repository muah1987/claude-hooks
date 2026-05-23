---
description: Load context for a new agent session — codebase structure, memory, crons, README
argument-hint: "[path/to/project]"
allowed-tools: Bash, Read
---

# Prime

Load essential context in one fast pass using `skill_runner.py context`.

## Execute (run all at once)

```bash
# Fast context: git state + memory index + crons + file list
uv run ~/.claude/scripts/skill_runner.py context

# Skills available
uv run ~/.claude/scripts/skill_runner.py skills
```

## Also read (if they exist)
- @README.md
- @CLAUDE.md

## Report

Provide a concise overview:
1. Project purpose + architecture
2. Active cron jobs (if any)
3. Memory items worth noting
4. Any open tasks or issues

End with: "Ready."

## Optional TTS

If `$ELEVENLABS_API_KEY` is set, summarise in one sentence via TTS.
