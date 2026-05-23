#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""go_validator.py — PostToolUse hook for .go files. Runs go vet."""
__version__ = "2026.04.20.1"

import json
import subprocess
import sys
from pathlib import Path


def _find_go_root(start: Path) -> Path | None:
    for parent in [start.parent, *start.parents]:
        if (parent / "go.mod").exists():
            return parent
    return None


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""

    if not file_path or not file_path.endswith(".go"):
        sys.exit(0)

    path = Path(file_path)
    if not path.exists():
        sys.exit(0)

    go_root = _find_go_root(path)
    if not go_root:
        sys.exit(0)

    try:
        result = subprocess.run(
            ["go", "vet", "./..."],
            capture_output=True, text=True, timeout=30, cwd=str(go_root),
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0 and output:
            lines = output.splitlines()
            print(f"[go vet] {len(lines)} issue(s) in {go_root.name}:", file=sys.stderr)
            for line in lines[:10]:
                print(f"  {line}", file=sys.stderr)
            if len(lines) > 10:
                print(f"  ... {len(lines) - 10} more", file=sys.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
