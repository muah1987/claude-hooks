#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
context_analyzer.py - Session state analysis, temporal profiling, cumulative risk tracking.

GOTCHA Layer: Context (domain knowledge / session awareness)
ATLAS Phase: ASSESS - Contextual risk evaluation and session profiling

Tracks session state across hook invocations, profiles temporal patterns,
and maintains cumulative risk using an exponentially weighted moving average.
Detects anomalies such as rapid high-risk operations, production branch
destructive actions, and unusual-hours activity.

Environment Variables:
  (none specific - reads session state from disk)
"""

from __future__ import annotations
__version__ = "2026.04.20.3"

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_FILE: Path = Path(".claude/data/session_profile.json")
PRODUCTION_BRANCHES: set[str] = {"main", "master", "release", "production", "prod"}

# EWMA smoothing factor
_EWMA_ALPHA: float = 0.3

# Anomaly detection: time window in seconds for rapid-fire check
_RAPID_WINDOW_SECONDS: int = 300  # 5 minutes
_RAPID_HIGH_RISK_THRESHOLD: int = 60
_RAPID_HIGH_RISK_COUNT: int = 3

# Risky tools for production branch anomaly
_DESTRUCTIVE_TOOLS: set[str] = {"Bash", "Write", "Edit"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    """Snapshot of the current session state and contextual analysis."""

    session_start_time: str  # ISO format
    operations_count: int
    risk_events: list[dict]  # recent risk events
    cumulative_risk: float
    current_branch: str
    is_production_branch: bool
    time_of_day: str  # "morning", "afternoon", "evening", "night"
    task_phase: str  # "exploratory", "development", "testing", "deployment"
    anomaly_flags: list[str]


# ---------------------------------------------------------------------------
# Session profile I/O
# ---------------------------------------------------------------------------

def _default_session() -> dict:
    """Return a default session profile."""
    return {
        "session_start_time": datetime.now(timezone.utc).isoformat(),
        "operations_count": 0,
        "risk_events": [],
        "cumulative_risk": 0.0,
    }


def _load_session() -> dict:
    """Load the session profile from disk, or create a default."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return _default_session()
    return _default_session()


def _save_session(profile: dict) -> None:
    """Persist the session profile to disk."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Git branch detection
# ---------------------------------------------------------------------------

def _detect_git_branch() -> str:
    """Detect the current git branch. Returns 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------

def _classify_time_of_day() -> str:
    """Classify the current local hour into a time-of-day bucket."""
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _guess_task_phase(event_data: dict | None) -> str:
    """Guess the task phase from event data heuristics."""
    if not event_data:
        return "development"

    # Check tool_input paths and command content for clues
    tool_input = event_data.get("tool_input", {})
    tool_name = event_data.get("tool_name", "")

    searchable_parts: list[str] = []
    if isinstance(tool_input, dict):
        for value in tool_input.values():
            if isinstance(value, str):
                searchable_parts.append(value.lower())
    searchable_parts.append(tool_name.lower())

    combined = " ".join(searchable_parts)

    if any(kw in combined for kw in ("test", "pytest", "jest", "spec", "unittest")):
        return "testing"
    if any(kw in combined for kw in ("deploy", "release", "publish", "production")):
        return "deployment"
    if any(kw in combined for kw in ("explore", "search", "grep", "find", "read", "glob")):
        return "exploratory"

    return "development"


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _detect_anomalies(
    risk_events: list[dict],
    is_production_branch: bool,
    time_of_day: str,
    event_data: dict | None,
) -> list[str]:
    """Detect anomalous patterns in the current session."""
    flags: list[str] = []
    now = datetime.now(timezone.utc)

    # Rapid high-risk: 3+ events with risk > 60 in the last 5 minutes
    recent_high = 0
    for evt in risk_events:
        try:
            evt_time = datetime.fromisoformat(evt.get("timestamp", ""))
            if evt_time.tzinfo is None:
                evt_time = evt_time.replace(tzinfo=timezone.utc)
            age_seconds = (now - evt_time).total_seconds()
            if age_seconds <= _RAPID_WINDOW_SECONDS and evt.get("risk_score", 0) > _RAPID_HIGH_RISK_THRESHOLD:
                recent_high += 1
        except (ValueError, TypeError):
            continue

    if recent_high >= _RAPID_HIGH_RISK_COUNT:
        flags.append("rapid_high_risk")

    # Production + destructive tool
    if is_production_branch and event_data:
        tool_name = event_data.get("tool_name", "")
        if tool_name in _DESTRUCTIVE_TOOLS:
            flags.append("production_destructive")

    # Unusual hours
    if time_of_day == "night":
        flags.append("unusual_hours")

    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_context(event_data: dict | None = None) -> SessionContext:
    """
    Analyze the current session context.

    Args:
        event_data: Optional dict with tool_name, tool_input, etc.

    Returns:
        SessionContext with full contextual analysis.
    """
    profile = _load_session()
    branch = _detect_git_branch()
    is_prod = branch in PRODUCTION_BRANCHES
    tod = _classify_time_of_day()
    phase = _guess_task_phase(event_data)
    risk_events = profile.get("risk_events", [])

    anomalies = _detect_anomalies(risk_events, is_prod, tod, event_data)

    return SessionContext(
        session_start_time=profile.get(
            "session_start_time",
            datetime.now(timezone.utc).isoformat(),
        ),
        operations_count=profile.get("operations_count", 0),
        risk_events=risk_events[-20:],  # keep last 20 for readability
        cumulative_risk=profile.get("cumulative_risk", 0.0),
        current_branch=branch,
        is_production_branch=is_prod,
        time_of_day=tod,
        task_phase=phase,
        anomaly_flags=anomalies,
    )


def update_session(risk_score: int, decision: str) -> None:
    """
    Record a new risk event in the session profile.

    Args:
        risk_score: Numeric risk score for this event.
        decision: The consensus decision ("allow", "ask", "deny").
    """
    profile = _load_session()

    # Append event
    events = profile.get("risk_events", [])
    events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "risk_score": risk_score,
        "decision": decision,
    })
    # Keep a reasonable window (last 100 events)
    profile["risk_events"] = events[-100:]

    # EWMA cumulative risk
    prev = profile.get("cumulative_risk", 0.0)
    profile["cumulative_risk"] = _EWMA_ALPHA * risk_score + (1 - _EWMA_ALPHA) * prev

    # Increment ops count
    profile["operations_count"] = profile.get("operations_count", 0) + 1

    _save_session(profile)


def get_risk_modifier(context: SessionContext) -> int:
    """
    Compute an additive risk modifier based on session context.

    Returns:
        Integer modifier to add to the base risk score.
    """
    modifier = 0

    if context.time_of_day == "night":
        modifier += 15

    if context.is_production_branch:
        modifier += 20

    if context.cumulative_risk > 60:
        modifier += 10

    if len(context.anomaly_flags) >= 2:
        modifier += 15

    if context.task_phase == "exploratory":
        modifier -= 10

    if context.task_phase == "testing":
        modifier -= 15

    return modifier


def reset_session() -> None:
    """Reset the session profile to a fresh default state."""
    _save_session(_default_session())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI interface for the context analyzer."""
    parser = argparse.ArgumentParser(
        description="Session state analysis and contextual risk profiling."
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze the current session context.",
    )
    parser.add_argument(
        "--update",
        type=str,
        metavar="JSON",
        help="Update session with JSON containing risk_score and decision.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the session profile to defaults.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output result as JSON.",
    )

    args = parser.parse_args()

    if args.reset:
        reset_session()
        print("Session profile reset.")
        return

    if args.update:
        try:
            data = json.loads(args.update)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        risk_score = data.get("risk_score", 0)
        decision = data.get("decision", "allow")
        update_session(risk_score, decision)
        print(f"Session updated: risk_score={risk_score}, decision={decision}")
        return

    if args.analyze:
        ctx = analyze_context()
        if args.output_json:
            print(json.dumps(asdict(ctx), indent=2))
        else:
            print(f"Session start:      {ctx.session_start_time}")
            print(f"Operations count:   {ctx.operations_count}")
            print(f"Cumulative risk:    {ctx.cumulative_risk:.1f}")
            print(f"Current branch:     {ctx.current_branch}")
            print(f"Production branch:  {ctx.is_production_branch}")
            print(f"Time of day:        {ctx.time_of_day}")
            print(f"Task phase:         {ctx.task_phase}")
            print(f"Anomaly flags:      {ctx.anomaly_flags}")
            print(f"Risk modifier:      {get_risk_modifier(ctx):+d}")
            print(f"Recent events:      {len(ctx.risk_events)}")
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
