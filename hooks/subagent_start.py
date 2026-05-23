#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
SubagentStart Hook - Lean Context Injector

Runs when a Claude Code sub-agent is spawned. Its job is narrow:

1. Log the spawn event to ~/.claude/logs/subagent_start.jsonl (JSONL, one per line)
2. Append to the agent registry at ~/.claude/data/agent_registry.jsonl
3. Inject useful `additionalContext` into the sub-agent (project, vault keys,
   skills, sub-agent reminder)

Philosophy: fast, silent, always exit 0. Never block a sub-agent from spawning.
TTS / announcements belong in subagent_stop, not here.
"""

from __future__ import annotations
__version__ = "2026.04.20.4"

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv  # ty: ignore[unresolved-import]
    load_dotenv()
except ImportError:
    pass


HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
LOG_DIR = CLAUDE_DIR / "logs"
DATA_DIR = CLAUDE_DIR / "data"
LOG_PATH = LOG_DIR / "subagent_start.jsonl"
REGISTRY_PATH = DATA_DIR / "agent_registry.jsonl"
VAULT_SCRIPT = CLAUDE_DIR / "vault" / "vault.py"
COMMANDS_DIR = CLAUDE_DIR / "commands"
SUBPROCESS_TIMEOUT = 3

# Agent types that warrant the full context block (vault, skills, model arsenal).
# Everything else gets a minimal context to save tokens.
HEAVY_AGENT_TYPES: frozenset[str] = frozenset({
    "builder",
    "general-purpose",
    "Plan",
    "backend-systems-architect",
    "mobile-engineer",
    "data-analytics-engineer",
    "web-developer",
    "product-manager",
    "qa-test-lead",
    "security-privacy-engineer",
})


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record as one line to a JSONL file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _list_vault_keys(cwd: str | None = None) -> list[str]:
    """Call the vault CLI to list available keys. Return [] on any failure."""
    if not VAULT_SCRIPT.exists():
        return []
    try:
        result = subprocess.run(
            ["uv", "run", str(VAULT_SCRIPT), "list"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=cwd if cwd else None,
        )
        if result.returncode != 0:
            return []
        keys: list[str] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Take the first whitespace-separated token; strip common prefixes.
            token = line.split()[0].lstrip("-*•").strip()
            if token:
                keys.append(token)
        return keys
    except Exception:
        return []


def _list_skills() -> list[str]:
    """Return skill names (filenames without .md) from ~/.claude/commands/."""
    if not COMMANDS_DIR.is_dir():
        return []
    try:
        return sorted(p.stem for p in COMMANDS_DIR.glob("*.md") if p.is_file())
    except Exception:
        return []


def _read_usage_status() -> dict:
    """Return the current usage_status.json contents, or {} on any failure."""
    try:
        status_path = DATA_DIR / "usage_status.json"
        if status_path.exists():
            return json.loads(status_path.read_text())
    except Exception:
        pass
    return {}


def _get_git_context(cwd: str) -> dict:
    """Collect a lightweight git snapshot for the given cwd.

    Every subprocess is capped at SUBPROCESS_TIMEOUT (3s) and wrapped in
    try/except so any failure degrades gracefully. Returns a dict with:
        - is_repo: bool
        - branch: str | None
        - uncommitted: int
        - last_commit: str | None   (e.g. 'abc1234 fix: update hook')
        - ahead: int
        - behind: int
        - clean: bool
    On any catastrophic failure, returns {"is_repo": False}.
    """
    fallback = {"is_repo": False}
    if not cwd or cwd == "unknown":
        return fallback

    def _run(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
                cwd=cwd,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except Exception:
            return None

    try:
        # Fast repo check. If this fails or returns non-"true", we're not in a repo.
        inside = _run(["git", "rev-parse", "--is-inside-work-tree"])
        if inside != "true":
            return fallback

        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or None

        porcelain = _run(["git", "status", "--porcelain"])
        if porcelain is None:
            uncommitted = 0
        else:
            uncommitted = sum(1 for line in porcelain.splitlines() if line.strip())

        last_commit = _run(["git", "log", "-1", "--pretty=%h %s"]) or None

        ahead = 0
        behind = 0
        # --left-right --count @{u}...HEAD prints "<behind>\t<ahead>".
        counts = _run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"])
        if counts:
            try:
                parts = counts.split()
                if len(parts) >= 2:
                    behind = int(parts[0])
                    ahead = int(parts[1])
            except Exception:
                ahead, behind = 0, 0

        return {
            "is_repo": True,
            "branch": branch,
            "uncommitted": uncommitted,
            "last_commit": last_commit,
            "ahead": ahead,
            "behind": behind,
            "clean": uncommitted == 0,
        }
    except Exception:
        return fallback


def _format_git_line(git: dict) -> str:
    """Render the git context dict into a single compact context line."""
    try:
        if not git or not git.get("is_repo"):
            return "- Git: not a git repo"

        branch = git.get("branch") or "detached"
        parts = [f"branch={branch}"]

        if git.get("clean"):
            parts.append("clean")
        else:
            parts.append(f"{git.get('uncommitted', 0)} uncommitted")

        last_commit = git.get("last_commit")
        if last_commit:
            # Split once so we can quote the subject while keeping the hash bare.
            split = last_commit.split(" ", 1)
            if len(split) == 2:
                sha, subject = split
                # Trim absurdly long subjects to keep the line compact.
                if len(subject) > 60:
                    subject = subject[:57] + "..."
                parts.append(f'last={sha} "{subject}"')
            else:
                parts.append(f"last={last_commit}")

        ahead = int(git.get("ahead") or 0)
        behind = int(git.get("behind") or 0)
        if ahead or behind:
            parts.append(f"\u2191{ahead} \u2193{behind}")

        return "- Git: " + ", ".join(parts)
    except Exception:
        return "- Git: not a git repo"


def _build_additional_context(cwd: str, session_id: str = "unknown", agent_type: str = "unknown") -> str:
    """Compose the additionalContext string injected into the sub-agent.

    For heavy agent types (see HEAVY_AGENT_TYPES), builds the full ~1600-char
    block including vault keys, skills, and model arsenal.

    For all other types (simple validators, explorers, checkers, unknown), builds
    a minimal ~250-char block containing only the output contract + project + git.
    This saves tokens for agents that don't need the full harness context.
    """
    try:
        project_path = Path(cwd) if cwd and cwd != "unknown" else Path.cwd()
    except Exception:
        project_path = Path.cwd()
    project_name = project_path.name or str(project_path)

    git_line = _format_git_line(_get_git_context(str(project_path)))

    # Shared header — output contract + project/git/session (always included)
    header_lines = [
        "## Sub-agent context",
        # Mandatory output contract placed FIRST so truncation never drops it.
        "## Output contract (MANDATORY — end your final message with this block)",
        "## RESULT",
        "- Status: completed|failed|partial",
        "- Output: <what was produced>",
        "- Files changed: <list or none>",
        "- Next: <what the orchestrator should do next>",
        "",
        f"- Project: {project_name} ({project_path})",
        git_line,
        f"- Session: {session_id}",
    ]

    minimal = agent_type not in HEAVY_AGENT_TYPES

    if minimal:
        text = "\n".join(header_lines)
        # Hard cap at 300 chars for minimal context
        if len(text) > 300:
            text = text[:297] + "..."
        return text

    # Full context for heavy agent types
    vault_keys = _list_vault_keys(cwd=cwd if cwd and cwd != "unknown" else None)
    skills = _list_skills()
    status = _read_usage_status()
    rate_limited = bool(status.get("rate_limited"))
    ollama_model = status.get("model_override") or status.get("ollama_model") or "gpt-oss:120b"

    lines = header_lines[:]

    # Vault (compact)
    if vault_keys:
        preview = ", ".join(vault_keys[:10])
        more = "" if len(vault_keys) <= 10 else f" +{len(vault_keys) - 10}"
        lines.append(f"- Vault keys: {preview}{more} | get: `uv run ~/.claude/vault/vault.py get KEY`")
    else:
        lines.append("- Vault: empty | `uv run ~/.claude/vault/vault.py get KEY`")

    # Skills (compact)
    if skills:
        preview = ", ".join(skills[:20])
        more = "" if len(skills) <= 20 else f" +{len(skills) - 20}"
        lines.append(f"- Skills: {preview}{more}")

    # Rate limit / model routing hint with full arsenal
    if rate_limited:
        lines.append(
            f"- Claude RATE-LIMITED — primary override: `{ollama_model}`"
        )
    else:
        lines.append("- Claude available (primary). Ollama cloud ready as fallback.")
    lines.append(
        "- Full model arsenal (use ~/.claude/scripts/ollama_cloud.py chat <model> '<prompt>'):\n"
        "  T1-heavy: kimi-k2:1t, qwen3-coder:480b, gpt-oss:120b, deepseek-v3.1:671b\n"
        "  T2-code:  kimi-k2-thinking, devstral-small-2:24b, qwen3-coder-next\n"
        "  T3-fast:  ministral-3:14b, gemma3:27b\n"
        "  routing:  uv run ~/.claude/scripts/model_selector.py select <score 0-100> <coding|thinking|general|fast>"
    )

    text = "\n".join(lines)
    # Hard cap to ~1600 chars — contract is at top, so tail truncation is safe.
    if len(text) > 1600:
        text = text[:1597] + "..."
    return text


def _write_env_file(cwd: str, session_id: str) -> str | None:
    """Write a CLAUDE_ENV_FILE that injects CLAUDE_PROJECT_DIR into the sub-agent.

    The harness reads the file referenced by `CLAUDE_ENV_FILE` in the hook
    response and exports those vars into the spawned sub-agent's environment.
    This guarantees the sub-agent sees the same project directory as the
    parent session, even if its own cwd gets reset between bash calls.

    Returns the absolute path to the env file on success, or None on failure.
    """
    try:
        if not cwd or cwd == "unknown":
            return None
        env_dir = DATA_DIR / "subagent_env"
        env_dir.mkdir(parents=True, exist_ok=True)
        safe_session = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:32] or "unknown"
        env_file = env_dir / f"{safe_session}.env"
        lines = [
            f"CLAUDE_PROJECT_DIR={cwd}",
            f"CLAUDE_SESSION_ID={session_id}",
        ]
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(env_file)
    except Exception:
        return None


def _emit_output(additional_context: str, env_file: str | None = None) -> None:
    """Always emit a hookSpecificOutput JSON object to stdout."""
    hook_specific: dict = {
        "hookEventName": "SubagentStart",
        "additionalContext": additional_context,
    }
    if env_file:
        hook_specific["envFile"] = env_file
    output: dict = {"hookSpecificOutput": hook_specific}
    if env_file:
        # Top-level CLAUDE_ENV_FILE for harnesses that read it there.
        output["CLAUDE_ENV_FILE"] = env_file
    try:
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()
    except Exception:
        pass


def main() -> None:
    additional_context = ""
    env_file: str | None = None
    try:
        # Read the hook payload from stdin. If stdin is empty/invalid, still
        # emit a valid (possibly empty-context) response.
        try:
            raw = sys.stdin.read()
            input_data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, ValueError):
            input_data = {}

        session_id = input_data.get("session_id", "unknown")
        agent_id = input_data.get("agent_id", "unknown")
        agent_type = input_data.get("agent_type", "unknown")
        cwd = input_data.get("cwd") or os.getcwd()
        permission_mode = input_data.get("permission_mode", "unknown")
        timestamp = datetime.now().isoformat()

        # 1. Append full event to ~/.claude/logs/subagent_start.jsonl
        log_record = {
            "timestamp": timestamp,
            "event": "subagent_start",
            "session_id": session_id,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "cwd": cwd,
            "permission_mode": permission_mode,
        }
        _append_jsonl(LOG_PATH, log_record)

        # 2. Append compact entry to ~/.claude/data/agent_registry.jsonl
        # Detect backend from usage_status.json
        backend = "claude"
        try:
            status_path = DATA_DIR / "usage_status.json"
            if status_path.exists():
                status = json.loads(status_path.read_text())
                if status.get("rate_limited"):
                    override = status.get("model_override") or ""
                    backend = f"ollama:{override}" if override else "ollama"
        except Exception:
            pass

        registry_record = {
            "event": "start",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "cwd": cwd,
            "backend": backend,
            "timestamp": timestamp,
        }
        _append_jsonl(REGISTRY_PATH, registry_record)

        # 3. Build injected context for the sub-agent
        additional_context = _build_additional_context(cwd, session_id, agent_type=agent_type)

        # 4. Write CLAUDE_ENV_FILE so the sub-agent inherits CLAUDE_PROJECT_DIR
        env_file = _write_env_file(cwd, session_id)

    except Exception:
        # Swallow everything; we must still produce a valid output and exit 0.
        additional_context = additional_context or ""
    finally:
        _emit_output(additional_context, env_file=env_file)
        sys.exit(0)


if __name__ == "__main__":
    main()
