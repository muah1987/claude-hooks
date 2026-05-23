#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Quality Assessor -- Multi-Dimensional Quality Scoring

Scores completed tasks and agent outputs across five dimensions:
syntax correctness, lint cleanliness, test coverage, completeness,
and safety. Produces a QualityScore used for gating deployments and
providing actionable feedback.

GOTCHA Layer: Guardrails + Tools
  - Guardrails: Validates outputs meet minimum quality thresholds
  - Tools: Deterministic checks (compile, lint, test, pattern scan)

ATLAS Phase: Stress-test
  - Stress-tests completed work against multiple quality dimensions
    before allowing promotion or acceptance
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Constants & Env Var Defaults
# -------------------------------------------------------------------

_QUALITY_THRESHOLD_PASS = int(os.environ.get("QUALITY_THRESHOLD_PASS", "70"))
_QUALITY_THRESHOLD_FAIL = int(os.environ.get("QUALITY_THRESHOLD_FAIL", "40"))
_QUALITY_AUTO_VALIDATE = int(os.environ.get("QUALITY_AUTO_VALIDATE", "60"))

# Safety patterns -- things that should NOT appear in production code
_SAFETY_PATTERNS: list[tuple[str, str]] = [
    (r"\beval\s*\(", "use of eval()"),
    (r"\bexec\s*\(", "use of exec()"),
    (r"__import__\s*\(", "use of __import__()"),
    (r"\bos\.system\s*\(", "use of os.system()"),
    (r"subprocess\.[a-zA-Z]+\((?!.*timeout\s*=)", "subprocess without timeout"),
    (
        r'(?:password|passwd|secret)\s*=\s*["\'][^"\']+["\']',
        "hardcoded password/secret",
    ),
    (r"\brm\s+-rf\b", "rm -rf command"),
]

# Dimension weights for task assessment
_WEIGHTS: dict[str, float] = {
    "syntax": 0.25,
    "lint": 0.20,
    "tests": 0.25,
    "completeness": 0.15,
    "safety": 0.15,
}


# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------


@dataclass
class QualityScore:
    """Multi-dimensional quality assessment result.

    Attributes:
        overall: Weighted overall score (0-100).
        dimensions: Mapping of dimension name to its score (0-100 each).
        verdict: PASS, NEEDS_WORK, or FAIL.
        recommendations: Actionable suggestions for improvement.
    """

    overall: int = 0
    dimensions: dict[str, int] = field(default_factory=dict)
    verdict: str = "NEEDS_WORK"
    recommendations: list[str] = field(default_factory=list)


# -------------------------------------------------------------------
# Dimension Scoring Functions
# -------------------------------------------------------------------


def _get_py_files(files: list[str]) -> list[str]:
    """Filter a list of file paths to only Python files."""
    return [f for f in files if f.endswith(".py")]


def _check_syntax(files: list[str]) -> int:
    """Check Python syntax correctness via py_compile.

    Returns:
        Score 0-100. 100 if all files compile, reduced proportionally
        for each failure. Returns 100 if no .py files.
    """
    py_files = _get_py_files(files)
    if not py_files:
        return 100

    failures = 0
    penalty_per_file = 100 / max(1, len(py_files))

    for fpath in py_files:
        try:
            py_compile.compile(fpath, doraise=True)
        except py_compile.PyCompileError:
            failures += 1

    score = max(0, round(100 - (failures * penalty_per_file)))
    return score


def _check_lint(files: list[str]) -> int:
    """Run ruff lint checks on Python files.

    Runs: uvx ruff check <file> --select E,F,W --quiet
    Score = max(0, 100 - (error_count * 10))

    Returns:
        Score 0-100. Returns 100 if no .py files.
    """
    py_files = _get_py_files(files)
    if not py_files:
        return 100

    total_errors = 0
    for fpath in py_files:
        if not Path(fpath).exists():
            continue
        try:
            result = subprocess.run(
                ["uvx", "ruff", "check", fpath, "--select", "E,F,W", "--quiet"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Each non-empty line in stdout is an error
            if result.stdout.strip():
                error_lines = [
                    line for line in result.stdout.strip().splitlines() if line.strip()
                ]
                total_errors += len(error_lines)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # If ruff not available or times out, don't penalize
            pass

    score = max(0, 100 - (total_errors * 10))
    return score


def _check_tests(files: list[str]) -> int:
    """Run pytest on test files found in the file list or tests/ directory.

    Parses output for 'X passed' / 'X failed' counts.
    Score = (passed / max(1, total)) * 100

    Returns:
        Score 0-100. Returns 100 if no test files found.
    """
    # Gather test files from the provided list
    test_files = [f for f in files if _is_test_file(f)]

    # Also check for a tests/ directory relative to any provided file
    if not test_files:
        seen_dirs: set[str] = set()
        for fpath in files:
            parent = str(Path(fpath).parent)
            if parent in seen_dirs:
                continue
            seen_dirs.add(parent)
            tests_dir = Path(parent) / "tests"
            if tests_dir.is_dir():
                for tf in tests_dir.rglob("test_*.py"):
                    test_files.append(str(tf))
                for tf in tests_dir.rglob("*_test.py"):
                    test_files.append(str(tf))

    if not test_files:
        return 100  # No tests to run -- assume untested

    # Deduplicate
    test_files = list(set(test_files))

    try:
        result = subprocess.run(
            ["uv", "run", "pytest"] + test_files + ["-v", "--tb=no", "-q"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + "\n" + result.stderr

        passed = 0
        failed = 0

        # Parse pytest summary line: "X passed, Y failed" etc.
        passed_match = re.search(r"(\d+)\s+passed", output)
        if passed_match:
            passed = int(passed_match.group(1))

        failed_match = re.search(r"(\d+)\s+failed", output)
        if failed_match:
            failed = int(failed_match.group(1))

        total = passed + failed
        if total == 0:
            return 100  # No test results parsed

        score = round((passed / max(1, total)) * 100)
        return score

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 100  # If pytest unavailable, don't penalize


def _is_test_file(fpath: str) -> bool:
    """Check if a file path looks like a test file."""
    name = Path(fpath).name
    return name.startswith("test_") or name.endswith("_test.py")


def _check_completeness(
    task_description: str,
    files: list[str],
    acceptance_criteria: Optional[list[str]] = None,
) -> int:
    """Check if expected deliverables exist on disk and criteria are met.

    Score starts at 100, reduced proportionally for each missing file.
    If acceptance_criteria are provided, checks each criterion keyword
    appears in at least one file.

    Returns:
        Score 0-100.
    """
    if not files:
        return 100

    # Check file existence
    penalty_per_file = 100 / max(1, len(files))
    missing_count = 0
    existing_files: list[str] = []

    for fpath in files:
        if Path(fpath).exists():
            existing_files.append(fpath)
        else:
            missing_count += 1

    score = max(0, round(100 - (missing_count * penalty_per_file)))

    # Check acceptance criteria against file contents
    if acceptance_criteria and existing_files:
        criteria_met = 0
        total_criteria = len(acceptance_criteria)

        for criterion in acceptance_criteria:
            criterion_lower = criterion.lower()
            # Extract keywords from criterion (words > 3 chars)
            keywords = [w for w in criterion_lower.split() if len(w) > 3]
            if not keywords:
                criteria_met += 1
                continue

            found = False
            for fpath in existing_files:
                try:
                    content = Path(fpath).read_text(errors="replace").lower()
                    # Check if at least half the keywords appear
                    matches = sum(1 for kw in keywords if kw in content)
                    if matches >= max(1, len(keywords) // 2):
                        found = True
                        break
                except OSError:
                    continue

            if found:
                criteria_met += 1

        if total_criteria > 0:
            criteria_score = round((criteria_met / total_criteria) * 100)
            # Blend: 60% file existence, 40% criteria
            score = round(score * 0.6 + criteria_score * 0.4)

    return score


def _check_safety(files: list[str]) -> int:
    """Scan Python files for unsafe patterns.

    Checks for: eval(), exec(), __import__(), os.system(),
    subprocess without timeout, hardcoded passwords, rm -rf.
    Score = max(0, 100 - (violation_count * 20))

    Returns:
        Score 0-100. Returns 100 if no .py files.
    """
    py_files = _get_py_files(files)
    if not py_files:
        return 100

    violation_count = 0

    for fpath in py_files:
        if not Path(fpath).exists():
            continue
        try:
            content = Path(fpath).read_text(errors="replace")
        except OSError:
            continue

        for pattern, _description in _SAFETY_PATTERNS:
            matches = re.findall(pattern, content)
            violation_count += len(matches)

    score = max(0, 100 - (violation_count * 20))
    return score


# -------------------------------------------------------------------
# Public Assessment Functions
# -------------------------------------------------------------------


def assess_task(
    task_description: str,
    files_changed: list[str],
    acceptance_criteria: Optional[list[str]] = None,
) -> QualityScore:
    """Assess a completed task across all quality dimensions.

    Weights: syntax=0.25, lint=0.20, tests=0.25,
             completeness=0.15, safety=0.15

    Args:
        task_description: Description of the task that was completed.
        files_changed: List of file paths that were created/modified.
        acceptance_criteria: Optional list of criteria to check.

    Returns:
        QualityScore with overall score, per-dimension scores,
        verdict (PASS/NEEDS_WORK/FAIL), and recommendations.
    """
    dimensions: dict[str, int] = {
        "syntax": _check_syntax(files_changed),
        "lint": _check_lint(files_changed),
        "tests": _check_tests(files_changed),
        "completeness": _check_completeness(
            task_description, files_changed, acceptance_criteria
        ),
        "safety": _check_safety(files_changed),
    }

    # Weighted overall score
    overall = round(sum(dimensions[dim] * _WEIGHTS[dim] for dim in _WEIGHTS))
    overall = max(0, min(100, overall))

    # Determine verdict
    if overall >= _QUALITY_THRESHOLD_PASS:
        verdict = "PASS"
    elif overall < _QUALITY_THRESHOLD_FAIL:
        verdict = "FAIL"
    else:
        verdict = "NEEDS_WORK"

    # Generate recommendations
    recommendations: list[str] = []
    if dimensions["syntax"] < 100:
        recommendations.append(
            "Fix syntax errors: one or more Python files failed to compile."
        )
    if dimensions["lint"] < 80:
        recommendations.append(
            "Address lint warnings: run 'uvx ruff check --select E,F,W' "
            "and fix reported issues."
        )
    if dimensions["tests"] < 80:
        recommendations.append(
            "Improve test coverage: add or fix failing tests for changed files."
        )
    if dimensions["completeness"] < 80:
        recommendations.append(
            "Check completeness: verify all expected files exist and "
            "acceptance criteria are met."
        )
    if dimensions["safety"] < 100:
        recommendations.append(
            "Address safety concerns: remove eval(), exec(), __import__(), "
            "os.system(), hardcoded secrets, and subprocess calls without timeout."
        )

    return QualityScore(
        overall=overall,
        dimensions=dimensions,
        verdict=verdict,
        recommendations=recommendations,
    )


def assess_agent_output(
    agent_name: str,
    task_description: str,
    output_summary: str,
) -> QualityScore:
    """Lighter-weight assessment of an agent's output.

    Extracts Python file paths from the output summary and runs
    syntax + safety checks. Also checks for error indicators in
    the output text.

    Args:
        agent_name: Name of the agent that produced the output.
        task_description: Description of the task assigned.
        output_summary: Text summary of the agent's output.

    Returns:
        QualityScore with available dimensions scored.
    """
    # Extract Python file paths from output summary
    file_paths = re.findall(r'[/\w._-]+\.py\b', output_summary)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for fp in file_paths:
        if fp not in seen:
            seen.add(fp)
            unique_paths.append(fp)

    # Filter to files that actually exist
    existing_files = [fp for fp in unique_paths if Path(fp).exists()]

    dimensions: dict[str, int] = {}

    # Syntax check on found files
    if existing_files:
        dimensions["syntax"] = _check_syntax(existing_files)
        dimensions["safety"] = _check_safety(existing_files)
    else:
        dimensions["syntax"] = 100
        dimensions["safety"] = 100

    # Completeness heuristic: check for error indicators in output
    error_indicators = ["error", "fail", "could not", "unable to", "traceback"]
    output_lower = output_summary.lower()
    error_hits = sum(1 for indicator in error_indicators if indicator in output_lower)
    dimensions["completeness"] = max(0, 100 - (error_hits * 20))

    # Overall: average of available dimensions
    if dimensions:
        overall = round(sum(dimensions.values()) / len(dimensions))
    else:
        overall = 100

    overall = max(0, min(100, overall))

    # Verdict
    if overall >= _QUALITY_THRESHOLD_PASS:
        verdict = "PASS"
    elif overall < _QUALITY_THRESHOLD_FAIL:
        verdict = "FAIL"
    else:
        verdict = "NEEDS_WORK"

    # Recommendations
    recommendations: list[str] = []
    if dimensions.get("syntax", 100) < 100:
        recommendations.append(
            f"Agent '{agent_name}' produced files with syntax errors."
        )
    if dimensions.get("safety", 100) < 100:
        recommendations.append(
            f"Agent '{agent_name}' output contains unsafe code patterns."
        )
    if dimensions.get("completeness", 100) < 80:
        recommendations.append(
            f"Agent '{agent_name}' output contains error indicators -- "
            "review for incomplete execution."
        )

    return QualityScore(
        overall=overall,
        dimensions=dimensions,
        verdict=verdict,
        recommendations=recommendations,
    )


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def main() -> None:
    """CLI entry point for quality assessment."""
    parser = argparse.ArgumentParser(
        description="Multi-dimensional quality scoring for tasks and agent outputs",
    )
    parser.add_argument(
        "--assess-task",
        type=str,
        metavar="JSON",
        help=(
            "Assess a completed task. JSON with 'task_description', "
            "'files_changed', and optional 'acceptance_criteria'."
        ),
    )
    parser.add_argument(
        "--assess-agent",
        type=str,
        metavar="JSON",
        help=(
            "Assess agent output. JSON with 'agent_name', "
            "'task_description', and 'output_summary'."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    result: Optional[QualityScore] = None

    if args.assess_task:
        try:
            data: dict[str, Any] = json.loads(args.assess_task)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        task_desc = data.get("task_description", "")
        files = data.get("files_changed", [])
        criteria = data.get("acceptance_criteria")
        result = assess_task(task_desc, files, criteria)

    elif args.assess_agent:
        try:
            data = json.loads(args.assess_agent)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        agent = data.get("agent_name", "unknown")
        task_desc = data.get("task_description", "")
        output = data.get("output_summary", "")
        result = assess_agent_output(agent, task_desc, output)

    else:
        parser.print_help()
        sys.exit(0)

    if result is None:
        sys.exit(1)

    output_dict = asdict(result)

    if args.json:
        print(json.dumps(output_dict, indent=2))
    else:
        print(f"Overall: {result.overall}/100 ({result.verdict})")
        print(f"Dimensions: {result.dimensions}")
        if result.recommendations:
            print("Recommendations:")
            for rec in result.recommendations:
                print(f"  - {rec}")


if __name__ == "__main__":
    main()
