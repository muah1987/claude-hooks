#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
TeammateIdle Hook - GOTCHA Framework Integration

This hook runs when an agent team teammate is about to go idle. It implements
GOTCHA framework principles by logging idle events and optionally enforcing
work completion before allowing teammates to go idle.

Claude Code Hooks Specification - TeammateIdle Input Fields:
- session_id: Unique identifier for the current session
- transcript_path: Path to the conversation transcript file
- cwd: Current working directory
- permission_mode: Permission level used during the session
- hook_event_name: "TeammateIdle"
- teammate_name: Name of the teammate going idle
- team_name: Name of the team the teammate belongs to

Decision Control (Exit Codes Only):
- Exit code 0: Allow the teammate to go idle
- Exit code 2: Block idle (stderr message fed back as feedback)

Command Line Arguments:
- --log-only: Just log the event, no enforcement (always exits 0)
- --enforce: Check for uncommitted changes and block idle if found (exit 2)

GOTCHA Framework Principles:
- Transparency: Log all teammate idle events for visibility
- Continuous improvement: Track idle patterns across sessions
- Guardrails: Ensure work is committed before going idle

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Orchestration
  - Orchestration: Monitors agent resource utilization and idle state transitions
  - Ensures teammates complete work before going idle through enforcement checks

ATLAS Phase: Trace (resource monitoring)
  - Traces resource utilization across the agent team for visibility
  - Monitors idle patterns to optimize task distribution and agent efficiency
"""
__version__ = "2026.04.20.4"

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def check_uncommitted_changes(cwd: str) -> bool:
    """
    Check if the working directory has uncommitted changes using git status.

    Args:
        cwd: The working directory to check for uncommitted changes

    Returns:
        True if there are uncommitted changes, False otherwise
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10
        )
        # If git status --porcelain produces any output, there are uncommitted changes
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        # If git is not available or fails, don't block
        return False


def log_event(input_data: dict, action: str) -> None:
    """
    Log teammate idle event to logs/teammate_idle.json.

    Appends a structured log entry to a JSON array file. Creates
    the logs directory and file if they do not exist.

    Args:
        input_data: JSON input from Claude Code containing event details
        action: The action taken (e.g., "logged", "allowed", "blocked")
    """
    log_dir = Path.home() / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "teammate_idle.jsonl"

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "teammate_name": input_data.get("teammate_name", "unknown"),
        "team_name": input_data.get("team_name", "unknown"),
        "session_id": input_data.get("session_id", "unknown"),
        "cwd": input_data.get("cwd", ""),
        "permission_mode": input_data.get("permission_mode", "unknown"),
        "action": action,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


def main() -> None:
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="TeammateIdle hook - logs and optionally enforces work completion before idle"
        )
        parser.add_argument('--log-only', action='store_true',
                            help='Just log the idle event, no enforcement (always exits 0)')
        parser.add_argument('--enforce', action='store_true',
                            help='Check for uncommitted changes and block idle if found (exit 2)')
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract key fields
        teammate_name = input_data.get("teammate_name", "unknown")
        team_name = input_data.get("team_name", "unknown")
        session_id = input_data.get("session_id", "unknown")
        cwd = input_data.get("cwd", "")

        # Log to stderr for visibility
        print(f"[TeammateIdle] teammate={teammate_name} team={team_name} "
              f"session={session_id[:8] if len(session_id) > 8 else session_id}...",
              file=sys.stderr)

        # --log-only mode: just log and allow
        if args.log_only:
            log_event(input_data, action="logged")
            sys.exit(0)

        # --enforce mode: check for uncommitted changes
        if args.enforce:
            if cwd and check_uncommitted_changes(cwd):
                log_event(input_data, action="blocked_uncommitted_changes")
                print("Uncommitted changes detected - complete your work before going idle",
                      file=sys.stderr)
                sys.exit(2)
            else:
                log_event(input_data, action="allowed")
                sys.exit(0)

        # Default: log and allow
        log_event(input_data, action="allowed")
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == "__main__":
    main()
