#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
SessionStart Hook - GOTCHA Framework Integration

This hook runs when a Claude Code session starts or resumes. It implements
the GOTCHA framework's memory protocol by loading development context.

Hook Input Schema (JSON via stdin):
{
    "session_id": "abc123",                    # Unique session identifier
    "transcript_path": "~/.claude/.../xxx.jsonl",  # Path to conversation transcript
    "cwd": "/path/to/project",                 # Current working directory
    "permission_mode": "default",              # Permission mode: "default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"
    "hook_event_name": "SessionStart",         # Always "SessionStart" for this hook
    "source": "startup",                       # How session started: "startup", "resume", "clear", "compact"
    "model": "claude-sonnet-4-20250514"        # Model identifier (optional)
    "agent_type": "custom-agent"               # Present when started with --agent (optional)
}

Matchers:
- "startup" - New session started
- "resume"  - Session resumed via --resume, --continue, or /resume
- "clear"   - Session cleared via /clear
- "compact" - Session compacted via auto or manual compact

Hook Output:
- Exit 0: Success, stdout added as context for Claude
- JSON output with hookSpecificOutput.additionalContext to add context

Environment Variables:
- CLAUDE_ENV_FILE: Path to file for persisting environment variables
  Write 'export VAR=value' lines to this file to set env vars for subsequent
  Bash commands in the session. Only available in SessionStart hooks.
- CLAUDE_PROJECT_DIR: Absolute path to the project root directory

GOTCHA Framework Layers:
- Goals: Check for existing goals/manifest.md before starting tasks
- Context: Load reference material and domain knowledge from memory/
- Args: Apply behavior settings from args/ if available

Memory Protocol (from CLAUDE.md):
1. Load memory/MEMORY.md for curated facts and preferences
2. Load today's log: memory/logs/YYYY-MM-DD.md
3. Load yesterday's log for continuity

Usage:
  .claude/hooks/session_start.py --load-context    # Load development context
  .claude/hooks/session_start.py --announce        # Announce via TTS

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Context + Args
  - Context: Loads development context, memory files, and domain knowledge at session start
  - Args: Applies session behavior settings from environment and configuration

ATLAS Phase: Architect
  - Loads the foundational context needed for the session
  - Establishes the information architecture before any task execution begins
"""
__version__ = "2026.04.26.1"

import argparse
import json
import sys
import subprocess
import os
from pathlib import Path
from datetime import datetime

try:
    import importlib
    _dotenv = importlib.import_module("dotenv")
    _dotenv.load_dotenv()
except Exception:
    pass  # dotenv is optional


def _resolve_project_dir(input_data=None):
    """Resolve the project directory, preferring $CLAUDE_PROJECT_DIR, then input cwd, then os.getcwd()."""
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '').strip()
    if project_dir and Path(project_dir).is_dir():
        return Path(project_dir)
    if input_data:
        cwd = input_data.get('cwd', '').strip()
        if cwd and Path(cwd).is_dir():
            return Path(cwd)
    return Path.cwd()


def _global_claude_dir():
    """Return the user-global ~/.claude directory."""
    return Path.home() / ".claude"


def log_session_start(input_data):
    """Log session start event to logs directory.

    Prefers writing to the project .claude/logs/ when a project dir is known;
    otherwise falls back to the global ~/.claude/logs/ so logs are never lost.
    """
    try:
        project_dir = _resolve_project_dir(input_data)
        # Prefer a .claude-scoped logs dir inside the project so logs don't
        # pollute the project root. Fall back to global ~/.claude/logs/.
        candidates = [
            project_dir / ".claude" / "logs",
            _global_claude_dir() / "logs",
        ]

        log_dir = None
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                log_dir = candidate
                break
            except OSError:
                continue

        if log_dir is None:
            return  # Nowhere writable — silently skip logging.

        log_file = log_dir / 'session_start.jsonl'

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(input_data) + '\n')
    except Exception:
        # Logging must never break the session.
        return


def get_git_status(cwd=None):
    """Get current git status information.

    Returns a dict with branch, uncommitted count, last commit summary, and
    ahead/behind counts vs upstream. Returns None on any failure.
    """
    try:
        run_kwargs: dict = {"capture_output": True, "text": True, "timeout": 5}
        if cwd:
            run_kwargs["cwd"] = str(cwd)

        # Verify we are inside a git repo first — cheapest probe.
        probe = subprocess.run(
            ['git', 'rev-parse', '--is-inside-work-tree'], **run_kwargs
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return None

        info = {}

        branch_result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], **run_kwargs
        )
        info['branch'] = (
            branch_result.stdout.strip()
            if branch_result.returncode == 0
            else "unknown"
        )

        status_result = subprocess.run(
            ['git', 'status', '--porcelain'], **run_kwargs
        )
        if status_result.returncode == 0 and status_result.stdout.strip():
            info['uncommitted'] = len(status_result.stdout.strip().splitlines())
        else:
            info['uncommitted'] = 0

        # Last commit (short hash + subject)
        try:
            last_commit = subprocess.run(
                ['git', 'log', '-1', '--pretty=%h %s'], **run_kwargs
            )
            if last_commit.returncode == 0 and last_commit.stdout.strip():
                info['last_commit'] = last_commit.stdout.strip()[:140]
        except Exception:
            pass

        # Ahead/behind upstream
        try:
            ab = subprocess.run(
                ['git', 'rev-list', '--left-right', '--count', '@{u}...HEAD'],
                **run_kwargs,
            )
            if ab.returncode == 0 and ab.stdout.strip():
                parts = ab.stdout.strip().split()
                if len(parts) == 2:
                    behind, ahead = int(parts[0]), int(parts[1])
                    if ahead or behind:
                        info['ahead_behind'] = (ahead, behind)
        except Exception:
            pass

        return info
    except Exception:
        return None


def get_recent_issues(cwd=None):
    """Get recent GitHub issues if gh CLI is available."""
    try:
        gh_check = subprocess.run(['which', 'gh'], capture_output=True, timeout=3)
        if gh_check.returncode != 0:
            return None

        run_kwargs: dict = {"capture_output": True, "text": True, "timeout": 10}
        if cwd:
            run_kwargs["cwd"] = str(cwd)

        result = subprocess.run(
            ['gh', 'issue', 'list', '--limit', '5', '--state', 'open'],
            **run_kwargs,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _safe_read_snippet(path, max_chars=1200):
    """Read up to max_chars from a file; return (content, truncated) or (None, False)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read().strip()
        if not content:
            return None, False
        if len(content) > max_chars:
            return content[:max_chars], True
        return content, False
    except Exception:
        return None, False


def _get_recent_global_sessions(limit=3):
    """Return a list of (name, mtime) for the most recently modified global session files."""
    try:
        sessions_dir = _global_claude_dir() / "data" / "sessions"
        if not sessions_dir.is_dir():
            return []
        entries = []
        for entry in sessions_dir.iterdir():
            if entry.is_file() and entry.suffix == '.json':
                try:
                    entries.append((entry.name, entry.stat().st_mtime))
                except OSError:
                    continue
        entries.sort(key=lambda x: x[1], reverse=True)
        return entries[:limit]
    except Exception:
        return []


def _get_recent_global_plans(limit=5):
    """Return names of recently modified plan files in ~/.claude/plans/."""
    try:
        plans_dir = _global_claude_dir() / "plans"
        if not plans_dir.is_dir():
            return []
        entries = []
        for entry in plans_dir.iterdir():
            if entry.is_file() and entry.suffix in ('.md', '.txt'):
                try:
                    entries.append((entry.name, entry.stat().st_mtime))
                except OSError:
                    continue
        entries.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in entries[:limit]]
    except Exception:
        return []


def _harness_stats() -> dict:
    """Quick read of harness_version.json for dashboard metrics."""
    try:
        p = _global_claude_dir() / "data" / "harness_version.json"
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return {}


def load_development_context(source, input_data=None):
    """Load relevant development context based on session source."""
    context_parts = []
    project_dir = _resolve_project_dir(input_data)

    # ── Dashboard header ─────────────────────────────────────────────────────
    try:
        now     = datetime.now().strftime('%Y-%m-%d %H:%M')
        project = project_dir.name
        stats   = _harness_stats()
        skills  = stats.get('skills', '?')
        hooks   = stats.get('hooks', '?')
        sl_ver  = stats.get('status_line', '?')
        src_map = {'startup': '▶ new', 'resume': '⏵ resume',
                   'clear': '↺ clear', 'compact': '⊡ compact'}
        src_lbl = src_map.get(source, source)
        context_parts.append(
            f"╔═══════════════════════════════════════════════════════╗"
        )
        context_parts.append(
            f"║  SESSION START · {project:<20} · {now}  ║"
        )
        context_parts.append(
            f"╚═══════════════════════════════════════════════════════╝"
        )
        context_parts.append(
            f"  Trigger: {src_lbl}   Skills: {skills}   Hooks: {hooks}   Status: {sl_ver}"
        )
    except Exception:
        context_parts.append(f"Session started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Git ──────────────────────────────────────────────────────────────────
    try:
        git_info = get_git_status(cwd=project_dir)
        if git_info:
            context_parts.append("")
            context_parts.append("── Git ─────────────────────────────────────────────────")
            context_parts.append(f"Branch: {git_info.get('branch', 'unknown')}")
            uncommitted = git_info.get('uncommitted', 0)
            if uncommitted:
                context_parts.append(f"Uncommitted changes: {uncommitted} files")
            else:
                context_parts.append("Working tree: clean")
            if git_info.get('last_commit'):
                context_parts.append(f"Last commit: {git_info['last_commit']}")
            if git_info.get('ahead_behind'):
                ahead, behind = git_info['ahead_behind']
                context_parts.append(
                    f"Upstream: {ahead} ahead, {behind} behind"
                )
    except Exception:
        pass

    # ── Project context files ────────────────────────────────────────────────
    try:
        context_parts.append("")
        context_parts.append("── Context files ───────────────────────────────────────")
    except Exception:
        pass
    try:
        context_files = [
            project_dir / ".claude" / "CONTEXT.md",
            project_dir / ".claude" / "TODO.md",
            project_dir / "CLAUDE.md",
            project_dir / "TODO.md",
            project_dir / ".github" / "ISSUE_TEMPLATE.md",
        ]
        for file_path in context_files:
            if file_path.exists() and file_path.is_file():
                content, truncated = _safe_read_snippet(file_path, max_chars=1200)
                if content:
                    rel = file_path.relative_to(project_dir) if file_path.is_relative_to(project_dir) else file_path
                    header = f"\n--- {rel} ---"
                    if truncated:
                        header += " (truncated)"
                    context_parts.append(header)
                    context_parts.append(content)
    except Exception:
        pass

    # Project-specific memory index at ~/.claude/projects/<path-key>/memory/MEMORY.md
    # This is where auto-memory saves user/feedback/project/reference memories.
    try:
        global_dir = _global_claude_dir()
        project_key = str(project_dir).replace('/', '-')
        project_memory_dir = global_dir / "projects" / project_key / "memory"
        project_memory_index = project_memory_dir / "MEMORY.md"
        if project_memory_index.exists():
            content, truncated = _safe_read_snippet(project_memory_index, max_chars=2000)
            if content:
                header = "\n── Memory index ────────────────────────────────────────"
                if truncated:
                    header += " (truncated)"
                context_parts.append(header)
                context_parts.append(content)
    except Exception:
        pass

    # Global fallback: user-level CLAUDE.md at ~/.claude/ (skip MEMORY.md — project-specific one above is preferred)
    try:
        global_dir = _global_claude_dir()
        global_files = [
            global_dir / "CLAUDE.md",
        ]
        for gf in global_files:
            if gf.exists() and gf.is_file():
                content, truncated = _safe_read_snippet(gf, max_chars=1500)
                if content:
                    header = f"\n--- Global {gf.name} ({gf}) ---"
                    if truncated:
                        header += " (truncated)"
                    context_parts.append(header)
                    context_parts.append(content)
                    break
    except Exception:
        pass

    # Recent plans from ~/.claude/plans/ — useful for continuity across sessions.
    try:
        recent_plans = _get_recent_global_plans(limit=5)
        if recent_plans:
            context_parts.append("\n── Recent plans ────────────────────────────────────────")
            for name in recent_plans:
                context_parts.append(f"  - {name}")
    except Exception:
        pass

    # Recent global sessions (helps on 'resume'/'clear' to remember what was
    # active lately without parsing transcripts).
    try:
        if source in ("resume", "clear", "compact", "startup"):
            recent_sessions = _get_recent_global_sessions(limit=3)
            if recent_sessions:
                context_parts.append("\n── Recent sessions ─────────────────────────────────────")
                for name, mtime in recent_sessions:
                    try:
                        ts = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                    except (OverflowError, OSError, ValueError):
                        ts = "?"
                    context_parts.append(f"  - {name} ({ts})")
    except Exception:
        pass

    # Recent GitHub issues via plain gh CLI (cheap, best-effort).
    try:
        issues = get_recent_issues(cwd=project_dir)
        if issues:
            context_parts.append("\n── GitHub issues ───────────────────────────────────────")
            context_parts.append(issues)
    except Exception:
        pass

    # Richer GitHub context via gh_detect helper (if present under the project).
    try:
        gh_detect_candidates = [
            project_dir / ".github" / "hooks",
            project_dir.parent / ".github" / "hooks",
            _global_claude_dir() / "hooks" / "utils",
        ]
        gh_detect_module = None
        for candidate in gh_detect_candidates:
            init_or_file = candidate / "gh_detect.py"
            if init_or_file.exists():
                sys.path.insert(0, str(candidate))
                try:
                    import importlib as _il
                    gh_detect_module = _il.import_module("gh_detect")
                    break
                except Exception:
                    continue

        if gh_detect_module is not None and (
            gh_detect_module.is_gh_installed()
            and gh_detect_module.is_gh_authenticated()
        ):
            gh_context_parts = []
            gh_branch = gh_detect_module.get_current_branch()
            if gh_branch:
                gh_context_parts.append(f"Branch: {gh_branch}")

            exit_code, stdout, _ = gh_detect_module.run_gh_command(
                ["pr", "list", "--state", "open", "--json", "number", "--limit", "100"]
            )
            if exit_code == 0 and stdout:
                try:
                    open_prs = json.loads(stdout)
                    gh_context_parts.append(f"Open PRs: {len(open_prs)}")
                except (json.JSONDecodeError, ValueError):
                    pass

            exit_code, stdout, _ = gh_detect_module.run_gh_command(
                ["issue", "list", "--assignee", "@me", "--state", "open", "--json", "number", "--limit", "100"]
            )
            if exit_code == 0 and stdout:
                try:
                    assigned_issues = json.loads(stdout)
                    gh_context_parts.append(f"Assigned issues: {len(assigned_issues)}")
                except (json.JSONDecodeError, ValueError):
                    pass

            if gh_context_parts:
                context_parts.append("\n--- GitHub Context ---")
                context_parts.extend(gh_context_parts)
    except ImportError:
        pass
    except Exception:
        pass

    return "\n".join(context_parts)


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--load-context', action='store_true',
                          help='Load development context at session start')
        parser.add_argument('--announce', action='store_true',
                          help='Announce session start via TTS')
        parser.add_argument('--assess', action='store_true',
                          help='Run system assessment and cache results')
        args = parser.parse_args()
        
        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())
        
        # Extract fields from input
        session_id = input_data.get('session_id', 'unknown')
        hook_event_name = input_data.get('hook_event_name', 'SessionStart')
        source = input_data.get('source', 'unknown')  # "startup", "resume", "clear", or "compact"
        model = input_data.get('model', '')  # Model identifier (optional)
        agent_type = input_data.get('agent_type', '')  # Present when started with --agent
        permission_mode = input_data.get('permission_mode', 'default')  # Permission mode
        cwd = input_data.get('cwd', '')  # Current working directory

        # Log the session start event with all fields
        log_session_start(input_data)

        # Refresh Claude rate-limit status in the background so every new session
        # starts with a current view of `usage_status.json`. Fire-and-forget —
        # never block the hook, never surface errors.
        try:
            usage_monitor = _global_claude_dir() / "scripts" / "usage_monitor.py"
            if usage_monitor.exists():
                subprocess.Popen(
                    ["uv", "run", str(usage_monitor), "check"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
        except Exception:
            pass

        # Ensure the usage_monitor watch daemon is running. Only start a new
        # instance if no `usage_monitor.py watch` process is already alive.
        try:
            usage_monitor = _global_claude_dir() / "scripts" / "usage_monitor.py"
            if usage_monitor.exists():
                _check = subprocess.run(
                    ["pgrep", "-f", "usage_monitor.py watch"],
                    capture_output=True, text=True, timeout=3,
                )
                if _check.returncode != 0:  # not running
                    subprocess.Popen(
                        ["uv", "run", str(usage_monitor), "watch"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
        except Exception:
            pass

        # ── Project anchor: register project UUID + init short-term memory ──
        try:
            anchor_script = _global_claude_dir() / "scripts" / "project_anchor.py"
            if anchor_script.exists():
                project_path = Path(cwd) if cwd else Path.cwd()
                # Register project in global registry (best-effort, background)
                subprocess.Popen(
                    ["uv", "run", str(anchor_script), "register", str(project_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                # Link session → project
                if session_id and session_id != "unknown":
                    subprocess.Popen(
                        ["uv", "run", str(anchor_script), "link-session", session_id],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_path)},
                    )
        except Exception:
            pass

        # ── Short-term memory: init session st_memory.json ──
        try:
            if session_id and session_id != "unknown":
                st_dir = _global_claude_dir() / "data" / "sessions" / session_id
                st_dir.mkdir(parents=True, exist_ok=True)
                st_file = st_dir / "st_memory.json"
                if not st_file.exists():
                    st_file.write_text(json.dumps({
                        "_session_id": session_id,
                        "_started_at": datetime.now().isoformat(),
                        "_project": cwd or str(Path.cwd()),
                        "_source": source,
                    }, indent=2), encoding="utf-8")
        except Exception:
            pass

        # Log key session information to stderr for debugging (visible in --debug mode)
        debug_info = [f"[{hook_event_name}] Session {session_id} started"]
        debug_info.append(f"Source: {source}")
        if model:
            debug_info.append(f"Model: {model}")
        if agent_type:
            debug_info.append(f"Agent: {agent_type}")
        debug_info.append(f"Permission mode: {permission_mode}")
        if cwd:
            debug_info.append(f"Working directory: {cwd}")

        # Write debug info to stderr (visible with claude --debug)
        print(" | ".join(debug_info), file=sys.stderr)

        # Check for CLAUDE_ENV_FILE environment variable for persisting env vars
        # This allows SessionStart hooks to set environment variables that persist
        # for all subsequent Bash commands in the session
        env_file = os.environ.get('CLAUDE_ENV_FILE', '')
        if env_file:
            # Example: persist some environment variables for the session
            # Users can customize this section to set project-specific env vars
            try:
                with open(env_file, 'a') as f:
                    # Write session metadata as env vars for reference
                    f.write(f'# SessionStart hook initialized at {datetime.now().isoformat()}\n')
                    if model:
                        f.write(f'export CLAUDE_SESSION_MODEL="{model}"\n')
            except OSError:
                pass  # Ignore errors writing to env file

        # Handle --assess: Run system assessment and cache results
        if args.assess:
            try:
                assess_script = Path(__file__).parent / "utils" / "assessment.py"
                if assess_script.exists():
                    result = subprocess.run(
                        ["uv", "run", str(assess_script), "--json", "--no-cache"],
                        capture_output=True,
                        text=True,
                        timeout=15
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        try:
                            assessment_data = json.loads(result.stdout.strip())
                            cli_list = []
                            for cli_name, cli_info in assessment_data.get("cli", {}).items():
                                if isinstance(cli_info, dict) and cli_info.get("installed"):
                                    cli_list.append(cli_name)
                            if cli_list:
                                print(f"Assessment: CLIs available: {', '.join(cli_list)}", file=sys.stderr)
                        except (json.JSONDecodeError, ValueError):
                            pass
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                pass
            except Exception:
                pass

        # Load development context if requested
        if args.load_context:
            try:
                context = load_development_context(source, input_data=input_data)
            except Exception:
                context = ""
            if context:
                # Using JSON output to add context
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context
                    }
                }
                print(json.dumps(output))
                sys.exit(0)
        
        # Announce session start if requested
        if args.announce:
            try:
                # Try to use TTS to announce session start
                script_dir = Path(__file__).parent
                tts_script = script_dir / "utils" / "tts" / "pyttsx3_tts.py"
                
                if tts_script.exists():
                    messages = {
                        "startup": "Claude Code session started",
                        "resume": "Resuming previous session",
                        "clear": "Starting fresh session",
                        "compact": "Context compacted"
                    }
                    message = messages.get(source, "Session started")
                    
                    subprocess.run(
                        ["uv", "run", str(tts_script), message],
                        capture_output=True,
                        timeout=5
                    )
            except Exception:
                pass
        
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