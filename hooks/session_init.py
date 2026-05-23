#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
session_init.py — Runs FIRST in SessionStart chain.

Forces four steps before Claude responds to the human:
  1. Memory check  — load MEMORY.md + top recent memory files
  2. Stop analysis — detect abnormal exits (crash, WSL drop, rate-limit)
  3. Codebase scan — git status, recent commits, pending work
  4. Context emit  — inject everything as additionalContext

Fast path: < 8 seconds, no external network calls.
"""
__version__ = "2026.04.21.1"

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
LOGS_DIR = CLAUDE_DIR / "logs"
DATA_DIR = CLAUDE_DIR / "data"


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(path: str) -> str:
    parts = path.strip("/").replace("\\", "/").split("/")
    slug = "-".join(parts)
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", slug)


def _project_memory_dir(cwd: str) -> Path:
    slug = _slug(cwd)
    return CLAUDE_DIR / "projects" / f"-{slug}" / "memory"


def _safe_read(path: Path, max_chars: int = 1500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n…(truncated, {len(text)} chars total)"
        return text
    except Exception:
        return ""


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 4) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or None,
        )
        return r.stdout.strip()
    except Exception:
        return ""


# ── Step 1: Memory ─────────────────────────────────────────────────────────

def load_memory(cwd: str) -> str:
    mem_dir = _project_memory_dir(cwd)
    if not mem_dir.exists():
        return ""

    parts: list[str] = []

    # Always load MEMORY.md index
    index = mem_dir / "MEMORY.md"
    if index.exists():
        content = _safe_read(index, 2000)
        if content.strip():
            parts.append("### Memory Index\n" + content)

    # Load up to 4 most-recently modified memory files (skip index + auto_ files for brevity)
    candidates = sorted(
        [f for f in mem_dir.glob("*.md") if f.name not in ("MEMORY.md",)],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    loaded = 0
    for f in candidates:
        if loaded >= 4:
            break
        content = _safe_read(f, 800)
        if content.strip():
            parts.append(f"### [{f.stem}]\n" + content)
            loaded += 1

    if not parts:
        return ""
    return "## Memory\n" + "\n\n".join(parts)


# ── Step 2: Stop analysis ──────────────────────────────────────────────────

def _last_stop_entry() -> dict | None:
    stop_log = LOGS_DIR / "stop.jsonl"
    if not stop_log.exists():
        return None
    try:
        lines = stop_log.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
    except Exception:
        pass
    return None


def _last_session_end_entry() -> dict | None:
    end_log = LOGS_DIR / "session_end.jsonl"
    if not end_log.exists():
        return None
    try:
        lines = end_log.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
    except Exception:
        pass
    return None


def _usage_status() -> dict:
    try:
        return json.loads((DATA_DIR / "usage_status.json").read_text())
    except Exception:
        return {}


def analyze_last_stop(current_session_id: str, cwd: str) -> str:
    stop = _last_stop_entry()
    end = _last_session_end_entry()
    usage = _usage_status()

    issues: list[str] = []
    notes: list[str] = []

    # WSL/network problem
    if usage.get("network_error"):
        notes.append("WSL2 DNS error recorded (probe disabled — api.claude.ai is NXDOMAIN; not rate-limited)")

    if usage.get("rate_limited"):
        notes.append(f"⚠ Rate limited since {usage.get('limited_since','?')} — routing via {usage.get('model_override','?')}")

    # Abnormal session end detection
    if end:
        reason = end.get("reason", "")
        end_cwd = end.get("cwd", "")
        end_sid = end.get("session_id", "")

        # "other" reason = crash/kill, not normal stop
        if reason == "other":
            issues.append(f"⚠ Previous session ended abnormally (reason=other) in {Path(end_cwd).name or end_cwd}")

        # Check if stop hook fired for that session (normal exit = both fire)
        if stop and stop.get("session_id") != end_sid and end_sid != current_session_id:
            if reason in ("other", "timeout", ""):
                issues.append("⚠ Stop hook did NOT fire for previous session — likely crash or force-kill")

    if not issues and not notes:
        return ""

    parts = ["## Last Session Status"]
    if issues:
        parts += issues
    if notes:
        parts += notes
    return "\n".join(parts)


# ── Step 3: Codebase scan ──────────────────────────────────────────────────

def scan_codebase(cwd: str) -> str:
    parts: list[str] = []

    # Verify it's a git repo
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd)
    if inside != "true":
        return ""

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd) or "unknown"
    parts.append(f"Branch: **{branch}**")

    # Status summary
    status_raw = _run(["git", "status", "--porcelain"], cwd=cwd)
    if status_raw:
        lines = status_raw.splitlines()
        modified = sum(1 for l in lines if l[:2].strip() in ("M", "MM", "AM"))
        added = sum(1 for l in lines if l[:2].strip() in ("A", "??"))
        deleted = sum(1 for l in lines if l[:2].strip() == "D")
        summary = []
        if modified:
            summary.append(f"{modified} modified")
        if added:
            summary.append(f"{added} new/untracked")
        if deleted:
            summary.append(f"{deleted} deleted")
        if summary:
            parts.append(f"Uncommitted: {', '.join(summary)}")
    else:
        parts.append("Working tree: clean")

    # Ahead/behind
    ab = _run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=cwd)
    if ab:
        tokens = ab.split()
        if len(tokens) == 2:
            behind, ahead = tokens
            if ahead != "0":
                parts.append(f"Ahead of remote: {ahead} commit(s)")
            if behind != "0":
                parts.append(f"Behind remote: {behind} commit(s)")

    # Last 3 commits
    log = _run(["git", "log", "-3", "--pretty=%h %s"], cwd=cwd)
    if log:
        parts.append("Recent commits:\n" + "\n".join(f"  {l}" for l in log.splitlines()))

    if not parts:
        return ""
    return "## Codebase\n" + "\n".join(parts)


# ── Step 4: Emit ───────────────────────────────────────────────────────────

def build_context(session_id: str, source: str, cwd: str, model: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"=== SESSION START · {Path(cwd).name} · {now} · {source} · {model} ==="

    sections: list[str] = [header]

    memory = load_memory(cwd)
    if memory:
        sections.append(memory)

    stop_analysis = analyze_last_stop(session_id, cwd)
    if stop_analysis:
        sections.append(stop_analysis)

    codebase = scan_codebase(cwd)
    if codebase:
        sections.append(codebase)

    sections.append("=== Ready — waiting for your first message ===")

    return "\n\n".join(sections)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    session_id = data.get("session_id", "")
    source = data.get("source", "startup")
    cwd = data.get("cwd", "") or str(Path.cwd())
    model = data.get("model", "").split("-")[1] if data.get("model", "") else "claude"

    # Skip for sub-agents — they get their context from subagent_start.py
    if data.get("agent_type"):
        sys.exit(0)

    try:
        context = build_context(session_id, source, cwd, model)
    except Exception:
        sys.exit(0)

    if context:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(out))

    sys.exit(0)


if __name__ == "__main__":
    main()
