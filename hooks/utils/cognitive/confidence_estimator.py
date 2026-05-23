#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Confidence Estimator -- Decision Confidence Scoring

Produces a 0.0-1.0 confidence score for tool execution decisions
by combining four sources: risk clarity, pattern history, policy
alignment, and context stability. Maps the result to a recommendation
of AUTO_EXECUTE, ASK_USER, or ESCALATE.

GOTCHA Layer: Guardrails + Orchestration
  - Guardrails: Prevents premature auto-execution on low confidence
  - Orchestration: Routes decisions to the correct approval pathway

ATLAS Phase: Link
  - Links risk assessment, policy, and pattern data into a single
    confidence signal consumed by the execution gateway
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

_DEFAULT_MIN_AUTO = 0.8
_DEFAULT_MIN_ASK = 0.5


# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------


@dataclass
class ConfidenceScore:
    """Decision confidence assessment result.

    Attributes:
        score: Overall confidence (0.0-1.0).
        sources: Mapping of source name to its contribution.
        recommendation: AUTO_EXECUTE, ASK_USER, or ESCALATE.
        reasoning: Human-readable explanation.
    """

    score: float = 0.0
    sources: dict[str, float] = field(default_factory=dict)
    recommendation: str = "ESCALATE"
    reasoning: str = ""


# -------------------------------------------------------------------
# Threshold helpers
# -------------------------------------------------------------------


def _threshold_float(env_var: str, default: float) -> float:
    """Read a float threshold from an env var."""
    raw = os.environ.get(env_var, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


# -------------------------------------------------------------------
# Internal source scoring
# -------------------------------------------------------------------


def _score_risk_clarity(risk_category: str) -> float:
    """Source 1: Risk clarity (0.0-0.3).

    Lower risk gives higher confidence that the decision is safe.
    """
    mapping: dict[str, float] = {
        "LOW": 0.3,
        "MEDIUM": 0.2,
        "HIGH": 0.1,
        "CRITICAL": 0.0,
    }
    return mapping.get(risk_category.upper(), 0.1)


def _score_pattern_history(
    pattern_match: Optional[dict[str, Any]],
) -> float:
    """Source 2: Pattern history (0.0-0.3).

    Strong pattern matches increase confidence.
    """
    if not pattern_match:
        return 0.0

    if pattern_match.get("auto_approve") is True:
        return 0.3

    confidence = pattern_match.get("confidence", 0)
    if isinstance(confidence, (int, float)) and confidence > 0.8:
        return 0.25

    if isinstance(confidence, (int, float)):
        return round(float(confidence) * 0.3, 4)

    return 0.0


def _score_policy_alignment(
    risk_score: int,
    policy_name: str,
) -> float:
    """Source 3: Policy alignment (0.0-0.2).

    Import and apply the policy to see what it would decide.
    """
    # Inline policy application to avoid circular imports.
    # Mirrors the thresholds from policy_selector.POLICIES.
    policy_thresholds: dict[str, tuple[int, int]] = {
        "STRICT": (60, 30),
        "BALANCED": (80, 50),
        "PERMISSIVE": (90, 70),
    }

    key = policy_name.strip().upper()
    block_at, ask_at = policy_thresholds.get(key, (80, 50))

    if risk_score >= block_at:
        return 0.0  # policy says deny
    if risk_score >= ask_at:
        return 0.1  # policy says ask
    return 0.2  # policy says allow


def _score_context_stability(
    context: Optional[dict[str, Any]],
) -> float:
    """Source 4: Context stability (0.0-0.2).

    Fewer anomaly flags mean more stable context.
    """
    if context is None:
        return 0.1  # neutral -- no context available

    anomaly_flags = context.get("anomaly_flags", [])
    if not isinstance(anomaly_flags, list):
        anomaly_flags = []

    count = len(anomaly_flags)
    if count == 0:
        return 0.2
    if count == 1:
        return 0.1
    return 0.05


# -------------------------------------------------------------------
# Public Function
# -------------------------------------------------------------------


def estimate_confidence(
    risk_score: int,
    risk_category: str,
    policy_name: str,
    pattern_match: Optional[dict[str, Any]] = None,
    context: Optional[dict[str, Any]] = None,
) -> ConfidenceScore:
    """Estimate decision confidence from multiple sources.

    Args:
        risk_score: Numeric risk (0-100).
        risk_category: LOW/MEDIUM/HIGH/CRITICAL.
        policy_name: Active policy name.
        pattern_match: Optional pattern match data.
        context: Optional context dict (may include anomaly_flags).

    Returns:
        ConfidenceScore with score, sources, recommendation, reasoning.
    """
    sources: dict[str, float] = {
        "risk_clarity": _score_risk_clarity(risk_category),
        "pattern_history": _score_pattern_history(pattern_match),
        "policy_alignment": _score_policy_alignment(
            risk_score, policy_name
        ),
        "context_stability": _score_context_stability(context),
    }

    total = round(sum(sources.values()), 4)
    total = min(total, 1.0)

    # Determine recommendation
    min_auto = _threshold_float("MIN_CONFIDENCE_AUTO", _DEFAULT_MIN_AUTO)
    min_ask = _threshold_float("MIN_CONFIDENCE_ASK", _DEFAULT_MIN_ASK)

    if total >= min_auto:
        recommendation = "AUTO_EXECUTE"
    elif total >= min_ask:
        recommendation = "ASK_USER"
    else:
        recommendation = "ESCALATE"

    # Build reasoning
    parts: list[str] = []
    for name, value in sources.items():
        parts.append(f"{name}={value:.2f}")
    reasoning = (
        f"Confidence {total:.2f} -> {recommendation}. "
        f"Sources: {', '.join(parts)}."
    )

    return ConfidenceScore(
        score=total,
        sources=sources,
        recommendation=recommendation,
        reasoning=reasoning,
    )


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def main() -> None:
    """CLI entry point for confidence estimation."""
    parser = argparse.ArgumentParser(
        description="Decision confidence estimator",
    )
    parser.add_argument(
        "--estimate",
        type=str,
        metavar="JSON",
        help=(
            "Estimate confidence. JSON with risk_score, risk_category, "
            "policy_name, and optional pattern_match/context."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON.",
    )
    args = parser.parse_args()

    if args.estimate:
        try:
            data = json.loads(args.estimate)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        risk_score = data.get("risk_score", 50)
        risk_category = data.get("risk_category", "MEDIUM")
        policy_name = data.get("policy_name", "BALANCED")
        pattern_match = data.get("pattern_match")
        context = data.get("context")

        result = estimate_confidence(
            risk_score=risk_score,
            risk_category=risk_category,
            policy_name=policy_name,
            pattern_match=pattern_match,
            context=context,
        )

        if args.json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print(
                f"Confidence: {result.score:.2f} "
                f"({result.recommendation})"
            )
            print(f"Sources: {result.sources}")
            print(f"Reasoning: {result.reasoning}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
