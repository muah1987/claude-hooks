#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
harness_sync.py — Auto-commit and push ~/.claude changes to GitHub.

Runs as an async Stop hook. Detects changes in hooks/, scripts/,
commands/, and CLAUDE.md, then commits + pushes if anything changed.
Fails silently — never blocks the harness.
"""
__version__ = "2026.05.23.1"

import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

CLAUDE_DIR = Path.home() / ".claude"
TRACKED_PATHS = ["hooks/", "scripts/", "commands/", "skills/", "CLAUDE.md"]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=CLAUDE_DIR,
                          timeout=30, **kwargs)


def main() -> None:
    try:
        # Verify it's a git repo
        r = run(["git", "rev-parse", "--is-inside-work-tree"])
        if r.returncode != 0:
            return

        # Check for uncommitted changes in tracked paths
        r = run(["git", "status", "--porcelain"] + TRACKED_PATHS)
        if r.returncode != 0 or not r.stdout.strip():
            return  # Nothing to commit

        changed = [line[3:].strip() for line in r.stdout.splitlines() if line.strip()]
        if not changed:
            return

        # Stage only tracked paths
        run(["git", "add"] + TRACKED_PATHS)

        # Commit
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"chore(harness): auto-sync {now}\n\nChanged: {', '.join(changed[:5])}"
        if len(changed) > 5:
            msg += f" (+{len(changed) - 5} more)"

        r = run(["git", "commit", "-m", msg])
        if r.returncode != 0:
            return

        # Push
        run(["git", "push", "origin", "master"])

    except Exception:
        pass  # Always fail silently


if __name__ == "__main__":
    main()
