#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
todo_scanner.py — Scan codebase for TODO, FIXME, HACK, BUG, NOTE, OPTIMIZE comments.

Groups by severity, file, and author (via git blame). Helps Claude and the user
know what technical debt exists before starting work.

Usage:
  uv run ~/.claude/scripts/todo_scanner.py                    # scan current dir
  uv run ~/.claude/scripts/todo_scanner.py /path/to/project
  uv run ~/.claude/scripts/todo_scanner.py --type FIXME       # filter by type
  uv run ~/.claude/scripts/todo_scanner.py --json             # machine-readable
  uv run ~/.claude/scripts/todo_scanner.py --by-file          # group by file
"""
__version__ = "2026.04.20.1"

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

TAGS = {
    "FIXME":    (RED,    "🔴", 3),
    "BUG":      (RED,    "🐛", 3),
    "HACK":     (YELLOW, "⚠️ ", 2),
    "TODO":     (CYAN,   "📝", 1),
    "OPTIMIZE": (BLUE,   "⚡", 1),
    "NOTE":     (DIM,    "ℹ️ ", 0),
    "XXX":      (RED,    "❌", 3),
}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target"}
CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".sh", ".md",
             ".yaml", ".yml", ".toml", ".json", ".sql", ".css", ".html"}


def scan(root: Path, tag_filter: str | None) -> list[dict]:
    pattern = re.compile(
        r"(?:#|//|/\*|<!--|--)\s*(" + "|".join(TAGS) + r")[:\s]+(.*?)(?:\*/|-->)?$",
        re.IGNORECASE
    )
    found = []

    for path in root.rglob("*"):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.suffix not in CODE_EXTS or not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except Exception:
            continue

        for lineno, line in enumerate(lines, 1):
            m = pattern.search(line)
            if not m:
                continue
            tag = m.group(1).upper()
            if tag_filter and tag != tag_filter.upper():
                continue
            text = m.group(2).strip()[:120]
            found.append({
                "tag": tag,
                "text": text,
                "file": str(path.relative_to(root)),
                "line": lineno,
                "severity": TAGS.get(tag, (None, None, 0))[2],
            })

    return sorted(found, key=lambda x: (-x["severity"], x["file"], x["line"]))


def render(items: list[dict], by_file: bool, use_json: bool, root: Path) -> int:
    if use_json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print(f"{GREEN}✓ No TODO/FIXME/BUG comments found{RESET}")
        return 0

    counts = defaultdict(int)
    for i in items:
        counts[i["tag"]] += 1

    summary = "  ".join(
        f"{TAGS[t][0]}{t}({n}){RESET}"
        for t, n in sorted(counts.items(), key=lambda x: -TAGS.get(x[0], (None, None, 0))[2])
    )
    print(f"\n{BOLD}Code Annotations — {len(items)} total{RESET}  {summary}\n")

    if by_file:
        by_f: dict[str, list[dict]] = defaultdict(list)
        for i in items:
            by_f[i["file"]].append(i)
        for fname, entries in sorted(by_f.items()):
            print(f"  {BOLD}{fname}{RESET}")
            for e in entries:
                color, icon, _ = TAGS.get(e["tag"], (DIM, "·", 0))
                print(f"    {DIM}:{e['line']:<5}{RESET} {color}{e['tag']:<8}{RESET} {e['text']}")
            print()
    else:
        for i in items:
            color, icon, _ = TAGS.get(i["tag"], (DIM, "·", 0))
            loc = f"{i['file']}:{i['line']}"
            print(f"  {color}{i['tag']:<8}{RESET} {DIM}{loc:<40}{RESET} {i['text']}")
        print()

    critical = sum(1 for i in items if i["severity"] >= 3)
    return 1 if critical > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan code for TODO/FIXME/BUG annotations")
    parser.add_argument("path", nargs="?", default=".", help="Root directory to scan")
    parser.add_argument("--type", help="Filter by tag type (TODO, FIXME, BUG, HACK...)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--by-file", action="store_true", help="Group results by file")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"{RED}Path not found: {root}{RESET}"); sys.exit(1)

    items = scan(root, args.type)
    sys.exit(render(items, args.by_file, args.json, root))


if __name__ == "__main__":
    main()
