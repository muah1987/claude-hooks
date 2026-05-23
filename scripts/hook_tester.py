#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
hook_tester.py — Fire any Claude Code hook locally with a synthetic payload.

Useful for debugging hooks without triggering a real Claude Code session.
Reads the hook command from settings.json or accepts it directly.

Usage:
  uv run ~/.claude/scripts/hook_tester.py --event UserPromptSubmit --prompt "fix this bug"
  uv run ~/.claude/scripts/hook_tester.py --event PostToolUse --tool Write --file /tmp/test.py
  uv run ~/.claude/scripts/hook_tester.py --event Stop --transcript ~/.claude/projects/.../session.jsonl
  uv run ~/.claude/scripts/hook_tester.py --list              # show all configured hook events
  uv run ~/.claude/scripts/hook_tester.py --cmd "uv run ~/.claude/hooks/model_router.py" --event UserPromptSubmit --prompt "hello"
"""
__version__ = "2026.04.20.1"


import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOME   = Path.home()
CLAUDE = HOME / ".claude"
SETTINGS = CLAUDE / "settings.json"

BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
RED   = "\033[91m"
DIM   = "\033[2m"
RESET = "\033[0m"


def load_hooks() -> dict[str, list[str]]:
    """Return {event: [command, ...]} from settings.json."""
    if not SETTINGS.exists():
        return {}
    try:
        data = json.loads(SETTINGS.read_text())
    except Exception:
        return {}
    result: dict[str, list[str]] = {}
    for event, entries in data.get("hooks", {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                if cmd:
                    result.setdefault(event, []).append(cmd)
    return result


def build_payload(event: str, args: argparse.Namespace) -> dict:
    """Build a synthetic hook input payload for the given event."""
    base: dict = {"session_id": "hook-tester-session", "hook_event_name": event}

    if event == "UserPromptSubmit":
        base["prompt"] = args.prompt or "test prompt"
        base["permission_mode"] = "default"

    elif event in ("PreToolUse", "PostToolUse"):
        tool = args.tool or "Write"
        base["tool_name"] = tool
        base["tool_input"] = {}
        if args.file:
            base["tool_input"]["file_path"] = args.file
        if event == "PostToolUse":
            base["tool_response"] = {"output": ""}

    elif event == "Stop":
        base["stop_hook_active"] = False
        base["transcript_path"] = args.transcript or ""

    elif event in ("SubagentStart", "SubagentStop"):
        base["agent_id"] = "test-agent-001"
        base["agent_type"] = "builder"
        if event == "SubagentStop":
            base["result_summary"] = args.prompt or "test result"

    elif event == "SessionStart":
        base["cwd"] = str(Path.cwd())

    return base


def run_hook(cmd: str, payload: dict, verbose: bool) -> int:
    env = {**os.environ, "HOME": str(HOME)}
    cmd_expanded = cmd.replace("$HOME", str(HOME))

    payload_str = json.dumps(payload)
    if verbose:
        print(f"{DIM}Payload: {payload_str[:200]}{RESET}\n")

    print(f"{BOLD}Running:{RESET} {CYAN}{cmd_expanded[:100]}{RESET}")
    print("─" * 60)

    try:
        result = subprocess.run(
            cmd_expanded, shell=True, input=payload_str,
            capture_output=False, text=True, timeout=30, env=env,
        )
        print("─" * 60)
        status = f"{GREEN}exit 0{RESET}" if result.returncode == 0 else f"{RED}exit {result.returncode}{RESET}"
        print(f"Status: {status}")
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f"{RED}TIMEOUT after 30s{RESET}")
        return 1
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Claude Code hooks locally")
    parser.add_argument("--event",      help="Hook event name (e.g. UserPromptSubmit, PostToolUse, Stop)")
    parser.add_argument("--cmd",        help="Hook command to run (overrides settings.json lookup)")
    parser.add_argument("--prompt",     help="Prompt text (UserPromptSubmit / SubagentStop)")
    parser.add_argument("--tool",       help="Tool name (PreToolUse / PostToolUse)")
    parser.add_argument("--file",       help="file_path in tool_input (PostToolUse)")
    parser.add_argument("--transcript", help="Transcript path (Stop event)")
    parser.add_argument("--list",       action="store_true", help="List all configured hooks")
    parser.add_argument("--verbose",    action="store_true", help="Print payload before running")
    parser.add_argument("--all",        action="store_true", help="Run ALL hooks for this event")
    args = parser.parse_args()

    hooks = load_hooks()

    if args.list:
        print(f"\n{BOLD}Configured hook events:{RESET}\n")
        for event, cmds in sorted(hooks.items()):
            print(f"  {CYAN}{event}{RESET} ({len(cmds)} hook(s))")
            for c in cmds:
                print(f"    {DIM}{c[:90]}{RESET}")
        print()
        return

    if not args.event:
        parser.print_help()
        sys.exit(1)

    payload = build_payload(args.event, args)

    if args.cmd:
        sys.exit(run_hook(args.cmd, payload, args.verbose))

    event_hooks = hooks.get(args.event, [])
    if not event_hooks:
        print(f"{RED}No hooks configured for event: {args.event}{RESET}")
        print(f"Use --cmd to specify a hook command directly.")
        sys.exit(1)

    cmds = event_hooks if args.all else [event_hooks[0]]
    if len(event_hooks) > 1 and not args.all:
        print(f"{DIM}Note: {len(event_hooks)} hooks configured. Running first only. Use --all to run all.{RESET}\n")

    code = 0
    for cmd in cmds:
        rc = run_hook(cmd, payload, args.verbose)
        if rc != 0:
            code = rc
    sys.exit(code)


if __name__ == "__main__":
    main()
