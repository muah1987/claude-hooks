#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
sync.py — version-aware sync between project .claude/ and ~/.claude/

Reads __version__ from each Python file and only copies if the source
has a strictly higher version than the destination. Falls back to mtime
comparison for files with no __version__.

Usage:
  uv run sync.py                         # project → global (deploy)
  uv run sync.py --reverse               # global → project (pull)
  uv run sync.py --dry-run               # show what would change
  uv run sync.py --force                 # copy regardless of version
  uv run sync.py --status                # show version of every file pair
"""
from __future__ import annotations

__version__ = "2026.04.21.3"

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

def _default_project_root() -> Path:
    """Derive project root from CLAUDE_PROJECT_DIR env, script location, or cwd."""
    env = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env:
        candidate = Path(env) / ".claude"
        if candidate.is_dir():
            return candidate
    # Script lives at <project>/.claude/scripts/sync.py — walk up two levels
    script_based = Path(__file__).resolve().parent.parent
    if (script_based / "hooks").is_dir():
        return script_based
    # Fallback: cwd/.claude
    cwd_based = Path(os.getcwd()) / ".claude"
    if cwd_based.is_dir():
        return cwd_based
    return script_based  # best guess

PROJECT_ROOT = _default_project_root()
GLOBAL_ROOT  = Path.home() / ".claude"

# Directories to sync (relative to their respective roots)
SYNC_DIRS = ["hooks", "scripts", "status_lines"]

VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def _read_version(path: Path) -> tuple[int, ...] | None:
    """Read __version__ from a Python file. Returns parsed tuple or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        m = VERSION_RE.search(text)
        if not m:
            return None
        return tuple(int(x) for x in m.group(1).split("."))
    except Exception:
        return None


def _version_str(path: Path) -> str:
    v = _read_version(path)
    return ".".join(str(x) for x in v) if v else "—"


def _should_copy(src: Path, dst: Path, force: bool) -> tuple[bool, str]:
    """Return (should_copy, reason)."""
    if not src.exists():
        return False, "src missing"
    if force:
        return True, "forced"
    if not dst.exists():
        return True, "dst missing"

    src_ver = _read_version(src)
    dst_ver = _read_version(dst)

    if src_ver is not None and dst_ver is not None:
        if src_ver > dst_ver:
            return True, f"version {'.'.join(str(x) for x in dst_ver)} → {'.'.join(str(x) for x in src_ver)}"
        if src_ver < dst_ver:
            return False, f"dst newer ({'.'.join(str(x) for x in dst_ver)} > {'.'.join(str(x) for x in src_ver)})"
        return False, f"same version ({'.'.join(str(x) for x in src_ver)})"

    # No __version__ in one or both — fall back to mtime
    src_mt = src.stat().st_mtime
    dst_mt = dst.stat().st_mtime
    if src_mt > dst_mt + 1:  # 1-second tolerance
        return True, "src mtime newer (no version)"
    return False, "same/older mtime (no version)"


def collect_files(root: Path) -> list[Path]:
    """Collect all .py and .md files under the given sync dirs."""
    files: list[Path] = []
    for d in SYNC_DIRS:
        target = root / d
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
            files.extend(sorted(target.rglob("*.md")))
    return files


def run_sync(src_root: Path, dst_root: Path, dry_run: bool, force: bool) -> None:
    files = collect_files(src_root)
    if not files:
        print(f"No files found under {src_root}")
        return

    copied = skipped = errors = 0
    for src in files:
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        try:
            do_copy, reason = _should_copy(src, dst, force)
        except Exception as e:
            print(f"  ERROR  {rel}: {e}")
            errors += 1
            continue

        tag = "COPY" if do_copy else "SKIP"
        print(f"  {tag:4s}  {rel}  [{reason}]")
        if do_copy and not dry_run:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
            except Exception as e:
                print(f"         ↳ ERROR copying: {e}")
                errors += 1
        elif do_copy:
            copied += 1  # count as "would copy"
        else:
            skipped += 1

    label = "[DRY RUN] " if dry_run else ""
    print(f"\n{label}{copied} copied, {skipped} skipped, {errors} errors.")


def run_status(src_root: Path, dst_root: Path) -> None:
    """Show version comparison for every file pair."""
    files = collect_files(src_root)
    if not files:
        print(f"No files found under {src_root}")
        return

    headers = ["file", "src_ver", "dst_ver", "status"]
    rows: list[tuple[str, str, str, str]] = []
    for src in files:
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        sv = _version_str(src)
        dv = _version_str(dst) if dst.exists() else "MISSING"

        src_ver = _read_version(src)
        dst_ver = _read_version(dst) if dst.exists() else None

        if not dst.exists():
            status = "MISSING"
        elif src_ver and dst_ver:
            if src_ver > dst_ver:
                status = "SRC_NEWER"
            elif src_ver < dst_ver:
                status = "DST_NEWER"
            else:
                status = "IN_SYNC"
        else:
            status = "NO_VER"
        rows.append((str(rel), sv, dv, status))

    # Print table
    widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    def fmt(cells: tuple) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))
    print(fmt(tuple(headers)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


def _find_sibling_projects(projects_root: Path) -> list[Path]:
    """Find all sibling project .claude/ dirs (skip the source project itself)."""
    siblings: list[Path] = []
    if not projects_root.is_dir():
        return siblings
    for child in sorted(projects_root.iterdir()):
        candidate = child / ".claude"
        if candidate.is_dir() and candidate != PROJECT_ROOT:
            siblings.append(candidate)
    return siblings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Version-aware sync between project .claude/ and ~/.claude/ and all sibling projects.",
    )
    parser.add_argument("--reverse", action="store_true",
                        help="Sync global → project instead of project → global.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be copied without writing.")
    parser.add_argument("--force", action="store_true",
                        help="Copy all files regardless of version.")
    parser.add_argument("--status", action="store_true",
                        help="Show version comparison table without copying.")
    parser.add_argument("--no-siblings", action="store_true",
                        help="Skip distributing to sibling projects.")
    args = parser.parse_args()

    if args.reverse:
        src_root, dst_root = GLOBAL_ROOT, PROJECT_ROOT
        direction = "~/.claude → project"
    else:
        src_root, dst_root = PROJECT_ROOT, GLOBAL_ROOT
        direction = "project → ~/.claude"

    if not src_root.exists():
        print(f"Source root not found: {src_root}")
        return 1

    print(f"Sync: {direction}" + (" [DRY RUN]" if args.dry_run else "") + "\n")

    if args.status:
        run_status(src_root, dst_root)
    else:
        run_sync(src_root, dst_root, dry_run=args.dry_run, force=args.force)

    # Distribute to all sibling projects (project → siblings, not reverse)
    if not args.reverse and not args.no_siblings and not args.status:
        projects_root = PROJECT_ROOT.parent.parent  # <projects_root>/<project>/.claude → <projects_root>
        siblings = _find_sibling_projects(projects_root)
        if siblings:
            print(f"\nDistributing to {len(siblings)} sibling project(s)...\n")
            total_copied = total_skipped = 0
            for sib in siblings:
                copied_before = 0
                # Temporarily capture counts by running sync
                files = collect_files(src_root)
                c = s = 0
                for src in files:
                    rel = src.relative_to(src_root)
                    dst = sib / rel
                    try:
                        do_copy, _ = _should_copy(src, dst, args.force)
                    except Exception:
                        continue
                    if do_copy and not args.dry_run:
                        try:
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            c += 1
                        except Exception:
                            pass
                    elif do_copy:
                        c += 1
                    else:
                        s += 1
                total_copied += c
                total_skipped += s
                if c:
                    print(f"  {sib.parent.name}: {c} copied, {s} skipped")
            if not total_copied:
                print(f"  All {len(siblings)} projects already in sync.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
