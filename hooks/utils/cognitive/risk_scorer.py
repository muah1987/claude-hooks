#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Risk Scorer -- Multi-Factor Risk Assessment for Tool Operations

Scores tool commands and file access on a 0-100 scale across four
weighted factors: destructiveness, target sensitivity, scope breadth,
and reversibility. Produces a categorised RiskScore used by the
policy selector and confidence estimator.

GOTCHA Layer: Guardrails + Orchestration
  - Guardrails: Quantifies operational risk before execution
  - Orchestration: Feeds numeric risk into downstream decision logic

ATLAS Phase: Link
  - Connects tool intent to a measurable risk profile that other
    cognitive modules consume
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

MAX_SCORE = 100

# Default thresholds (overridable via env vars)
_DEFAULT_CRITICAL = 90
_DEFAULT_HIGH = 70
_DEFAULT_MEDIUM = 40
_DEFAULT_LOW = 20

# Destructive Bash commands and their base scores
_DESTRUCTIVE_COMMANDS: dict[str, int] = {
    "rm": 40,
    "rmdir": 40,
    "delete": 35,
    "drop": 35,
    "truncate": 35,
    "kill": 30,
    "pkill": 30,
    "killall": 30,
    "chmod": 25,
    "chown": 25,
    "mkfs": 40,
    "dd": 35,
    "mv": 20,
    "cp": 10,
    "curl": 15,
    "wget": 15,
    "pip": 15,
    "npm": 15,
    "apt": 20,
    "yum": 20,
    "brew": 15,
    "docker": 20,
    "git": 10,
}

# Sensitive file patterns
_SENSITIVE_PATTERNS: list[tuple[str, int]] = [
    (r"\.env", 30),
    (r"credentials", 30),
    (r"secret", 30),
    (r"token\.json", 30),
    (r"\.pem$", 30),
    (r"\.key$", 30),
    (r"id_rsa", 30),
    (r"docker-compose", 25),
    (r"nginx\.conf", 25),
    (r"Dockerfile", 25),
    (r"\.ya?ml$", 20),
    (r"\.toml$", 15),
    (r"\.cfg$", 15),
    (r"\.ini$", 15),
    (r"\.py$", 15),
    (r"\.js$", 15),
    (r"\.ts$", 15),
    (r"\.jsx$", 15),
    (r"\.tsx$", 15),
    (r"\.go$", 15),
    (r"\.rs$", 15),
    (r"test", 5),
    (r"spec", 5),
    (r"\.md$", 2),
    (r"\.txt$", 2),
    (r"\.rst$", 2),
    (r"README", 2),
    (r"LICENSE", 2),
    (r"CHANGELOG", 2),
]

# Recursive / broad-scope indicators
_RECURSIVE_INDICATORS: list[str] = [
    "-r", "-R", "--recursive",
    "-rf", "-Rf",
    "find", "xargs",
    "-exec",
    "**/",
    "**",
    "...",
]

# Tool destructiveness base scores
_TOOL_SCORES: dict[str, int] = {
    "Write": 20,
    "Edit": 15,
    "MultiEdit": 15,
    "NotebookEdit": 15,
    "Read": 5,
    "Glob": 2,
    "Grep": 2,
    "WebFetch": 2,
    "WebSearch": 1,
}

# Operation reversibility scores
_REVERSIBILITY: dict[str, int] = {
    "delete": 15,
    "write": 10,
    "overwrite": 10,
    "edit": 5,
    "append": 5,
    "read": 0,
}


# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------


@dataclass
class RiskScore:
    """Multi-factor risk assessment result.

    Attributes:
        score: Overall risk score (0-100).
        factors: Mapping of factor name to its contribution.
        category: LOW, MEDIUM, HIGH, or CRITICAL.
        explanation: Human-readable summary.
    """

    score: int = 0
    factors: dict[str, int] = field(default_factory=dict)
    category: str = "LOW"
    explanation: str = ""


# -------------------------------------------------------------------
# Threshold helpers
# -------------------------------------------------------------------


def _threshold(env_var: str, default: int) -> int:
    """Read an integer threshold from an env var."""
    raw = os.environ.get(env_var, "").strip()
    if raw.isdigit():
        return int(raw)
    return default


def categorize_score(score: int) -> str:
    """Categorise a numeric risk score.

    Thresholds are read from env vars:
        RISK_THRESHOLD_CRITICAL, RISK_THRESHOLD_HIGH,
        RISK_THRESHOLD_MEDIUM, RISK_THRESHOLD_LOW.

    Returns:
        One of CRITICAL, HIGH, MEDIUM, or LOW.
    """
    critical = _threshold("RISK_THRESHOLD_CRITICAL", _DEFAULT_CRITICAL)
    high = _threshold("RISK_THRESHOLD_HIGH", _DEFAULT_HIGH)
    medium = _threshold("RISK_THRESHOLD_MEDIUM", _DEFAULT_MEDIUM)

    if score >= critical:
        return "CRITICAL"
    if score >= high:
        return "HIGH"
    if score >= medium:
        return "MEDIUM"
    return "LOW"


# -------------------------------------------------------------------
# Internal scoring helpers
# -------------------------------------------------------------------


def _extract_command(tool_input: dict[str, Any]) -> str:
    """Extract the shell command string from Bash tool_input."""
    return tool_input.get("command", "")


def _extract_file_path(tool_input: dict[str, Any]) -> str:
    """Extract a file path from tool_input (various key names)."""
    for key in ("file_path", "path", "notebook_path"):
        val = tool_input.get(key, "")
        if val:
            return str(val)
    # Fallback: try to parse from command
    cmd = _extract_command(tool_input)
    parts = cmd.split()
    for part in reversed(parts):
        if "/" in part or "." in part:
            return part
    return ""


def _score_destructiveness(tool_name: str, tool_input: dict[str, Any]) -> int:
    """Factor 1: Command destructiveness (0-40)."""
    if tool_name == "Bash":
        cmd = _extract_command(tool_input)
        cmd_lower = cmd.lower()
        best = 10  # default for unknown Bash
        for keyword, value in _DESTRUCTIVE_COMMANDS.items():
            if keyword in cmd_lower:
                best = max(best, value)
        return min(best, 40)

    return min(_TOOL_SCORES.get(tool_name, 10), 40)


def _score_sensitivity(tool_name: str, tool_input: dict[str, Any]) -> int:
    """Factor 2: Target sensitivity (0-30)."""
    path = _extract_file_path(tool_input)
    if not path:
        cmd = _extract_command(tool_input)
        path = cmd

    if not path:
        return 5  # unknown target, moderate default

    path_lower = path.lower()
    best = 2  # baseline
    for pattern, value in _SENSITIVE_PATTERNS:
        if re.search(pattern, path_lower):
            best = max(best, value)
    return min(best, 30)


def _score_scope(tool_name: str, tool_input: dict[str, Any]) -> int:
    """Factor 3: Scope breadth (0-15)."""
    if tool_name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        return 1  # read-only

    cmd = _extract_command(tool_input)
    combined = cmd + " " + json.dumps(tool_input)
    combined_lower = combined.lower()

    for indicator in _RECURSIVE_INDICATORS:
        if indicator in combined_lower:
            return 15

    path = _extract_file_path(tool_input)
    if path:
        # Directory-level if path ends with / or has no extension
        p = PurePosixPath(path)
        if path.endswith("/") or (not p.suffix and "/" in path):
            return 10
        return 5

    return 5  # single file default


def _score_reversibility(tool_name: str, tool_input: dict[str, Any]) -> int:
    """Factor 4: Reversibility (0-15)."""
    if tool_name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        return 0

    cmd = _extract_command(tool_input)
    cmd_lower = cmd.lower()

    # Irreversible deletes
    delete_keywords = ["rm ", "rm\t", "rmdir", "delete", "drop", "unlink"]
    for kw in delete_keywords:
        if kw in cmd_lower:
            return 15

    if tool_name == "Write":
        return 10  # full overwrite

    if tool_name in ("Edit", "MultiEdit", "NotebookEdit"):
        return 5

    # Bash write-like ops
    if ">" in cmd and ">>" not in cmd:
        return 10
    if ">>" in cmd:
        return 5

    return 5  # default for unknown mutation


# -------------------------------------------------------------------
# Public scoring functions
# -------------------------------------------------------------------


def score_command(
    tool_name: str,
    tool_input: dict[str, Any],
    context: Optional[dict[str, Any]] = None,
) -> RiskScore:
    """Score a tool command across four risk factors.

    Args:
        tool_name: The tool being invoked (Bash, Write, Edit, etc.).
        tool_input: The tool's input parameters.
        context: Optional contextual information.

    Returns:
        RiskScore with score, factors, category, and explanation.
    """
    factors: dict[str, int] = {
        "destructiveness": _score_destructiveness(tool_name, tool_input),
        "sensitivity": _score_sensitivity(tool_name, tool_input),
        "scope": _score_scope(tool_name, tool_input),
        "reversibility": _score_reversibility(tool_name, tool_input),
    }

    total = min(sum(factors.values()), MAX_SCORE)
    category = categorize_score(total)

    parts: list[str] = []
    for name, value in factors.items():
        parts.append(f"{name}={value}")
    explanation = (
        f"Tool '{tool_name}' scored {total}/100 ({category}). "
        f"Factors: {', '.join(parts)}."
    )

    return RiskScore(
        score=total,
        factors=factors,
        category=category,
        explanation=explanation,
    )


def score_file_access(
    file_path: str,
    operation: str,
) -> RiskScore:
    """Score a file-level access operation.

    Args:
        file_path: Path to the target file.
        operation: One of read, write, delete, edit.

    Returns:
        RiskScore focused on file characteristics.
    """
    op_lower = operation.lower()

    # Map operation to a pseudo tool for reuse
    tool_map: dict[str, str] = {
        "read": "Read",
        "write": "Write",
        "delete": "Bash",
        "edit": "Edit",
    }
    pseudo_tool = tool_map.get(op_lower, "Bash")
    pseudo_input: dict[str, Any] = {"file_path": file_path}

    if op_lower == "delete":
        pseudo_input["command"] = f"rm {file_path}"

    # Destructiveness from operation type
    op_destructiveness: dict[str, int] = {
        "read": 0,
        "write": 20,
        "delete": 40,
        "edit": 15,
    }
    destructiveness = op_destructiveness.get(op_lower, 10)

    sensitivity = _score_sensitivity(pseudo_tool, pseudo_input)

    # Scope: single file
    scope = 5
    if op_lower == "read":
        scope = 1

    reversibility = _REVERSIBILITY.get(op_lower, 5)

    factors: dict[str, int] = {
        "destructiveness": min(destructiveness, 40),
        "sensitivity": min(sensitivity, 30),
        "scope": min(scope, 15),
        "reversibility": min(reversibility, 15),
    }

    total = min(sum(factors.values()), MAX_SCORE)
    category = categorize_score(total)

    parts_list: list[str] = []
    for name, value in factors.items():
        parts_list.append(f"{name}={value}")
    explanation = (
        f"File '{file_path}' {op_lower} scored {total}/100 ({category}). "
        f"Factors: {', '.join(parts_list)}."
    )

    return RiskScore(
        score=total,
        factors=factors,
        category=category,
        explanation=explanation,
    )


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def main() -> None:
    """CLI entry point for risk scoring."""
    parser = argparse.ArgumentParser(
        description="Multi-factor risk scorer for tool operations",
    )
    parser.add_argument(
        "--score-command",
        type=str,
        metavar="JSON",
        help='Score a command. JSON with "tool_name" and "tool_input" keys.',
    )
    parser.add_argument(
        "--score-file",
        nargs=2,
        metavar=("PATH", "OP"),
        help="Score a file access. PATH is the file, OP is read/write/delete/edit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Include detailed explanation in output",
    )
    args = parser.parse_args()

    if args.score_command:
        try:
            data = json.loads(args.score_command)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        tool_name = data.get("tool_name", "Bash")
        tool_input = data.get("tool_input", {})
        context = data.get("context")
        result = score_command(tool_name, tool_input, context)

    elif args.score_file:
        file_path, operation = args.score_file
        result = score_file_access(file_path, operation)

    else:
        parser.print_help()
        sys.exit(0)

    output = asdict(result)
    if not args.explain:
        output.pop("explanation", None)

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Score: {result.score}/100 ({result.category})")
        print(f"Factors: {result.factors}")
        if args.explain:
            print(f"Explanation: {result.explanation}")


if __name__ == "__main__":
    main()
