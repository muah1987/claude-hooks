#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
PostToolUseFailure Hook - GOTCHA Framework Integration

This hook runs when a tool execution fails. It implements GOTCHA framework
principles by:

1. Logging tool failures with detailed error information
2. Supporting the continuous improvement loop: identify → fix → document
3. Recording failures to help identify patterns and improve tools

GOTCHA Continuous Improvement Loop:
1. Identify what broke and why
2. Fix the tool script
3. Test until it works reliably
4. Update the goal with new knowledge
5. Next time → automatic success

Guardrails:
- When tools fail, fix and document what was learned
- Update goals with new knowledge about API constraints, rate limits, etc.
- Preserve intermediate outputs before retrying

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Guardrails + Improvement
  - Guardrails: Captures failure data to prevent recurring errors
  - Improvement: Feeds the continuous improvement loop (identify, fix, document, test)

ATLAS Phase: Stress-test
  - Evaluates tool failures to identify weaknesses in the execution pipeline
  - Stress-tests the system by recording and analyzing failure patterns
"""
__version__ = "2026.04.20.5"

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def resolve_log_dir(input_data: dict) -> Path:
    """Resolve a stable log directory.

    Prefer CLAUDE_PROJECT_DIR env var, then the hook's 'cwd' field, and
    finally ~/.claude/logs — never Path.cwd(), which pollutes whichever
    directory Claude Code happens to be running in.
    """
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if project_dir and Path(project_dir).is_dir():
        return Path(project_dir) / 'logs'
    cwd = (input_data.get('cwd') or '').strip()
    if cwd and Path(cwd).is_dir():
        return Path(cwd) / 'logs'
    return Path.home() / '.claude' / 'logs'


def send_telegram_failure_notification(tool_name: str, error: dict | str, cwd: str) -> None:
    """Send a Telegram notification for a tool failure.

    Best-effort, non-blocking: swallows ALL exceptions and never raises.
    """
    try:
        # Extract error message and truncate
        if isinstance(error, dict):
            error_msg = error.get('message', str(error))
        else:
            error_msg = str(error)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + '…'

        # Project name from cwd basename
        project_name = Path(cwd).name if cwd else 'unknown'

        # Timestamp
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        message = (
            f"\u26a0\ufe0f <b>Tool Failure</b>\n"
            f"<b>Tool:</b> {tool_name}\n"
            f"<b>Project:</b> {project_name}\n"
            f"<b>Time:</b> {ts}\n"
            f"<b>Error:</b> <code>{error_msg}</code>"
        )

        telegram_script = Path.home() / '.claude' / 'hooks' / 'telegram_notify.py'
        if not telegram_script.exists():
            return

        subprocess.run(
            [
                str(Path.home() / '.local' / 'bin' / 'uv'),
                'run',
                str(telegram_script),
                '--event', 'error',
                '--message', message,
            ],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except Exception:
        # Never block, never raise
        pass


def main():
    try:
        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Add timestamp to the log entry
        input_data['logged_at'] = datetime.now().isoformat()

        # Extract key fields for enhanced logging
        tool_name = input_data.get('tool_name', 'unknown')
        tool_use_id = input_data.get('tool_use_id', 'unknown')
        error = input_data.get('error', {})
        is_interrupt = input_data.get('is_interrupt')  # Optional boolean, may not be present

        # Create a structured log entry with error details
        log_entry = {
            'timestamp': input_data['logged_at'],
            'session_id': input_data.get('session_id', ''),
            'hook_event_name': input_data.get('hook_event_name', 'PostToolUseFailure'),
            'tool_name': tool_name,
            'tool_use_id': tool_use_id,
            'tool_input': input_data.get('tool_input', {}),
            'error': error,
            'is_interrupt': is_interrupt,
            'cwd': input_data.get('cwd', ''),
            'permission_mode': input_data.get('permission_mode', ''),
            'transcript_path': input_data.get('transcript_path', ''),
            'raw_input': input_data
        }

        # Ensure log directory exists (never Path.cwd() — pollutes random dirs)
        log_dir = resolve_log_dir(input_data)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / 'post_tool_use_failure.jsonl'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

        # Send Telegram notification (best-effort, non-blocking, never raises)
        try:
            send_telegram_failure_notification(
                tool_name=tool_name,
                error=error,
                cwd=input_data.get('cwd', ''),
            )
        except Exception:
            pass

        # Build additionalContext to provide failure details back to Claude
        context_parts = [f"Tool '{tool_name}' failed."]
        if is_interrupt is not None:
            context_parts.append(f"Interrupted: {is_interrupt}")
        if error:
            error_msg = error.get('message', str(error)) if isinstance(error, dict) else str(error)
            context_parts.append(f"Error: {error_msg}")

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUseFailure",
                "additionalContext": " ".join(context_parts)
            }
        }
        print(json.dumps(output))

        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Exit cleanly on any other error
        sys.exit(0)


if __name__ == '__main__':
    main()
