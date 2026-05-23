#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
shellcheck_validator.py — PostToolUse hook for .sh files.

Runs shellcheck on any shell script that was just written or edited.
Exits 0 always (informational only — errors are surfaced as stderr warnings,
not blocking decisions). Claude can see and act on the output.
"""
__version__ = "2026.04.20.1"

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""

    if not file_path or not file_path.endswith(".sh"):
        sys.exit(0)

    path = Path(file_path)
    if not path.exists():
        sys.exit(0)

    try:
        result = subprocess.run(
            ["shellcheck", "--severity=style", "--format=gcc", str(path)],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode != 0 and result.stdout.strip():
            issues = result.stdout.strip().splitlines()
            print(f"[shellcheck] {len(issues)} warning(s) in {path.name}:", file=sys.stderr)
            for line in issues[:10]:  # cap at 10 lines
                print(f"  {line}", file=sys.stderr)
            if len(issues) > 10:
                print(f"  ... {len(issues) - 10} more", file=sys.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # shellcheck not available or timed out — skip silently
    except Exception:
        pass

    sys.exit(0)  # always allow, never block


if __name__ == "__main__":
    main()
