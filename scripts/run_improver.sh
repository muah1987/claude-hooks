#!/usr/bin/env bash
# run_improver.sh — Run harness_improver.py for every active Claude project.
# Called by crontab every 20 minutes. Discovers projects dynamically.
# No hardcoded project paths.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
IMPROVER="$CLAUDE_DIR/scripts/harness_improver.py"
LOG="$CLAUDE_DIR/data/harness_improver.log"

# Source OLLAMA_API_KEY from settings.json if not already in environment
if [[ -z "${OLLAMA_API_KEY:-}" ]]; then
    export OLLAMA_API_KEY
    OLLAMA_API_KEY=$(python3 -c "
import json, sys
try:
    d = json.load(open('$HOME/.claude/settings.json'))
    print(d.get('env', {}).get('OLLAMA_API_KEY', ''))
except Exception:
    print('')
" 2>/dev/null)
fi

# Find all active Claude projects: directories containing a .claude/ subdir
# Looks in /mnt/d/projects/ — the standard multi-project root
PROJECTS_ROOT="${PROJECTS_ROOT:-/mnt/d/projects}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] run_improver.sh start" >> "$LOG"

found=0
while IFS= read -r -d '' project_dir; do
    # Trim trailing /.claude
    proj="${project_dir%/.claude}"
    [[ -d "$proj" ]] || continue

    # Skip if no Python files in hooks/ (not a real harness project)
    [[ -f "$proj/.claude/hooks/stop.py" ]] || continue

    export CLAUDE_PROJECT_DIR="$proj"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] improving: $proj" >> "$LOG"
    uv run "$IMPROVER" >> "$LOG" 2>&1 || true
    found=$((found + 1))
done < <(find "$PROJECTS_ROOT" -maxdepth 2 -name ".claude" -type d -print0 2>/dev/null)

# Also run for ~/.claude itself as a meta-project (the harness project)
if [[ -f "$IMPROVER" ]]; then
    export CLAUDE_PROJECT_DIR="/mnt/d/projects/cc-main"
    uv run "$IMPROVER" >> "$LOG" 2>&1 || true
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] run_improver.sh done (${found} projects)" >> "$LOG"
