#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
UserPromptSubmit Hook — GOTCHA Framework Integration

Fires before Claude processes the user's prompt. Responsibilities:
1. Append the prompt to a JSONL log (append-only, never reads back)
2. Track prompt count in stats-cache.json for the status line
3. Store the last prompt text for status line display
4. Optionally generate an agent name for the session
5. Inject additionalContext if --add-context is provided

Design rules:
- Always exits 0 — never blocks prompt submission.
- Uses JSONL (append-only) so the log never needs to be read in full.
- All paths are absolute (never rely on cwd).
- Stats update is best-effort; failure is silently swallowed.
"""
__version__ = "2026.04.20.3"

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()
except ImportError:
    pass


HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
LOG_DIR = CLAUDE_DIR / "logs"
DATA_DIR = CLAUDE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
STATS_CACHE = DATA_DIR / "stats-cache.json"
LAST_PROMPT_FILE = DATA_DIR / "last_prompt.txt"


# ──────────────────────────────────────────────────────────────────────────────
# Logging — JSONL append (never re-read the whole file)
# ──────────────────────────────────────────────────────────────────────────────

def log_prompt_jsonl(input_data: dict) -> None:
    """Append one JSONL line to user_prompt_submit.jsonl. Never raises."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {**input_data, "logged_at": datetime.now().isoformat()}
        with (LOG_DIR / "user_prompt_submit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Stats — increment daily prompt counter for status line
# ──────────────────────────────────────────────────────────────────────────────

def bump_prompt_count() -> None:
    """Increment today's prompt count in stats-cache.json. Never raises."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        stats: dict = {}
        if STATS_CACHE.exists():
            try:
                stats = json.loads(STATS_CACHE.read_text(encoding="utf-8"))
            except Exception:
                stats = {}
        daily = stats.setdefault("dailyActivity", {})
        day = daily.setdefault(today, {"prompts": 0, "tool_uses": 0})
        day["prompts"] = int(day.get("prompts", 0)) + 1
        STATS_CACHE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Last-prompt store — for status line display
# ──────────────────────────────────────────────────────────────────────────────

def store_last_prompt(prompt: str) -> None:
    """Write the prompt (truncated) to last_prompt.txt. Never raises."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LAST_PROMPT_FILE.write_text(prompt[:500], encoding="utf-8")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Session data — track prompts per session
# ──────────────────────────────────────────────────────────────────────────────

def manage_session_data(session_id: str, prompt: str, name_agent: bool = False) -> None:
    """Append prompt to session JSON; optionally generate an agent name."""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        session_file = SESSIONS_DIR / f"{session_id}.json"
        session_data: dict
        if session_file.exists():
            try:
                session_data = json.loads(session_file.read_text(encoding="utf-8"))
            except Exception:
                session_data = {"session_id": session_id, "prompts": []}
        else:
            session_data = {"session_id": session_id, "prompts": []}

        session_data.setdefault("prompts", []).append(prompt[:200])

        if name_agent and "agent_name" not in session_data:
            _try_name_agent(session_data)

        session_file.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _try_name_agent(session_data: dict) -> None:
    """Best-effort: ask Ollama then Anthropic for a single-word agent name."""
    import subprocess

    scripts = [
        CLAUDE_DIR / "hooks" / "utils" / "llm" / "ollama.py",
        CLAUDE_DIR / "hooks" / "utils" / "llm" / "anth.py",
    ]
    timeouts = [5, 10]

    for script, timeout in zip(scripts, timeouts):
        if not script.exists():
            continue
        try:
            result = subprocess.run(
                ["uv", "run", str(script), "--agent-name"],
                capture_output=True, text=True, timeout=timeout,
            )
            name = result.stdout.strip()
            if result.returncode == 0 and name and name.isalnum() and " " not in name:
                session_data["agent_name"] = name
                return
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Output helpers
# ──────────────────────────────────────────────────────────────────────────────

def emit_context(context: str = "") -> None:
    """Always emit a valid UserPromptSubmit hookSpecificOutput."""
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }), flush=True)
    except Exception:
        pass


def emit_block(reason: str) -> None:
    """Block the prompt with a user-visible reason."""
    try:
        print(json.dumps({"decision": "block", "reason": reason}), flush=True)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        parser = argparse.ArgumentParser(
            description="UserPromptSubmit hook for Claude Code - processes user prompts"
        )
        parser.add_argument("--validate", action="store_true",
                            help="Enable prompt validation (currently no-op)")
        parser.add_argument("--log-only", action="store_true",
                            help="Only log prompts; skip session management")
        parser.add_argument("--store-last-prompt", action="store_true",
                            help="Write prompt to last_prompt.txt for status line")
        parser.add_argument("--name-agent", action="store_true",
                            help="Generate a single-word agent name for the session")
        parser.add_argument("--add-context", type=str, default=None,
                            help="Inject this string as additionalContext")
        args = parser.parse_args()

        try:
            raw = sys.stdin.read()
            input_data = json.loads(raw) if raw.strip() else {}
        except Exception:
            input_data = {}

        session_id = str(input_data.get("session_id") or "unknown")
        prompt = str(input_data.get("prompt") or "")

        # 1. Append to JSONL log (replaces the old read-entire-JSON approach)
        log_prompt_jsonl(input_data)

        # 2. Bump daily prompt count for status line
        bump_prompt_count()

        # 3. Store last prompt text for status line display
        if args.store_last_prompt:
            store_last_prompt(prompt)

        # 4. Session tracking / agent naming
        if not args.log_only and (args.store_last_prompt or args.name_agent):
            manage_session_data(session_id, prompt, name_agent=args.name_agent)

        # 5. Emit output
        if args.add_context:
            emit_context(args.add_context)
        else:
            emit_context()

        return 0

    except Exception:
        # Last-resort safety: never block the prompt
        try:
            emit_context()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
