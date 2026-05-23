#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
debug_info.py — Capture system and project state for debugging.

Collects: OS/WSL info, Python/Node/Go/Rust versions, env vars (safe),
git state, recent errors from logs, disk/memory, running processes.
Dumps a clean snapshot Claude can reason over.

Usage:
  uv run ~/.claude/scripts/debug_info.py               # full snapshot
  uv run ~/.claude/scripts/debug_info.py --env         # include env vars
  uv run ~/.claude/scripts/debug_info.py --project /path
  uv run ~/.claude/scripts/debug_info.py --json
  uv run ~/.claude/scripts/debug_info.py --errors      # focus on recent errors
"""
__version__ = "2026.04.20.1"

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
RED   = "\033[91m"
DIM   = "\033[2m"
RESET = "\033[0m"

SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL",
    "NODE_ENV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
    "GOPATH", "GOROOT", "CARGO_HOME", "RUSTUP_HOME",
    "OLLAMA_API_BASE", "CLAUDE_PROJECT_DIR",
    "WSL_DISTRO_NAME", "WSL_INTEROP",
}

SENSITIVE_PATTERNS = {"TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "CREDENTIAL", "AUTH"}


def _run(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return ""


def gather(project: Path | None, include_env: bool) -> dict:
    snap: dict = {}

    # System
    snap["system"] = {
        "os": platform.system(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "arch": platform.machine(),
        "hostname": platform.node(),
        "wsl": _run("uname -r"),
    }

    # Tool versions
    tools: dict[str, str] = {}
    for tool, cmd in [
        ("node", "node --version"),
        ("npm", "npm --version"),
        ("bun", "bun --version"),
        ("go", "go version"),
        ("rustc", "rustc --version"),
        ("cargo", "cargo --version"),
        ("git", "git --version"),
        ("docker", "docker --version"),
        ("uv", "uv --version"),
    ]:
        v = _run(cmd)
        if v:
            tools[tool] = v.splitlines()[0]
    snap["tools"] = tools

    # Disk/memory
    snap["resources"] = {
        "disk_free": _run("df -h / | tail -1 | awk '{print $4\" free of \"$2}'"),
        "memory": _run("free -h 2>/dev/null | grep Mem | awk '{print $3\"/\"$2}'"),
        "load": _run("uptime | awk -F'load average:' '{print $2}'").strip(),
    }

    # Git state
    git: dict = {}
    rc_git = subprocess.run("git rev-parse --show-toplevel", shell=True,
                            capture_output=True, text=True)
    if rc_git.returncode == 0:
        git["root"] = rc_git.stdout.strip()
        git["branch"] = _run("git rev-parse --abbrev-ref HEAD")
        git["last_commit"] = _run("git log -1 --format='%h %s (%ar)'")
        git["status"] = _run("git status --short")
        git["stash_count"] = _run("git stash list | wc -l").strip()
    snap["git"] = git

    # Project-specific
    if project and project.exists():
        proj: dict = {"path": str(project)}
        if (project / "package.json").exists():
            try:
                pkg = json.loads((project / "package.json").read_text())
                proj["name"] = pkg.get("name", "")
                proj["version"] = pkg.get("version", "")
                proj["scripts"] = list((pkg.get("scripts") or {}).keys())
            except Exception:
                pass
        if (project / "pyproject.toml").exists():
            proj["pyproject"] = True
        if (project / "Cargo.toml").exists():
            proj["cargo"] = True
        snap["project"] = proj

    # Environment (filtered)
    if include_env:
        env_out = {}
        for k, v in os.environ.items():
            if k in SAFE_ENV_KEYS:
                env_out[k] = v
            elif not any(p in k.upper() for p in SENSITIVE_PATTERNS):
                env_out[k] = v[:80]
        snap["env"] = env_out

    # Recent errors (hook logs, stderr files)
    errors: list[str] = []
    for log in Path.home().glob(".claude/hooks/validators/*.log"):
        try:
            lines = log.read_text().splitlines()[-20:]
            errors.extend([f"[{log.name}] {l}" for l in lines if "error" in l.lower() or "fail" in l.lower()])
        except Exception:
            pass
    snap["recent_errors"] = errors[:20]

    return snap


def render(snap: dict) -> None:
    print(f"\n{BOLD}Debug Snapshot{RESET}\n")

    s = snap.get("system", {})
    print(f"  {CYAN}System{RESET}")
    print(f"    OS: {s.get('platform', '?')}")
    print(f"    Python: {s.get('python', '?')}  WSL: {s.get('wsl', 'N/A')[:40]}\n")

    tools = snap.get("tools", {})
    if tools:
        print(f"  {CYAN}Tools{RESET}")
        for k, v in tools.items():
            print(f"    {k:<10} {v[:60]}")
        print()

    res = snap.get("resources", {})
    print(f"  {CYAN}Resources{RESET}")
    for k, v in res.items():
        if v:
            print(f"    {k:<12} {v}")
    print()

    git = snap.get("git", {})
    if git:
        print(f"  {CYAN}Git{RESET}")
        print(f"    Branch: {git.get('branch', '?')}  Last: {git.get('last_commit', '?')[:60]}")
        status = git.get("status", "")
        if status:
            print(f"    {RED}Uncommitted:{RESET}")
            for line in status.splitlines()[:8]:
                print(f"      {line}")
        print()

    errors = snap.get("recent_errors", [])
    if errors:
        print(f"  {RED}Recent Errors{RESET}")
        for e in errors[:10]:
            print(f"    {e[:100]}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture debug snapshot of system and project state")
    parser.add_argument("--project", help="Project path to analyse", default=".")
    parser.add_argument("--env",    action="store_true", help="Include environment variables")
    parser.add_argument("--json",   action="store_true", help="Output as JSON")
    parser.add_argument("--errors", action="store_true", help="Focus on recent errors only")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    snap = gather(project, args.env)

    if args.errors:
        errors = snap.get("recent_errors", [])
        if errors:
            print(f"{RED}Recent errors:{RESET}")
            for e in errors:
                print(f"  {e}")
        else:
            print(f"{GREEN}No recent errors found{RESET}")
        return

    if args.json:
        print(json.dumps(snap, indent=2))
        return

    render(snap)


if __name__ == "__main__":
    main()
