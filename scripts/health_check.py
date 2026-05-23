#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
health_check.py — Full Claude Code setup health report.

Checks hooks, scripts, validators, settings, memory, vault, and key data files.
Prints a colour-coded PASS/WARN/FAIL table and exits 0 (all ok), 1 (warnings), 2 (failures).

Usage:
  uv run ~/.claude/scripts/health_check.py
  uv run ~/.claude/scripts/health_check.py --json
"""
__version__ = "2026.04.20.1"


import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


@dataclass
class Check:
    name: str
    status: str   # "pass" | "warn" | "fail"
    detail: str = ""


results: list[Check] = []


def ok(name: str, detail: str = "") -> None:
    results.append(Check(name, "pass", detail))


def warn(name: str, detail: str) -> None:
    results.append(Check(name, "warn", detail))


def fail(name: str, detail: str) -> None:
    results.append(Check(name, "fail", detail))


# ── checks ────────────────────────────────────────────────────────────────────

def check_settings() -> None:
    f = CLAUDE / "settings.json"
    if not f.exists():
        fail("settings.json", "missing"); return
    try:
        data = json.loads(f.read_text())
    except Exception as e:
        fail("settings.json", f"invalid JSON: {e}"); return

    # Check no $CLAUDE_PROJECT_DIR in hook commands
    hooks = data.get("hooks", {})
    bad = []
    for event, entries in hooks.items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                if "$CLAUDE_PROJECT_DIR" in cmd:
                    bad.append(f"{event}: {cmd[:60]}")
    if bad:
        warn("settings.json/$CLAUDE_PROJECT_DIR", "; ".join(bad[:3]))
    else:
        ok("settings.json", "valid JSON, no $CLAUDE_PROJECT_DIR")


def check_hook_files() -> None:
    settings = CLAUDE / "settings.json"
    if not settings.exists():
        return
    data = json.loads(settings.read_text())
    missing = []
    for entries in data.get("hooks", {}).values():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                for part in cmd.split():
                    p = part.replace("$HOME", str(HOME))
                    if p.endswith(".py") and not Path(p).exists():
                        missing.append(p)
    if missing:
        fail("hook files", f"{len(missing)} missing: " + ", ".join(missing[:3]))
    else:
        ok("hook files", "all hook script paths exist")


def check_validators() -> None:
    expected = [
        "ruff_validator.py", "shellcheck_validator.py",
        "yaml_validator.py", "markdown_validator.py",
        "rust_validator.py", "go_validator.py",
        "ts_eslint_validator.js", "ts_tsc_validator.js",
        "validate_build.py",
    ]
    vdir = CLAUDE / "hooks" / "validators"
    missing = [v for v in expected if not (vdir / v).exists()]
    if missing:
        warn("validators", f"missing: {', '.join(missing)}")
    else:
        ok("validators", f"{len(expected)} validators present")


def check_scripts() -> None:
    expected = [
        "agents.py", "agent_results.py", "model_selector.py",
        "ollama_cloud.py", "usage_monitor.py", "fetch_usage.py",
        "project_anchor.py", "session_cleanup.py", "sync.py",
        "stamp_versions.py", "memory_compact.py",
    ]
    sdir = CLAUDE / "scripts"
    missing = [s for s in expected if not (sdir / s).exists()]
    if missing:
        warn("scripts", f"missing: {', '.join(missing)}")
    else:
        ok("scripts", f"all {len(expected)} core scripts present")


def check_data_dir() -> None:
    data = CLAUDE / "data"
    if not data.exists():
        fail("data dir", "~/.claude/data/ missing"); return

    files = {
        "usage_status.json": "warn",
        "agent_registry.jsonl": "warn",
    }
    missing = [f for f, _ in files.items() if not (data / f).exists()]
    if missing:
        warn("data files", f"not yet created: {', '.join(missing)}")
    else:
        ok("data dir", "usage_status.json and agent_registry.jsonl exist")


def check_memory() -> None:
    mem_dirs = list((CLAUDE / "projects").glob("*/memory/MEMORY.md")) if (CLAUDE / "projects").exists() else []
    if not mem_dirs:
        warn("memory", "no MEMORY.md found under ~/.claude/projects/*/memory/")
    else:
        ok("memory", f"{len(mem_dirs)} MEMORY.md file(s) found")


def check_vault() -> None:
    vault = CLAUDE / "vault" / "vault.py"
    if not vault.exists():
        warn("vault", "vault.py not found at ~/.claude/vault/vault.py"); return
    try:
        r = subprocess.run(
            ["uv", "run", str(vault), "list"],
            capture_output=True, text=True, timeout=8,
        )
        if r.returncode == 0:
            keys = [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("#")]
            ok("vault", f"{len(keys)} secret(s) stored")
        else:
            warn("vault", r.stderr.strip()[:80] or "non-zero exit")
    except Exception as e:
        warn("vault", str(e)[:80])


def check_tools() -> None:
    tools = {"shellcheck": "shell linting", "yamllint": "YAML linting",
             "markdownlint": "Markdown linting", "uv": "script runner"}
    missing = []
    for tool, purpose in tools.items():
        r = subprocess.run(["which", tool], capture_output=True)
        if r.returncode != 0:
            missing.append(f"{tool} ({purpose})")
    if missing:
        warn("external tools", f"not installed: {', '.join(missing)}")
    else:
        ok("external tools", "shellcheck, yamllint, markdownlint, uv all present")


def check_status_line() -> None:
    settings = CLAUDE / "settings.json"
    if not settings.exists():
        return
    data = json.loads(settings.read_text())
    sl = data.get("statusLine", {})
    cmd = sl.get("command", "")
    if not cmd:
        warn("status line", "no statusLine.command in settings.json"); return
    script = cmd.split()[-1].replace("$HOME", str(HOME))
    if not Path(script).exists():
        fail("status line", f"script not found: {script}")
    else:
        ok("status line", f"configured: {Path(script).name}")


def check_commands() -> None:
    cmd_dir = CLAUDE / "commands"
    if not cmd_dir.exists():
        warn("commands", "~/.claude/commands/ missing"); return
    files = list(cmd_dir.glob("*.md"))
    no_desc = [f.name for f in files if "description:" not in f.read_text()]
    no_tools = [f.name for f in files if "allowed-tools:" not in f.read_text()]
    if no_desc:
        warn("commands/description", f"{len(no_desc)} missing description: {', '.join(no_desc[:4])}")
    else:
        ok("commands/description", f"all {len(files)} skills have description")
    if no_tools:
        warn("commands/allowed-tools", f"{len(no_tools)} missing allowed-tools: {', '.join(no_tools[:4])}")
    else:
        ok("commands/allowed-tools", f"all {len(files)} skills have allowed-tools")


# ── render ────────────────────────────────────────────────────────────────────

def render_table(use_json: bool) -> int:
    if use_json:
        print(json.dumps([{"name": r.name, "status": r.status, "detail": r.detail} for r in results], indent=2))
        failures = sum(1 for r in results if r.status == "fail")
        return 2 if failures else (1 if any(r.status == "warn" for r in results) else 0)

    col = max(len(r.name) for r in results) + 2
    print(f"\n{BOLD}Claude Code Health Check{RESET}")
    print("─" * (col + 60))
    for r in results:
        if r.status == "pass":
            icon = f"{GREEN}✓ PASS{RESET}"
        elif r.status == "warn":
            icon = f"{YELLOW}⚠ WARN{RESET}"
        else:
            icon = f"{RED}✗ FAIL{RESET}"
        print(f"  {icon}  {r.name:<{col}}  {r.detail}")
    print("─" * (col + 60))

    passes = sum(1 for r in results if r.status == "pass")
    warns  = sum(1 for r in results if r.status == "warn")
    fails  = sum(1 for r in results if r.status == "fail")
    print(f"  {GREEN}{passes} passed{RESET}  {YELLOW}{warns} warnings{RESET}  {RED}{fails} failed{RESET}\n")

    return 2 if fails else (1 if warns else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code setup health check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    check_settings()
    check_hook_files()
    check_validators()
    check_scripts()
    check_data_dir()
    check_memory()
    check_vault()
    check_tools()
    check_status_line()
    check_commands()

    sys.exit(render_table(args.json))


if __name__ == "__main__":
    main()
