#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
log_tail.py — Tail and pretty-print Claude Code hook logs and session events.

Follows hook stderr output, session JSONL transcripts, or the agent registry
in real-time. Much easier than raw `tail -f`.

Usage:
  uv run ~/.claude/scripts/log_tail.py hooks          # tail all hook stderr logs
  uv run ~/.claude/scripts/log_tail.py agents         # tail agent registry (live)
  uv run ~/.claude/scripts/log_tail.py session        # tail the latest session transcript
  uv run ~/.claude/scripts/log_tail.py session <id>   # tail a specific session
  uv run ~/.claude/scripts/log_tail.py --last N       # show last N lines then follow
"""
__version__ = "2026.04.20.1"


import argparse
import json
import sys
import time
from pathlib import Path

HOME   = Path.home()
CLAUDE = HOME / ".claude"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

EVENT_COLORS = {
    "start":           GREEN,
    "stop":            CYAN,
    "task_completed":  BLUE,
    "error":           RED,
    "warn":            YELLOW,
}

ROLE_COLORS = {
    "assistant": CYAN,
    "user":      GREEN,
    "system":    DIM,
    "tool":      YELLOW,
}


def _format_agent_line(line: str) -> str:
    try:
        e = json.loads(line)
    except Exception:
        return line
    event  = e.get("event", "?")
    color  = EVENT_COLORS.get(event, RESET)
    ts     = e.get("timestamp", "")[:19]
    aid    = str(e.get("agent_id", ""))[:12]
    atype  = str(e.get("agent_type", ""))[:14]
    summary = str(e.get("result_summary", ""))[:80]
    return f"{DIM}{ts}{RESET}  {color}{event:<6}{RESET}  {aid:<12}  {atype:<14}  {DIM}{summary}{RESET}"


def _format_session_line(line: str) -> str:
    try:
        e = json.loads(line)
    except Exception:
        return line

    ts   = e.get("timestamp", "")[:19]
    role = str(e.get("type") or (e.get("message", {}) or {}).get("role") or e.get("role") or "?")
    color = ROLE_COLORS.get(role, RESET)

    content = e.get("content") or (e.get("message", {}) or {}).get("content") or ""
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("text") or c.get("input") or ""
                if t:
                    parts.append(str(t)[:120])
        content = " | ".join(parts)
    content = str(content)[:120].replace("\n", " ")

    usage = e.get("usage") or (e.get("message", {}) or {}).get("usage")
    usage_str = ""
    if isinstance(usage, dict):
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        usage_str = f"  {DIM}[{inp}→{out}]{RESET}"

    return f"{DIM}{ts}{RESET}  {color}{role:<10}{RESET}  {content}{usage_str}"


def tail_file(path: Path, last: int, formatter, follow: bool = True) -> None:
    if not path.exists():
        print(f"{RED}File not found: {path}{RESET}")
        sys.exit(1)

    lines = path.read_text(errors="replace").splitlines()
    for line in lines[-last:]:
        if line.strip():
            print(formatter(line))

    if not follow:
        return

    print(f"\n{DIM}--- following {path.name} ---{RESET}\n")
    with path.open("r", errors="replace") as f:
        f.seek(0, 2)  # seek to end
        while True:
            line = f.readline()
            if line:
                stripped = line.strip()
                if stripped:
                    print(formatter(stripped))
                    sys.stdout.flush()
            else:
                time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tail Claude Code logs")
    parser.add_argument("target", nargs="?", default="agents",
                        choices=["agents", "session", "hooks"],
                        help="What to tail: agents, session, or hooks")
    parser.add_argument("session_id", nargs="?", help="Specific session ID (for 'session' target)")
    parser.add_argument("--last",   type=int, default=20, help="Show last N lines before following")
    parser.add_argument("--no-follow", action="store_true", help="Print and exit (no follow)")
    args = parser.parse_args()

    follow = not args.no_follow

    if args.target == "agents":
        reg = CLAUDE / "data" / "agent_registry.jsonl"
        if not reg.exists():
            reg.parent.mkdir(parents=True, exist_ok=True)
            reg.touch()
        print(f"{BOLD}Agent Registry{RESET}  {DIM}{reg}{RESET}\n")
        tail_file(reg, args.last, _format_agent_line, follow)

    elif args.target == "session":
        if args.session_id:
            matches = list(CLAUDE.glob(f"projects/**/{args.session_id}*.jsonl"))
            if not matches:
                print(f"Session not found: {args.session_id}")
                sys.exit(1)
            path = matches[0]
        else:
            all_j = sorted(CLAUDE.glob("projects/**/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
            if not all_j:
                print("No session transcripts found.")
                sys.exit(1)
            path = all_j[0]
        print(f"{BOLD}Session: {path.stem}{RESET}  {DIM}{path}{RESET}\n")
        tail_file(path, args.last, _format_session_line, follow)

    elif args.target == "hooks":
        log_files = sorted(CLAUDE.glob("hooks/validators/*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not log_files:
            print(f"{YELLOW}No hook log files found in ~/.claude/hooks/validators/*.log{RESET}")
            sys.exit(0)
        # Show last N lines from most recent
        path = log_files[0]
        print(f"{BOLD}Hook log: {path.name}{RESET}  {DIM}{path}{RESET}\n")
        tail_file(path, args.last, lambda l: l, follow)


if __name__ == "__main__":
    main()
