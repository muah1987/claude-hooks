#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""yaml_validator.py — PostToolUse hook for .yml/.yaml files."""
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

    if not file_path or not (file_path.endswith(".yml") or file_path.endswith(".yaml")):
        sys.exit(0)

    path = Path(file_path)
    if not path.exists():
        sys.exit(0)

    try:
        result = subprocess.run(
            ["yamllint", "-f", "parsable", str(path)],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode != 0 and result.stdout.strip():
            issues = result.stdout.strip().splitlines()
            print(f"[yamllint] {len(issues)} issue(s) in {path.name}:", file=sys.stderr)
            for line in issues[:10]:
                print(f"  {line}", file=sys.stderr)
            if len(issues) > 10:
                print(f"  ... {len(issues) - 10} more", file=sys.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
