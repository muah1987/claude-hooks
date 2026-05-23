#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
cost_tracker.py — Estimate token cost from Claude Code session transcripts.

Reads JSONL transcript files from ~/.claude/projects/*/  and tallies
input/output/cache tokens per session, per model, and in total.
Applies Anthropic list prices so you see estimated USD spend.

Usage:
  uv run ~/.claude/scripts/cost_tracker.py              # all sessions
  uv run ~/.claude/scripts/cost_tracker.py --today      # today only
  uv run ~/.claude/scripts/cost_tracker.py --top 5      # top 5 most expensive sessions
  uv run ~/.claude/scripts/cost_tracker.py --json       # machine-readable output
"""
__version__ = "2026.04.20.1"


import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HOME   = Path.home()
CLAUDE = HOME / ".claude"

# Prices per 1M tokens (USD) — Anthropic list prices as of 2026-04
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6":   {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-7":     {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-haiku-4-5":    {"input": 0.80, "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "default":             {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
}

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _price(model: str, kind: str, tokens: int) -> float:
    p = PRICES.get(model) or PRICES["default"]
    return p.get(kind, 0) * tokens / 1_000_000


def _short_model(m: str) -> str:
    return m.replace("claude-", "").replace("-20", " ")


def scan_transcripts(today_only: bool) -> dict[str, dict]:
    """Walk all JSONL transcripts, sum token usage per session."""
    today_str = date.today().isoformat()
    sessions: dict[str, dict] = {}

    for jsonl in CLAUDE.glob("projects/**/*.jsonl"):
        session_id = jsonl.stem
        for line in jsonl.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp", "")
            if today_only and not ts.startswith(today_str):
                continue

            usage = None
            # Direct usage field
            if "usage" in entry:
                usage = entry["usage"]
            # Nested under message
            msg = entry.get("message", {})
            if isinstance(msg, dict) and "usage" in msg:
                usage = msg["usage"]

            if not isinstance(usage, dict):
                continue

            model = (
                entry.get("model")
                or (msg.get("model") if isinstance(msg, dict) else None)
                or "default"
            )
            # Normalise model name
            for known in PRICES:
                if known != "default" and known in model:
                    model = known
                    break

            s = sessions.setdefault(session_id, {
                "session_id": session_id,
                "model": model,
                "first_ts": ts,
                "input": 0, "output": 0,
                "cache_write": 0, "cache_read": 0,
                "cost": 0.0,
            })
            if s["first_ts"] > ts or not s["first_ts"]:
                s["first_ts"] = ts

            inp = int(usage.get("input_tokens", 0) or 0)
            out = int(usage.get("output_tokens", 0) or 0)
            cw  = int(usage.get("cache_creation_input_tokens", 0) or 0)
            cr  = int(usage.get("cache_read_input_tokens", 0) or 0)

            s["input"]       += inp
            s["output"]      += out
            s["cache_write"] += cw
            s["cache_read"]  += cr
            s["cost"] += (
                _price(model, "input", inp)
                + _price(model, "output", out)
                + _price(model, "cache_write", cw)
                + _price(model, "cache_read", cr)
            )

    return sessions


def render(sessions: dict[str, dict], top: int | None, use_json: bool) -> None:
    rows = sorted(sessions.values(), key=lambda r: r["cost"], reverse=True)
    if top:
        rows = rows[:top]

    if use_json:
        print(json.dumps(rows, indent=2))
        return

    total_cost  = sum(r["cost"] for r in sessions.values())
    total_in    = sum(r["input"] for r in sessions.values())
    total_out   = sum(r["output"] for r in sessions.values())
    total_cw    = sum(r["cache_write"] for r in sessions.values())
    total_cr    = sum(r["cache_read"] for r in sessions.values())

    print(f"\n{BOLD}Token Cost Estimate{RESET}")
    print(f"  {len(sessions)} session(s)  •  "
          f"in {total_in:,}  out {total_out:,}  "
          f"cache↑{total_cw:,} ↓{total_cr:,}  •  "
          f"{YELLOW}${total_cost:.4f} total{RESET}\n")

    if not rows:
        print("  (no token usage data found)")
        return

    print(f"  {'Session':<18} {'Model':<18} {'Input':>8} {'Output':>8} {'CacheR':>8} {'Cost':>8}  {'Date'}")
    print("  " + "─" * 78)
    for r in rows:
        dt = r["first_ts"][:10] if r["first_ts"] else "?"
        print(
            f"  {r['session_id'][:16]:<18} "
            f"{_short_model(r['model']):<18} "
            f"{r['input']:>8,} "
            f"{r['output']:>8,} "
            f"{r['cache_read']:>8,} "
            f"{CYAN}${r['cost']:>7.4f}{RESET}  "
            f"{dt}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code cost estimator")
    parser.add_argument("--today", action="store_true", help="Only count today's sessions")
    parser.add_argument("--top",   type=int, metavar="N", help="Show top N most expensive sessions")
    parser.add_argument("--json",  action="store_true", help="Output as JSON")
    args = parser.parse_args()

    sessions = scan_transcripts(today_only=args.today)
    render(sessions, top=args.top, use_json=args.json)


if __name__ == "__main__":
    main()
