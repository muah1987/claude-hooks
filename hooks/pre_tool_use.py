#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""
PreToolUse Hook - GOTCHA Framework Integration

This hook validates tool use before execution, ensuring alignment with the
GOTCHA Framework principles:

1. Pushes reliability into deterministic code (tools)
2. Blocks dangerous operations that could cause data loss
3. Logs all tool usage for transparency and debugging
4. Enforces guardrails learned from past mistakes

Guardrails enforced:
- Blocks .env file access (sensitive data protection)
- Blocks dangerous rm -rf commands (prevents data loss)

Hook Output Modes (Claude Code Hooks Specification):
- Exit code 0: Success (JSON output processed for decision control)
- Exit code 2: Blocking error (stderr shown to Claude, tool blocked)
- Other exit codes: Non-blocking error (stderr shown in verbose mode)

JSON Output Decision Control:
- hookSpecificOutput.permissionDecision: "allow" | "deny" | "ask"
- hookSpecificOutput.permissionDecisionReason: Explanation for decision
- hookSpecificOutput.updatedInput: Modify tool inputs before execution
- hookSpecificOutput.additionalContext: Add context before tool executes

DEPRECATED: Top-level `decision` and `reason` fields are deprecated for PreToolUse hooks.
Use `hookSpecificOutput.permissionDecision` and `hookSpecificOutput.permissionDecisionReason`
instead. The deprecated values "approve" and "block" map to "allow" and "deny" respectively.

Command Line Arguments:
- --auto-approve: Output JSON to auto-approve safe operations
- --add-context: Add additional context to tool execution

See CLAUDE.md for full GOTCHA framework documentation.
See ai_docs/claude_code_hooks_docs.md for Claude Code hooks specification.

GOTCHA Layer: Orchestration + Guardrails
  - Orchestration: Coordinates pre-execution validation decisions for tool calls
  - Guardrails: Enforces security rules (env file protection, dangerous command blocking)

ATLAS Phase: Link (validation)
  - Validates connections and permissions before tools execute
  - Ensures all safety checks pass before proceeding to the Assemble phase
"""
__version__ = "2026.04.20.6"

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def is_dangerous_rm_command(command: str) -> bool:
    """
    Comprehensive detection of dangerous rm commands.
    Matches various forms of rm -rf and similar destructive patterns.
    """
    # Normalize command by removing extra spaces and converting to lowercase
    normalized = ' '.join(command.lower().split())

    # Pattern 1: Standard rm -rf variations
    patterns = [
        r'\brm\s+.*-[a-z]*r[a-z]*f',  # rm -rf, rm -fr, rm -Rf, etc.
        r'\brm\s+.*-[a-z]*f[a-z]*r',  # rm -fr variations
        r'\brm\s+--recursive\s+--force',  # rm --recursive --force
        r'\brm\s+--force\s+--recursive',  # rm --force --recursive
        r'\brm\s+-r\s+.*-f',  # rm -r ... -f
        r'\brm\s+-f\s+.*-r',  # rm -f ... -r
    ]

    # Check for dangerous patterns
    for pattern in patterns:
        if re.search(pattern, normalized):
            return True

    # Pattern 2: Check for rm with recursive flag targeting truly dangerous paths
    # (Only block when targeting root, home, or bare wildcards — not project subdirs)
    if re.search(r'\brm\s+.*-[a-z]*r', normalized):  # If rm has recursive flag
        truly_dangerous = [
            r'\brm\s+.*-[a-z]*r[a-z]*\s+/\s',          # rm -r / (root)
            r'\brm\s+.*-[a-z]*r[a-z]*\s+/\*',           # rm -r /*
            r'\brm\s+.*-[a-z]*r[a-z]*\s+~[/\s]',        # rm -r ~/
            r'\brm\s+.*-[a-z]*r[a-z]*\s+\$HOME',        # rm -r $HOME
            r'\brm\s+.*-[a-z]*r[a-z]*\s+\.\s*$',        # rm -r . (current dir only, end of cmd)
            r'\brm\s+.*-[a-z]*r[a-z]*\s+\.\.\b',        # rm -r ..
        ]
        for pattern in truly_dangerous:
            if re.search(pattern, normalized):
                return True

    return False


def is_env_file_access(tool_name: str, tool_input: Dict[str, Any]) -> bool:
    """
    Check if any tool is trying to directly read/write .env files with sensitive data.

    Blocks:
    - Read/Edit/Write tool on .env files (direct file access)
    - Bash commands that cat, print, or write the contents of a .env file

    Allows:
    - .env.sample, .env.test, .env.example (non-sensitive templates)
    - --env-file=.env flags (Node.js, docker — these don't expose the file contents)
    - grep/check existence of .env (doesn't expose contents)
    - Remote SSH heredocs that mention .env inside the script
    """
    # Allowed .env variants (non-sensitive) — referenced implicitly by the
    # regex negative lookahead below (.env.sample, .env.test, .env.example,
    # .env.ci, .env.local.example are all permitted). Kept as a comment
    # only to avoid an unused-variable lint error.

    if tool_name in ['Read', 'Edit', 'MultiEdit', 'Write']:
        file_path = tool_input.get('file_path', '')
        # Block direct file tool access to .env files (but not safe variants)
        if re.search(r'\.env$', file_path) or re.search(r'\.env\b(?!\.(?:sample|test|example|ci|local\.example))', file_path):
            return True

    elif tool_name == 'Bash':
        command = tool_input.get('command', '')
        # Only block commands that actually READ or WRITE .env file contents
        # (cat/print/echo-redirect), not mere references to .env
        dangerous_env_patterns = [
            r'\bcat\s+["\']?[./\w-]*\.env["\']?\s*(?:&&|\||;|$)',  # cat .env (read contents)
            r'\bcat\s+["\']?\.env["\']?\b',                          # cat .env variants
            r'<\s*["\']?[./\w-]*\.env["\']?\b',                      # redirect from .env
            r'\bsource\s+["\']?[./\w-]*\.env["\']?\b',               # source .env
            r'\.\s+["\']?[./\w-]*\.env["\']?\b',                     # . .env (dot source)
            r'echo\s+[^|>]*>+\s*["\']?[./\w-]*\.env["\']?\b(?!\.(?:sample|test|example))',  # echo > .env
            r'\btee\s+["\']?[./\w-]*\.env["\']?\b(?!\.(?:sample|test|example))',  # tee .env
        ]

        for pattern in dangerous_env_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True

    return False


def is_safe_read_operation(tool_name: str, tool_input: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check if this is a safe read operation that can be auto-approved.
    Returns (is_safe, reason).
    """
    if tool_name == 'Read':
        file_path = tool_input.get('file_path', '')
        # Auto-approve reading documentation and config files
        safe_extensions = ('.md', '.mdx', '.txt', '.json', '.yaml', '.yml', '.toml')
        if file_path.endswith(safe_extensions):
            return True, f"Documentation/config file auto-approved: {file_path}"

    if tool_name == 'Glob':
        # Glob is generally safe (read-only file pattern matching)
        return True, "Glob operations are read-only and safe"

    if tool_name == 'Grep':
        # Grep is generally safe (read-only content search)
        return True, "Grep operations are read-only and safe"

    return False, ""


def create_json_output(
    permission_decision: Optional[str] = None,
    permission_decision_reason: Optional[str] = None,
    updated_input: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None,
    continue_execution: bool = True,
    stop_reason: Optional[str] = None,
    suppress_output: bool = False,
    system_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a JSON output structure following Claude Code hooks specification.

    Args:
        permission_decision: "allow" | "deny" | "ask" - decision control
        permission_decision_reason: Explanation for the decision
        updated_input: Modified tool inputs before execution
        additional_context: Context to add before tool executes
        continue_execution: Whether Claude should continue (default True)
        stop_reason: Message shown when continue is False
        suppress_output: Hide stdout from transcript mode
        system_message: Optional warning message shown to user

    Returns:
        Dictionary with hook-specific output following the specification
    """
    output: Dict[str, Any] = {}

    # Common fields
    if not continue_execution:
        output["continue"] = False
        if stop_reason:
            output["stopReason"] = stop_reason

    if suppress_output:
        output["suppressOutput"] = True

    if system_message:
        output["systemMessage"] = system_message

    # Hook-specific output for PreToolUse
    hook_specific: Dict[str, Any] = {
        "hookEventName": "PreToolUse"
    }

    if permission_decision:
        hook_specific["permissionDecision"] = permission_decision

    if permission_decision_reason:
        hook_specific["permissionDecisionReason"] = permission_decision_reason

    if updated_input is not None:
        hook_specific["updatedInput"] = updated_input

    if additional_context:
        hook_specific["additionalContext"] = additional_context

    if hook_specific != {"hookEventName": "PreToolUse"}:
        output["hookSpecificOutput"] = hook_specific

    return output


def log_tool_use(log_path: Path, input_data: Dict[str, Any], decision: Optional[str] = None) -> None:
    """
    Log tool usage for transparency and debugging.
    Appends to a JSONL log file.
    """
    try:
        log_entry = {
            **input_data,
            "logged_at": datetime.now().isoformat(),
        }
        if decision:
            log_entry["hook_decision"] = decision
        log_path_jsonl = log_path.with_suffix('.jsonl')
        with open(log_path_jsonl, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass


def is_git_push_command(command: str) -> bool:
    """Detect git push commands (excludes force-push to main which is blocked elsewhere)."""
    normalized = ' '.join(command.lower().split())
    # Match: git push, git push origin ..., git push -u origin ..., etc.
    return bool(re.search(r'\bgit\s+push\b', normalized))


def write_session_docs_before_push(session_id: str, input_data: Dict[str, Any] | None = None) -> None:
    """
    Write session memory + changelog files and commit them so they're
    included in the upcoming git push.

    Runs the pre_compact.py hook logic directly (without needing the full
    transcript — we write minimal stub docs here; the real docs are written
    at compact time).
    """
    try:
        # Derive repo_root from the hook input's `cwd` field — never
        # Path(__file__).resolve().parents[2], which resolves to ~/.claude
        # when this hook lives in ~/.claude/hooks/ and would write docs
        # into /home/mohammed instead of the active project.
        input_data = input_data or {}
        repo_root_str = (
            input_data.get("cwd")
            or os.environ.get("CLAUDE_PROJECT_DIR")
            or os.getcwd()
        )
        repo_root = Path(repo_root_str).resolve()
        ai_model = os.environ.get("CLAUDE_MODEL_ID", "claude-sonnet-4-6")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_str = timestamp[:10]
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', (session_id or 'unknown')[:16])

        # --- memory file ---
        mem_dir = repo_root / ".github" / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_file = mem_dir / f"memory_{ai_model}_session_{safe_id}.md"

        if not mem_file.exists():
            mem_file.write_text(
                f"### [{timestamp}] — {ai_model}\n\n"
                f"**AI Model:** {ai_model}\n"
                f"**Agent ID:** session_{safe_id}\n"
                f"**Task:** (auto-saved before git push)\n\n"
                f"#### Context Loaded\n"
                f"- Repository: muah1987/Alhashimifoundation\n"
                f"- Branch: main\n\n"
                f"#### Actions Taken\n"
                f"1. (session in progress — see transcript for details)\n\n"
                f"#### Findings\n- (see transcript)\n\n"
                f"#### Lessons Learned\n- (see transcript)\n\n"
                f"#### Test Results\n- Tests run: unknown\n",
                encoding="utf-8",
            )

        # --- changelog file ---
        cl_dir = repo_root / ".github" / "changelogs"
        cl_dir.mkdir(parents=True, exist_ok=True)
        cl_file = cl_dir / f"changelog_{ai_model}_session_{safe_id}.md"

        if not cl_file.exists():
            cl_file.write_text(
                f"## [{date_str}] — Session changes\n\n"
                f"**AI Model:** {ai_model} | **Agent ID:** session_{safe_id}\n\n"
                f"### Added\n- (auto-saved before git push)\n\n"
                f"### Changed\n- (see git diff)\n\n"
                f"### Fixed\n- (see git log)\n\n"
                f"### Removed\n- (none recorded)\n\n"
                f"### Verified\n- (see CI run)\n",
                encoding="utf-8",
            )

        # Stage + commit if anything changed
        def git(args: List[str]) -> int:
            r = subprocess.run(
                ["git"] + args, cwd=repo_root,
                capture_output=True, text=True, timeout=30,
            )
            return r.returncode

        git(["add", str(mem_file.relative_to(repo_root))])
        git(["add", str(cl_file.relative_to(repo_root))])

        # Only commit if staged changes exist
        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_root, capture_output=True, timeout=10,
        )
        if r.returncode != 0:  # non-zero means there ARE staged changes
            git(["commit", "-m",
                 f"docs: pre-push session memory/changelog [{safe_id[:8]}]"])
            print(
                f"[PreToolUse] Pre-push: committed session docs ({safe_id[:8]})",
                file=sys.stderr,
            )

    except Exception as exc:
        # Fail open — never block a legitimate git push
        print(f"[PreToolUse] Pre-push docs write skipped: {exc}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PreToolUse hook for Claude Code with GOTCHA Framework integration"
    )
    parser.add_argument(
        '--auto-approve',
        action='store_true',
        help='Output JSON to auto-approve safe read operations (Glob, Grep, safe Read)'
    )
    parser.add_argument(
        '--add-context',
        action='store_true',
        help='Add additional context information to tool execution'
    )
    parser.add_argument(
        '--context-message',
        type=str,
        default='',
        help='Custom context message to add (used with --add-context)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Enable strict mode: ask for confirmation on potentially dangerous operations'
    )
    parser.add_argument(
        '--cognitive',
        action='store_true',
        help='Enable Cognitive Control Engine for risk-scored decisions'
    )
    return parser.parse_args()


def _resolve_log_dir(input_data: Dict[str, Any]) -> Path:
    """Resolve a stable log directory.

    Prefer CLAUDE_PROJECT_DIR env var, then the hook's 'cwd' field, and
    finally ~/.claude/logs — never Path.cwd(), which pollutes whichever
    directory Claude Code happens to be running in.
    """
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if project_dir and Path(project_dir).is_dir():
        return Path(project_dir) / '.claude' / 'logs'
    cwd_val = (input_data.get('cwd') or '').strip()
    if cwd_val and Path(cwd_val).is_dir():
        return Path(cwd_val) / '.claude' / 'logs'
    return Path.home() / '.claude' / 'logs'


def main() -> None:
    """Main hook execution logic."""
    args = parse_args()

    try:
        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})

        # New fields from Claude Code hooks specification (used for context)
        cwd = input_data.get('cwd', '')
        permission_mode = input_data.get('permission_mode', 'default')

        # Ensure log directory exists (never Path.cwd() — pollutes random dirs)
        log_dir = _resolve_log_dir(input_data)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / 'pre_tool_use.jsonl'

        # ── Project scope guard ──────────────────────────────────────────────
        # Block Write/Edit/MultiEdit outside the project root and ~/.claude/.
        # Read/Glob/Grep are not blocked — needed for context loading.
        _project_root = Path(
            os.environ.get('CLAUDE_PROJECT_DIR', '') or cwd or os.getcwd()
        ).resolve()
        _WRITE_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
        if tool_name in _WRITE_TOOLS:
            _target = tool_input.get('file_path', '') or tool_input.get('notebook_path', '')
            if _target:
                try:
                    _target_resolved = Path(_target).resolve()
                    _claude_dir = (Path.home() / '.claude').resolve()
                    _in_project = _target_resolved.is_relative_to(_project_root)
                    _in_claude = _target_resolved.is_relative_to(_claude_dir)
                    if not _in_project and not _in_claude:
                        log_tool_use(log_path, input_data, decision="blocked_out_of_scope")
                        print(json.dumps({
                            "decision": "block",
                            "reason": (
                                f"Out-of-scope write blocked: {_target_resolved} is outside "
                                f"project root {_project_root}. "
                                "Switch to the target project directory first."
                            ),
                        }))
                        sys.exit(0)
                except Exception:
                    pass  # path resolution failure — let through

        # Check for .env file access — ask user to confirm rather than hard-block
        if is_env_file_access(tool_name, tool_input):
            log_tool_use(log_path, input_data, decision="ask_env_access")
            output = create_json_output(
                permission_decision="ask",
                permission_decision_reason=(
                    "This operation accesses a .env file which may contain sensitive credentials. "
                    "Please confirm you want to allow this action."
                ),
            )
            print(json.dumps(output))
            sys.exit(0)

        # Check for dangerous rm -rf commands; also intercept git push
        if tool_name == 'Bash':
            command = tool_input.get('command', '')

            # Block rm -rf commands with comprehensive pattern matching
            if is_dangerous_rm_command(command):
                log_tool_use(log_path, input_data, decision="blocked_dangerous_rm")
                print("BLOCKED: Dangerous rm command detected and prevented", file=sys.stderr)
                sys.exit(2)  # Exit code 2 blocks tool call and shows error to Claude

            # Write session docs before every git push so they're included in the push
            if is_git_push_command(command):
                write_session_docs_before_push(
                    input_data.get('session_id', 'unknown'),
                    input_data,
                )

        # Handle --auto-approve mode: auto-approve safe operations via JSON output
        if args.auto_approve:
            is_safe, reason = is_safe_read_operation(tool_name, tool_input)
            if is_safe:
                output = create_json_output(
                    permission_decision="allow",
                    permission_decision_reason=reason,
                    suppress_output=True
                )
                log_tool_use(log_path, input_data, decision="auto_approved")
                print(json.dumps(output))
                sys.exit(0)

        # Handle --strict mode: ask for confirmation on potentially risky operations
        if args.strict:
            risky_tools = ['Bash', 'Write', 'Edit', 'MultiEdit']
            if tool_name in risky_tools:
                output = create_json_output(
                    permission_decision="ask",
                    permission_decision_reason=f"Strict mode: requesting confirmation for {tool_name} operation"
                )
                log_tool_use(log_path, input_data, decision="ask_strict_mode")
                print(json.dumps(output))
                sys.exit(0)

        # Handle --add-context mode: add context information
        if args.add_context:
            context_parts: List[str] = []

            # Add custom context message if provided
            if args.context_message:
                context_parts.append(args.context_message)

            # Add permission mode context
            if permission_mode != 'default':
                context_parts.append(f"Current permission mode: {permission_mode}")

            # Add working directory context
            if cwd:
                context_parts.append(f"Working directory: {cwd}")

            if context_parts:
                output = create_json_output(
                    additional_context="\n".join(context_parts)
                )
                log_tool_use(log_path, input_data, decision="context_added")
                print(json.dumps(output))
                sys.exit(0)

        # Handle --cognitive mode: CCE risk-scored decision making
        if args.cognitive and os.getenv('CCE_ENABLED', 'true').lower() != 'false':
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from utils.cognitive import cognitive_decide  # noqa: E402

                decision = cognitive_decide(tool_name, tool_input, input_data)

                if decision.action == "deny":
                    log_tool_use(log_path, input_data, decision="cognitive_denied")
                    print(
                        f"CCE BLOCKED (risk={decision.risk_score}, {decision.risk_category}): "
                        f"{decision.reasoning}",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                elif decision.action == "ask":
                    output = create_json_output(
                        permission_decision="ask",
                        permission_decision_reason=(
                            f"CCE: {decision.reasoning} "
                            f"(risk={decision.risk_score}, confidence={decision.confidence:.2f})"
                        ),
                    )
                    log_tool_use(log_path, input_data, decision="cognitive_ask")
                    print(json.dumps(output))
                    sys.exit(0)
                else:  # allow
                    context_msg = (
                        f"CCE: Allowed (risk={decision.risk_score}/{decision.risk_category}, "
                        f"confidence={decision.confidence:.2f})"
                    )
                    output = create_json_output(additional_context=context_msg)
                    log_tool_use(log_path, input_data, decision="cognitive_allowed")
                    print(json.dumps(output))
                    sys.exit(0)
            except ImportError:
                pass  # Cognitive modules not available, fall through
            except Exception:
                pass  # Fail open on errors

        # Default: log and allow (exit 0 with no output)
        log_tool_use(log_path, input_data, decision="allowed")
        sys.exit(0)

    except json.JSONDecodeError:
        # Gracefully handle JSON decode errors
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == '__main__':
    main()
