#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
stamp_versions.py — add/bump __version__ in every .claude Python file.

Usage:
  uv run stamp_versions.py           # stamp all files with today's version
  uv run stamp_versions.py --bump    # increment build number on already-versioned files
  uv run stamp_versions.py --dry-run # show what would change without writing

Version format: "YYYY.MM.DD.N"  (N = build counter, resets each day)
"""
from __future__ import annotations

__version__ = "2026.04.20.1"

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SEARCH_DIRS = [
    CLAUDE_DIR / "hooks",
    CLAUDE_DIR / "scripts",
    CLAUDE_DIR / "status_lines",
]

VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
METADATA_END_RE = re.compile(r'^# ///$', re.MULTILINE)  # end of uv /// block


def _today_base() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}.{now.month:02d}.{now.day:02d}"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse "YYYY.MM.DD.N" into a sortable tuple."""
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def _next_version(current: str | None) -> str:
    today = _today_base()
    if not current:
        return f"{today}.1"
    parts = current.split(".")
    # If same date prefix, increment build number
    if len(parts) >= 4 and ".".join(parts[:3]) == today:
        try:
            build = int(parts[3]) + 1
            return f"{today}.{build}"
        except ValueError:
            pass
    return f"{today}.1"


def _insert_version(source: str, version: str) -> str:
    """Insert or replace __version__ in source text.

    Correct insertion order:
      1. shebang + uv /// metadata block
      2. module docstring
      3. from __future__ imports
      4. __version__  ← insert here
      5. other imports

    If __version__ already present, replace in-place.
    """
    if VERSION_RE.search(source):
        return VERSION_RE.sub(f'__version__ = "{version}"', source)

    lines = source.splitlines(keepends=True)
    insert_at = 1  # fallback: after shebang

    # Phase 1: skip past uv /// metadata block
    meta_end = -1
    for i, line in enumerate(lines):
        if line.strip() == "# ///":
            meta_end = i
    if meta_end >= 0:
        insert_at = meta_end + 1

    # Phase 2: skip past module docstring (triple-quoted string)
    i = insert_at
    while i < len(lines) and not lines[i].strip():
        i += 1  # skip blank lines
    if i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2 and len(stripped) > 3:
                insert_at = i + 1  # single-line docstring
            else:
                i += 1
                while i < len(lines):
                    if quote in lines[i]:
                        insert_at = i + 1
                        break
                    i += 1

    # Phase 3: skip past any `from __future__ import` lines
    i = insert_at
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].startswith("from __future__"):
        i += 1
        insert_at = i

    version_line = f'__version__ = "{version}"\n'
    lines.insert(insert_at, version_line)
    return "".join(lines)


def stamp_file(path: Path, bump: bool, dry_run: bool) -> str:
    """Stamp or bump a single file. Returns action taken."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"READ_ERROR: {e}"

    m = VERSION_RE.search(source)
    current = m.group(1) if m else None

    if bump and current:
        new_ver = _next_version(current)
    elif current:
        return f"SKIP (already {current})"
    else:
        new_ver = _next_version(None)

    new_source = _insert_version(source, new_ver)
    if new_source == source:
        return f"UNCHANGED ({current})"

    if not dry_run:
        path.write_text(new_source, encoding="utf-8")
    return f"{'WOULD SET' if dry_run else 'SET'} {current or 'none'} → {new_ver}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Stamp __version__ into .claude Python files.")
    parser.add_argument("--bump", action="store_true", help="Increment build on already-versioned files.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--dirs", nargs="+", help="Override directories to scan.")
    args = parser.parse_args()

    dirs = [Path(d) for d in args.dirs] if args.dirs else SEARCH_DIRS

    files: list[Path] = []
    for d in dirs:
        if d.is_dir():
            files.extend(sorted(d.rglob("*.py")))

    if not files:
        print("No Python files found.")
        return 0

    changed = skipped = errors = 0
    for f in files:
        action = stamp_file(f, bump=args.bump, dry_run=args.dry_run)
        rel = str(f).replace(str(Path.home()), "~")
        print(f"  {rel}: {action}")
        if "SET" in action:
            changed += 1
        elif "SKIP" in action or "UNCHANGED" in action:
            skipped += 1
        else:
            errors += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done: {changed} stamped, {skipped} skipped, {errors} errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
