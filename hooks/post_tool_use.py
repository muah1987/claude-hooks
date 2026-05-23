#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
PostToolUse Hook - GOTCHA Framework Integration

This hook runs after a tool completes successfully. It implements GOTCHA
framework principles by:

1. Logging successful tool executions for transparency
2. Supporting the memory protocol for session tracking
3. Recording tool outputs for debugging and continuous improvement
4. Providing feedback to Claude via additionalContext
5. Optionally blocking tool responses with decision: "block"

GOTCHA Framework Principles:
- Tools are deterministic - their execution should be logged
- Logs help identify patterns and improve the system over time
- Transparency in tool usage builds trust

Hook Output JSON specification:
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "decision": "proceed" | "block",
    "reason": "...",            // required if decision is "block"
    "additionalContext": "..."  // optional feedback to Claude
  }
}

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Tools + Context
  - Tools: Processes and logs deterministic tool execution results
  - Context: Updates session context with tool output data for downstream decisions

ATLAS Phase: Assemble
  - Integrates tool outputs into the ongoing workflow
  - Assembles results from executed tools into coherent context for Claude
"""
__version__ = "2026.04.20.5"

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _resolve_log_dir(input_data: dict) -> Path:
    """Resolve a stable log directory.

    Prefer CLAUDE_PROJECT_DIR env var, then the hook's 'cwd' field, and
    finally ~/.claude/logs — never Path.cwd(), which pollutes whichever
    directory Claude Code happens to be running in.
    """
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if project_dir and Path(project_dir).is_dir():
        return Path(project_dir) / 'logs'
    cwd_val = (input_data.get('cwd') or '').strip()
    if cwd_val and Path(cwd_val).is_dir():
        return Path(cwd_val) / 'logs'
    return Path.home() / '.claude' / 'logs'

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def create_proceed_response(additional_context: str | None = None) -> dict:
    """
    Create a JSON response to proceed with the tool result.

    Args:
        additional_context: Optional feedback/context to provide to Claude

    Returns:
        JSON-serializable response dict
    """
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "decision": "proceed"
        }
    }

    if additional_context:
        response["hookSpecificOutput"]["additionalContext"] = additional_context

    return response


def create_block_response(reason: str, additional_context: str | None = None) -> dict:
    """
    Create a JSON response to block the tool result from reaching Claude.

    Args:
        reason: Required explanation for why the result is blocked
        additional_context: Optional additional feedback to Claude

    Returns:
        JSON-serializable response dict
    """
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "decision": "block",
            "reason": reason
        }
    }

    if additional_context:
        response["hookSpecificOutput"]["additionalContext"] = additional_context

    return response


def should_block_on_error(tool_response: dict) -> tuple[bool, str]:
    """
    Check if the tool response contains an error that should block the result.

    Args:
        tool_response: The tool response object

    Returns:
        Tuple of (should_block, reason)
    """
    # Check for error indicators in the response
    if isinstance(tool_response, dict):
        # Check for explicit error field
        if tool_response.get("error"):
            error_msg = tool_response.get("error", "Unknown error")
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            return True, f"Tool execution returned error: {error_msg}"

        # Check for error status
        status = tool_response.get("status", "")
        if status in ("error", "failed", "failure"):
            return True, f"Tool execution failed with status: {status}"

    return False, ""


def log_tool_execution(log_entry: dict, log_dir: Path):
    """
    Log the tool execution to a JSON file.

    Args:
        log_entry: The structured log entry
        log_dir: Path to the logs directory
    """
    log_path = log_dir / "post_tool_use.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def truncate_response(response: Any, max_length: int = 1000) -> str:
    """
    Truncate a response for logging purposes.

    Args:
        response: The response to truncate
        max_length: Maximum length of the string representation

    Returns:
        Truncated string representation
    """
    response_str = str(response)
    if len(response_str) > max_length:
        return response_str[:max_length] + "... [truncated]"
    return response_str


def _run_ruff(file_path: str) -> tuple[bool, str]:
    """Run ruff on file_path. Returns (clean, status_message)."""
    try:
        r = subprocess.run(
            ["ruff", "check", "--output-format=concise", file_path],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, "✓ ruff clean"
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        n = len(lines)
        return False, f"⚠ ruff: {n} issue{'s' if n != 1 else ''}"
    except FileNotFoundError:
        return True, ""
    except Exception:
        return True, ""


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="PostToolUse hook for Claude Code"
        )
        parser.add_argument(
            "--log-only",
            action="store_true",
            help="Only log; skip linting and statusMessage output"
        )
        parser.add_argument(
            "--feedback",
            type=str,
            default="",
            help="Custom feedback message to provide to Claude via additionalContext"
        )
        parser.add_argument(
            "--block-on-error",
            action="store_true",
            help="Block tool results that contain error indicators"
        )
        parser.add_argument(
            "--log-response",
            action="store_true",
            default=True,
            help="Log the tool response data (default: True)"
        )
        parser.add_argument(
            "--max-response-log-size",
            type=int,
            default=1000,
            help="Maximum characters to log from tool response (default: 1000)"
        )
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract key fields
        tool_name = input_data.get("tool_name", "unknown")
        tool_use_id = input_data.get("tool_use_id", "unknown")
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", {})
        session_id = input_data.get("session_id", "")
        cwd = input_data.get("cwd", "")
        permission_mode = input_data.get("permission_mode", "")
        transcript_path = input_data.get("transcript_path", "")
        hook_event_name = input_data.get("hook_event_name", "PostToolUse")

        # Verify this is a PostToolUse event
        if hook_event_name != "PostToolUse":
            # Not a PostToolUse event, exit gracefully
            sys.exit(0)

        # Add timestamp
        timestamp = datetime.now().isoformat()

        # Create structured log entry
        log_entry = {
            "timestamp": timestamp,
            "session_id": session_id,
            "hook_event_name": hook_event_name,
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "tool_input": tool_input,
            "permission_mode": permission_mode,
            "cwd": cwd,
            "transcript_path": transcript_path,
        }

        # Detect gh CLI commands in Bash tool usage
        if tool_name == "Bash" and isinstance(tool_input, dict):
            command = tool_input.get("command", "")
            if isinstance(command, str) and command.lstrip().startswith("gh "):
                log_entry["gh_command"] = command.strip()

        # Log tool response if enabled
        if args.log_response:
            log_entry["tool_response_summary"] = truncate_response(
                tool_response, args.max_response_log_size
            )
            # Also store response type for analysis
            log_entry["tool_response_type"] = type(tool_response).__name__

        # Ensure log directory exists — use the helper to avoid polluting
        # whatever project directory Claude Code happens to be running in.
        log_dir = _resolve_log_dir(input_data)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Log the tool execution
        log_tool_execution(log_entry, log_dir)

        # Check for blocking conditions
        if args.block_on_error:
            should_block, reason = should_block_on_error(tool_response)
            if should_block:
                response = create_block_response(
                    reason=reason,
                    additional_context=f"Tool '{tool_name}' execution failed. Check logs for details."
                )
                print(json.dumps(response))
                sys.exit(0)

        # Build additional context if feedback is provided
        additional_context = None
        if args.feedback:
            additional_context = args.feedback

        # Check if there's useful context to add based on the tool
        if tool_name == "Bash" and permission_mode:
            context_parts = []
            if args.feedback:
                context_parts.append(args.feedback)
            context_parts.append(f"Executed in permission mode: {permission_mode}")
            additional_context = " | ".join(context_parts)

        # If we have additional context, return a response with it
        if additional_context:
            response = create_proceed_response(additional_context=additional_context)
            print(json.dumps(response))

        # Run ruff on edited Python files (only for the .py PostToolUse variant)
        if not getattr(args, 'log_only', False):
            edited_file = ""
            if isinstance(tool_input, dict):
                edited_file = str(tool_input.get("file_path") or "")
            if edited_file.endswith(".py") and Path(edited_file).exists():
                _clean, status_msg = _run_ruff(edited_file)
                if status_msg:
                    print(json.dumps({
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "statusMessage": status_msg,
                            "decision": "proceed",
                        }
                    }))
                    sys.exit(0)

        # Exit successfully
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Exit cleanly on any other error
        sys.exit(0)


if __name__ == "__main__":
    main()
