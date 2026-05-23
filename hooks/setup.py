#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Setup Hook - GOTCHA Framework Integration

This hook runs when Claude Code is invoked with repository setup and maintenance flags.
It implements GOTCHA framework principles by:

1. Initializing the memory infrastructure on first run (Memory protocol)
2. Loading context for new AI assistant sessions (Context layer)
3. Supporting the Args layer with environment configuration

GOTCHA Framework Layers:
- Context: Load reference material and domain knowledge
- Args: Apply behavior settings from environment
- Memory Protocol: Initialize persistent storage if needed

Claude Code Hook Specification:
-------------------------------
Event: Setup
Trigger: When Claude Code is invoked with --init, --init-only, or --maintenance flags

Matchers:
  - "init"        : Runs when invoked with --init or --init-only flags.
                    Use for one-time repository initialization tasks like
                    installing dependencies, running initial migrations, etc.
  - "maintenance" : Runs when invoked with --maintenance flag.
                    Use for periodic maintenance tasks like cleanup, health checks,
                    log rotation, etc.

Input (via stdin JSON):
  {
    "session_id": string,        # Unique session identifier
    "transcript_path": string,   # Path to conversation transcript JSON
    "cwd": string,               # Current working directory
    "permission_mode": string,   # "default", "plan", "acceptEdits", "dontAsk", or "bypassPermissions"
    "hook_event_name": "Setup",  # Always "Setup" for this hook
    "trigger": "init" | "maintenance"  # What triggered this hook
  }

Output (JSON to stdout):
  {
    "hookSpecificOutput": {
      "hookEventName": "Setup",
      "additionalContext": string  # Context added to Claude's conversation
    }
  }

Environment Variables:
  - CLAUDE_PROJECT_DIR : Absolute path to the project root directory
  - CLAUDE_ENV_FILE    : File path where environment variables can be persisted
                         for subsequent bash commands. Write "export VAR=value"
                         lines to this file to set environment variables.

Note: Use Setup hooks for one-time or occasional operations (dependency installation,
      migrations, cleanup). Use SessionStart hooks for things you want on every session
      (loading context, setting environment variables). Setup hooks require explicit
      flags because running them automatically would slow down every session start.

Usage:
  .claude/hooks/setup.py --load-context    # Load development context at setup
  .claude/hooks/setup.py --install-clis    # Install all supported CLIs via tools/install_clis.py
  .claude/hooks/setup.py --upgrade-clis    # Upgrade all supported CLIs via tools/upgrade_clis.py

See CLAUDE.md for full GOTCHA framework documentation.

GOTCHA Layer: Goals + Context
  - Goals: Initializes project structure and defines what the setup process must achieve
  - Context: Loads reference material, domain knowledge, and environment configuration on first run

ATLAS Phase: Architect
  - Establishes the foundational project structure and environment
  - Sets up the scaffolding that all subsequent phases build upon
"""
__version__ = "2026.04.20.5"

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


def log_setup(input_data):
    """Log setup event to logs directory."""
    log_dir = Path.home() / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'setup.jsonl'
    entry = {"timestamp": datetime.now().isoformat(), **input_data}
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def persist_env_variable(name, value):
    """Persist an environment variable via CLAUDE_ENV_FILE."""
    env_file = os.environ.get('CLAUDE_ENV_FILE')
    if env_file:
        with open(env_file, 'a') as f:
            f.write(f'export {name}="{value}"\n')
        return True
    return False


def check_dependencies():
    """Check if common project dependencies are available."""
    deps_status = {}

    # Check for Node.js / npm
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=5)
        deps_status['node'] = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        deps_status['node'] = None

    # Check for Python
    try:
        result = subprocess.run(['python3', '--version'], capture_output=True, text=True, timeout=5)
        deps_status['python'] = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        deps_status['python'] = None

    # Check for uv
    try:
        result = subprocess.run(['uv', '--version'], capture_output=True, text=True, timeout=5)
        deps_status['uv'] = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        deps_status['uv'] = None

    # Check for git
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5)
        deps_status['git'] = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        deps_status['git'] = None

    return deps_status


def install_project_dependencies(cwd=None):
    """Attempt to install project dependencies based on detected files."""
    installed = []
    errors = []
    base = Path(cwd) if cwd else Path(os.getcwd())

    # Check for package.json (Node.js)
    if (base / 'package.json').exists():
        try:
            # Prefer npm ci for CI environments, npm install otherwise
            cmd = ['npm', 'ci'] if (base / 'package-lock.json').exists() else ['npm', 'install']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(base))
            if result.returncode == 0:
                installed.append('npm dependencies')
            else:
                errors.append(f'npm: {result.stderr[:200]}')
        except Exception as e:
            errors.append(f'npm: {str(e)}')

    # Check for requirements.txt (Python)
    if (base / 'requirements.txt').exists():
        try:
            result = subprocess.run(
                ['pip', 'install', '-r', str(base / 'requirements.txt')],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                installed.append('pip dependencies')
            else:
                errors.append(f'pip: {result.stderr[:200]}')
        except Exception as e:
            errors.append(f'pip: {str(e)}')

    # Check for pyproject.toml (Python with uv or pip)
    if (base / 'pyproject.toml').exists() and not (base / 'requirements.txt').exists():
        try:
            # Try uv first
            result = subprocess.run(['uv', 'sync'], capture_output=True, text=True, timeout=300, cwd=str(base))
            if result.returncode == 0:
                installed.append('uv dependencies')
            else:
                # Fallback to pip install .
                result = subprocess.run(
                    ['pip', 'install', '-e', '.'],
                    capture_output=True, text=True, timeout=300, cwd=str(base)
                )
                if result.returncode == 0:
                    installed.append('pip (pyproject.toml)')
                else:
                    errors.append(f'pyproject.toml: {result.stderr[:200]}')
        except Exception as e:
            errors.append(f'pyproject.toml: {str(e)}')

    return installed, errors


def get_project_info(cwd):
    """Gather project information for context."""
    info = []

    # Check for git repository
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=5, cwd=cwd
        )
        if result.returncode == 0:
            info.append(f"Git branch: {result.stdout.strip()}")
    except Exception:
        pass

    # Check for common project files
    project_files = [
        ('package.json', 'Node.js project'),
        ('pyproject.toml', 'Python project (pyproject.toml)'),
        ('requirements.txt', 'Python project (requirements.txt)'),
        ('Cargo.toml', 'Rust project'),
        ('go.mod', 'Go project'),
        ('Makefile', 'Makefile present'),
    ]

    for filename, description in project_files:
        if Path(cwd, filename).exists():
            info.append(f"Detected: {description}")

    # Check for .claude directory
    if Path(cwd, '.claude').exists():
        info.append("Claude Code configuration directory present")

        # Check for CLAUDE.md or CONTEXT.md
        for context_file in ['CLAUDE.md', 'CONTEXT.md']:
            context_path = Path(cwd, '.claude', context_file)
            if context_path.exists():
                info.append(f"Found {context_file} in .claude/")

    return info


def run_maintenance_tasks(cwd):
    """Run periodic maintenance tasks."""
    tasks_completed = []

    # Check disk usage of logs directory
    logs_dir = Path(cwd, 'logs')
    if logs_dir.exists():
        try:
            total_size = sum(f.stat().st_size for f in logs_dir.rglob('*') if f.is_file())
            size_mb = total_size / (1024 * 1024)
            if size_mb > 10:
                tasks_completed.append(f"Warning: logs directory is {size_mb:.2f}MB")
            else:
                tasks_completed.append(f"Logs directory size: {size_mb:.2f}MB")
        except Exception:
            pass

    # Run git gc if repository is large
    try:
        result = subprocess.run(
            ['git', 'count-objects', '-v'],
            capture_output=True, text=True, timeout=10, cwd=cwd
        )
        if result.returncode == 0:
            tasks_completed.append("Git repository status checked")
    except Exception:
        pass

    return tasks_completed


def main():
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--install-deps', action='store_true',
                          help='Install project dependencies')
        parser.add_argument('--verbose', action='store_true',
                          help='Print verbose output')
        parser.add_argument('--install-clis', action='store_true',
                          help='Install all supported CLIs via tools/install_clis.py')
        parser.add_argument('--upgrade-clis', action='store_true',
                          help='Upgrade all supported CLIs via tools/upgrade_clis.py')
        args = parser.parse_args()

        # Always consume stdin first — Claude Code hangs if we don't
        raw_stdin = sys.stdin.read()

        # Handle CLI installer/upgrader flags (short-circuit, no stdin needed)
        project_root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
        if args.install_clis:
            result = subprocess.run(
                [sys.executable, str(project_root / "tools" / "install_clis.py"), "--all"],
                timeout=600, text=True
            )
            sys.exit(0)
        if args.upgrade_clis:
            result = subprocess.run(
                [sys.executable, str(project_root / "tools" / "upgrade_clis.py"), "--all"],
                timeout=600, text=True
            )
            sys.exit(0)

        # Parse JSON input from already-consumed stdin
        input_data = json.loads(raw_stdin) if raw_stdin.strip() else {}

        # Extract fields from Setup hook input
        session_id = input_data.get('session_id', 'unknown')
        hook_event_name = input_data.get('hook_event_name', 'Setup')
        cwd = input_data.get('cwd', os.getcwd())
        permission_mode = input_data.get('permission_mode', 'default')
        trigger = input_data.get('trigger', 'init')  # "init" or "maintenance"

        # Log the setup event
        log_setup(input_data)

        # Build context information
        context_parts = []
        context_parts.append(f"[{hook_event_name}] Setup triggered: {trigger}")
        context_parts.append(f"Session: {session_id[:8]}...")
        context_parts.append(f"Working directory: {cwd}")
        context_parts.append(f"Permission mode: {permission_mode}")

        # Gather project information
        project_info = get_project_info(cwd)
        if project_info:
            context_parts.append("\n--- Project Information ---")
            context_parts.extend(project_info)

        # Check dependencies status
        deps_status = check_dependencies()
        available_deps = [f"{k}: {v}" for k, v in deps_status.items() if v]
        if available_deps:
            context_parts.append("\n--- Available Tools ---")
            context_parts.extend(available_deps)

        # Handle trigger-specific actions
        if trigger == 'init':
            context_parts.append("\n--- Repository Initialization ---")

            # Persist project path as environment variable
            persist_env_variable('PROJECT_ROOT', cwd)

            # Install dependencies if requested
            if args.install_deps:
                context_parts.append("Installing dependencies...")
                installed, errors = install_project_dependencies(cwd)
                if installed:
                    context_parts.append(f"Installed: {', '.join(installed)}")
                if errors:
                    context_parts.append(f"Errors: {'; '.join(errors)}")

            context_parts.append("Repository initialized with custom configuration")

        elif trigger == 'maintenance':
            context_parts.append("\n--- Maintenance Tasks ---")

            # Run maintenance tasks
            maintenance_results = run_maintenance_tasks(cwd)
            if maintenance_results:
                context_parts.extend(maintenance_results)

            context_parts.append("Maintenance tasks completed")

        # Prepare JSON output with additionalContext
        context = "\n".join(context_parts)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "Setup",
                "additionalContext": context
            }
        }

        print(json.dumps(output))
        sys.exit(0)

    except json.JSONDecodeError:
        # Handle JSON decode errors gracefully
        sys.exit(0)
    except Exception:
        # Handle any other errors gracefully
        sys.exit(0)


if __name__ == '__main__':
    main()
