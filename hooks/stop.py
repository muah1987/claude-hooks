#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Stop Hook - GOTCHA Framework Integration

This hook runs when Claude Code finishes responding. It implements GOTCHA
framework principles by providing completion feedback to the user.

Claude Code Hooks Specification Support:
- Supports command-based hooks (type: "command") - this script
- Supports prompt-based hooks (type: "prompt") when configured in settings.json
  Example settings.json for prompt-based hook:
  {
    "hooks": {
      "Stop": [{
        "type": "prompt",
        "prompt": "Before stopping, verify all tasks are complete."
      }]
    }
  }

Hook Input Fields (received via stdin JSON):
- session_id: The current session identifier
- transcript_path: Path to the conversation transcript file
- stop_hook_active: Boolean indicating if a stop hook is currently running
  (CRITICAL: Must check this to prevent infinite loops when using --prevent-stop)

Hook Output (JSON to stdout):
- {} or exit 0: Allow Claude to stop normally
- {"decision": "block", "reason": "..."}: Prevent Claude from stopping
  and show the reason to Claude (use --prevent-stop flag to enable)

GOTCHA Framework Principles:
- Orchestration layer: Confirm task completion
- Transparency: Announce when work is complete
- Context: Provide audible feedback if configured
- Guardrails: Prevent infinite loops via stop_hook_active check

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Orchestration + Transparency
  - Orchestration: Manages the final state of Claude's response cycle and stop decisions
  - Transparency: Announces completion and provides audible feedback to the user

ATLAS Phase: Stress-test (final state)
  - Verifies the final state of the system before allowing Claude to stop
  - Stress-tests completion by optionally blocking premature stops via decision control
"""
__version__ = "2026.04.20.5"

import argparse
import json
import os
import sys
import random
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def get_completion_messages():
    """Return list of friendly completion messages."""
    return [
        "Work complete!",
        "All done!",
        "Task finished!",
        "Job complete!",
        "Ready for next task!"
    ]


def get_tts_script_path():
    """
    Determine which TTS script to use based on available API keys.
    Priority order: ElevenLabs > OpenAI > pyttsx3
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


def get_llm_completion_message():
    """
    Generate completion message using available LLM services.
    Priority order: OpenAI > Anthropic > Ollama > fallback to random message

    Returns:
        str: Generated or fallback completion message
    """
    # Get current script directory and construct utils/llm path
    script_dir = Path(__file__).parent
    llm_dir = script_dir / "utils" / "llm"

    # Try OpenAI first (highest priority)
    if os.getenv('OPENAI_API_KEY'):
        oai_script = llm_dir / "oai.py"
        if oai_script.exists():
            try:
                result = subprocess.run([
                    "uv", "run", str(oai_script), "--completion"
                ],
                capture_output=True,
                text=True,
                timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Try Anthropic second
    if os.getenv('ANTHROPIC_API_KEY'):
        anth_script = llm_dir / "anth.py"
        if anth_script.exists():
            try:
                result = subprocess.run([
                    "uv", "run", str(anth_script), "--completion"
                ],
                capture_output=True,
                text=True,
                timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Try Ollama third (local LLM)
    ollama_script = llm_dir / "ollama.py"
    if ollama_script.exists():
        try:
            result = subprocess.run([
                "uv", "run", str(ollama_script), "--completion"
            ],
            capture_output=True,
            text=True,
            timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

    # Fallback to random predefined message
    messages = get_completion_messages()
    return random.choice(messages)


def announce_completion():
    """Announce completion using the best available TTS service."""
    try:
        tts_script = get_tts_script_path()
        if not tts_script:
            return  # No TTS scripts available

        # Get completion message (LLM-generated or fallback)
        completion_message = get_llm_completion_message()

        # Call the TTS script with the completion message
        subprocess.run([
            "uv", "run", tts_script, completion_message
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


def _check_git_state(cwd: str) -> dict | None:
    """
    Check git state of the given working directory.

    Returns a dict with keys: branch, uncommitted, ahead, behind.
    Returns None if not in a git repository or on any error.

    All git operations use a 3-second timeout and are wrapped in try/except
    so that git issues never block the hook.
    """
    try:
        # Bail out early if this is not a git repository
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=3, cwd=cwd
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    except Exception:
        return None

    state: dict = {
        "branch": None,
        "uncommitted": 0,
        "ahead": 0,
        "behind": 0,
    }

    # Current branch
    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3, cwd=cwd
        )
        if branch_result.returncode == 0:
            state["branch"] = branch_result.stdout.strip() or None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    except Exception:
        pass

    # Uncommitted count
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=3, cwd=cwd
        )
        if status_result.returncode == 0:
            raw = status_result.stdout.strip()
            state["uncommitted"] = len(raw.split("\n")) if raw else 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    except Exception:
        pass

    # Ahead / behind vs upstream
    try:
        ab_result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"],
            capture_output=True, text=True, timeout=3, cwd=cwd
        )
        if ab_result.returncode == 0:
            parts = ab_result.stdout.strip().split()
            if len(parts) == 2:
                try:
                    state["behind"] = int(parts[0])
                    state["ahead"] = int(parts[1])
                except (ValueError, TypeError):
                    pass
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    except Exception:
        pass

    return state


def _build_result_summary(decision: str, session_id: str = "", git_state: dict | None = None) -> str:
    """
    Build a `## RESULT` summary block describing the Stop hook outcome.

    Provides a graceful fallback output contract so downstream tooling (and
    humans tailing logs) can parse what happened without reading the whole
    JSON payload.
    """
    try:
        lines = [
            "## RESULT",
            f"- Status: {'blocked' if decision == 'block' else 'completed'}",
            f"- Output: Stop hook {'blocked Claude from stopping' if decision == 'block' else 'allowed Claude to stop'}",
        ]
        if session_id:
            lines.append(f"- Session: {session_id[:16]}")
        if git_state and git_state.get("branch"):
            branch = git_state.get("branch") or "?"
            uncommitted = git_state.get("uncommitted", 0) or 0
            ahead = git_state.get("ahead", 0) or 0
            lines.append(
                f"- Git: branch={branch}, uncommitted={uncommitted}, ahead={ahead}"
            )
        lines.append("- Next: session end or user follow-up")
        return "\n".join(lines)
    except Exception:
        return "## RESULT\n- Status: completed\n- Next: none"


def output_block_decision(reason: str, session_id: str = "", git_state: dict | None = None) -> None:
    """
    Output a block decision to prevent Claude from stopping.

    Args:
        reason: The reason to show Claude for why stopping was blocked
        session_id: Optional session id for the RESULT summary
        git_state: Optional git state dict for the RESULT summary
    """
    print(json.dumps({
        "decision": "block",
        "reason": reason,
    }))



def output_allow_decision(session_id: str = "", git_state: dict | None = None) -> None:
    """Output an allow decision to let Claude stop normally."""
    print(json.dumps({}))


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="Stop hook for Claude Code - runs when Claude finishes responding"
        )
        parser.add_argument('--chat', action='store_true',
                          help='Copy transcript to chat.json')
        parser.add_argument('--notify', action='store_true',
                          help='Enable TTS completion announcement')
        parser.add_argument('--prevent-stop', action='store_true',
                          help='Enable decision control to potentially block Claude from stopping')
        parser.add_argument('--prevent-stop-reason', type=str, default="",
                          help='Custom reason to show when blocking stop (requires --prevent-stop)')
        parser.add_argument('--gh-summary', action='store_true',
                          help='Include GitHub context (branch, PR status) in stop log entry')
        parser.add_argument('--trigger', action='store_true',
                          help='Run trigger engine to check for automated next actions')
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract and log all input fields
        session_id = input_data.get("session_id", "")
        transcript_path = input_data.get("transcript_path", "")
        stop_hook_active = input_data.get("stop_hook_active", False)

        # Ensure log directory exists — use ~/.claude/logs/ so we never
        # pollute whatever project directory Claude Code is running in.
        log_dir = Path.home() / ".claude" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "stop.jsonl"

        # Build log entry with all fields logged
        hook_event_name = input_data.get("hook_event_name", "Stop")
        log_entry = {
            "hook_event_name": hook_event_name,
            "session_id": session_id,
            "transcript_path": transcript_path,
            "stop_hook_active": stop_hook_active,
            "prevent_stop_enabled": args.prevent_stop,
            "raw_input": input_data
        }

        # Always capture git state (informational; never blocks the hook)
        try:
            git_state = _check_git_state(input_data.get("cwd") or os.getcwd())
        except Exception:
            git_state = None
        log_entry["git_state"] = git_state

        if git_state:
            try:
                branch = git_state.get("branch") or "?"
                uncommitted = git_state.get("uncommitted", 0) or 0
                ahead = git_state.get("ahead", 0) or 0
                if uncommitted > 0:
                    print(
                        f"[Stop] \u26a0 {uncommitted} uncommitted files on branch '{branch}'",
                        file=sys.stderr,
                    )
                if ahead > 0:
                    print(
                        f"[Stop] \u26a0 {ahead} unpushed commits on branch '{branch}'",
                        file=sys.stderr,
                    )
            except Exception:
                pass

        # Add GitHub context if --gh-summary is set
        if args.gh_summary:
            try:
                sys.path.insert(0, str(Path(input_data.get("cwd") or os.getcwd()) / ".github" / "hooks"))
                from gh_detect import is_gh_installed, get_current_branch, run_gh_command

                if is_gh_installed():
                    gh_context = {}
                    branch = get_current_branch()
                    if branch:
                        gh_context["branch"] = branch

                    # Check for uncommitted changes
                    try:
                        git_result = subprocess.run(
                            ["git", "status", "--porcelain"],
                            capture_output=True, text=True, timeout=5
                        )
                        if git_result.returncode == 0:
                            changes = git_result.stdout.strip().split('\n') if git_result.stdout.strip() else []
                            gh_context["uncommitted_changes"] = len(changes)
                    except Exception:
                        pass

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

                    if gh_context:
                        log_entry["gh_context"] = gh_context
            except ImportError:
                pass  # gh_detect not available
            except Exception:
                pass  # Any error, skip gracefully

        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')

        # Handle --chat switch
        if args.chat and transcript_path:
            if os.path.exists(transcript_path):
                # Read .jsonl file and convert to JSON array
                chat_data = []
                try:
                    with open(transcript_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    chat_data.append(json.loads(line))
                                except json.JSONDecodeError:
                                    pass  # Skip invalid lines

                    # Write to logs/chat.json
                    chat_file = os.path.join(log_dir, 'chat.json')
                    with open(chat_file, 'w') as f:
                        json.dump(chat_data, f, indent=2)
                except Exception:
                    pass  # Fail silently

        # Announce completion via TTS (only if --notify flag is set)
        if args.notify:
            announce_completion()

        # Handle --trigger: Run trigger engine for completion verification
        if args.trigger and os.getenv('TRIGGER_ENABLED', 'true').lower() != 'false':
            try:
                trigger_script = Path(__file__).parent / "utils" / "trigger.py"
                if trigger_script.exists():
                    trigger_input = json.dumps({
                        "hook_event_name": "Stop",
                        "session_id": session_id,
                        "stop_hook_active": stop_hook_active
                    })
                    result = subprocess.run(
                        ["uv", "run", str(trigger_script), "--event", "Stop"],
                        input=trigger_input,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        try:
                            trigger_results = json.loads(result.stdout.strip())
                            if trigger_results:
                                log_entry["trigger_results"] = trigger_results
                        except (json.JSONDecodeError, ValueError):
                            pass
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                pass
            except Exception:
                pass

        # Handle --prevent-stop decision control
        if args.prevent_stop:
            # CRITICAL: Check stop_hook_active to prevent infinite loops
            # If stop_hook_active is True, a stop hook is already running,
            # so we must allow this stop to proceed to break the loop
            if stop_hook_active:
                # Allow stop to prevent infinite loop
                output_allow_decision(session_id=session_id, git_state=git_state)
                sys.exit(0)

            # Determine if we should block the stop
            # By default, block when --prevent-stop is enabled
            # Users can customize the reason via --prevent-stop-reason
            reason = args.prevent_stop_reason or "Stop hook is preventing Claude from stopping. Please confirm task completion or use /stop to force stop."
            output_block_decision(reason, session_id=session_id, git_state=git_state)
            sys.exit(0)

        # Default: allow Claude to stop normally
        output_allow_decision(session_id=session_id, git_state=git_state)
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully - allow stop
        output_allow_decision()
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully - allow stop
        output_allow_decision()
        sys.exit(0)


if __name__ == "__main__":
    main()
