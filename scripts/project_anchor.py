#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
project_anchor.py — Stable UUID-based project registry.

Each project gets a `.claude-project.json` anchor file with a UUID that
persists even if the directory is renamed. The registry in
~/.claude/data/project_registry.json maps UUID → path → memory dirs.

Commands:
  anchor [name]         Create/update .claude-project.json in cwd
  resolve [path]        Print UUID for project at path (or cwd)
  memory-path [long|short] [session_id]
                        Print the correct memory dir for current project
  register [path]       Add/refresh project in global registry
  list                  List all registered projects
  link-session <sid>    Associate session_id with current project anchor
  st-get <sid> <key>    Read short-term memory value
  st-set <sid> <key> <value>
                        Write short-term memory value (session-scoped)
"""
__version__ = "2026.04.20.1"

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


CLAUDE_DIR = Path.home() / ".claude"
REGISTRY_FILE = CLAUDE_DIR / "data" / "project_registry.json"
ANCHOR_FILE = ".claude-project.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry() -> dict:
    try:
        if REGISTRY_FILE.exists():
            data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_registry(reg: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, REGISTRY_FILE)


def _slug(path: Path) -> str:
    """Derive the legacy slug used as the ~/.claude/projects/ directory name."""
    return str(path).replace("/", "-").replace("\\", "-").lstrip("-")


def _memory_dir_long(project_uuid: str, project_path: Path) -> Path:
    """Long-term memory: UUID-anchored dir under ~/.claude/projects/<uuid>/"""
    return CLAUDE_DIR / "projects" / project_uuid / "memory"


def _st_memory_file(session_id: str) -> Path:
    return CLAUDE_DIR / "data" / "sessions" / session_id / "st_memory.json"


# ── anchor ────────────────────────────────────────────────────────────────────

def cmd_anchor(args: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()
    anchor_path = cwd / ANCHOR_FILE
    name = args[0] if args else cwd.name

    if anchor_path.exists():
        try:
            existing = json.loads(anchor_path.read_text())
            project_uuid = existing.get("uuid") or str(uuid.uuid4())
        except Exception:
            project_uuid = str(uuid.uuid4())
    else:
        project_uuid = str(uuid.uuid4())

    anchor = {
        "uuid": project_uuid,
        "name": name,
        "path": str(cwd),
        "created_at": _now(),
    }
    anchor_path.write_text(json.dumps(anchor, indent=2), encoding="utf-8")

    # Register in global registry
    reg = _load_registry()
    reg[project_uuid] = {
        "name": name,
        "path": str(cwd),
        "memory_dir_long": str(_memory_dir_long(project_uuid, cwd)),
        "legacy_slug": _slug(cwd),
        "anchored_at": _now(),
        "last_seen": _now(),
    }
    _save_registry(reg)

    print(f"Anchored: {name} ({project_uuid[:8]}…) at {cwd}")
    print(f"Memory: {_memory_dir_long(project_uuid, cwd)}")
    return 0


def cmd_resolve(args: list[str]) -> int:
    path = Path(args[0]).resolve() if args else Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()
    anchor_path = path / ANCHOR_FILE
    if not anchor_path.exists():
        # Fallback: search registry by path
        reg = _load_registry()
        for uid, info in reg.items():
            if Path(info.get("path", "")) == path:
                print(uid)
                return 0
        print("", end="")
        return 1
    try:
        data = json.loads(anchor_path.read_text())
        print(data.get("uuid", ""))
        return 0
    except Exception:
        return 1


def cmd_memory_path(args: list[str]) -> int:
    kind = args[0] if args else "long"
    session_id = args[1] if len(args) > 1 else os.environ.get("CLAUDE_SESSION_ID", "")

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()

    if kind == "short":
        if not session_id:
            print("", end="")
            return 1
        p = _st_memory_file(session_id).parent
        p.mkdir(parents=True, exist_ok=True)
        print(str(_st_memory_file(session_id)))
        return 0

    # Long-term: try UUID anchor first, fall back to legacy slug
    anchor_path = cwd / ANCHOR_FILE
    if anchor_path.exists():
        try:
            data = json.loads(anchor_path.read_text())
            uid = data.get("uuid", "")
            if uid:
                p = _memory_dir_long(uid, cwd)
                p.mkdir(parents=True, exist_ok=True)
                print(str(p))
                return 0
        except Exception:
            pass

    # Legacy slug fallback
    slug = _slug(cwd)
    p = CLAUDE_DIR / "projects" / slug / "memory"
    p.mkdir(parents=True, exist_ok=True)
    print(str(p))
    return 0


def cmd_register(args: list[str]) -> int:
    path = Path(args[0]).resolve() if args else Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()
    anchor_path = path / ANCHOR_FILE
    reg = _load_registry()

    if anchor_path.exists():
        try:
            data = json.loads(anchor_path.read_text())
            uid = data.get("uuid") or str(uuid.uuid4())
            name = data.get("name") or path.name
            entry = reg.get(uid, {})
            entry.update({
                "name": name,
                "path": str(path),
                "memory_dir_long": str(_memory_dir_long(uid, path)),
                "legacy_slug": _slug(path),
                "last_seen": _now(),
            })
            entry.setdefault("anchored_at", _now())
            reg[uid] = entry
            _save_registry(reg)
            print(f"Registered: {name} ({uid[:8]}…)")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # No anchor file — register by path only with generated UUID
    slug = _slug(path)
    # Check if already registered by path
    for uid, info in reg.items():
        if Path(info.get("path", "")) == path:
            info["last_seen"] = _now()
            reg[uid] = info
            _save_registry(reg)
            print(f"Updated: {path.name} ({uid[:8]}…)")
            return 0

    uid = str(uuid.uuid4())
    reg[uid] = {
        "name": path.name,
        "path": str(path),
        "memory_dir_long": str(_memory_dir_long(uid, path)),
        "legacy_slug": slug,
        "anchored_at": _now(),
        "last_seen": _now(),
    }
    _save_registry(reg)
    print(f"Registered (no anchor): {path.name} ({uid[:8]}…)")
    return 0


def cmd_list(_args: list[str]) -> int:
    reg = _load_registry()
    if not reg:
        print("No projects registered.")
        return 0
    print(f"{'UUID':36}  {'Name':20}  Path")
    print("-" * 90)
    for uid, info in sorted(reg.items(), key=lambda x: x[1].get("last_seen", ""), reverse=True):
        name = info.get("name", "?")[:20]
        path = info.get("path", "?")
        print(f"{uid}  {name:<20}  {path}")
    return 0


def cmd_link_session(args: list[str]) -> int:
    if not args:
        print("Usage: link-session <session_id>", file=sys.stderr)
        return 1
    session_id = args[0]
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()).resolve()

    # Find project UUID
    anchor_path = cwd / ANCHOR_FILE
    uid = None
    if anchor_path.exists():
        try:
            uid = json.loads(anchor_path.read_text()).get("uuid")
        except Exception:
            pass

    # Write session → project link
    link_file = CLAUDE_DIR / "data" / "sessions" / session_id / "project_link.json"
    link_file.parent.mkdir(parents=True, exist_ok=True)
    link_data = {
        "session_id": session_id,
        "project_path": str(cwd),
        "project_uuid": uid or "",
        "linked_at": _now(),
    }
    link_file.write_text(json.dumps(link_data, indent=2), encoding="utf-8")
    return 0


def cmd_st_get(args: list[str]) -> int:
    if len(args) < 2:
        print("Usage: st-get <session_id> <key>", file=sys.stderr)
        return 1
    session_id, key = args[0], args[1]
    st_file = _st_memory_file(session_id)
    if not st_file.exists():
        return 1
    try:
        data = json.loads(st_file.read_text())
        val = data.get(key)
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
    session_id, key = args[0], args[1]
    value = " ".join(args[2:])
    st_file = _st_memory_file(session_id)
    st_file.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if st_file.exists():
        try:
            data = json.loads(st_file.read_text()) or {}
        except Exception:
            data = {}
    data[key] = value
    data["_updated"] = _now()

    tmp = st_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, st_file)
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "anchor": cmd_anchor,
    "resolve": cmd_resolve,
    "memory-path": cmd_memory_path,
    "register": cmd_register,
    "list": cmd_list,
    "link-session": cmd_link_session,
    "st-get": cmd_st_get,
    "st-set": cmd_st_set,
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
