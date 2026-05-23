#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
context_stats.py — Analyse token usage patterns across Claude Code sessions.

Shows per-session context window utilisation, compaction events, cache hit rate,
and which sessions are approaching the limit.

Usage:
  uv run ~/.claude/scripts/context_stats.py              # last 10 sessions
  uv run ~/.claude/scripts/context_stats.py --all        # all sessions
  uv run ~/.claude/scripts/context_stats.py --session <id>   # one session
  uv run ~/.claude/scripts/context_stats.py --json       # machine-readable
"""
__version__ = "2026.04.20.1"


import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

HOME   = Path.home()
CLAUDE = HOME / ".claude"

# Approximate context window sizes per model
CTX_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-7":   200_000,
    "claude-haiku-4-5":  200_000,
    "default":           200_000,
}

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _bar(pct: float, width: int = 12) -> str:
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if pct >= 85:
        color = RED
    elif pct >= 60:
        color = YELLOW
    else:
        color = GREEN
    return f"{color}{bar}{RESET}"


def analyse_session(jsonl: Path) -> dict:
    """Parse a single session transcript and return stats."""
    result: dict = {
        "session_id": jsonl.stem,
        "path": str(jsonl),
        "turns": 0,
        "compactions": 0,
        "max_input": 0,
        "last_input": 0,
        "total_output": 0,
        "total_cache_read": 0,
        "total_cache_write": 0,
        "model": "default",
        "first_ts": "",
        "last_ts": "",
    }

    for line in jsonl.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = entry.get("timestamp", "")
        if ts:
            if not result["first_ts"] or ts < result["first_ts"]:
                result["first_ts"] = ts
            if ts > result["last_ts"]:
                result["last_ts"] = ts

        # Detect compactions
        etype = entry.get("type", "")
        if etype == "system" and "compact" in str(entry.get("content", "")).lower():
            result["compactions"] += 1

        # Find usage
        usage = entry.get("usage") or entry.get("message", {}).get("usage") if isinstance(entry.get("message"), dict) else None
        if not isinstance(usage, dict):
            continue

        result["turns"] += 1
        model = entry.get("model") or (entry.get("message", {}).get("model") if isinstance(entry.get("message"), dict) else None) or "default"
        for known in CTX_WINDOWS:
            if known != "default" and known in str(model):
                result["model"] = known
                break

        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        cr  = int(usage.get("cache_read_input_tokens", 0) or 0)
        cw  = int(usage.get("cache_creation_input_tokens", 0) or 0)

        result["last_input"] = inp
        result["max_input"] = max(result["max_input"], inp)
        result["total_output"] += out
        result["total_cache_read"] += cr
        result["total_cache_write"] += cw

    ctx = CTX_WINDOWS.get(result["model"], CTX_WINDOWS["default"])
    result["ctx_window"] = ctx
    result["peak_pct"] = round(result["max_input"] / ctx * 100, 1) if ctx else 0
    result["last_pct"] = round(result["last_input"] / ctx * 100, 1) if ctx else 0
    total_cache = result["total_cache_read"] + result["total_cache_write"]
    result["cache_hit_rate"] = round(result["total_cache_read"] / total_cache * 100, 1) if total_cache else 0

    return result


def render(sessions: list[dict], use_json: bool) -> None:
    if use_json:
        print(json.dumps(sessions, indent=2))
        return

    print(f"\n{BOLD}Context Window Stats{RESET}  ({len(sessions)} session(s))\n")
    header = f"  {'Session':<20} {'Model':<14} {'Turns':>5} {'Peak%':>6} {'Last%':>6} {'Cache%':>7} {'Compact':>7}  Context"
    print(header)
    print("  " + "─" * 80)

    for s in sessions:
        date = s["first_ts"][:10] if s["first_ts"] else "?"
        model_short = s["model"].replace("claude-", "").replace("-20", "")[:13]
        bar = _bar(s["peak_pct"])
        compact_indicator = f"{RED}{s['compactions']}✗{RESET}" if s["compactions"] else f"{DIM}0{RESET}"
        print(
            f"  {s['session_id'][:18]:<20} "
            f"{model_short:<14} "
            f"{s['turns']:>5} "
            f"{s['peak_pct']:>5.1f}% "
            f"{s['last_pct']:>5.1f}% "
            f"{s['cache_hit_rate']:>6.1f}% "
            f"{compact_indicator:>7}  "
            f"{bar} {date}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code context window analyser")
    parser.add_argument("--all",     action="store_true", help="Show all sessions (default: last 10)")
    parser.add_argument("--session", help="Analyse a specific session ID or JSONL path")
    parser.add_argument("--json",    action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.session:
        p = Path(args.session)
        if not p.exists():
            # Try finding by session ID prefix
            matches = list(CLAUDE.glob(f"projects/**/{args.session}*.jsonl"))
            if not matches:
                print(f"Session not found: {args.session}")
                sys.exit(1)
            p = matches[0]
        render([analyse_session(p)], args.json)
        return

    all_jsonl = sorted(CLAUDE.glob("projects/**/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not args.all:
        all_jsonl = all_jsonl[:10]

    sessions = [analyse_session(f) for f in all_jsonl]
    sessions.sort(key=lambda s: s["first_ts"], reverse=True)
    render(sessions, args.json)


if __name__ == "__main__":
    main()
