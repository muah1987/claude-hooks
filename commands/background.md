---
description: Save session, commit to GitHub, update memory, install daemon, and run Claude Code as a persistent background service that auto-starts on every boot — works across ALL projects
argument-hint: [optional note to include in resume context]
allowed-tools: Bash, Read, Write, Edit
---

# /background — Run Claude Code as a Global Background Daemon

This skill performs a full session handoff then starts Claude Code as a persistent
background daemon that works **across all Claude projects**.

The daemon:
- Auto-starts when the machine boots (systemd user service)
- Registers the **current project** for background processing
- Loads CLAUDE.md + memory for every registered project
- Runs Claude with `--dangerously-skip-permissions` so it can act autonomously
- Accepts tasks via Telegram and routes them to the right project
- Runs hourly dependency/CI checks per project
- Restores saved cron jobs on resume

## Variables

NOTE: $ARGUMENTS

## Steps

Execute these steps **in order**:

### 1. Save and Commit Current Session State

```bash
cd $(pwd)
git add -A 2>/dev/null || true
git status --short 2>/dev/null | head -20
```

Commit all staged changes with a descriptive message, then push:

```bash
git stash -- .claude/hooks/start_telegram_bridge.py 2>/dev/null || true
git pull --rebase origin main 2>/dev/null || true
git commit -m "chore: /background — save session state before daemon handoff" 2>/dev/null || echo "nothing to commit"
git push origin main 2>/dev/null || true
git stash pop 2>/dev/null || true
```

### 2. Register Current Project with Daemon

Write the current project to the daemon's project registry:

```bash
PROJ_DIR=$(pwd)
DAEMON_REGISTRY="$HOME/.claude/daemon/projects.json"
mkdir -p "$HOME/.claude/daemon"

# Read existing registry or create new
python3 -c "
import json, os, sys
from pathlib import Path

registry_path = Path('$DAEMON_REGISTRY')
cwd = '$PROJ_DIR'

if registry_path.exists():
    registry = json.loads(registry_path.read_text())
else:
    registry = {'projects': []}

# Add/update current project
existing = [p for p in registry['projects'] if p['path'] == cwd]
if existing:
    existing[0]['last_registered'] = '$( date -u +%Y-%m-%dT%H:%M:%SZ )'
    existing[0]['active'] = True
else:
    registry['projects'].append({
        'path': cwd,
        'name': Path(cwd).name,
        'last_registered': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
        'active': True
    })

registry_path.write_text(json.dumps(registry, indent=2))
print(f'Registered: {cwd}')
print(f'Total projects: {len(registry[\"projects\"])}')
"
```

### 3. Write Resume Context for This Project

```bash
NOTE="$NOTE"
cat > "$HOME/.claude/daemon/resume_$(basename $(pwd)).md" << RESUME
# Resume Context — $(basename $(pwd))
# Written: $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Project Path
$(pwd)

## What Was Happening
${NOTE:-No specific note provided}

## Resume Instructions
1. Read CLAUDE.md in $(pwd) for full project context
2. Read memory files in ~/.claude/projects/$(echo $(pwd) | sed 's|/|-|g')/memory/
3. Check GitHub CI status
4. Run dependency check if overdue
5. Continue from last known state
RESUME
echo "Resume context saved"
```

### 4. Save Active Cron Jobs

Use the CronList tool to list all active cron jobs, then save them:

```bash
# Crons will be listed and saved by Claude via CronList tool — done in step below
echo "Saving cron job list..."
```

(Use CronList to get all jobs, write the result as JSON to `~/.claude/daemon/saved_crons.json`)

### 5. Install/Update and Start the Background Daemon

```bash
uv run $HOME/.claude/daemon/install_daemon.py
```

If the daemon is already running, restart it to pick up the new project registration:

```bash
systemctl --user restart claude-code-daemon.service 2>/dev/null && echo "Daemon restarted" || echo "Daemon start failed — check: journalctl --user -u claude-code-daemon"
```

### 6. Verify and Report

```bash
systemctl --user status claude-code-daemon.service --no-pager | head -15
tail -20 $HOME/.claude/daemon/daemon.log 2>/dev/null || echo "No log yet"
```

Report to the user:
- What was committed and pushed
- How many projects are registered
- Daemon PID and status
- Commands to manage it:
  - Status: `systemctl --user status claude-code-daemon`
  - Logs: `journalctl --user -u claude-code-daemon -f`
  - Stop: `systemctl --user stop claude-code-daemon`
  - Log file: `~/.claude/daemon/daemon.log`
  - Resume interactive: `claude --continue`

Done — the session is handed off to the background daemon.
