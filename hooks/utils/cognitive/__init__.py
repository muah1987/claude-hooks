"""
__version__ = "2026.04.20.3"
Cognitive Control Engine (CCE) Package

Unified entry point for the cognitive decision-making system.
Orchestrates: Perceive -> Debate -> Decide -> Act -> Reflect

GOTCHA Layer: Orchestration
  - Orchestration: Central coordinator for all cognitive modules

ATLAS Phase: Link + Stress-test
  - Links all cognitive signals into unified decisions
  - Stress-tests decisions through multi-faculty debate
"""

import os
from dataclasses import asdict, dataclass
from typing import Optional


# -------------------------------------------------------------------
# Configuration from env vars
# -------------------------------------------------------------------

_MIN_CONFIDENCE_ASK = float(os.environ.get("MIN_CONFIDENCE_ASK", "0.6"))
_CONFIDENCE_AUTO = float(os.environ.get("CONFIDENCE_AUTO", "0.85"))


# -------------------------------------------------------------------
# Dataclass
# -------------------------------------------------------------------


@dataclass
class CognitiveDecision:
    """Result of the full cognitive Perceive-Debate-Decide-Act-Reflect loop.

    Attributes:
        action: Final decision -- "allow", "ask", or "deny".
        risk_score: Adjusted risk score (0-100).
        risk_category: LOW, MEDIUM, HIGH, or CRITICAL.
        policy_name: Name of the policy that governed the decision.
        confidence: Confidence in the decision (0.0-1.0).
        confidence_recommendation: Human-readable confidence note.
        debate_consensus: Consensus from multi-perspective debate, if run.
        guardian_veto: Whether a guardian faculty issued a hard veto.
        pattern_match: Learned pattern data, if a match was found.
        context_modifiers: Net risk modifier from session context.
        reasoning: Human-readable explanation of the decision.
        debug_log: Detailed log of all intermediate values for debugging.
    """

    action: str = "ask"
    risk_score: int = 0
    risk_category: str = "LOW"
    policy_name: str = "default"
    confidence: float = 0.0
    confidence_recommendation: str = ""
    debate_consensus: Optional[str] = None
    guardian_veto: bool = False
    pattern_match: Optional[dict] = None
    context_modifiers: int = 0
    reasoning: str = ""
    debug_log: str = ""


# -------------------------------------------------------------------
# Core cognitive loop
# -------------------------------------------------------------------


def cognitive_decide(
    tool_name: str,
    tool_input: dict,
    event_data: Optional[dict] = None,
) -> CognitiveDecision:
    """Execute the full Perceive-Debate-Decide-Act-Reflect cognitive loop.

    Uses lazy imports to keep hook startup fast. Each cognitive module
    is loaded only when this function is first called.

    Args:
        tool_name: The tool being invoked (Bash, Write, Edit, etc.).
        tool_input: The tool's input parameters.
        event_data: Optional raw event data from the hook system.

    Returns:
        CognitiveDecision with the final action and full reasoning chain.
    """
    from .risk_scorer import score_command, categorize_score
    from .policy_selector import select_policy, apply_policy
    from .confidence_estimator import estimate_confidence
    from .perspective_debater import debate
    from .context_analyzer import analyze_context, get_risk_modifier
    from .pattern_learner import check_pattern

    if event_data is None:
        event_data = {}

    debug_parts: list[str] = []

    # ------------------------------------------------------------------
    # 1. PERCEIVE: Gather session context
    # ------------------------------------------------------------------
    ctx = analyze_context(event_data)
    ctx_dict = asdict(ctx) if hasattr(ctx, "__dataclass_fields__") else dict(ctx)
    debug_parts.append(f"[perceive] context={ctx_dict}")

    # ------------------------------------------------------------------
    # 2. SCORE: Multi-factor risk assessment
    # ------------------------------------------------------------------
    risk = score_command(tool_name, tool_input, ctx_dict)
    debug_parts.append(
        f"[score] raw_risk={risk.score} category={risk.category} "
        f"factors={risk.factors}"
    )

    # ------------------------------------------------------------------
    # 3. Apply context modifiers to risk
    # ------------------------------------------------------------------
    modifier = get_risk_modifier(ctx)
    adjusted_risk = min(100, max(0, risk.score + modifier))
    adjusted_category = categorize_score(adjusted_risk)
    debug_parts.append(
        f"[context] modifier={modifier} adjusted_risk={adjusted_risk} "
        f"adjusted_category={adjusted_category}"
    )

    # ------------------------------------------------------------------
    # 4. POLICY: Select governing policy
    # ------------------------------------------------------------------
    policy = select_policy(ctx_dict)
    if hasattr(policy, "__dataclass_fields__"):
        policy_dict = asdict(policy)
    else:
        policy_dict = dict(policy)
    debug_parts.append(
        f"[policy] selected={policy.name} details={policy_dict}"
    )

    # ------------------------------------------------------------------
    # 5. PATTERN: Check learned patterns
    # ------------------------------------------------------------------
    pattern = check_pattern(tool_name, tool_input)
    debug_parts.append(f"[pattern] match={pattern}")

    # ------------------------------------------------------------------
    # 6. QUICK PATH: Auto-approve known safe patterns
    # ------------------------------------------------------------------
    risk_ask_threshold = getattr(policy, "risk_ask_threshold", 40)
    if pattern and pattern.get("auto_approve") and adjusted_risk < risk_ask_threshold:
        reasoning = (
            f"Quick-path allow: pattern '{pattern.get('name', 'unnamed')}' "
            f"auto-approved with adjusted risk {adjusted_risk} "
            f"below policy threshold {risk_ask_threshold}."
        )
        debug_parts.append(f"[quick_path] {reasoning}")
        return CognitiveDecision(
            action="allow",
            risk_score=adjusted_risk,
            risk_category=adjusted_category,
            policy_name=policy.name,
            confidence=1.0,
            confidence_recommendation="High confidence: known safe pattern.",
            debate_consensus=None,
            guardian_veto=False,
            pattern_match=pattern,
            context_modifiers=modifier,
            reasoning=reasoning,
            debug_log="\n".join(debug_parts),
        )

    # ------------------------------------------------------------------
    # 7. CONFIDENCE: Estimate decision confidence
    # ------------------------------------------------------------------
    conf = estimate_confidence(
        adjusted_risk, adjusted_category, policy.name, pattern, ctx_dict
    )
    conf_score = conf.score if hasattr(conf, "score") else float(conf)
    conf_recommendation = (
        conf.recommendation if hasattr(conf, "recommendation") else str(conf)
    )
    debug_parts.append(
        f"[confidence] score={conf_score} recommendation={conf_recommendation}"
    )

    # ------------------------------------------------------------------
    # 8. POLICY DECISION: Apply policy rules
    # ------------------------------------------------------------------
    policy_action = apply_policy(policy, adjusted_risk)
    debug_parts.append(f"[policy_action] result={policy_action}")

    # ------------------------------------------------------------------
    # 9. DEBATE: Multi-perspective evaluation (conditional)
    # ------------------------------------------------------------------
    debate_result = None
    guardian_veto = False
    debate_consensus: Optional[str] = None
    require_debate_above = getattr(policy, "require_debate_above", 70)

    if conf_score < _MIN_CONFIDENCE_ASK or adjusted_risk > require_debate_above:
        debug_parts.append(
            f"[debate] triggered: confidence={conf_score} < {_MIN_CONFIDENCE_ASK} "
            f"or risk={adjusted_risk} > {require_debate_above}"
        )
        debate_result = debate(
            adjusted_risk, adjusted_category, ctx_dict, tool_name, tool_input
        )
        if hasattr(debate_result, "guardian_veto"):
            guardian_veto = debate_result.guardian_veto
        elif isinstance(debate_result, dict):
            guardian_veto = debate_result.get("guardian_veto", False)

        if hasattr(debate_result, "consensus"):
            debate_consensus = debate_result.consensus
        elif isinstance(debate_result, dict):
            debate_consensus = debate_result.get("consensus")

        debug_parts.append(
            f"[debate] consensus={debate_consensus} "
            f"guardian_veto={guardian_veto}"
        )
    else:
        debug_parts.append(
            "[debate] skipped: confidence sufficient, "
            "risk within bounds"
        )

    # ------------------------------------------------------------------
    # 10. DECIDE: Combine all signals into final action
    # ------------------------------------------------------------------
    final_action: str
    reasoning_parts: list[str] = []

    if guardian_veto:
        final_action = "deny"
        reasoning_parts.append("Guardian faculty issued a hard veto.")
    elif policy_action == "deny":
        final_action = "deny"
        reasoning_parts.append(
            f"Policy '{policy.name}' denied at risk level {adjusted_risk}."
        )
    elif debate_result is not None and debate_consensus == "deny":
        final_action = "deny"
        reasoning_parts.append("Multi-perspective debate reached 'deny' consensus.")
    elif conf_score >= _CONFIDENCE_AUTO and policy_action == "allow":
        final_action = "allow"
        reasoning_parts.append(
            f"High confidence ({conf_score:.2f}) and policy allows."
        )
    elif pattern and pattern.get("auto_approve") and policy_action != "deny":
        final_action = "allow"
        reasoning_parts.append(
            f"Learned pattern '{pattern.get('name', 'unnamed')}' auto-approved."
        )
    else:
        final_action = policy_action
        reasoning_parts.append(
            f"Defaulting to policy action '{policy_action}' "
            f"(confidence={conf_score:.2f}, risk={adjusted_risk})."
        )

    reasoning = " ".join(reasoning_parts)
    debug_parts.append(f"[decide] final_action={final_action} reasoning={reasoning}")

    return CognitiveDecision(
        action=final_action,
        risk_score=adjusted_risk,
        risk_category=adjusted_category,
        policy_name=policy.name,
        confidence=conf_score,
        confidence_recommendation=conf_recommendation,
        debate_consensus=debate_consensus,
        guardian_veto=guardian_veto,
        pattern_match=pattern,
        context_modifiers=modifier,
        reasoning=reasoning,
        debug_log="\n".join(debug_parts),
    )


# -------------------------------------------------------------------
# Quality assessment convenience function
# -------------------------------------------------------------------


def cognitive_assess(
    task_description: str,
    files_changed: list[str],
    acceptance_criteria: Optional[list[str]] = None,
):
    """Run multi-dimensional quality assessment on completed work.

    Lazy-imports the quality_assessor module and delegates to
    assess_task(). Returns a QualityScore dataclass.

    Args:
        task_description: Description of the task that was completed.
        files_changed: List of file paths that were created/modified.
        acceptance_criteria: Optional list of acceptance criteria.

    Returns:
        QualityScore with overall score, dimensions, verdict,
        and recommendations.
    """
    from .quality_assessor import assess_task

    return assess_task(task_description, files_changed, acceptance_criteria)
