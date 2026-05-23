#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
pattern_learner.py - Learn from user approval/denial patterns.

GOTCHA Layer: Args (behavioral adaptation)
ATLAS Phase: LEARN - Pattern recognition and auto-approval

Tracks user decisions (approve/deny) for specific tool+input combinations,
normalizes commands into stable pattern keys, and enables auto-approval
once sufficient consistent approval samples accumulate.

Environment Variables:
  LEARN_FROM_DECISIONS  - Enable pattern learning (default: true)
  PATTERN_MIN_SAMPLES   - Minimum approvals before auto-approve (default: 5)
  PATTERN_DECAY_DAYS    - Days before unused patterns expire (default: 30)
"""

from __future__ import annotations
__version__ = "2026.04.20.3"

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

LEARN_FROM_DECISIONS: bool = os.getenv("LEARN_FROM_DECISIONS", "true").lower() in (
    "true", "1", "yes",
)
PATTERN_MIN_SAMPLES: int = int(os.getenv("PATTERN_MIN_SAMPLES", "5"))
PATTERN_DECAY_DAYS: int = int(os.getenv("PATTERN_DECAY_DAYS", "30"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATTERNS_FILE: Path = Path(".claude/data/learned_patterns.json")

# Known command prefixes that should retain their first subcommand
_KNOWN_PREFIXES: set[str] = {"npm", "git", "pip", "uv", "python", "node"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LearnedPattern:
    """A learned approval/denial pattern for a specific tool+input combination."""

    pattern_key: str  # e.g. "Bash:npm_install"
    approval_count: int
    denial_count: int
    last_seen: str  # ISO timestamp
    auto_approve: bool
    confidence: float  # 0.0-1.0


# ---------------------------------------------------------------------------
# Command normalization
# ---------------------------------------------------------------------------

def normalize_command(command: str) -> str:
    """
    Normalize a shell command to a stable pattern key component.

    Extracts the command name (and first subcommand for known prefixes),
    strips arguments, paths, and variable content.

    Examples:
        "npm install foo"        -> "npm_install"
        "git commit -m msg"      -> "git_commit"
        "rm -rf /tmp/*.log"      -> "rm"
        "python3 -m pytest"      -> "python3_m_pytest"
        "ls -la /some/path"      -> "ls"
    """
    stripped = command.strip()
    if not stripped:
        return "unknown"

    parts = stripped.split()
    first_word = parts[0]

    # Strip leading path from command name (e.g. /usr/bin/git -> git)
    first_word = first_word.rsplit("/", 1)[-1]

    # Check if first word (without trailing version numbers like python3)
    base_cmd = first_word.rstrip("0123456789")

    if base_cmd in _KNOWN_PREFIXES:
        # Collect subcommand tokens (skip flags starting with -)
        sub_parts = [first_word]
        for part in parts[1:]:
            if part.startswith("-"):
                # For -m style flags, include the flag and next token
                if part == "-m" and len(sub_parts) < 3:
                    sub_parts.append(part.lstrip("-"))
                    continue
                # Skip other flags
                continue
            # First non-flag token is the subcommand
            sub_parts.append(part)
            break
        return "_".join(sub_parts)

    # For rm, handle -rf as a special compound
    if first_word == "rm":
        for part in parts[1:]:
            if part.startswith("-") and "r" in part and "f" in part:
                return "rm_rf"
        return "rm"

    return first_word


# ---------------------------------------------------------------------------
# Pattern key generation
# ---------------------------------------------------------------------------

def generate_pattern_key(tool_name: str, tool_input: dict) -> str:
    """
    Generate a stable pattern key for a tool invocation.

    Args:
        tool_name: Name of the tool (e.g. "Bash", "Read", "Write").
        tool_input: Input parameters dict for the tool.

    Returns:
        Pattern key string, e.g. "Bash:npm_install" or "Read:.py".
    """
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"Bash:{normalize_command(cmd)}"

    if tool_name in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        ext = Path(file_path).suffix if file_path else ".unknown"
        if not ext:
            ext = ".noext"
        return f"{tool_name}:{ext}"

    if tool_name in ("Glob", "Grep"):
        return f"{tool_name}:search"

    return tool_name


# ---------------------------------------------------------------------------
# Pattern storage I/O
# ---------------------------------------------------------------------------

def load_patterns() -> dict[str, dict]:
    """
    Load learned patterns from disk.

    Returns expired-cleaned dict of pattern_key -> pattern data.
    """
    if not PATTERNS_FILE.exists():
        return {}

    try:
        raw = json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(raw, dict):
        return {}

    # Clean expired patterns
    cutoff = datetime.now(timezone.utc) - timedelta(days=PATTERN_DECAY_DAYS)
    cleaned: dict[str, dict] = {}

    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        last_seen_str = entry.get("last_seen", "")
        try:
            last_seen = datetime.fromisoformat(last_seen_str)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen >= cutoff:
                cleaned[key] = entry
        except (ValueError, TypeError):
            # If we cannot parse the date, keep the entry (be conservative)
            cleaned[key] = entry

    return cleaned


def save_patterns(patterns: dict[str, dict]) -> None:
    """Persist patterns to disk, creating parent directories if needed."""
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATTERNS_FILE.write_text(
        json.dumps(patterns, indent=2, default=str),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_decision(tool_name: str, tool_input: dict, decision: str) -> None:
    """
    Record a user decision for a tool invocation.

    Args:
        tool_name: Name of the tool.
        tool_input: Input parameters dict.
        decision: The decision string ("allow", "approve", "deny", "block").
    """
    if not LEARN_FROM_DECISIONS:
        return

    pattern_key = generate_pattern_key(tool_name, tool_input)
    patterns = load_patterns()

    now_iso = datetime.now(timezone.utc).isoformat()

    if pattern_key in patterns:
        entry = patterns[pattern_key]
    else:
        entry = {
            "pattern_key": pattern_key,
            "approval_count": 0,
            "denial_count": 0,
            "last_seen": now_iso,
            "auto_approve": False,
            "confidence": 0.0,
        }

    # Update counts
    decision_lower = decision.lower()
    if decision_lower in ("allow", "approve"):
        entry["approval_count"] = int(entry.get("approval_count", 0)) + 1
    elif decision_lower in ("deny", "block"):
        entry["denial_count"] = int(entry.get("denial_count", 0)) + 1

    entry["last_seen"] = now_iso

    # Determine auto_approve
    approvals: int = int(entry.get("approval_count", 0))
    denials: int = int(entry.get("denial_count", 0))

    if denials > 0:
        entry["auto_approve"] = False
    elif approvals >= PATTERN_MIN_SAMPLES:
        entry["auto_approve"] = True
    else:
        entry["auto_approve"] = False

    # Confidence
    total: int = approvals + denials
    entry["confidence"] = approvals / max(1, total)

    patterns[pattern_key] = entry
    save_patterns(patterns)


def check_pattern(tool_name: str, tool_input: dict) -> dict | None:
    """
    Check if a learned pattern exists for the given tool invocation.

    Args:
        tool_name: Name of the tool.
        tool_input: Input parameters dict.

    Returns:
        Dict with pattern info if found, None otherwise.
    """
    pattern_key = generate_pattern_key(tool_name, tool_input)
    patterns = load_patterns()

    entry = patterns.get(pattern_key)
    if entry is None:
        return None

    return {
        "pattern_key": entry.get("pattern_key", pattern_key),
        "auto_approve": entry.get("auto_approve", False),
        "confidence": entry.get("confidence", 0.0),
        "approval_count": entry.get("approval_count", 0),
        "denial_count": entry.get("denial_count", 0),
        "last_seen": entry.get("last_seen", ""),
    }


def list_patterns() -> list[dict]:
    """
    List all learned patterns, sorted by confidence descending.

    Returns:
        List of pattern dicts.
    """
    patterns = load_patterns()
    entries = list(patterns.values())
    entries.sort(key=lambda e: e.get("confidence", 0.0), reverse=True)
    return entries


def reset_patterns() -> None:
    """Delete all learned patterns."""
    if PATTERNS_FILE.exists():
        PATTERNS_FILE.unlink()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI interface for the pattern learner."""
    parser = argparse.ArgumentParser(
        description="Learn from user approval/denial patterns for auto-approval."
    )
    parser.add_argument(
        "--record",
        type=str,
        metavar="JSON",
        help="Record a decision. JSON with tool_name, tool_input, decision.",
    )
    parser.add_argument(
        "--check",
        type=str,
        metavar="JSON",
        help="Check for a learned pattern. JSON with tool_name, tool_input.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_all",
        help="List all learned patterns.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear all learned patterns.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output result as JSON.",
    )

    args = parser.parse_args()

    if args.reset:
        reset_patterns()
        print("All learned patterns cleared.")
        return

    if args.record:
        try:
            data = json.loads(args.record)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        decision = data.get("decision", "allow")
        record_decision(tool_name, tool_input, decision)
        key = generate_pattern_key(tool_name, tool_input)
        print(f"Recorded: {key} -> {decision}")
        return

    if args.check:
        try:
            data = json.loads(args.check)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        result = check_pattern(tool_name, tool_input)
        if result is None:
            if args.output_json:
                print(json.dumps({"found": False}))
            else:
                print("No learned pattern found.")
        else:
            if args.output_json:
                result["found"] = True
                print(json.dumps(result, indent=2))
            else:
                print(f"Pattern:      {result['pattern_key']}")
                print(f"Auto-approve: {result['auto_approve']}")
                print(f"Confidence:   {result['confidence']:.2f}")
                print(f"Approvals:    {result['approval_count']}")
                print(f"Denials:      {result['denial_count']}")
                print(f"Last seen:    {result['last_seen']}")
        return

    if args.list_all:
        entries = list_patterns()
        if args.output_json:
            print(json.dumps(entries, indent=2))
        else:
            if not entries:
                print("No learned patterns.")
            else:
                print(f"{'Pattern Key':<35} {'Auto':>5} {'Conf':>6} {'Appr':>5} {'Deny':>5}")
                print("-" * 65)
                for entry in entries:
                    print(
                        f"{entry.get('pattern_key', '?'):<35} "
                        f"{'yes' if entry.get('auto_approve') else 'no':>5} "
                        f"{entry.get('confidence', 0.0):>6.2f} "
                        f"{entry.get('approval_count', 0):>5} "
                        f"{entry.get('denial_count', 0):>5}"
                    )
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
