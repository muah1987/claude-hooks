#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
session_cleanup.py — Prune stale session data from ~/.claude/data/sessions/

Runs automatically on SessionEnd. Removes session directories older than
MAX_AGE_DAYS. Keeps the N most recent sessions regardless of age.

Usage:
  uv run session_cleanup.py              # default: prune >7 days, keep 20
  uv run session_cleanup.py --dry-run    # show what would be deleted
  uv run session_cleanup.py --max-age 3  # custom age threshold
"""
__version__ = "2026.04.20.1"

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SESSIONS_DIR = Path.home() / ".claude" / "data" / "sessions"
MAX_AGE_DAYS = 7
KEEP_MIN = 20  # always keep at least this many sessions


def cleanup(dry_run: bool = False, max_age_days: int = MAX_AGE_DAYS) -> dict:
    if not SESSIONS_DIR.exists():
        return {"deleted": 0, "kept": 0, "errors": 0}

    # Collect all session dirs with their mtime
    entries: list[tuple[float, Path]] = []
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            mtime = d.stat().st_mtime
            entries.append((mtime, d))
        except OSError:
            continue

    # Sort newest first
    entries.sort(reverse=True)

    cutoff = time.time() - (max_age_days * 86400)
    deleted = kept = errors = 0

    for idx, (mtime, d) in enumerate(entries):
        if idx < KEEP_MIN:
            # Always keep the KEEP_MIN most recent
            kept += 1
            continue
        if mtime >= cutoff:
            kept += 1
            continue
        # Stale and beyond minimum keep threshold — delete
        if dry_run:
            print(f"  [DRY] would delete: {d.name} (age {int((time.time()-mtime)/86400)}d)")
            deleted += 1
        else:
            try:
                shutil.rmtree(d)
                deleted += 1
            except OSError as e:
                print(f"  ERROR deleting {d.name}: {e}", file=sys.stderr)
                errors += 1

    return {"deleted": deleted, "kept": kept, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune stale session directories")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-age", type=int, default=MAX_AGE_DAYS,
                        help=f"Days before a session is eligible for deletion (default {MAX_AGE_DAYS})")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = cleanup(dry_run=args.dry_run, max_age_days=args.max_age)

    if not args.quiet:
        label = "[DRY RUN] " if args.dry_run else ""
        print(f"session_cleanup v{__version__}: {label}"
              f"deleted={result['deleted']} kept={result['kept']} errors={result['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
