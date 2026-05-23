#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
memory_compact.py — compress and deduplicate memory files under ~/.claude/projects/

Runs on SessionEnd. For each memory/*.md file:
- Truncates any single bullet line > 200 chars to 200 chars + "…"
- Deduplicates identical lines
- Skips files modified < 120 seconds ago (just written by pre_compact)

Also prunes: if more than 20 memory files exist per project, delete the oldest ones beyond 20.
"""
__version__ = "2026.04.20.2"

import sys
import time
from pathlib import Path


def compact_file(path: Path) -> bool:
    """
    Compact a single memory file: dedup lines and truncate long bullet lines.
    Returns True if the file was modified.
    """
    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return False

    lines = original.splitlines(keepends=True)
    seen: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.rstrip("\n")
        # Truncate bullet lines longer than 200 chars
        if len(stripped) > 200 and stripped.lstrip().startswith(("-", "*", "+")):
            stripped = stripped[:200] + "…"
        key = stripped.strip()
        if key in seen and key:
            # Skip duplicate non-empty lines
            continue
        seen.add(key)
        new_lines.append(stripped + "\n")

    new_content = "".join(new_lines)
    if new_content == original:
        return False

    try:
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(new_content, encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def main() -> None:
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        print("memory_compact: no projects dir found, nothing to do.")
        sys.exit(0)

    now = time.time()
    skip_threshold = 120  # seconds — skip recently written files

    files_checked = 0
    files_compacted = 0
    files_pruned = 0

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        memory_dir = project_dir / "memory"
        if not memory_dir.exists():
            continue

        md_files = sorted(
            memory_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
        )

        # Prune: keep only 20 most-recent files
        if len(md_files) > 20:
            to_delete = md_files[: len(md_files) - 20]  # oldest first
            for old_file in to_delete:
                try:
                    old_file.unlink()
                    files_pruned += 1
                except Exception:
                    pass
            md_files = md_files[len(md_files) - 20 :]

        # Compact each file not modified in last 120s
        for md_file in md_files:
            files_checked += 1
            try:
                age = now - md_file.stat().st_mtime
            except Exception:
                continue
            if age < skip_threshold:
                continue
            if compact_file(md_file):
                files_compacted += 1

    print(
        f"memory_compact v{__version__}: checked={files_checked} "
        f"compacted={files_compacted} pruned={files_pruned}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
