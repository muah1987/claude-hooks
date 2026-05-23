#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
agent_results.py — Structured sub-agent result storage and retrieval.

Commands:
    store <agent_id> <status> <summary>
        Write a result to ~/.claude/data/results/<agent_id>.json as:
        {agent_id, status, summary, stored_at}

    get <agent_id>
        Print the stored result as JSON.

    list
        Show last 10 results: timestamp | agent_id (8 chars) | status |
        summary (60 chars).

    wait <agent_id> [--timeout 60]
        Poll ~/.claude/data/agent_registry.jsonl until agent_id appears
        in a "stop" event, then print its result_summary. Default timeout
        is 60 seconds.

    wait-all <id1> <id2> ... [--timeout 120]
        Poll until ALL given agent IDs have stop events. Prints one JSON
        line per agent as each one completes. Exits 0 when all complete,
        exit 1 on timeout with "error": "timeout" lines for stragglers.

Design:
    - Shebang uses `uv run --script` but also works as plain Python.
    - Stdlib only.
    - Always exits 0 (never blocks callers).
    - All paths rooted under ~/.claude/.
"""

from __future__ import annotations
__version__ = "2026.04.20.2"

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

CLAUDE_HOME = Path.home() / ".claude"
DATA_DIR = CLAUDE_HOME / "data"
RESULTS_DIR = DATA_DIR / "results"
AGENT_REGISTRY_PATH = DATA_DIR / "agent_registry.jsonl"


def _ensure_dirs() -> None:
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _now_iso() -> str:
    return datetime.now().isoformat()


def _result_path(agent_id: str) -> Path:
    # Sanitise: only allow safe characters in filename
    safe = "".join(c for c in agent_id if c.isalnum() or c in ("-", "_"))
    if not safe:
        safe = "unknown"
    return RESULTS_DIR / f"{safe}.json"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------
def cmd_store(agent_id: str, status: str, summary: str) -> int:
    _ensure_dirs()
    record = {
        "agent_id": agent_id,
        "status": status,
        "summary": summary,
        "stored_at": _now_iso(),
    }
    try:
        path = _result_path(agent_id)
        tmp = path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
        tmp.replace(path)
        print(f"stored: {path}")
    except OSError as e:
        print(f"store failed: {e}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------
def cmd_get(agent_id: str) -> int:
    path = _result_path(agent_id)
    if not path.exists():
        print(json.dumps({"error": "not_found", "agent_id": agent_id}))
        return 0
    try:
        with open(path, "r") as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e), "agent_id": agent_id}))
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)] + "…"


def cmd_list() -> int:
    _ensure_dirs()
    if not RESULTS_DIR.exists():
        print("no results yet")
        return 0

    files = sorted(
        RESULTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:10]

    if not files:
        print("no results yet")
        return 0

    header = f"{'timestamp':<26} {'agent_id':<10} {'status':<10} summary"
    print(header)
    print("-" * len(header))

    for path in files:
        try:
            with open(path, "r") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        ts = _truncate(str(rec.get("stored_at", "")), 25)
        aid = _truncate(str(rec.get("agent_id", "")), 8)
        status = _truncate(str(rec.get("status", "")), 10)
        summary = _truncate(str(rec.get("summary", "")), 60)
        print(f"{ts:<26} {aid:<10} {status:<10} {summary}")

    return 0


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------
def _find_stop_in_registry(agent_id: str) -> Optional[str]:
    """Return the result_summary for agent_id from a stop event, or None."""
    if not AGENT_REGISTRY_PATH.exists():
        return None
    try:
        with open(AGENT_REGISTRY_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if rec.get("event") == "stop" and rec.get("agent_id") == agent_id:
                    return rec.get("result_summary", "") or ""
    except OSError:
        return None
    return None


def cmd_wait(agent_id: str, timeout: float) -> int:
    deadline = time.monotonic() + max(0.0, timeout)
    poll_interval = 1.0

    while True:
        summary = _find_stop_in_registry(agent_id)
        if summary is not None:
            print(summary)
            return 0
        if time.monotonic() >= deadline:
            print(
                json.dumps(
                    {
                        "error": "timeout",
                        "agent_id": agent_id,
                        "timeout": timeout,
                    }
                ),
                file=sys.stderr,
            )
            return 0
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# wait-all
# ---------------------------------------------------------------------------
def _get_result_for_wait_all(agent_id: str) -> dict | None:
    """Return a result dict for agent_id if completed, else None.

    Prefers a stored result file (written by cmd_store) so summaries survive
    registry log rotation. Falls back to scanning the registry for a stop
    event.
    """
    # Priority 1: stored result file.
    try:
        path = _result_path(agent_id)
        if path.exists():
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                status = str(data.get("status") or "").lower()
                if status and status != "waiting":
                    return data
    except Exception:
        pass

    # Priority 2: stop event in agent_registry.jsonl.
    try:
        summary = _find_stop_in_registry(agent_id)
        if summary is not None:
            return {
                "agent_id": agent_id,
                "status": "completed",
                "summary": summary,
            }
    except Exception:
        pass

    return None


def cmd_wait_all(agent_ids: list[str], timeout: float) -> int:
    deadline = time.time() + max(0.0, timeout)
    pending: set[str] = {aid for aid in agent_ids if aid}
    poll_interval = 1.0

    if not pending:
        return 0

    while pending and time.time() < deadline:
        for aid in list(pending):
            result = _get_result_for_wait_all(aid)
            if result is not None:
                try:
                    print(
                        json.dumps({"agent_id": aid, "result": result}),
                        flush=True,
                    )
                except Exception:
                    pass
                pending.discard(aid)
        if pending:
            time.sleep(poll_interval)

    if pending:
        for aid in pending:
            try:
                print(
                    json.dumps({"agent_id": aid, "error": "timeout"}),
                    flush=True,
                )
            except Exception:
                pass
        return 1
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Structured sub-agent result storage and retrieval.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_store = sub.add_parser("store", help="Store a result.")
    p_store.add_argument("agent_id")
    p_store.add_argument("status")
    p_store.add_argument("summary")

    p_get = sub.add_parser("get", help="Print a stored result as JSON.")
    p_get.add_argument("agent_id")

    sub.add_parser("list", help="Show last 10 results.")

    p_wait = sub.add_parser(
        "wait",
        help="Poll agent_registry.jsonl until agent_id has a stop event.",
    )
    p_wait.add_argument("agent_id")
    p_wait.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds (default: 60).",
    )

    p_wait_all = sub.add_parser(
        "wait-all",
        help="Poll until all given agent IDs complete, one JSON line per completion.",
    )
    p_wait_all.add_argument("agent_ids", nargs="+")
    p_wait_all.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds (default: 120).",
    )

    args = parser.parse_args()

    try:
        if args.command == "store":
            return cmd_store(args.agent_id, args.status, args.summary)
        if args.command == "get":
            return cmd_get(args.agent_id)
        if args.command == "list":
            return cmd_list()
        if args.command == "wait":
            return cmd_wait(args.agent_id, args.timeout)
        if args.command == "wait-all":
            return cmd_wait_all(args.agent_ids, args.timeout)
        parser.print_help()
        return 0
    except Exception as e:  # never block callers
        print(f"error: {e}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
