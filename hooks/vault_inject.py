#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SessionStart hook: inject vault key list for the current project.

Tells Claude *which* secrets are available for the current project (keys
only — never values) and how to retrieve each one via the vault CLI.
Always exits 0 so it can never block a session start.
"""

from __future__ import annotations
__version__ = "2026.04.20.4"

import hashlib
import json
import os
import sys
from pathlib import Path

VAULT_ROOT = Path.home() / ".claude" / "vault"
PROJECTS_DIR = VAULT_ROOT / "projects"
VAULT_CLI = VAULT_ROOT / "vault.py"


def current_project_path() -> Path:
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(raw).resolve()


def project_id_for(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def emit_empty() -> None:
    # Silent no-op: nothing to inject.
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ""}}))


def build_context(project_path: Path, pid: str, keys: list[str]) -> str:
    lines = [
        "## Project vault",
        "",
        f"Project: `{project_path}`",
        f"Vault id: `{pid}`",
        "",
        "Available secret keys (values are encrypted — not shown):",
    ]
    for k in keys:
        lines.append(f"  - `{k}`")
    lines.extend(
        [
            "",
            "Retrieve a value with:",
            "",
            "```bash",
            f"uv run {VAULT_CLI} get KEY",
            "```",
            "",
            "Manage secrets with `vault.py add|delete|list|show|projects`.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdin.read()  # always consume stdin — Claude Code hangs if we don't
        project_path = current_project_path()
        pid = project_id_for(project_path)
        pdir = PROJECTS_DIR / pid
        secrets_path = pdir / "secrets.json"
        if not secrets_path.exists():
            emit_empty()
            return 0
        try:
            data = json.loads(secrets_path.read_text())
        except (OSError, json.JSONDecodeError):
            emit_empty()
            return 0
        if not isinstance(data, dict) or not data:
            emit_empty()
            return 0
        keys = sorted(str(k) for k in data.keys())
        context = build_context(project_path, pid, keys)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context,
                    }
                }
            )
        )
        return 0
    except Exception:  # noqa: BLE001 — never block the session
        try:
            emit_empty()
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        sys.exit(0)
