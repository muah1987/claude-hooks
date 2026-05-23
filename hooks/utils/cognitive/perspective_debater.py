#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
perspective_debater.py - Four-faculty debate synthesis with Guardian VETO.

GOTCHA Layer: Orchestration (reasoning/decision support)
ATLAS Phase: DECIDE - Multi-perspective risk evaluation

Implements a deterministic four-faculty debate system:
  - Warrior: Speed and impact focus
  - Thinker: Root cause analysis
  - Guardian: Safety and compliance (with VETO power)
  - Worker: SOP compliance

Each faculty evaluates the risk independently, then votes are weighted
and aggregated to produce a consensus decision of allow/ask/deny.

Environment Variables:
  CCE_LLM_DEBATE   - Reserved for future LLM-based debate (default: false)
  CCE_GUARDIAN_VETO - Enable Guardian veto power (default: true)
  RISK_THRESHOLD_CRITICAL - Risk score that triggers Guardian veto (default: 90)
"""

from __future__ import annotations
__version__ = "2026.04.20.3"

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

CCE_GUARDIAN_VETO: bool = os.getenv("CCE_GUARDIAN_VETO", "true").lower() in ("true", "1", "yes")
RISK_THRESHOLD_CRITICAL: int = int(os.getenv("RISK_THRESHOLD_CRITICAL", "90"))

# Known safe / risky tool lists for Worker faculty
SAFE_TOOLS: set[str] = {"Read", "Glob", "Grep"}
RISKY_TOOLS: set[str] = {"Bash", "Write"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Faculty:
    """Represents a single debate faculty with its perspective and proposal."""

    name: str
    emoji: str
    weight: float
    perspective: str
    proposal: str  # "allow", "ask", or "deny"
    risk_modifier: int


@dataclass
class Debate:
    """Result of a four-faculty debate session."""

    faculties: list[Faculty]
    consensus: str  # "allow", "ask", or "deny"
    winning_faculty: str
    score: float
    log: str  # human-readable debate log
    guardian_veto: bool


# ---------------------------------------------------------------------------
# Faculty creation helpers
# ---------------------------------------------------------------------------

def _create_warrior() -> Faculty:
    return Faculty(
        name="Warrior",
        emoji="\u2694\ufe0f",
        weight=1.0,
        perspective="Allow it, user needs to make progress.",
        proposal="",
        risk_modifier=-15,
    )


def _create_thinker() -> Faculty:
    return Faculty(
        name="Thinker",
        emoji="\U0001f300",
        weight=1.0,
        perspective="Consider why this is needed and if there's a safer alternative.",
        proposal="",
        risk_modifier=5,
    )


def _create_guardian() -> Faculty:
    return Faculty(
        name="Guardian",
        emoji="\U0001f441\ufe0f",
        weight=1.0,
        perspective="Block if any risk of data loss or secret exposure.",
        proposal="",
        risk_modifier=20,
    )


def _create_worker() -> Faculty:
    return Faculty(
        name="Worker",
        emoji="\U0001f9f9",
        weight=1.0,
        perspective="Follow the established pattern. Check if this matches known safe operations.",
        proposal="",
        risk_modifier=0,
    )


# ---------------------------------------------------------------------------
# Faculty proposal generation (deterministic heuristics)
# ---------------------------------------------------------------------------

def _warrior_propose(risk_score: int, risk_category: str, context: dict | None,
                     tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """Warrior evaluates risk from a speed/impact perspective."""
    if risk_score < 50:
        proposal = "allow"
        text = "Risk is manageable. Let the user proceed without delay."
    elif risk_score < 70:
        proposal = "ask"
        text = "Moderate risk detected. Confirm with user before proceeding."
    else:
        proposal = "deny"
        text = "High risk threatens progress more than blocking does. Deny."
    return proposal, text


def _thinker_propose(risk_score: int, risk_category: str, context: dict | None,
                     tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """Thinker evaluates from a root-cause analysis perspective."""
    if risk_score < 40:
        proposal = "allow"
        text = "Low risk. The operation appears well-understood and safe."
    elif risk_score < 80:
        proposal = "ask"
        text = (
            "Medium risk zone. Worth considering whether there is a "
            "safer alternative before proceeding."
        )
    else:
        proposal = "deny"
        text = "Risk is too high. Underlying cause needs investigation first."
    return proposal, text


def _guardian_propose(risk_score: int, risk_category: str, context: dict | None,
                      tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """Guardian evaluates from a safety/compliance perspective. May VETO."""
    if risk_score >= RISK_THRESHOLD_CRITICAL:
        proposal = "deny"
        text = (
            f"VETO: Risk score {risk_score} meets or exceeds critical "
            f"threshold ({RISK_THRESHOLD_CRITICAL}). Operation blocked for safety."
        )
    elif risk_score >= 60:
        proposal = "deny"
        text = "Risk is elevated. Potential for data loss or secret exposure. Blocking."
    elif risk_score >= 30:
        proposal = "ask"
        text = "Moderate risk. Requesting user confirmation before allowing."
    else:
        proposal = "allow"
        text = "Risk is within acceptable bounds. No safety concerns."
    return proposal, text


def _worker_propose(risk_score: int, risk_category: str, context: dict | None,
                    tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """Worker evaluates from an SOP compliance perspective."""
    if tool_name in SAFE_TOOLS:
        proposal = "allow"
        text = f"{tool_name} is a known safe operation. Matches established patterns."
    elif tool_name in RISKY_TOOLS and risk_score > 50:
        proposal = "ask"
        text = (
            f"{tool_name} is a potentially risky tool and risk score is "
            f"above 50. Confirm with user."
        )
    else:
        proposal = "allow"
        text = "Operation matches known safe patterns or low risk threshold."
    return proposal, text


# Mapping from faculty name to its proposal function
_PROPOSAL_FUNCTIONS = {
    "Warrior": _warrior_propose,
    "Thinker": _thinker_propose,
    "Guardian": _guardian_propose,
    "Worker": _worker_propose,
}


# ---------------------------------------------------------------------------
# Core debate engine
# ---------------------------------------------------------------------------

def debate(
    risk_score: int,
    risk_category: str,
    context: dict | None = None,
    tool_name: str = "",
    tool_input: dict | None = None,
) -> Debate:
    """
    Run a four-faculty debate and return the consensus result.

    Args:
        risk_score: Numeric risk score (0-100).
        risk_category: Category string e.g. "LOW", "MEDIUM", "HIGH", "CRITICAL".
        context: Optional context dict (may contain time_sensitivity, etc.).
        tool_name: Name of the tool being evaluated.
        tool_input: Input parameters for the tool.

    Returns:
        Debate dataclass with consensus, scoring, and full log.
    """
    # Step 1: Create fresh faculty instances
    warrior = _create_warrior()
    thinker = _create_thinker()
    guardian = _create_guardian()
    worker = _create_worker()
    faculties = [warrior, thinker, guardian, worker]

    # Step 2: Apply weight bonuses based on context
    if risk_category in ("HIGH", "CRITICAL"):
        guardian.weight += 50

    if context and context.get("time_sensitivity") == "IMMEDIATE":
        warrior.weight += 30

    # Step 3: Generate proposals for each faculty
    for faculty in faculties:
        propose_fn = _PROPOSAL_FUNCTIONS[faculty.name]
        proposal, proposal_text = propose_fn(
            risk_score, risk_category, context, tool_name, tool_input
        )
        faculty.proposal = proposal
        faculty.perspective = proposal_text

    # Step 4: Guardian VETO check
    guardian_veto = False
    if (
        CCE_GUARDIAN_VETO
        and guardian.proposal == "deny"
        and risk_score >= RISK_THRESHOLD_CRITICAL
    ):
        guardian_veto = True

    # Step 5: Scoring
    total_weight = 0.0
    weighted_score_sum = 0.0
    faculty_scores: dict[str, float] = {}

    for faculty in faculties:
        if faculty.proposal == "allow":
            raw = 1.0
        elif faculty.proposal == "ask":
            raw = 0.5
        else:
            raw = 0.0

        faculty_score = faculty.weight * raw
        faculty_scores[faculty.name] = faculty_score
        weighted_score_sum += faculty_score
        total_weight += faculty.weight

    normalized_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0

    # Determine consensus from score
    if normalized_score > 0.6:
        consensus = "allow"
    elif normalized_score > 0.3:
        consensus = "ask"
    else:
        consensus = "deny"

    # Override with Guardian VETO
    if guardian_veto:
        consensus = "deny"

    # Determine winning faculty (highest individual weighted score)
    winning_faculty = max(faculty_scores, key=lambda k: faculty_scores[k])

    # Step 6: Build debate log
    log_lines = [
        f"{'=' * 60}",
        f"  DEBATE SESSION  |  Risk: {risk_score}  |  Category: {risk_category}",
        f"{'=' * 60}",
        "",
    ]
    for faculty in faculties:
        veto_marker = " [VETO]" if (faculty.name == "Guardian" and guardian_veto) else ""
        log_lines.append(
            f"  {faculty.emoji} {faculty.name.upper()} "
            f"(w={faculty.weight:.1f}): {faculty.proposal.upper()}{veto_marker}"
        )
        log_lines.append(f"     {faculty.perspective}")
        log_lines.append("")

    log_lines.append(f"  Score: {normalized_score:.3f}  |  Consensus: {consensus.upper()}")
    if guardian_veto:
        log_lines.append("  ** Guardian VETO active - consensus forced to DENY **")
    log_lines.append(f"{'=' * 60}")

    debate_log = "\n".join(log_lines)

    return Debate(
        faculties=faculties,
        consensus=consensus,
        winning_faculty=winning_faculty,
        score=normalized_score,
        log=debate_log,
        guardian_veto=guardian_veto,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_debate_log(debate_result: Debate) -> str:
    """Return the human-readable debate log from a Debate result."""
    return debate_result.log


def _debate_to_dict(debate_result: Debate) -> dict:
    """Convert a Debate to a JSON-serializable dict."""
    return {
        "faculties": [asdict(f) for f in debate_result.faculties],
        "consensus": debate_result.consensus,
        "winning_faculty": debate_result.winning_faculty,
        "score": debate_result.score,
        "log": debate_result.log,
        "guardian_veto": debate_result.guardian_veto,
    }


def _verbose_scoring(debate_result: Debate) -> str:
    """Return detailed scoring breakdown."""
    lines = [
        "",
        "--- Scoring Breakdown ---",
    ]
    total_weight = sum(f.weight for f in debate_result.faculties)
    for faculty in debate_result.faculties:
        if faculty.proposal == "allow":
            raw = 1.0
        elif faculty.proposal == "ask":
            raw = 0.5
        else:
            raw = 0.0
        contrib = faculty.weight * raw
        pct = (contrib / total_weight * 100) if total_weight > 0 else 0.0
        lines.append(
            f"  {faculty.emoji} {faculty.name}: "
            f"weight={faculty.weight:.1f} x raw={raw:.1f} = {contrib:.2f} "
            f"({pct:.1f}% of total)"
        )
    lines.append(f"  Total weight: {total_weight:.1f}")
    lines.append(f"  Normalized score: {debate_result.score:.3f}")
    lines.append(f"  Final consensus: {debate_result.consensus.upper()}")
    lines.append("--- End Breakdown ---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI interface for the perspective debater."""
    parser = argparse.ArgumentParser(
        description="Four-faculty debate synthesis with Guardian VETO."
    )
    parser.add_argument(
        "--debate",
        type=str,
        help=(
            "JSON string with keys: risk_score (int), risk_category (str), "
            "and optional context (dict), tool_name (str), tool_input (dict)."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed scoring breakdown.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output result as JSON.",
    )

    args = parser.parse_args()

    if not args.debate:
        parser.print_help()
        sys.exit(1)

    try:
        data = json.loads(args.debate)
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON input: {exc}", file=sys.stderr)
        sys.exit(1)

    risk_score = data.get("risk_score", 0)
    risk_category = data.get("risk_category", "LOW")
    context = data.get("context")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input")

    result = debate(
        risk_score=risk_score,
        risk_category=risk_category,
        context=context,
        tool_name=tool_name,
        tool_input=tool_input,
    )

    if args.output_json:
        output = _debate_to_dict(result)
        if args.verbose:
            # Attach verbose info as an extra key
            output["scoring_breakdown"] = _verbose_scoring(result)
        print(json.dumps(output, indent=2))
    else:
        print(format_debate_log(result))
        if args.verbose:
            print(_verbose_scoring(result))


if __name__ == "__main__":
    main()
