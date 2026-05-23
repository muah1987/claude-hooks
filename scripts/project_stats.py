#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
project_stats.py — Code statistics for any project directory.

Shows: file counts, lines of code, language breakdown, largest files,
most-changed files (git), and a complexity estimate.

Usage:
  uv run ~/.claude/scripts/project_stats.py              # current directory
  uv run ~/.claude/scripts/project_stats.py /path/to/project
  uv run ~/.claude/scripts/project_stats.py --top 20     # show top 20 files
  uv run ~/.claude/scripts/project_stats.py --json
"""
__version__ = "2026.04.20.1"

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path
import sys

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "dist", "build", ".next", "target", ".cargo", "coverage"}

LANG_MAP = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TSX", ".js": "JavaScript",
    ".jsx": "JSX", ".go": "Go", ".rs": "Rust", ".sh": "Shell",
    ".md": "Markdown", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".json": "JSON", ".sql": "SQL", ".css": "CSS", ".html": "HTML",
    ".java": "Java", ".cpp": "C++", ".c": "C", ".rb": "Ruby",
    ".swift": "Swift", ".kt": "Kotlin", ".cs": "C#",
}

BAR_WIDTH = 20


def _bar(count: int, max_count: int) -> str:
    filled = int(count / max_count * BAR_WIDTH) if max_count else 0
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def gather(root: Path, top: int) -> dict:
    lang_lines: dict[str, int] = defaultdict(int)
    lang_files: dict[str, int] = defaultdict(int)
    file_sizes: list[tuple[int, str]] = []
    total_files = total_lines = 0

    for path in sorted(root.rglob("*")):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        lang = LANG_MAP.get(ext)
        if not lang:
            continue
        try:
            content = path.read_text(errors="replace")
            lines = content.count("\n") + 1
        except Exception:
            continue
        lang_lines[lang] += lines
        lang_files[lang] += 1
        file_sizes.append((lines, str(path.relative_to(root))))
        total_files += 1
        total_lines += lines

    file_sizes.sort(reverse=True)

    # Git most-changed files
    hot_files: list[tuple[int, str]] = []
    try:
        r = subprocess.run(
            "git log --name-only --pretty=format: | sort | uniq -c | sort -rn | head -15",
            shell=True, capture_output=True, text=True, cwd=root
        )
        for line in r.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                hot_files.append((int(parts[0]), parts[1]))
    except Exception:
        pass

    return {
        "root": str(root),
        "total_files": total_files,
        "total_lines": total_lines,
        "lang_lines": dict(sorted(lang_lines.items(), key=lambda x: -x[1])),
        "lang_files": dict(sorted(lang_files.items(), key=lambda x: -x[1])),
        "largest_files": file_sizes[:top],
        "hot_files": hot_files[:10],
    }


def render(data: dict, use_json: bool) -> None:
    if use_json:
        print(json.dumps(data, indent=2))
        return

    root = data["root"]
    print(f"\n{BOLD}Project Stats{RESET}  {DIM}{root}{RESET}")
    print(f"  {data['total_files']:,} files  ·  {data['total_lines']:,} lines\n")

    # Language breakdown
    lang_lines = data["lang_lines"]
    if lang_lines:
        max_l = max(lang_lines.values())
        print(f"  {BOLD}Languages (by lines){RESET}")
        for lang, lines in list(lang_lines.items())[:12]:
            files = data["lang_files"].get(lang, 0)
            bar = _bar(lines, max_l)
            pct = lines / data["total_lines"] * 100 if data["total_lines"] else 0
            print(f"  {CYAN}{lang:<14}{RESET} {bar} {lines:>8,}  {pct:>5.1f}%  {DIM}({files} files){RESET}")
        print()

    # Largest files
    if data["largest_files"]:
        print(f"  {BOLD}Largest files{RESET}")
        for lines, fname in data["largest_files"][:10]:
            print(f"  {lines:>7,}  {DIM}{fname}{RESET}")
        print()

    # Hot files (most git commits)
    if data["hot_files"]:
        print(f"  {BOLD}Most changed (git){RESET}")
        for commits, fname in data["hot_files"][:8]:
            print(f"  {YELLOW}{commits:>5} commits{RESET}  {DIM}{fname}{RESET}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Project code statistics")
    parser.add_argument("path", nargs="?", default=".", help="Project root")
    parser.add_argument("--top", type=int, default=10, help="Number of files to show per category")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Path not found: {root}"); sys.exit(1)

    data = gather(root, args.top)
    render(data, args.json)


if __name__ == "__main__":
    main()
