#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
SessionEnd Hook - GOTCHA Framework Integration

This hook runs when a Claude Code session ends. It implements GOTCHA framework
principles by logging session events for transparency and continuous improvement.

Claude Code Hooks Specification - SessionEnd Input Fields:
- session_id: Unique identifier for the session
- cwd: Current working directory
- reason: Why the session ended. One of:
    - "clear": User explicitly cleared the session (e.g., /clear command)
    - "logout": User logged out of the application
    - "prompt_input_exit": User exited via prompt input (Ctrl+C, Ctrl+D, or quit command)
    - "bypass_permissions_disabled": Session ended because bypass permissions mode was disabled
    - "other": Any other termination reason (timeout, crash, etc.)
- permission_mode: Permission level used during the session (e.g., "default", "full", "ask-always")
- transcript: Array of conversation turns (if available)

GOTCHA Framework Principles:
- Transparency: Log session termination reasons with full context
- Continuous improvement: Use logs to identify patterns and session behaviors
- Memory protocol: Support session state cleanup

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Context + Transparency
  - Context: Preserves session context and state for future session continuity
  - Transparency: Generates session summary logs with termination reasons and cleanup actions

ATLAS Phase: Stress-test (session summary)
  - Summarizes the session outcome and validates clean termination
  - Stress-tests session lifecycle by logging end-state data for pattern analysis
"""
__version__ = "2026.04.20.6"

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def log_session_end(input_data: dict, gh_context: dict | None = None) -> None:
    """
    Log session end event to logs directory.

    Extracts and logs key fields from the session end event:
    - session_id: Unique session identifier
    - reason: Why the session ended (clear, logout, prompt_input_exit, bypass_permissions_disabled, other)
    - permission_mode: Permission level used during session
    - cwd: Current working directory
    - transcript: Conversation history (if available)

    Args:
        input_data: JSON input from Claude Code containing session end details
        gh_context: Optional GitHub context dict (branch, PR info) to include in log entry
    """
    # Ensure logs directory exists
    log_dir = Path.home() / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'session_end.jsonl'

    # Extract key fields with defaults for logging
    session_id = input_data.get('session_id', 'unknown')
    reason = input_data.get('reason', 'other')
    permission_mode = input_data.get('permission_mode', 'unknown')
    cwd = input_data.get('cwd', '')

    # Validate reason field against known values
    valid_reasons = {'clear', 'logout', 'prompt_input_exit', 'bypass_permissions_disabled', 'other'}
    if reason not in valid_reasons:
        reason = 'other'  # Default to 'other' for unknown reasons

    # Create structured log entry with explicit field extraction
    hook_event_name = input_data.get('hook_event_name', 'SessionEnd')
    log_entry = {
        'hook_event_name': hook_event_name,
        'session_id': session_id,
        'reason': reason,
        'permission_mode': permission_mode,
        'cwd': cwd,
        'logged_at': datetime.now().isoformat(),
        # Include any additional fields from input_data
        'raw_input': input_data
    }

    # Add GitHub context if provided
    if gh_context:
        log_entry['gh_context'] = gh_context

    # Append-only JSONL write — one line per session end
    with open(log_file, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')

    # Also log to stderr for visibility (non-blocking)
    reason_descriptions = {
        'clear': 'User cleared session',
        'logout': 'User logged out',
        'prompt_input_exit': 'User exited via prompt (Ctrl+C/D or quit)',
        'bypass_permissions_disabled': 'Bypass permissions mode was disabled',
        'other': 'Session ended (other reason)'
    }
    print(f"[SessionEnd] {reason_descriptions.get(reason, reason)} | "
          f"permission_mode={permission_mode} | session={session_id[:8] if len(session_id) > 8 else session_id}...",
          file=sys.stderr)


def perform_cleanup():
    """Perform optional cleanup tasks at session end."""
    cleanup_actions = []

    # Clean up any .tmp files from logs directory
    log_dir = Path.home() / ".claude" / "logs"
    if log_dir.exists():
        for tmp_file in log_dir.glob("*.tmp"):
            try:
                tmp_file.unlink()
                cleanup_actions.append(f"Removed temp file: {tmp_file.name}")
            except Exception:
                pass

    # Clean up old chat.json if it exists and is stale
    chat_file = log_dir / "chat.json" if log_dir.exists() else None
    if chat_file and chat_file.exists():
        try:
            file_age = datetime.now().timestamp() - chat_file.stat().st_mtime
            if file_age > 86400:  # 24 hours in seconds
                chat_file.unlink()
                cleanup_actions.append("Removed stale chat.json (older than 24 hours)")
        except Exception:
            pass

    return cleanup_actions


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--cleanup', action='store_true',
                          help='Perform cleanup tasks at session end')
        parser.add_argument('--gh-log', action='store_true',
                          help='Log GitHub state (branch, open PR) at session end')
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract session_id for cleanup logging
        session_id = input_data.get('session_id', 'unknown')

        # Gather GitHub context if --gh-log is set
        gh_context = None
        if args.gh_log:
            try:
                sys.path.insert(0, str(Path(input_data.get("cwd") or os.getcwd()) / ".github" / "hooks"))
                from gh_detect import is_gh_installed, get_current_branch, run_gh_command

                if is_gh_installed():
                    gh_context = {}
                    branch = get_current_branch()
                    if branch:
                        gh_context["branch"] = branch

                    # Check for open PR on current branch
                    if branch:
                        exit_code, stdout, _ = run_gh_command(
                            ["pr", "view", "--json", "number,title,state"]
                        )
                        if exit_code == 0 and stdout:
                            try:
                                pr_info = json.loads(stdout)
                                gh_context["current_pr"] = pr_info
                            except (json.JSONDecodeError, ValueError):
                                pass

                    # Only keep gh_context if we got any data
                    if not gh_context:
                        gh_context = None
            except ImportError:
                pass  # gh_detect not available
            except Exception:
                pass  # Any error, skip gracefully

        # Log the session end event
        log_session_end(input_data, gh_context=gh_context)

        # Best-effort memory compaction — never block exit
        try:
            subprocess.run(
                ["uv", "run", str(Path.home() / ".claude/scripts/memory_compact.py")],
                timeout=10, capture_output=True,
            )
        except Exception:
            pass

        # Best-effort session data cleanup — prune stale sessions (>7 days, keep 20)
        try:
            subprocess.Popen(
                ["uv", "run", str(Path.home() / ".claude/scripts/session_cleanup.py"), "--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception:
            pass

        # Perform cleanup if requested
        if args.cleanup:
            perform_cleanup()

        # Success
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == '__main__':
    main()
