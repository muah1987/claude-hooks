#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
Agent Registry Viewer

Inspect the agent-lifecycle registry at ~/.claude/data/agent_registry.jsonl.

The registry is a JSON Lines file — one event per line — written by
hooks such as SubagentStart, SubagentStop, and TaskCompleted. Each
entry has at minimum:

    {
      "timestamp": ISO-8601 string,
      "event":     "start" | "stop" | "task_completed" | ...,
      "agent_id":  opaque id,
      "agent_type": teammate/subagent name,
      "session_id": parent session identifier,
      "result_summary": free-form summary (stop/task_completed only)
    }

Commands
--------
    agents.py list      Show last 20 events in a table.
    agents.py active    Show agents with an unmatched "start" event + elapsed time.
    agents.py results   Show last 10 "stop" events with their summary.
    agents.py session   Show all agents grouped by session, with start/stop pairs.
    agents.py tree      Show agent tree for the current (or specified) session.
    agents.py clear     Truncate the registry file.

Stdlib only; no third-party dependencies.
"""

from __future__ import annotations
__version__ = "2026.04.20.1"

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_FILE = Path.home() / ".claude" / "data" / "agent_registry.jsonl"
RESULTS_DIR   = Path.home() / ".claude" / "data" / "results"


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

def load_events() -> list[dict[str, Any]]:
    """Return every event in the registry, oldest-first. Skips malformed lines."""
    if not REGISTRY_FILE.exists():
        return []
    events: list[dict[str, Any]] = []
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return events


# ---------------------------------------------------------------------------
# Table rendering (pure ASCII, no external deps)
# ---------------------------------------------------------------------------

def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "~"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "(no rows)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return "  ".join(
            cells[i].ljust(widths[i]) if i < len(widths) else cells[i]
            for i in range(len(headers))
        )

    sep = "  ".join("-" * w for w in widths)
    lines = [fmt_row(headers), sep]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _short_id(event: dict[str, Any], chars: int = 8) -> str:
    agent_id = str(event.get("agent_id", "") or "")
    return agent_id[:chars] if agent_id else "-"


def _summary(event: dict[str, Any], width: int = 50) -> str:
    raw = (
        event.get("result_summary")
        or event.get("task_subject")
        or event.get("summary")
        or ""
    )
    raw = str(raw).replace("\n", " ").replace("\r", " ").strip()
    return _truncate(raw, width) if raw else "-"


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse an ISO timestamp string, returning a UTC-aware datetime or None."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _elapsed(start_ts: str) -> str:
    """Return human-readable elapsed time since start_ts."""
    dt = _parse_ts(start_ts)
    if dt is None:
        return "?"
    now = datetime.now(timezone.utc)
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60}m"


def _duration_between(start_ts: str, stop_ts: str) -> str:
    """Return human-readable duration between two ISO timestamps."""
    s = _parse_ts(start_ts)
    e = _parse_ts(stop_ts)
    if s is None or e is None:
        return "?"
    secs = max(0, int((e - s).total_seconds()))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60}m"


def _result_status(agent_id: str) -> str:
    """Read stored status from results/<agent_id>.json if available."""
    try:
        safe = "".join(c for c in agent_id if c.isalnum() or c in ("-", "_"))
        p = RESULTS_DIR / f"{safe}.json"
        if p.exists():
            data = json.loads(p.read_text())
            return str(data.get("status", "?"))
    except Exception:
        pass
    return "?"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(limit: int = 20) -> int:
    events = load_events()
    if not events:
        print(f"No events in {REGISTRY_FILE}")
        return 0

    recent = events[-limit:]
    headers = ["timestamp", "event", "agent_id", "agent_type", "session", "summary"]
    rows = [
        [
            str(e.get("timestamp", "-"))[:19],
            str(e.get("event", "-")),
            _short_id(e),
            str(e.get("agent_type", "-") or "-"),
            str(e.get("session_id", "-") or "-")[:8],
            _summary(e, 50),
        ]
        for e in recent
    ]
    print(f"Showing last {len(recent)} of {len(events)} events from {REGISTRY_FILE}")
    print()
    print(render_table(headers, rows))
    return 0


STALE_HOURS = 2  # agents older than this are considered stale/timed-out


def _is_stale(ts_str: str, max_hours: float = STALE_HOURS) -> bool:
    dt = _parse_ts(ts_str)
    if dt is None:
        return True
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    return secs > max_hours * 3600


def cmd_active(show_stale: bool = False) -> int:
    """Show agents that have a 'start' but no subsequent 'stop', with elapsed time.

    Agents older than STALE_HOURS are hidden by default (--stale to show them).
    Stale orphans are auto-expired before display so they never accumulate.
    """
    cmd_expire(STALE_HOURS, silent=True)  # auto-clean ghosts before showing active list
    events = load_events()
    if not events:
        print(f"No events in {REGISTRY_FILE}")
        return 0

    open_starts: dict[str, dict[str, Any]] = {}
    for e in events:
        agent_id = str(e.get("agent_id", "") or "")
        if not agent_id:
            continue
        event_type = str(e.get("event", "")).lower()
        if event_type == "start":
            open_starts[agent_id] = e
        elif event_type == "stop":
            open_starts.pop(agent_id, None)

    if not open_starts:
        print("No active agents (all starts have matching stops).")
        return 0

    fresh = {aid: e for aid, e in open_starts.items()
             if not _is_stale(str(e.get("timestamp", "")))}
    stale = {aid: e for aid, e in open_starts.items()
             if _is_stale(str(e.get("timestamp", "")))}

    shown = open_starts if show_stale else fresh

    if not shown:
        print(f"No active agents. ({len(stale)} stale ghost entries hidden — run `expire` to clean.)")
        return 0

    headers = ["started_at", "elapsed", "agent_id", "agent_type", "session", "backend"]
    rows = []
    for agent_id, e in sorted(shown.items(), key=lambda x: x[1].get("timestamp", "")):
        ts = str(e.get("timestamp", "-"))
        rows.append([
            ts[:19],
            _elapsed(ts),
            _short_id(e),
            str(e.get("agent_type", "-") or "-"),
            str(e.get("session_id", "-") or "-")[:8],
            str(e.get("backend", "claude")),
        ])
    label = "Active agents" if not show_stale else "All unmatched agents (incl. stale)"
    print(f"{label}: {len(shown)}" + (f"  ({len(stale)} stale hidden)" if not show_stale and stale else ""))
    print()
    print(render_table(headers, rows))
    return 0


def cmd_expire(max_hours: float = STALE_HOURS, silent: bool = False) -> int:
    """Write synthetic 'stop' entries for orphaned starts older than max_hours.

    This cleans ghost entries from `active` without losing history.
    Pass silent=True to suppress output (used by auto-expire in cmd_active).
    """
    events = load_events()
    open_starts: dict[str, dict[str, Any]] = {}
    for e in events:
        agent_id = str(e.get("agent_id", "") or "")
        if not agent_id:
            continue
        if str(e.get("event", "")).lower() == "start":
            open_starts[agent_id] = e
        elif str(e.get("event", "")).lower() == "stop":
            open_starts.pop(agent_id, None)

    expired = {aid: e for aid, e in open_starts.items()
               if _is_stale(str(e.get("timestamp", "")), max_hours)}

    if not expired:
        if not silent:
            print(f"No stale agents found (threshold: {max_hours}h).")
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    written = 0
    try:
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, "a", encoding="utf-8") as f:
            for aid, start_e in expired.items():
                synthetic_stop = {
                    "event": "stop",
                    "agent_id": aid,
                    "agent_type": str(start_e.get("agent_type", "unknown") or "unknown"),
                    "session_id": str(start_e.get("session_id", "") or ""),
                    "result_summary": "[expired: no stop event received]",
                    "result_block": {"status": "timed_out"},
                    "timestamp": now_iso,
                    "synthetic": True,
                }
                f.write(json.dumps(synthetic_stop) + "\n")
                written += 1
    except Exception as exc:
        if not silent:
            print(f"Error writing synthetic stops: {exc}")
        return 1

    if not silent:
        print(f"Expired {written} stale agent(s) (>{max_hours}h with no stop event).")
    return 0


def cmd_results(limit: int = 10) -> int:
    """Show the last `limit` stop events with summaries and resolved status."""
    events = load_events()
    stops = [e for e in events if str(e.get("event", "")).lower() == "stop"]
    if not stops:
        print("No 'stop' events found in the registry.")
        return 0

    recent = stops[-limit:]
    headers = ["timestamp", "agent_id", "agent_type", "status", "result_summary"]
    rows = []
    for e in recent:
        aid = str(e.get("agent_id", "") or "")
        # Prefer result_block status > stored file status > fallback
        rb_status = ""
        try:
            rb = e.get("result_block") or {}
            rb_status = str(rb.get("status", "") or "")
        except Exception:
            pass
        status = rb_status if rb_status and rb_status != "unknown" else _result_status(aid)
        rows.append([
            str(e.get("timestamp", "-"))[:19],
            _short_id(e),
            str(e.get("agent_type", "-") or "-"),
            status or "?",
            _summary(e, 70),
        ])
    print(f"Last {len(recent)} stop events (of {len(stops)} total)")
    print()
    print(render_table(headers, rows))
    return 0


def cmd_session(session_id: str | None = None) -> int:
    """Show all agents grouped by session, with start/stop pairs and duration."""
    events = load_events()
    if not events:
        print(f"No events in {REGISTRY_FILE}")
        return 0

    # Group events by session_id
    by_session: dict[str, list[dict]] = {}
    for e in events:
        sid = str(e.get("session_id", "") or "unknown")
        by_session.setdefault(sid, []).append(e)

    # Filter to requested session or show all (most recent 5)
    if session_id:
        # Find by prefix match
        matched = [s for s in by_session if s.startswith(session_id)]
        if not matched:
            print(f"No session matching '{session_id}'")
            return 0
        sessions_to_show = matched
    else:
        # Pick the 5 most recent sessions by their latest event timestamp
        def _latest_ts(sid: str) -> str:
            return max((e.get("timestamp", "") for e in by_session[sid]), default="")
        sessions_to_show = sorted(by_session.keys(), key=_latest_ts, reverse=True)[:5]

    for sid in sessions_to_show:
        evts = by_session[sid]
        starts = {e["agent_id"]: e for e in evts if e.get("event") == "start" and e.get("agent_id")}
        stops  = {e["agent_id"]: e for e in evts if e.get("event") == "stop"  and e.get("agent_id")}

        total = len(starts)
        done  = len([a for a in starts if a in stops])
        active = total - done

        print(f"\n{'─' * 70}")
        print(f"Session: {sid[:16]}…  |  {total} agents  |  {done} done  |  {active} active")
        print(f"{'─' * 70}")

        if not starts:
            print("  (no agent start events)")
            continue

        headers = ["agent_id", "agent_type", "backend", "started", "duration", "status"]
        rows = []
        for aid, start_e in sorted(starts.items(), key=lambda x: x[1].get("timestamp", "")):
            stop_e = stops.get(aid)
            start_ts = str(start_e.get("timestamp", ""))
            if stop_e:
                dur = _duration_between(start_ts, str(stop_e.get("timestamp", "")))
                rb = stop_e.get("result_block") or {}
                status = str(rb.get("status", "") or _result_status(aid) or "?")
            else:
                dur = _elapsed(start_ts) + " (running)"
                status = "active"
            rows.append([
                _short_id(start_e),
                str(start_e.get("agent_type", "-") or "-"),
                str(start_e.get("backend", "claude")),
                start_ts[:19],
                dur,
                status,
            ])
        print(render_table(headers, rows))

    return 0


def cmd_tree(session_id: str | None = None) -> int:
    """Show the agent tree for a session — parent session with its sub-agents."""
    events = load_events()
    if not events:
        print(f"No events in {REGISTRY_FILE}")
        return 0

    # Resolve session to show
    if not session_id:
        # Most recent session_id
        for e in reversed(events):
            sid = str(e.get("session_id", "") or "")
            if sid:
                session_id = sid
                break
    if not session_id:
        print("No sessions found.")
        return 0

    # Collect agents for this session (prefix match)
    relevant = [e for e in events if str(e.get("session_id", "") or "").startswith(session_id[:16])]

    starts = {e["agent_id"]: e for e in relevant if e.get("event") == "start" and e.get("agent_id")}
    stops  = {e["agent_id"]: e for e in relevant if e.get("event") == "stop"  and e.get("agent_id")}

    print(f"\nAgent tree for session: {session_id[:32]}")
    print(f"  {len(starts)} sub-agents  |  {len(stops)} completed\n")

    for aid, start_e in sorted(starts.items(), key=lambda x: x[1].get("timestamp", "")):
        stop_e = stops.get(aid)
        start_ts = str(start_e.get("timestamp", ""))
        agent_type = str(start_e.get("agent_type", "unknown") or "unknown")
        backend = str(start_e.get("backend", "claude"))

        if stop_e:
            dur = _duration_between(start_ts, str(stop_e.get("timestamp", "")))
            rb = stop_e.get("result_block") or {}
            status = str(rb.get("status", "") or _result_status(aid) or "done")
            summary = _summary(stop_e, 60)
            status_icon = "✔" if status == "completed" else ("✘" if status == "failed" else "~")
        else:
            dur = _elapsed(start_ts) + " …"
            status = "running"
            status_icon = "▶"
            summary = "-"

        print(f"  {status_icon} [{agent_type:12s}] {aid[:12]}  backend={backend:10s} dur={dur}")
        if summary and summary != "-":
            print(f"      └─ {summary}")

    return 0


def cmd_clear() -> int:
    if not REGISTRY_FILE.exists():
        print(f"Nothing to clear; {REGISTRY_FILE} does not exist.")
        return 0
    with open(REGISTRY_FILE, "w", encoding="utf-8"):
        pass
    print(f"Cleared {REGISTRY_FILE}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents.py",
        description="Inspect the Claude agent registry (~/.claude/data/agent_registry.jsonl).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Show last 20 agent events in a table.")
    p_list.add_argument("--limit", type=int, default=20,
                        help="Number of events to show (default: 20).")

    p_active = sub.add_parser("active", help="Show agents with a start but no stop, with elapsed time.")
    p_active.add_argument("--stale", action="store_true",
                          help=f"Also show ghost entries older than {STALE_HOURS}h (hidden by default).")

    p_expire = sub.add_parser("expire", help=f"Write synthetic stops for orphaned starts >{STALE_HOURS}h old.")
    p_expire.add_argument("--hours", type=float, default=STALE_HOURS,
                          help=f"Staleness threshold in hours (default: {STALE_HOURS}).")

    p_results = sub.add_parser("results", help="Show last 10 stop events with result_summary.")
    p_results.add_argument("--limit", type=int, default=10,
                           help="Number of stop events to show (default: 10).")

    p_session = sub.add_parser("session", help="Show agents grouped by session with duration.")
    p_session.add_argument("session_id", nargs="?", default=None,
                           help="Session ID prefix to filter (default: last 5 sessions).")

    p_tree = sub.add_parser("tree", help="Show agent hierarchy tree for a session.")
    p_tree.add_argument("session_id", nargs="?", default=None,
                        help="Session ID prefix (default: most recent session).")

    sub.add_parser("clear", help="Truncate the registry file.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list(limit=args.limit)
    if args.command == "active":
        return cmd_active(show_stale=getattr(args, "stale", False))
    if args.command == "expire":
        return cmd_expire(max_hours=getattr(args, "hours", STALE_HOURS))
    if args.command == "results":
        return cmd_results(limit=args.limit)
    if args.command == "session":
        return cmd_session(session_id=args.session_id)
    if args.command == "tree":
        return cmd_tree(session_id=args.session_id)
    if args.command == "clear":
        return cmd_clear()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
