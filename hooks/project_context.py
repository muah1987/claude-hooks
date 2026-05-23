#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""
Project Context Loader — SessionStart Hook
AlHashimi Foundation

Fires on every Claude Code session start.
Injects project context into the session so Claude always boots with:
  1. Key facts from CLAUDE.md (architecture, conventions, status)
  2. Latest memory file from .github/memory/
  3. Latest changelog from .github/changelogs/
  4. Active skills, MCP servers, and hooks summary

This ensures Claude never starts blind — even after auto-compact or
a fresh session start, full project context is immediately available.

GOTCHA Layer: Context (boot-time knowledge injection)
"""
__version__ = "2026.04.20.5"

import json
import os
import sys
from pathlib import Path
from datetime import datetime


PROJECT_DIR = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())

# Markers that indicate a real project worth injecting context for
_PROJECT_MARKERS = {'CLAUDE.md', '.claude', 'package.json', 'Cargo.toml', 'pyproject.toml', 'go.mod'}


def is_known_project(directory: Path) -> bool:
    """Return True only if the directory looks like a real project."""
    return any((directory / marker).exists() for marker in _PROJECT_MARKERS)


def read_claude_md_summary() -> str:
    """Extract key sections from CLAUDE.md without bloating context."""
    claude_md = PROJECT_DIR / 'CLAUDE.md'
    if not claude_md.exists():
        return ''

    text = claude_md.read_text(encoding='utf-8')
    lines = text.splitlines()

    # Extract: Project Overview, Repository Structure summary, Current Status, Important Notes
    sections = []
    current_section = []
    capture = False
    capture_sections = {
        '## Project Overview',
        '## Current Implementation Status',
        '## Important Notes for AI Assistants',
        '## Git Workflow',
        '## Changelog & Memory',
    }

    for line in lines:
        if any(line.strip().startswith(s) for s in capture_sections):
            if current_section:
                sections.append('\n'.join(current_section))
            current_section = [line]
            capture = True
        elif line.startswith('## ') and capture:
            # New section not in our list — stop capturing
            if current_section:
                sections.append('\n'.join(current_section))
            current_section = []
            capture = False
        elif capture:
            current_section.append(line)

    if current_section:
        sections.append('\n'.join(current_section))

    combined = '\n\n'.join(sections)
    # Limit to 1500 chars to keep context lean
    return combined[:1500] if len(combined) > 1500 else combined


def get_latest_file(directory: Path, pattern: str) -> str:
    """Return content of the most recently modified file matching pattern."""
    if not directory.exists():
        return ''

    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return ''

    content = files[0].read_text(encoding='utf-8')
    return files[0], content


def count_skills() -> int:
    global_dir = Path.home() / '.claude' / 'commands'
    project_dir = PROJECT_DIR / '.claude' / 'commands'
    total = 0
    for d in (global_dir, project_dir):
        if d and d.is_dir():
            total += len(list(d.glob('*.md')))
    return total


def count_hooks() -> int:
    global_dir = Path.home() / '.claude' / 'hooks'
    project_dir = PROJECT_DIR / '.claude' / 'hooks'
    total = 0
    for d in (global_dir, project_dir):
        if d and d.is_dir():
            total += len(list(d.glob('*.py')))
    return total


def _project_label() -> str:
    """Derive a human-readable project label from config or directory name."""
    # Try .company/config.json first
    cfg = PROJECT_DIR / '.company' / 'config.json'
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            name = data.get('company_name') or data.get('project_name')
            if name:
                return str(name)
        except Exception:
            pass
    # Fallback: directory name
    return PROJECT_DIR.name


def _infra_summary() -> str:
    """Read infrastructure facts from .company/infrastructure.json if present."""
    infra = PROJECT_DIR / '.company' / 'infrastructure.json'
    if not infra.exists():
        return ''
    try:
        data = json.loads(infra.read_text())
        parts = []
        vps = data.get('vps_host') or data.get('host')
        user = data.get('vps_user') or data.get('user')
        app = data.get('app_path') or data.get('app_dir')
        repo = data.get('github_repo') or data.get('repo')
        if vps and user:
            parts.append(f"VPS: {user}@{vps}")
        if app:
            parts.append(f"App: {app}")
        if repo:
            parts.append(f"Repo: {repo}")
        return ' | '.join(parts)
    except Exception:
        return ''


def build_context(source: str) -> str:
    parts = []

    # Header — fully dynamic, no hardcoded project name
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    label = _project_label()
    parts.append(f"=== {label} — Project Context ({now}, trigger: {source}) ===")

    # CLAUDE.md key facts
    claude_summary = read_claude_md_summary()
    if claude_summary:
        parts.append("\n--- CLAUDE.md Key Facts ---")
        parts.append(claude_summary)

    # Persistent agent-log (cap: 400 chars) — separate from session memory
    agent_log = PROJECT_DIR / '.github' / 'memory' / 'memory_agent-log.md'
    if agent_log.exists():
        try:
            log_snippet = agent_log.read_text(encoding='utf-8')[:400]
            parts.append("\n--- Agent Log ---")
            parts.append(log_snippet)
        except Exception:
            pass

    # Latest session memory (cap: 800 chars) — skip agent-log to avoid duplication
    memory_dir = PROJECT_DIR / '.github' / 'memory'
    memory_result = None
    memory_mtime = None
    if memory_dir.exists():
        candidates = sorted(
            (f for f in memory_dir.glob('memory_*.md') if f.name != 'memory_agent-log.md'),
            key=lambda f: f.stat().st_mtime, reverse=True
        )
        if candidates:
            mem_file = candidates[0]
            mem_content = mem_file.read_text(encoding='utf-8')
            memory_mtime = mem_file.stat().st_mtime
            mem_snippet = mem_content[:800]
            parts.append("\n--- Latest Session Memory ---")
            parts.append(f"[{mem_file.name}]\n{mem_snippet}")
            memory_result = (mem_file, mem_content)

    # Latest changelog (cap: 600 chars) — skip if pre_compact just ran both files recently
    changelog_result = get_latest_file(PROJECT_DIR / '.github' / 'changelogs', 'changelog_*.md')
    if changelog_result:
        cl_file, cl_content = changelog_result
        cl_mtime = cl_file.stat().st_mtime
        now_ts = datetime.utcnow().timestamp()
        both_recent = (
            memory_mtime is not None
            and (now_ts - memory_mtime) < 60
            and (now_ts - cl_mtime) < 60
        )
        if not both_recent:
            cl_snippet = cl_content[:600]
            parts.append("\n--- Latest Session Changelog ---")
            parts.append(f"[{cl_file.name}]\n{cl_snippet}")

    # Quick capability summary
    n_skills = count_skills()
    n_hooks = count_hooks()
    mcp_file = PROJECT_DIR / '.mcp.json'
    mcp_servers = []
    if mcp_file.exists():
        try:
            mcp_data = json.loads(mcp_file.read_text())
            mcp_servers = list(mcp_data.get('mcpServers', {}).keys())
        except Exception:
            pass

    parts.append("\n--- Capabilities ---")
    parts.append(f"Skills: {n_skills} in .claude/commands/")
    parts.append(f"Hooks: {n_hooks} active hook files (~/.claude/hooks/)")
    parts.append(f"MCP servers (.mcp.json): {', '.join(mcp_servers) if mcp_servers else 'none'}")

    # Infrastructure — read from .company/infrastructure.json, never hardcoded
    infra = _infra_summary()
    if infra:
        parts.append(infra)

    return '\n'.join(parts)


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
        source = input_data.get('source', 'unknown')

        # Skip expensive injection for unknown/non-project directories
        if not is_known_project(PROJECT_DIR):
            print(json.dumps({}))
            sys.exit(0)

        # Always inject context — on every boot (startup, resume, compact, clear)
        context = build_context(source)

        output = {
            'hookSpecificOutput': {
                'hookEventName': 'SessionStart',
                'additionalContext': context
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == '__main__':
    main()
