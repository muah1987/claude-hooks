#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Policy Selector -- Context-Aware Execution Policy

Selects one of three predefined policies (STRICT, BALANCED, PERMISSIVE)
based on environmental context such as branch type, time of day, and
cumulative risk. Each policy defines thresholds for blocking, asking,
and triggering debate.

GOTCHA Layer: Guardrails + Orchestration
  - Guardrails: Enforces appropriate caution levels per environment
  - Orchestration: Routes risk scores to allow/ask/deny decisions

ATLAS Phase: Link
  - Links environmental signals to the correct decision framework
    before tool execution proceeds
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------


@dataclass
class Policy:
    """Execution policy controlling risk tolerance.

    Attributes:
        name: STRICT, BALANCED, or PERMISSIVE.
        risk_block_threshold: Block if risk score >= this.
        risk_ask_threshold: Ask user if risk score >= this.
        auto_approve_reads: Allow read-only ops without asking.
        require_debate_above: Trigger debate if risk above this.
        description: Human-readable policy summary.
    """

    name: str
    risk_block_threshold: int
    risk_ask_threshold: int
    auto_approve_reads: bool
    require_debate_above: int
    description: str


# -------------------------------------------------------------------
# Predefined Policies
# -------------------------------------------------------------------

POLICIES: dict[str, Policy] = {
    "STRICT": Policy(
        name="STRICT",
        risk_block_threshold=60,
        risk_ask_threshold=30,
        auto_approve_reads=False,
        require_debate_above=40,
        description="Production/sensitive operations.",
    ),
    "BALANCED": Policy(
        name="BALANCED",
        risk_block_threshold=80,
        risk_ask_threshold=50,
        auto_approve_reads=True,
        require_debate_above=60,
        description="Default development.",
    ),
    "PERMISSIVE": Policy(
        name="PERMISSIVE",
        risk_block_threshold=90,
        risk_ask_threshold=70,
        auto_approve_reads=True,
        require_debate_above=80,
        description="Exploration/testing.",
    ),
}


# -------------------------------------------------------------------
# Public Functions
# -------------------------------------------------------------------


def get_policy(name: str) -> Policy:
    """Look up a policy by name (case-insensitive).

    Args:
        name: Policy name to retrieve.

    Returns:
        The matching Policy.

    Raises:
        ValueError: If the name does not match any policy.
    """
    key = name.strip().upper()
    if key not in POLICIES:
        valid = ", ".join(sorted(POLICIES.keys()))
        raise ValueError(
            f"Unknown policy '{name}'. Valid policies: {valid}"
        )
    return POLICIES[key]


def select_policy(context: Optional[dict[str, Any]] = None) -> Policy:
    """Select the appropriate policy based on context.

    Selection logic:
        1. DECISION_POLICY env var overrides everything.
        2. If POLICY_AUTO_SELECT is true (default), context signals
           determine the policy.
        3. Falls back to BALANCED.

    Args:
        context: Optional dict with keys like time_of_day,
            is_production_branch, task_phase, cumulative_risk.

    Returns:
        The selected Policy.
    """
    # Manual override via env var
    manual = os.environ.get("DECISION_POLICY", "").strip().upper()
    if manual and manual in POLICIES:
        return POLICIES[manual]

    # Auto-select (default behaviour)
    auto_select = os.environ.get(
        "POLICY_AUTO_SELECT", "true"
    ).strip().lower()

    if auto_select in ("true", "1", "yes"):
        ctx = context or {}

        # Night-time -> STRICT
        time_of_day = str(ctx.get("time_of_day", "")).lower()
        if time_of_day == "night":
            return POLICIES["STRICT"]

        # Production branch -> STRICT
        if ctx.get("is_production_branch") is True:
            return POLICIES["STRICT"]

        # Testing phase or test directory ops -> PERMISSIVE
        task_phase = str(ctx.get("task_phase", "")).lower()
        if task_phase == "testing":
            return POLICIES["PERMISSIVE"]

        # Check for test-directory indicators in context
        target_path = str(ctx.get("target_path", "")).lower()
        if "test" in target_path or "spec" in target_path:
            return POLICIES["PERMISSIVE"]

        # High cumulative risk -> STRICT
        cumulative_risk = ctx.get("cumulative_risk", 0)
        if isinstance(cumulative_risk, (int, float)) and cumulative_risk > 60:
            return POLICIES["STRICT"]

    # Default
    return POLICIES["BALANCED"]


def apply_policy(policy: Policy, risk_score: int) -> str:
    """Apply a policy to a risk score.

    Args:
        policy: The active policy.
        risk_score: Numeric risk score (0-100).

    Returns:
        One of "deny", "ask", or "allow".
    """
    if risk_score >= policy.risk_block_threshold:
        return "deny"
    if risk_score >= policy.risk_ask_threshold:
        return "ask"
    return "allow"


# -------------------------------------------------------------------
# CLI Formatting Helpers
# -------------------------------------------------------------------


def _format_policy_table() -> str:
    """Format all policies as a text table."""
    header = (
        f"{'Name':<12} {'Block>=':<9} {'Ask>=':<8} "
        f"{'AutoRead':<10} {'Debate>':<9} Description"
    )
    sep = "-" * len(header)
    lines: list[str] = [header, sep]
    for policy in POLICIES.values():
        lines.append(
            f"{policy.name:<12} {policy.risk_block_threshold:<9} "
            f"{policy.risk_ask_threshold:<8} "
            f"{str(policy.auto_approve_reads):<10} "
            f"{policy.require_debate_above:<9} "
            f"{policy.description}"
        )
    return "\n".join(lines)


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def main() -> None:
    """CLI entry point for policy selection."""
    parser = argparse.ArgumentParser(
        description="Context-aware policy selector",
    )
    parser.add_argument(
        "--select",
        type=str,
        metavar="CONTEXT_JSON",
        help="Select policy based on context (JSON string).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available policies.",
    )
    parser.add_argument(
        "--apply",
        nargs=2,
        metavar=("POLICY_NAME", "RISK_SCORE"),
        help="Apply a policy to a risk score.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON.",
    )
    args = parser.parse_args()

    if args.list:
        if args.json:
            output = {
                name: asdict(policy)
                for name, policy in POLICIES.items()
            }
            print(json.dumps(output, indent=2))
        else:
            print(_format_policy_table())
        return

    if args.select is not None:
        try:
            context = json.loads(args.select) if args.select else {}
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        policy = select_policy(context)
        if args.json:
            print(json.dumps(asdict(policy), indent=2))
        else:
            print(f"Selected: {policy.name} -- {policy.description}")
        return

    if args.apply:
        policy_name, score_str = args.apply
        try:
            policy = get_policy(policy_name)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        try:
            risk_score = int(score_str)
        except ValueError:
            print(
                f"Invalid risk score: {score_str!r} (must be integer)",
                file=sys.stderr,
            )
            sys.exit(1)

        decision = apply_policy(policy, risk_score)
        if args.json:
            output = {
                "policy": policy.name,
                "risk_score": risk_score,
                "decision": decision,
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"Policy: {policy.name} | Risk: {risk_score} | Decision: {decision}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
