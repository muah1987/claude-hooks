#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
TaskCompleted Hook - GOTCHA Framework Integration

This hook runs when a task is being marked as completed. It implements GOTCHA
framework principles by logging task completion events and optionally enforcing
code quality checks before allowing task completion.

Claude Code Hooks Specification - TaskCompleted Input Fields:
- session_id: Unique identifier for the current session
- transcript_path: Path to the conversation transcript file
- cwd: Current working directory
- permission_mode: Permission level used during the session
- hook_event_name: "TaskCompleted"
- task_id: Unique identifier for the task
- task_subject: Short subject/title of the task
- task_description: Full description of the task
- teammate_name: Name of the teammate completing the task
- team_name: Name of the team the teammate belongs to

Decision Control (Exit Codes Only):
- Exit code 0: Allow the task to be marked as completed
- Exit code 2: Block completion (stderr message fed back as feedback)

Command Line Arguments:
- --log-only: Just log the event, no enforcement (always exits 0)
- --enforce: Check for Python syntax errors in .claude/hooks/ and block if found (exit 2)
- --trigger: Run trigger engine to check for automated next actions
- --cognitive: Enable Cognitive Control Engine quality assessment

Storage Locations:
- Event log: ~/.claude/logs/task_completed.jsonl  (JSON Lines — one event per line)
- Agent registry: ~/.claude/data/agent_registry.jsonl  (event: "task_completed")

GOTCHA Framework Principles:
- Transparency: Log all task completion events for audit trail
- Continuous improvement: Track task completion patterns
- Guardrails: Ensure code quality before marking tasks done
- Reliability: Push validation into deterministic checks

GOTCHA Layer: Goals + Improvement
  - Goals: Validates task completion against the original goal definitions
  - Improvement: Feeds completion data into the continuous improvement loop

ATLAS Phase: Stress-test (completion validation)
  - Validates that completed tasks meet quality standards before acceptance
  - Stress-tests deliverables through syntax checks and enforcement gates
"""
__version__ = "2026.04.20.4"

import argparse
import json
import os
import py_compile
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Optional .env loading — imported dynamically so type checkers (e.g. `ty`)
# don't fail when python-dotenv isn't installed in their resolution paths.
try:
    import importlib
    _dotenv = importlib.import_module("dotenv")
    _dotenv.load_dotenv()
except Exception:
    pass  # dotenv is optional


# Absolute paths — never depend on cwd.
CLAUDE_HOME = Path.home() / ".claude"
LOG_FILE = CLAUDE_HOME / "logs" / "task_completed.jsonl"
REGISTRY_FILE = CLAUDE_HOME / "data" / "agent_registry.jsonl"


def check_hook_syntax_errors() -> list[str]:
    """
    Check all Python files in .claude/hooks/ for syntax errors using py_compile.

    Returns:
        List of error messages for files with syntax errors. Empty list if all files pass.
    """
    errors = []
    hooks_dir = Path.home() / ".claude" / "hooks"

    if not hooks_dir.exists():
        return errors

    for py_file in hooks_dir.glob("*.py"):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{py_file.name}: {e}")

    return errors


def _append_jsonl(path: Path, entry: dict) -> None:
    """Append a single JSON object as one line to a .jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_event(input_data: dict, action: str) -> None:
    """
    Append a task-completed event to ~/.claude/logs/task_completed.jsonl.

    Uses JSON Lines so concurrent writes from multiple agents do not
    corrupt the file the way a single JSON array would.
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "task_id": input_data.get("task_id", "unknown"),
        "task_subject": input_data.get("task_subject", ""),
        "task_description": input_data.get("task_description", ""),
        "teammate_name": input_data.get("teammate_name", "unknown"),
        "team_name": input_data.get("team_name", "unknown"),
        "session_id": input_data.get("session_id", "unknown"),
        "cwd": input_data.get("cwd", ""),
        "permission_mode": input_data.get("permission_mode", "unknown"),
        "action": action,
    }

    try:
        _append_jsonl(LOG_FILE, entry)
    except Exception:
        # Never let logging errors break the hook.
        pass


def register_agent_event(input_data: dict, action: str) -> None:
    """
    Write a "task_completed" event to the agent registry.

    The agent registry (~/.claude/data/agent_registry.jsonl) tracks
    agent lifecycle events (start / stop / task_completed) and is the
    source of truth for `agents.py` inspection commands.
    """
    task_id = input_data.get("task_id", "unknown")
    teammate = input_data.get("teammate_name", "unknown")
    session_id = input_data.get("session_id", "unknown")

    # Agent identity: prefer task_id, fall back to session_id so the
    # entry is still correlatable.
    agent_id = task_id if task_id != "unknown" else session_id

    summary_parts = []
    subject = input_data.get("task_subject", "")
    if subject:
        summary_parts.append(subject)
    if action and action != "allowed":
        summary_parts.append(f"[{action}]")
    result_summary = " ".join(summary_parts) or "task completed"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "task_completed",
        "agent_id": agent_id,
        "agent_type": teammate,
        "team_name": input_data.get("team_name", "unknown"),
        "session_id": session_id,
        "task_id": task_id,
        "result_summary": result_summary,
        "action": action,
    }

    try:
        _append_jsonl(REGISTRY_FILE, entry)
    except Exception:
        # Registry write failures must not break task completion.
        pass


def main() -> None:
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description="TaskCompleted hook - logs and optionally enforces quality checks before task completion"
        )
        parser.add_argument('--log-only', action='store_true',
                            help='Just log the completion event, no enforcement (always exits 0)')
        parser.add_argument('--enforce', action='store_true',
                            help='Check for Python syntax errors in hooks and block completion if found (exit 2)')
        parser.add_argument('--trigger', action='store_true',
                            help='Run trigger engine to check for automated next actions')
        parser.add_argument('--cognitive', action='store_true',
                            help='Enable Cognitive Control Engine quality assessment')
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract key fields
        task_id = input_data.get("task_id", "unknown")
        task_subject = input_data.get("task_subject", "")
        teammate_name = input_data.get("teammate_name", "unknown")
        team_name = input_data.get("team_name", "unknown")
        session_id = input_data.get("session_id", "unknown")

        # Log to stderr for visibility
        print(f"[TaskCompleted] task={task_id} subject=\"{task_subject}\" "
              f"teammate={teammate_name} team={team_name} "
              f"session={session_id[:8] if len(session_id) > 8 else session_id}...",
              file=sys.stderr)

        # --log-only mode: just log and allow
        if args.log_only:
            log_event(input_data, action="logged")
            register_agent_event(input_data, action="logged")

            # Handle --trigger: Run trigger engine for workflow progression
            if args.trigger and os.getenv('TRIGGER_ENABLED', 'true').lower() != 'false':
                try:
                    trigger_script = Path(__file__).parent / "utils" / "trigger.py"
                    if trigger_script.exists():
                        trigger_input = json.dumps({
                            "hook_event_name": "TaskCompleted",
                            "task_id": input_data.get("task_id", ""),
                            "task_name": input_data.get("task_name", ""),
                            "task_result": input_data.get("task_result", ""),
                            "session_id": input_data.get("session_id", "")
                        })
                        result = subprocess.run(
                            ["uv", "run", str(trigger_script), "--event", "TaskCompleted"],
                            input=trigger_input,
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            try:
                                trigger_results = json.loads(result.stdout.strip())
                                if trigger_results:
                                    input_data["trigger_results"] = trigger_results
                            except (json.JSONDecodeError, ValueError):
                                pass
                except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                    pass
                except Exception:
                    pass

            # Handle --cognitive: quality assessment before completion.
            # The cognitive module is imported dynamically so type checkers
            # (e.g. `ty`) do not attempt to resolve an optional sibling package.
            if args.cognitive and os.getenv('CCE_ENABLED', 'true').lower() != 'false':
                try:
                    import importlib
                    sys.path.insert(0, str(Path(__file__).parent))
                    _cog = importlib.import_module("utils.cognitive")
                    cognitive_assess = _cog.cognitive_assess

                    quality = cognitive_assess(
                        task_description=input_data.get("task_description", ""),
                        files_changed=[],  # Will check hooks dir by default
                    )

                    if quality.verdict == "FAIL":
                        print(
                            f"CCE Quality FAIL (score={quality.overall}/100): "
                            f"{'; '.join(quality.recommendations)}",
                            file=sys.stderr,
                        )
                        sys.exit(2)
                    elif quality.verdict == "NEEDS_WORK":
                        print(
                            f"[CCE Quality] Score: {quality.overall}/100 - NEEDS_WORK. "
                            f"Consider deploying a validator.",
                            file=sys.stderr,
                        )
                except Exception:
                    pass

            sys.exit(0)

        # --enforce mode: check for Python syntax errors in hook scripts
        if args.enforce:
            syntax_errors = check_hook_syntax_errors()
            if syntax_errors:
                log_event(input_data, action="blocked_syntax_errors")
                register_agent_event(input_data, action="blocked_syntax_errors")
                error_details = "; ".join(syntax_errors)
                print(f"Python syntax errors found in .claude/hooks/: {error_details}",
                      file=sys.stderr)
                sys.exit(2)
            else:
                log_event(input_data, action="allowed")
                register_agent_event(input_data, action="allowed")
                sys.exit(0)

        # Default: log and allow
        log_event(input_data, action="allowed")
        register_agent_event(input_data, action="allowed")
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == "__main__":
    main()
