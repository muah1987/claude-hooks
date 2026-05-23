#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
skill_runner.py — Python fast-paths for Claude Code skills.

Executes common skill sub-tasks in Python rather than passing them through
Claude, reducing token usage by generating structured output directly.

Commands:
  context [--brief]       Emit project context summary (replaces /prime read loop)
  crons                   List active cron jobs from daemon
  memory long [--index]   Print long-term memory index for current project
  memory short <sid>      Print short-term memory for session
  st-get <sid> <key>      Read short-term memory key
  st-set <sid> <key> <v>  Write short-term memory key
  skills [--list]         List available skills with descriptions
  anchor                  Ensure current project is anchored (create if missing)
"""
__version__ = "2026.04.20.1"

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


CLAUDE_DIR = Path.home() / ".claude"


# ── utilities ─────────────────────────────────────────────────────────────────

def _cwd() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _anchor_uuid(project_path: Path) -> str | None:
    anchor = project_path / ".claude-project.json"
    if anchor.exists():
        try:
            return json.loads(anchor.read_text()).get("uuid")
        except Exception:
            pass
    return None


def _memory_dir(project_path: Path) -> Path:
    uid = _anchor_uuid(project_path)
    if uid:
        return CLAUDE_DIR / "projects" / uid / "memory"
    slug = str(project_path).replace("/", "-").replace("\\", "-").lstrip("-")
    return CLAUDE_DIR / "projects" / slug / "memory"


# ── context ───────────────────────────────────────────────────────────────────

def cmd_context(args: list[str]) -> int:
    brief = "--brief" in args
    cwd = _cwd()

    lines: list[str] = []
    lines.append(f"=== Project Context: {cwd.name} ===")
    lines.append(f"Path: {cwd}")

    # Git info
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    if branch:
        last = _run(["git", "log", "-1", "--pretty=%h %s"], cwd=cwd)
        dirty = _run(["git", "status", "--short"], cwd=cwd)
        dirty_count = len([l for l in dirty.splitlines() if l.strip()]) if dirty else 0
        lines.append(f"Git: {branch} | last: {last} | dirty: {dirty_count} files")

    # Project anchor UUID
    uid = _anchor_uuid(cwd)
    if uid:
        lines.append(f"Anchor UUID: {uid[:8]}…")

    if not brief:
        # Long-term memory index
        mem_dir = _memory_dir(cwd)
        if mem_dir.exists():
            mem_idx = mem_dir / "MEMORY.md"
            if mem_idx.exists():
                lines.append("\n--- Memory Index ---")
                lines.append(mem_idx.read_text(encoding="utf-8", errors="replace")[:600].strip())

        # Recent crons for this project
        cron_data = _load_crons()
        proj_crons = [c for c in cron_data if c.get("project") == str(cwd)]
        if proj_crons:
            lines.append(f"\n--- Cron Jobs ({len(proj_crons)}) ---")
            for c in proj_crons[:3]:
                lines.append(f"  [{c.get('id','?')}] {c.get('schedule','?')} — {c.get('prompt','')[:80]}")

        # File tree (git-tracked)
        tracked = _run(["git", "ls-files", "--others", "--cached", "--exclude-standard"], cwd=cwd)
        if tracked:
            files = [f for f in tracked.splitlines() if f.strip()][:30]
            lines.append(f"\n--- Files ({len(files)} shown) ---")
            lines.extend(f"  {f}" for f in files)

    print("\n".join(lines))
    return 0


# ── crons ─────────────────────────────────────────────────────────────────────

def _load_crons() -> list[dict]:
    try:
        cron_file = CLAUDE_DIR / "daemon" / "saved_crons.json"
        if cron_file.exists():
            data = json.loads(cron_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _load_daemon_state() -> dict:
    try:
        state_file = CLAUDE_DIR / "daemon" / "daemon_state.json"
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def cmd_crons(_args: list[str]) -> int:
    crons = _load_crons()
    if not crons:
        print("No cron jobs registered.")
        return 0

    state = _load_daemon_state()
    last_checks: dict = state.get("last_checks", {})

    print(f"Cron Jobs ({len(crons)}):")
    print("-" * 60)
    for c in crons:
        cid = c.get("id", "?")
        schedule = c.get("schedule", "?")
        project = c.get("project", "?")
        prompt = c.get("prompt", "")[:60]
        last_run = last_checks.get(project, 0)
        if last_run:
            import time
            age_min = int((time.time() - last_run) / 60)
            last_str = f"{age_min}m ago"
        else:
            last_str = "never"
        saved_at = c.get("saved_at", "")[:10]
        print(f"  [{cid}] {schedule}")
        print(f"       Project: {project}")
        print(f"       Task: {prompt}…")
        print(f"       Last run: {last_str} | Saved: {saved_at}")
        print()
    return 0


# ── memory ────────────────────────────────────────────────────────────────────

def cmd_memory(args: list[str]) -> int:
    kind = args[0] if args else "long"
    if kind == "long":
        cwd = _cwd()
        mem_dir = _memory_dir(cwd)
        if not mem_dir.exists():
            print(f"No long-term memory at {mem_dir}")
            return 0
        files = sorted(mem_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if "--index" in args:
            idx = mem_dir / "MEMORY.md"
            if idx.exists():
                print(idx.read_text(encoding="utf-8", errors="replace"))
            else:
                print(f"Files ({len(files)}):")
                for f in files:
                    print(f"  {f.name}")
        else:
            print(f"Long-term memory: {mem_dir} ({len(files)} files)")
            for f in files[:10]:
                print(f"  {f.name}")
        return 0

    if kind == "short":
        session_id = args[1] if len(args) > 1 else os.environ.get("CLAUDE_SESSION_ID", "")
        if not session_id:
            print("No session_id provided", file=sys.stderr)
            return 1
        st_file = CLAUDE_DIR / "data" / "sessions" / session_id / "st_memory.json"
        if not st_file.exists():
            print("{}")
            return 0
        print(st_file.read_text(encoding="utf-8"))
        return 0

    print(f"Unknown memory kind: {kind}. Use 'long' or 'short'", file=sys.stderr)
    return 1


def cmd_st_get(args: list[str]) -> int:
    if len(args) < 2:
        print("Usage: st-get <session_id> <key>", file=sys.stderr)
        return 1
    sid, key = args[0], args[1]
    st_file = CLAUDE_DIR / "data" / "sessions" / sid / "st_memory.json"
    if not st_file.exists():
        return 1
    try:
        val = json.loads(st_file.read_text()).get(key)
        if val is None:
            return 1
        print(val)
        return 0
    except Exception:
        return 1


def cmd_st_set(args: list[str]) -> int:
    if len(args) < 3:
        print("Usage: st-set <session_id> <key> <value>", file=sys.stderr)
        return 1
    sid, key = args[0], args[1]
    value = " ".join(args[2:])
    st_file = CLAUDE_DIR / "data" / "sessions" / sid / "st_memory.json"
    st_file.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if st_file.exists():
        try:
            data = json.loads(st_file.read_text()) or {}
        except Exception:
            pass
    data[key] = value
    data["_updated"] = datetime.now(timezone.utc).isoformat()
    tmp = st_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, st_file)
    return 0


# ── skills ────────────────────────────────────────────────────────────────────

def cmd_skills(args: list[str]) -> int:
    commands_dir = CLAUDE_DIR / "commands"
    if not commands_dir.exists():
        print("No commands directory found.")
        return 0
    files = sorted(commands_dir.glob("*.md"))
    if "--list" in args or not args:
        print(f"Skills ({len(files)}):")
        for f in files:
            desc = ""
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                # Extract description from frontmatter or first heading
                for line in lines[:10]:
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[-1].strip()
                        break
                    if line.startswith("# ") and not desc:
                        desc = line[2:].strip()
            except Exception:
                pass
            print(f"  /{f.stem:<22} {desc[:60]}")
    return 0


# ── anchor ────────────────────────────────────────────────────────────────────

def cmd_anchor(_args: list[str]) -> int:
    anchor_script = CLAUDE_DIR / "scripts" / "project_anchor.py"
    if anchor_script.exists():
        result = subprocess.run(
            ["uv", "run", str(anchor_script), "anchor"],
            capture_output=False,
        )
        return result.returncode
    print("project_anchor.py not found", file=sys.stderr)
    return 1


# ── dispatch ──────────────────────────────────────────────────────────────────

COMMANDS = {
    "context": cmd_context,
    "crons": cmd_crons,
    "memory": cmd_memory,
    "st-get": cmd_st_get,
    "st-set": cmd_st_set,
    "skills": cmd_skills,
    "anchor": cmd_anchor,
}


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}", file=sys.stderr)
        return 1
    return fn(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
