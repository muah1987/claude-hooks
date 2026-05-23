#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Notification Hook - GOTCHA Framework Integration

This hook runs when Claude Code sends notifications. It implements GOTCHA
framework principles by providing user feedback at key interaction points.

GOTCHA Framework Principles:
- Transparent communication about system state
- Context-aware notifications (permission prompts, idle prompts, etc.)
- Support for user interaction through TTS feedback

See CLAUDE.md for full GOTCHA framework documentation.

Notification Types (notification_type field):
--------------------------------------------
The Notification hook supports matcher-based filtering to run different hooks
for different notification types. The following notification types are available:

- permission_prompt: Permission requests from Claude Code (tool approval dialogs)
- idle_prompt: When Claude is waiting for user input (after 60+ seconds of idle time)
- auth_success: Authentication success notifications
- elicitation_dialog: When Claude Code needs input for MCP tool elicitation

Matcher-Based Filtering:
-----------------------
In your settings.json, you can configure matchers to filter notifications by type:

    {
      "hooks": {
        "Notification": [
          {
            "matcher": "permission_prompt",
            "hooks": [
              {
                "type": "command",
                "command": "/path/to/permission-alert.sh"
              }
            ]
          },
          {
            "matcher": "idle_prompt",
            "hooks": [
              {
                "type": "command",
                "command": "/path/to/idle-notification.sh"
              }
            ]
          }
        ]
      }
    }

Omit the matcher to run hooks for all notification types.

Input Schema:
------------
The hook receives JSON data via stdin:

    {
      "session_id": "abc123",
      "transcript_path": "/path/to/transcript.jsonl",
      "cwd": "/current/working/directory",
      "permission_mode": "default",  // "default", "plan", "acceptEdits", "dontAsk", or "bypassPermissions"
      "hook_event_name": "Notification",
      "message": "Claude needs your permission to use Bash",
      "notification_type": "permission_prompt"
    }

Command Line Arguments:
----------------------
- --notify: Enable TTS notifications for user feedback
- --filter-type: Only process specific notification types (comma-separated)
                 Example: --filter-type permission_prompt,idle_prompt

GOTCHA Layer: Orchestration
  - Orchestration: Coordinates user communication and feedback during workflow execution
  - Routes notifications to appropriate channels (TTS, logs) based on type and priority

ATLAS Phase: Assemble
  - Delivers assembled status updates and feedback to the user during execution
  - Keeps the user informed as components are assembled into the final result
"""
__version__ = "2026.04.20.4"

import argparse
import json
import os
import sys
import subprocess
import random
from datetime import datetime
from pathlib import Path

# Keywords that indicate a notification describes an error / issue
ERROR_KEYWORDS = ('error', 'failed', 'exception', 'traceback', 'timeout', 'crash')

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def get_tts_script_path() -> str | None:
    """
    Determine which TTS script to use based on available API keys.

    Priority order: ElevenLabs > OpenAI > pyttsx3

    Returns:
        Path to the TTS script to use, or None if no TTS scripts are available.
    """
    # Get current script directory and construct utils/tts path
    script_dir = Path(__file__).parent
    tts_dir = script_dir / "utils" / "tts"
    
    # Check for ElevenLabs API key (highest priority)
    if os.getenv('ELEVENLABS_API_KEY'):
        elevenlabs_script = tts_dir / "elevenlabs_tts.py"
        if elevenlabs_script.exists():
            return str(elevenlabs_script)
    
    # Check for OpenAI API key (second priority)
    if os.getenv('OPENAI_API_KEY'):
        openai_script = tts_dir / "openai_tts.py"
        if openai_script.exists():
            return str(openai_script)
    
    # Fall back to pyttsx3 (no API key required)
    pyttsx3_script = tts_dir / "pyttsx3_tts.py"
    if pyttsx3_script.exists():
        return str(pyttsx3_script)
    
    return None


def announce_notification() -> None:
    """
    Announce that the agent needs user input via text-to-speech.

    Uses the TTS provider configured via environment variables (ELEVENLABS_API_KEY
    or OPENAI_API_KEY). Falls back to pyttsx3 if no API keys are available.

    Optionally personalizes the message with the engineer's name (from ENGINEER_NAME
    environment variable) with a 30% probability.
    """
    try:
        tts_script = get_tts_script_path()
        if not tts_script:
            return  # No TTS scripts available
        
        # Get engineer name if available
        engineer_name = os.getenv('ENGINEER_NAME', '').strip()
        
        # Create notification message with 30% chance to include name
        if engineer_name and random.random() < 0.3:
            notification_message = f"{engineer_name}, your agent needs your input"
        else:
            notification_message = "Your agent needs your input"
        
        # Call the TTS script with the notification message
        subprocess.run([
            "uv", "run", tts_script, notification_message
        ], 
        capture_output=True,  # Suppress output
        timeout=10  # 10-second timeout
        )
        
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        # Fail silently if TTS encounters issues
        pass
    except Exception:
        # Fail silently for any other errors
        pass


def _contains_error_keywords(text: str) -> bool:
    """Return True if text contains any of the defined error keywords (case-insensitive)."""
    try:
        low = text.lower()
        return any(k in low for k in ERROR_KEYWORDS)
    except Exception:
        return False


def send_telegram_notification(input_data: dict) -> None:
    """Send every notification to Telegram via telegram_notify.py.

    - Detects error keywords and prepends a warning prefix.
    - Best-effort: swallows all exceptions, never blocks.
    """
    try:
        message = str(input_data.get('message', '') or '')
        title = str(input_data.get('title', '') or '')
        ntype = str(input_data.get('notification_type', 'unknown'))
        cwd = str(input_data.get('cwd', '') or '')
        project_name = Path(cwd).name if cwd else 'unknown'
        ts = datetime.now().strftime('%H:%M:%S')

        # Build combined body for keyword scan
        scan_target = f"{title}\n{message}"
        issue = _contains_error_keywords(scan_target)
        prefix = '\u26a0\ufe0f ISSUE: ' if issue else ''

        header = f"{prefix}<b>Notification</b> ({ntype})"
        body_parts = [header, f"<b>Project:</b> {project_name}", f"<b>Time:</b> {ts}"]
        if title:
            body_parts.append(f"<b>Title:</b> {title}")
        if message:
            body_parts.append(f"<b>Message:</b> {message}")
        body = "\n".join(body_parts)

        telegram_script = Path.home() / '.claude' / 'hooks' / 'telegram_notify.py'
        if not telegram_script.exists():
            return

        subprocess.run(
            [
                str(Path.home() / '.local' / 'bin' / 'uv'),
                'run',
                str(telegram_script),
                '--event', 'notification',
                '--message', body,
            ],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except Exception:
        # Never raise, never block
        pass


def main() -> None:
    """
    Main entry point for the notification hook.

    Processes incoming notification data from Claude Code, logs it to a JSON file,
    and optionally announces the notification via TTS.

    The hook receives the following fields in the input JSON:
    - session_id: Unique session identifier
    - transcript_path: Path to the conversation transcript
    - cwd: Current working directory
    - permission_mode: Current permission mode (default, plan, acceptEdits, dontAsk, bypassPermissions)
    - hook_event_name: Always "Notification" for this hook
    - message: The notification message text
    - notification_type: Type of notification (permission_prompt, idle_prompt, auth_success, elicitation_dialog)
    """
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="Notification hook for Claude Code - logs notifications and optionally provides TTS feedback"
        )
        parser.add_argument(
            '--notify',
            action='store_true',
            help='Enable TTS notifications for user feedback'
        )
        parser.add_argument(
            '--filter-type',
            type=str,
            default='',
            help='Only process specific notification types (comma-separated). '
                 'Valid types: permission_prompt, idle_prompt, auth_success, elicitation_dialog. '
                 'Example: --filter-type permission_prompt,idle_prompt'
        )
        args = parser.parse_args()

        # Read JSON input from stdin
        raw = sys.stdin.read()
        input_data: dict[str, object] = json.loads(raw) if raw.strip() else {}

        # Extract notification_type and optional title for filtering and logging
        notification_type = input_data.get('notification_type', 'unknown')
        title = input_data.get('title', '')  # Optional field alongside message

        # If filter-type is specified, check if this notification type should be processed
        if args.filter_type:
            allowed_types = [t.strip() for t in args.filter_type.split(',')]
            if notification_type not in allowed_types:
                # Skip this notification - not in the allowed types
                sys.exit(0)

        # Ensure log directory exists — use ~/.claude/logs/ so we never
        # pollute whatever project directory Claude Code is running in.
        log_dir = Path.home() / '.claude' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / 'notification.jsonl'

        # Create enriched log entry with all input fields
        # This ensures we capture: session_id, transcript_path, cwd, permission_mode,
        # hook_event_name, message, title, notification_type
        log_entry: dict[str, object] = {
            'timestamp': datetime.now().isoformat(),
            'notification_type': notification_type,
            'title': title,
            'permission_mode': input_data.get('permission_mode', 'unknown'),
            'session_id': input_data.get('session_id', 'unknown'),
            'message': input_data.get('message', ''),
            'cwd': input_data.get('cwd', ''),
            'transcript_path': input_data.get('transcript_path', ''),
            'hook_event_name': input_data.get('hook_event_name', 'Notification'),
            # Store the full raw input for debugging purposes
            '_raw_input': input_data
        }

        # Append new entry as JSONL
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')

        # Announce notification via TTS only if --notify flag is set
        # Skip TTS for the generic "Claude is waiting for your input" message
        if args.notify and input_data.get('message') != 'Claude is waiting for your input':
            announce_notification()

        # Always send notifications to Telegram (best-effort, non-blocking)
        try:
            send_telegram_notification(input_data)
        except Exception:
            pass

        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)

if __name__ == '__main__':
    main()