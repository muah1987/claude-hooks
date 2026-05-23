#!/usr/bin/env python3
"""
parallel_runner.py — Universal parallel command executor

Runs multiple shell commands concurrently with:
  - Full output capture (stdout + stderr merged)
  - Per-command isolation: one failure never cancels others
  - Retry with exponential backoff
  - Configurable concurrency limit
  - Configurable per-command timeout
  - Working directory per command or global default
  - JSON or human-readable output

Usage (CLI):
  python3 parallel_runner.py "cmd1" "cmd2" "cmd3"
  python3 parallel_runner.py "cmd1" "cmd2" --limit 2 --retry 2 --timeout 30 --cwd /my/dir
  python3 parallel_runner.py --json-input cmds.json
  echo '[{"cmd":"ls","cwd":"/tmp"},{"cmd":"pwd"}]' | python3 parallel_runner.py --stdin

Output (always valid JSON on stdout):
  [
    {"cmd": "...", "exit": 0, "output": "...", "attempts": 1, "ok": true},
    {"cmd": "...", "exit": 1, "output": "error text", "attempts": 3, "ok": false}
  ]

Exit code:
  0 — all commands succeeded (or --allow-failures passed)
  1 — one or more commands failed
"""
__version__ = "2026.04.20.3"

import asyncio
import json
import sys
import argparse
import time
from pathlib import Path


async def run_one(cmd: str, cwd: str | None, timeout: int, retries: int) -> dict:
    """Run a single command, retrying on failure with exponential backoff."""
    last_output = ""
    last_exit = -1
    delay = 1.0

    for attempt in range(1, retries + 1):
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd or None,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                last_output = stdout.decode("utf-8", errors="replace").rstrip()
                last_exit = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                last_output = f"[TIMEOUT after {timeout}s]"
                last_exit = 124  # same as shell timeout exit code

        except Exception as exc:
            last_output = f"[LAUNCH ERROR] {exc}"
            last_exit = -1

        if last_exit == 0:
            return {"cmd": cmd, "exit": 0, "output": last_output, "attempts": attempt, "ok": True}

        # Failed — wait before retry (unless last attempt)
        if attempt < retries:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 16)  # cap at 16s

    return {"cmd": cmd, "exit": last_exit, "output": last_output, "attempts": retries, "ok": False}


async def run_parallel(tasks: list[dict], limit: int, timeout: int, retries: int) -> list[dict]:
    """Run all tasks concurrently, bounded by semaphore."""
    sem = asyncio.Semaphore(limit)
    results = [None] * len(tasks)

    async def bounded(i, task):
        async with sem:
            results[i] = await run_one(
                task["cmd"],
                task.get("cwd"),
                timeout,
                retries,
            )

    await asyncio.gather(*[bounded(i, t) for i, t in enumerate(tasks)])
    return results


def parse_args():
    p = argparse.ArgumentParser(description="Run commands in parallel")
    p.add_argument("commands", nargs="*", help="Shell commands to run")
    p.add_argument("--limit",   type=int,   default=4,     help="Max concurrent commands (default: 4)")
    p.add_argument("--retry",   type=int,   default=3,     help="Max retries per command (default: 3)")
    p.add_argument("--timeout", type=int,   default=120,   help="Timeout in seconds per command (default: 120)")
    p.add_argument("--cwd",     type=str,   default=None,  help="Working directory for all commands")
    p.add_argument("--json-input",  type=str, default=None, help="JSON file with [{cmd, cwd?}] list")
    p.add_argument("--stdin",   action="store_true",        help="Read [{cmd, cwd?}] JSON from stdin")
    p.add_argument("--allow-failures", action="store_true", help="Exit 0 even if some commands fail")
    p.add_argument("--quiet",   action="store_true",        help="Only print JSON, no human output")
    return p.parse_args()


def build_tasks(args) -> list[dict]:
    if args.stdin:
        raw = sys.stdin.read()
        data = json.loads(raw)
        return [{"cmd": d["cmd"], "cwd": d.get("cwd", args.cwd)} for d in data]
    if args.json_input:
        data = json.loads(Path(args.json_input).read_text())
        return [{"cmd": d["cmd"], "cwd": d.get("cwd", args.cwd)} for d in data]
    if not args.commands:
        print(json.dumps([{"error": "No commands provided"}]))
        sys.exit(1)
    return [{"cmd": cmd, "cwd": args.cwd} for cmd in args.commands]


def print_human(results: list[dict]):
    ok_count  = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    print(f"\n{'='*60}")
    print(f"  Parallel run: {ok_count}/{len(results)} succeeded, {fail_count} failed")
    print(f"{'='*60}")
    for r in results:
        icon = "✓" if r["ok"] else "✗"
        label = f"[exit {r['exit']}]" if not r["ok"] else ""
        print(f"\n{icon} {r['cmd'][:80]} {label}")
        if r["output"]:
            for line in r["output"].splitlines()[:20]:
                print(f"    {line}")
            if r["output"].count("\n") > 20:
                print(f"    ... ({r['output'].count(chr(10))+1} lines total)")
    print()


def main():
    args = parse_args()
    tasks = build_tasks(args)

    results = asyncio.run(run_parallel(tasks, args.limit, args.timeout, args.retry))

    # Always emit JSON for AI parsing
    print(json.dumps(results, indent=2))

    if not args.quiet:
        print_human(results)

    any_failed = any(not r["ok"] for r in results)
    sys.exit(0 if (args.allow_failures or not any_failed) else 1)


if __name__ == "__main__":
    main()
