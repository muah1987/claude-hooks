#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
validate_build.py — Stop hook validator for the /build skill.

Blocks Claude from stopping if the build response does not contain a
Validation Summary. This enforces the rule: every build must be validated
before reporting success.

Exit codes:
  0  — validation evidence found, allow stop
  2  — no validation found, block and ask Claude to run validation
"""
__version__ = "2026.04.20.1"

import json
import sys
from pathlib import Path

_SIGNALS = [
    "## Validation Summary",
    "## validation summary",
    "Validation Summary",
    "validation summary",
    "Checks run:",
    "checks run:",
    "Acceptance criteria:",
    "acceptance criteria:",
    "Test results:",
    "test results:",
    "LSP diagnostics:",
]

# Phrases that indicate a read-only turn (no build occurred) — skip validation
_READONLY_SIGNALS = [
    "Read-only",
    "read-only",
    "no files modified",
    "no source files modified",
    "no build performed",
    "no files changed",
    "zero files changed",
    "cron check",
    "status check",
    "roadmap check",
    "no code was written",
    "nothing was built",
    "nothing built",
    "Task type**: Read-only",
    "Task type: Read-only",
    "roadmap completion check",
    "MAHNE roadmap completion check",
    "auto-stops when done",
    "recurring — auto-stops",
    "Count open items",
    "mip_review.sh",
]

_BLOCK_REASON = (
    "BUILD VALIDATION REQUIRED\n\n"
    "You have not completed the mandatory Validation phase.\n\n"
    "Before stopping, you MUST:\n"
    "1. Run the plan's Validation Commands (if any)\n"
    "2. Auto-detect and run checks (lint, type-check, tests) for the tech stack\n"
    "3. Verify every Acceptance Criterion from the plan\n"
    "4. Append a '## Validation Summary' to your response with results\n\n"
    "Do not stop until validation is complete."
)


def _extract_content(content: object) -> str:
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text") or c.get("content") or "")
            elif isinstance(c, str):
                parts.append(c)
        return " ".join(parts)
    if isinstance(content, str):
        return content
    return ""


def _scan_transcript(transcript_path: str, max_assistant: int = 6) -> tuple[str, str]:
    """Return (combined_recent_assistant_text, last_human_text).

    Scans the last `max_assistant` assistant messages so that a response
    ending with tool calls (which produces a tool_use-only final entry)
    doesn't hide a Validation Summary written in the preceding text block.
    """
    assistant_parts: list[str] = []
    human_text = ""
    try:
        path = Path(transcript_path)
        if not path.exists():
            return "", ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = entry.get("message") or entry
            role = msg.get("role") or entry.get("type") or ""
            content = msg.get("content") or ""
            if role in ("assistant", "text"):
                text = _extract_content(content)
                if text.strip():
                    assistant_parts.append(text)
                if len(assistant_parts) >= max_assistant:
                    break
            elif role in ("user", "human") and not human_text:
                human_text = _extract_content(content)
    except Exception:
        pass
    return " ".join(assistant_parts), human_text


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    # stop_hook_active guard: if a stop hook is already running, never loop
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path", "")
    text, prompt_text = _scan_transcript(transcript_path)

    # If the human prompt itself signals a read-only/cron turn, skip validation
    if any(sig in prompt_text for sig in _READONLY_SIGNALS):
        print(json.dumps({"result": "continue", "message": "Read-only prompt — no validation required."}))
        sys.exit(0)

    if any(sig in text for sig in _READONLY_SIGNALS):
        print(json.dumps({"result": "continue", "message": "Read-only turn — no validation required."}))
        sys.exit(0)

    if any(sig in text for sig in _SIGNALS):
        # Validation evidence found
        print(json.dumps({"result": "continue", "message": "Validation summary found."}))
        sys.exit(0)

    # No validation found — block
    print(json.dumps({"decision": "block", "reason": _BLOCK_REASON}))
    sys.exit(2)


if __name__ == "__main__":
    main()
