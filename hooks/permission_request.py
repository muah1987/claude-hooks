#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
PermissionRequest Hook - GOTCHA Framework Integration

Triggered when the user is shown a permission dialog. This hook can automatically
allow or deny permission requests based on configurable rules.

This hook implements GOTCHA framework principles by:
1. Logging all permission requests for auditing (transparency)
2. Supporting the Args layer with permission behavior settings
3. Implementing guardrails for security decisions

GOTCHA Framework Principles:
- Transparency in permission builds trust
- Guardrails prevent accidental data loss
- Args layer controls permission behavior

Input JSON includes:
- session_id: Unique session identifier
- transcript_path: Path to conversation JSON file
- cwd: Current working directory
- permission_mode: Current permission mode ("default", "plan", "acceptEdits", "dontAsk", "bypassPermissions")
- hook_event_name: "PermissionRequest"
- tool_name: Name of the tool requesting permission
- tool_input: The tool's input parameters (varies by tool)
- tool_use_id: Unique identifier for this tool use

Output JSON for decision control (per Claude Code Hooks Specification):
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow" | "deny",
      "updatedInput": {...},  // optional, only for "allow" - modifies tool input before execution
      "message": "...",       // optional, only for "deny" - explanation shown to Claude
      "interrupt": false      // optional, only for "deny" - if true, stops Claude after denying
    }
  }
}

Exit Code Behavior:
- Exit code 0: Success. JSON output in stdout is parsed for decision control.
- Exit code 2: Denies the permission, shows stderr to Claude.
- Other exit codes: Non-blocking error, permission flow continues normally.

Note: If no JSON output is provided (exit code 0), the normal permission dialog is shown to the user.

GOTCHA Layer: Guardrails
  - Guardrails: Manages permission decisions and enforces access control policies
  - Prevents unauthorized operations through configurable allow/deny rules

ATLAS Phase: Link (validation)
  - Validates that permission requirements are met before tool execution proceeds
  - Acts as the access control gate between intent and execution
"""
__version__ = "2026.04.20.4"

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Add hooks directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


# Read-only patterns that can be auto-allowed
READ_ONLY_PATTERNS = {
    "Read": lambda tool_input: True,  # All Read operations
    "Glob": lambda tool_input: True,  # All Glob operations
    "Grep": lambda tool_input: True,  # All Grep operations
    "Bash": lambda tool_input: is_safe_bash_command(tool_input.get("command", "")),
}

# Safe bash commands that can be auto-allowed
SAFE_BASH_COMMANDS = [
    r"^ls\b",
    r"^pwd\b",
    r"^echo\b",
    r"^cat\b(?!.*>)",  # cat without redirection
    r"^head\b",
    r"^tail\b",
    r"^wc\b",
    r"^which\b",
    r"^whereis\b",
    r"^type\b",
    r"^file\b",
    r"^stat\b",
    r"^git\s+(status|log|diff|show|branch|tag)\b",
    r"^git\s+remote\s+-v\b",
    r"^npm\s+(list|ls|outdated|view)\b",
    r"^pip\s+(list|show|freeze)\b",
    r"^uv\s+(pip\s+list|tree)\b",
    r"^python\s+--version\b",
    r"^node\s+--version\b",
    r"^npm\s+--version\b",
]


def is_safe_bash_command(command: str) -> bool:
    """
    Check if a bash command is safe (read-only).

    Args:
        command: The bash command to check

    Returns:
        True if the command is considered safe/read-only
    """
    if not command:
        return False

    # Normalize command
    normalized = command.strip()

    # Check against safe patterns
    for pattern in SAFE_BASH_COMMANDS:
        if re.search(pattern, normalized):
            return True

    return False


def should_auto_allow(tool_name: str, tool_input: dict) -> bool:
    """
    Determine if a tool call should be auto-allowed based on read-only patterns.

    Args:
        tool_name: Name of the tool being called
        tool_input: The tool's input parameters

    Returns:
        True if the tool call should be auto-allowed
    """
    if tool_name in READ_ONLY_PATTERNS:
        check_func = READ_ONLY_PATTERNS[tool_name]
        return check_func(tool_input)

    return False


def get_auto_allow_reason(tool_name: str, tool_input: dict) -> str:
    """
    Get a reason string for why a tool was auto-allowed.

    Args:
        tool_name: Name of the tool being called
        tool_input: The tool's input parameters

    Returns:
        Human-readable reason for auto-allowing
    """
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "unknown")
        return f"Read operation auto-allowed: {file_path}"
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "unknown")
        return f"Glob pattern search auto-allowed: {pattern}"
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "unknown")
        return f"Grep search auto-allowed: {pattern}"
    elif tool_name == "Bash":
        command = tool_input.get("command", "unknown")
        return f"Safe bash command auto-allowed: {command[:50]}..."

    return f"{tool_name} auto-allowed (read-only operation)"


def create_allow_response(
    updated_input: dict | None = None,
    updated_permissions: list | None = None,
    reason: str | None = None,
    suppress_output: bool = False
) -> dict:
    """
    Create a JSON response to allow a permission request.

    Per the Claude Code Hooks Specification, for "behavior": "allow" you can
    optionally pass in an "updatedInput" that modifies the tool's input
    parameters before the tool executes, and "updatedPermissions" to update
    permission rules.

    Args:
        updated_input: Optional modified tool input parameters. If provided,
                       these values will replace the original tool input.
        updated_permissions: Optional list of updated permission rules to apply
                             alongside the allow decision.
        reason: Optional reason for allowing (for internal logging only,
                not sent to Claude).
        suppress_output: If True, hides output from verbose/transcript mode.

    Returns:
        JSON-serializable response dict conforming to PermissionRequest spec.

    Example output:
        {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "allow",
                    "updatedInput": {"command": "npm run lint"},
                    "updatedPermissions": [...]
                }
            }
        }
    """
    decision: dict = {"behavior": "allow"}

    if updated_input is not None:
        decision["updatedInput"] = updated_input

    if updated_permissions is not None:
        decision["updatedPermissions"] = updated_permissions

    response: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision
        }
    }

    if suppress_output:
        response["suppressOutput"] = True

    return response


def create_deny_response(
    message: str,
    interrupt: bool = False,
    suppress_output: bool = False
) -> dict:
    """
    Create a JSON response to deny a permission request.

    Per the Claude Code Hooks Specification, for "behavior": "deny" you can
    optionally pass in a "message" string that tells the model why the
    permission was denied, and a boolean "interrupt" which will stop Claude.

    Args:
        message: Message explaining why permission was denied. This is shown
                 to Claude so it can understand why and adjust its approach.
        interrupt: If True, stops Claude completely after denying. If False
                   (default), Claude continues and may try alternative approaches.
        suppress_output: If True, hides output from verbose/transcript mode.

    Returns:
        JSON-serializable response dict conforming to PermissionRequest spec.

    Example output:
        {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                    "message": "Operation blocked by security policy",
                    "interrupt": false
                }
            }
        }
    """
    response: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": "deny",
                "message": message,
                "interrupt": interrupt
            }
        }
    }

    if suppress_output:
        response["suppressOutput"] = True

    return response


def log_permission_request(input_data: dict, log_dir: Path):
    """
    Log the permission request to a JSON file.

    Args:
        input_data: The input data from the hook
        log_dir: Path to the logs directory
    """
    log_path = log_dir / "permission_request.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(input_data, ensure_ascii=False) + "\n")


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="PermissionRequest hook for Claude Code"
        )
        parser.add_argument(
            "--auto-allow",
            action="store_true",
            help="Auto-allow read-only operations (Read, Glob, Grep, safe Bash commands)"
        )
        parser.add_argument(
            "--log-only",
            action="store_true",
            help="Only log permission requests, do not make decisions"
        )
        parser.add_argument(
            "--cognitive",
            action="store_true",
            help="Enable Cognitive Control Engine for pattern learning and risk scoring"
        )
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract fields
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        hook_event_name = input_data.get("hook_event_name", "")
        permission_suggestions = input_data.get("permission_suggestions", [])

        # Verify this is a PermissionRequest event
        if hook_event_name != "PermissionRequest":
            # Not a PermissionRequest event, exit gracefully
            sys.exit(0)

        # Ensure log directory exists
        log_dir = Path.home() / ".claude" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Log the permission request (includes permission_suggestions if present)
        log_permission_request(input_data, log_dir)

        # Log permission suggestions to stderr for debugging if present
        if permission_suggestions:
            print(f"[PermissionRequest] {len(permission_suggestions)} permission suggestion(s) available",
                  file=sys.stderr)

        # If log-only mode, exit without making a decision
        if args.log_only:
            sys.exit(0)

        # Handle --cognitive mode: pattern learning + cognitive scoring
        if args.cognitive and os.getenv('CCE_ENABLED', 'true').lower() != 'false':
            try:
                from utils.cognitive import cognitive_decide  # noqa: E402
                from utils.cognitive.pattern_learner import check_pattern  # noqa: E402

                # Quick path: check learned patterns first
                pattern = check_pattern(tool_name, tool_input)
                if pattern and pattern.get("auto_approve"):
                    response = create_allow_response(
                        reason=(
                            f"CCE: Auto-approved from learned pattern "
                            f"(confidence={pattern.get('confidence', 0):.2f})"
                        )
                    )
                    print(json.dumps(response))
                    sys.exit(0)

                # Full cognitive analysis
                decision = cognitive_decide(tool_name, tool_input, input_data)

                if decision.action == "allow":
                    response = create_allow_response(
                        reason=f"CCE: {decision.reasoning}"
                    )
                    print(json.dumps(response))
                    sys.exit(0)
                elif decision.action == "deny":
                    response = create_deny_response(
                        message=f"CCE: {decision.reasoning} (risk={decision.risk_score})",
                        interrupt=decision.guardian_veto,
                    )
                    print(json.dumps(response))
                    sys.exit(0)
                # "ask" falls through to normal permission dialog
            except ImportError:
                pass
            except Exception:
                pass

        # Handle auto-allow for read-only operations
        if args.auto_allow and should_auto_allow(tool_name, tool_input):
            reason = get_auto_allow_reason(tool_name, tool_input)
            response = create_allow_response(reason=reason)
            print(json.dumps(response))
            sys.exit(0)

        # Default: exit without making a decision (let user decide)
        sys.exit(0)

    except json.JSONDecodeError:
        # Gracefully handle JSON decode errors
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == "__main__":
    main()
