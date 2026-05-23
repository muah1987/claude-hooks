#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Trigger Engine -- Workflow Automation for Hook Events

Evaluates trigger rules against hook events to automate task progression.
Called by hooks (SubagentStop, TaskCompleted, Stop, SessionStart) to determine
next actions without human intervention.

GOTCHA Layer: Orchestration
  - Orchestration: Coordinates automatic workflow progression between hooks and subagents
  - Acts as the intelligent dispatcher between hook events and follow-up actions

ATLAS Phase: Trace (delegation planning)
  - Plans the next action based on completed work and available capabilities
  - Routes tasks to optimal models based on assessment data
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = SCRIPT_DIR / "trigger_rules.json"
CACHE_FILE = Path(".claude/data/assessment_cache.json")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "trigger.json"


# -------------------------------------------------------------------
# Data Structures
# -------------------------------------------------------------------


@dataclass
class TriggerRule:
    name: str  # Unique rule name
    when: str  # Hook event to match (e.g., "TaskCompleted")
    condition: dict  # Condition dict with field/operator/value keys
    action: str  # "deploy_agent", "suggest_next", "log", "notify"
    model_preference: str = "best_available"
    enabled: bool = True  # Can be toggled
    priority: int = 50  # Lower = first (0-100)
    description: str = ""  # Human-readable description


@dataclass
class TriggerResult:
    rule_name: str
    action: str
    suggestion: str  # Human-readable suggestion text
    model: str | None = None  # Recommended model if applicable
    metadata: dict = field(default_factory=dict)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def get_nested_value(data: dict, field_path: str):
    """Get value from nested dict using dot notation: 'cli.ollama.installed'"""
    parts = field_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


# -------------------------------------------------------------------
# Core Functions
# -------------------------------------------------------------------


def load_rules(rules_path: Path | None = None) -> list[TriggerRule]:
    """Load rules from trigger_rules.json.

    Merges with env var overrides: TRIGGER_RULE_{NAME}_ENABLED=false
    disables a rule (name uppercased, hyphens become underscores).
    """
    path = rules_path or DEFAULT_RULES_PATH
    if not path.exists():
        return []

    with open(path) as f:
        raw_rules = json.load(f)

    rules: list[TriggerRule] = []
    for entry in raw_rules:
        rule = TriggerRule(
            name=entry["name"],
            when=entry["when"],
            condition=entry.get("condition", {}),
            action=entry["action"],
            model_preference=entry.get("model_preference", "best_available"),
            enabled=entry.get("enabled", True),
            priority=entry.get("priority", 50),
            description=entry.get("description", ""),
        )

        # Check env var override: TRIGGER_RULE_AUTO_VALIDATE_ON_BUILD_ENABLED
        env_key = "TRIGGER_RULE_{}_ENABLED".format(
            rule.name.upper().replace("-", "_")
        )
        env_val = os.environ.get(env_key)
        if env_val is not None:
            rule.enabled = env_val.lower() not in ("false", "0", "no")

        rules.append(rule)

    return rules


def evaluate_condition(
    condition: dict,
    event_data: dict,
    assessment: dict | None = None,
) -> bool:
    """SAFE condition evaluation using operator-based matching.

    Condition format:
        {"field": "task_result", "operator": "equals", "value": "success"}

    Compound conditions (recursive, depth-limited to 5 subconditions):
        {"and": [condition1, condition2, ...]}
        {"or": [condition1, condition2, ...]}
        {"not": condition}

    Risk-based operators:
        {"operator": "risk_above", "value": 50}
        {"operator": "risk_below", "value": 50}
        {"operator": "policy_is", "value": "strict"}

    Supported operators: equals, not_equals, contains, not_contains,
    exists, not_exists, in, always, risk_above, risk_below, policy_is.

    Field lookup: event_data first, then assessment if not found.
    NEVER uses eval() or exec().
    """
    # Compound conditions (recursive, depth-limited)
    if "and" in condition:
        subconditions = condition["and"]
        if not isinstance(subconditions, list):
            return False
        return all(
            evaluate_condition(c, event_data, assessment)
            for c in subconditions[:5]
        )

    if "or" in condition:
        subconditions = condition["or"]
        if not isinstance(subconditions, list):
            return False
        return any(
            evaluate_condition(c, event_data, assessment)
            for c in subconditions[:5]
        )

    if "not" in condition:
        subcondition = condition["not"]
        if not isinstance(subcondition, dict):
            return False
        return not evaluate_condition(subcondition, event_data, assessment)

    # Risk-based operators
    operator = condition.get("operator", "always")

    if operator == "risk_above":
        threshold = condition.get("value", 50)
        session_risk = get_nested_value(event_data, "cumulative_risk") or 0
        return session_risk > threshold

    if operator == "risk_below":
        threshold = condition.get("value", 50)
        session_risk = get_nested_value(event_data, "cumulative_risk") or 0
        return session_risk < threshold

    if operator == "policy_is":
        expected_policy = condition.get("value", "").lower()
        current_policy = get_nested_value(event_data, "current_policy") or ""
        return current_policy.lower() == expected_policy

    # Existing operator logic
    operator = condition.get("operator", "always")

    if operator == "always":
        return True

    field_path = condition.get("field", "")
    expected = condition.get("value")

    # Look up field value: event_data first, then assessment
    actual = get_nested_value(event_data, field_path)
    if actual is None and assessment is not None:
        actual = get_nested_value(assessment, field_path)

    if operator == "equals":
        return actual == expected
    elif operator == "not_equals":
        return actual != expected
    elif operator == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, (list, tuple)):
            return expected in actual
        return False
    elif operator == "not_contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected not in actual
        if isinstance(actual, (list, tuple)):
            return expected not in actual
        return True
    elif operator == "exists":
        return actual is not None
    elif operator == "not_exists":
        return actual is None
    elif operator == "in":
        if isinstance(expected, (list, tuple)):
            return actual in expected
        return False

    # Unknown operator -- fail closed
    return False


def select_model(
    preference: str,
    assessment: dict | None = None,
) -> str | None:
    """Select a model based on preference and assessment data.

    Preferences:
      - "ollama": Ollama model if available, else "haiku"
      - "best_available": Best model from available providers
      - "cheapest": Cheapest option (Ollama > haiku)
      - "fastest": Fastest option (Ollama > haiku)
    """
    if assessment is None:
        return None

    ollama_installed = get_nested_value(assessment, "ollama.installed")
    ollama_models = get_nested_value(assessment, "ollama.models") or []
    first_ollama = ollama_models[0] if ollama_models else None

    active_cli = get_nested_value(assessment, "active_cli")

    if preference == "ollama":
        if ollama_installed and first_ollama:
            return os.environ.get("OLLAMA_MODEL", first_ollama)
        return "haiku"

    elif preference == "best_available":
        if active_cli == "claude":
            return "opus"
        if active_cli == "codex":
            return "gpt-4o"
        if ollama_installed and first_ollama:
            return first_ollama
        return None

    elif preference in ("cheapest", "fastest"):
        if ollama_installed and first_ollama:
            return first_ollama
        return "haiku"

    return None


def execute_action(
    rule: TriggerRule,
    event_data: dict,
    assessment: dict | None = None,
) -> TriggerResult:
    """Dispatch action based on rule.action type.

    Actions:
      - deploy_agent: Suggest deploying next agent with recommended model
      - suggest_next: Suggest what to do next
      - log: Append event to logs/trigger.json
      - notify: Suggest triggering TTS notification
    """
    model = select_model(rule.model_preference, assessment)

    if rule.action == "deploy_agent":
        task_name = event_data.get("task_name", "next task")
        return TriggerResult(
            rule_name=rule.name,
            action="deploy_agent",
            suggestion="Deploy agent for '{}' using model {}".format(
                task_name, model or "default"
            ),
            model=model,
            metadata={
                "task_name": task_name,
                "rule_description": rule.description,
            },
        )

    elif rule.action == "suggest_next":
        return TriggerResult(
            rule_name=rule.name,
            action="suggest_next",
            suggestion=_build_suggestion(rule, event_data),
            model=model,
            metadata={"rule_description": rule.description},
        )

    elif rule.action == "log":
        return TriggerResult(
            rule_name=rule.name,
            action="log",
            suggestion="Logged event for rule '{}'".format(rule.name),
            model=None,
            metadata={
                "logged": True,
                "rule_description": rule.description,
                "event_keys": list(event_data.keys()),
            },
        )

    elif rule.action == "notify":
        task_name = event_data.get("task_name", "task")
        return TriggerResult(
            rule_name=rule.name,
            action="notify",
            suggestion="Notify: '{}' completed successfully".format(task_name),
            model=model,
            metadata={
                "notification_type": "tts",
                "rule_description": rule.description,
            },
        )

    # Unknown action
    return TriggerResult(
        rule_name=rule.name,
        action=rule.action,
        suggestion="Unknown action '{}' for rule '{}'".format(
            rule.action, rule.name
        ),
        model=None,
        metadata={"error": "unknown_action"},
    )


def _build_suggestion(rule: TriggerRule, event_data: dict) -> str:
    """Build a human-readable suggestion based on the rule and event."""
    when = rule.when

    if when == "TaskCompleted":
        task = event_data.get("task_name", "the task")
        return (
            "Task '{}' completed. "
            "Check the task list for the next unblocked task "
            "or deploy a validator."
        ).format(task)
    elif when == "SubagentStop":
        return (
            "Subagent finished. Check the task list for newly unblocked "
            "tasks and deploy the next builder if available."
        )
    elif when == "Stop":
        return (
            "Session ending. Consider committing staged changes "
            "and updating the task list before closing."
        )
    elif when == "SessionStart":
        return (
            "New session started. Run assessment refresh and "
            "check for pending tasks from the previous session."
        )

    return "Rule '{}' triggered: {}".format(rule.name, rule.description)


def log_trigger_event(
    event_name: str,
    results: list[TriggerResult],
    event_data: dict,
    dry_run: bool = False,
) -> None:
    """Append trigger event to logs/trigger.json."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_name,
        "rules_matched": len(results),
        "results": [
            {
                "rule": r.rule_name,
                "action": r.action,
                "suggestion": r.suggestion,
            }
            for r in results
        ],
        "dry_run": dry_run,
    }

    # Read existing log or start fresh
    existing: list[dict] = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE) as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = [existing]
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)

    with open(LOG_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def process_event(
    event_name: str,
    event_data: dict,
    dry_run: bool = False,
) -> list[TriggerResult]:
    """Main entry point: evaluate all matching rules for an event.

    - Checks TRIGGER_ENABLED env var (default "true")
    - Loads assessment from cache (gracefully handles missing)
    - Loads rules, filters to enabled ones matching event_name
    - Sorts by priority (lower first)
    - Evaluates conditions and executes actions
    - Logs all results to logs/trigger.json
    """
    # Check global toggle
    trigger_enabled = os.environ.get("TRIGGER_ENABLED", "true").lower()
    if trigger_enabled in ("false", "0", "no"):
        return []

    # Load assessment cache (optional)
    assessment: dict | None = None
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                assessment = json.load(f)
        except (json.JSONDecodeError, OSError):
            assessment = None

    # Load and filter rules
    rules = load_rules()
    matching = [r for r in rules if r.enabled and r.when == event_name]
    matching.sort(key=lambda r: r.priority)

    results: list[TriggerResult] = []
    for rule in matching:
        if evaluate_condition(rule.condition, event_data, assessment):
            if dry_run:
                result = TriggerResult(
                    rule_name=rule.name,
                    action=rule.action,
                    suggestion="[DRY RUN] Would execute '{}' for rule '{}'".format(
                        rule.action, rule.name
                    ),
                    model=select_model(rule.model_preference, assessment),
                    metadata={
                        "dry_run": True,
                        "rule_description": rule.description,
                    },
                )
            else:
                result = execute_action(rule, event_data, assessment)
            results.append(result)

    # Log results (even if empty, for audit trail)
    log_trigger_event(event_name, results, event_data, dry_run=dry_run)

    return results


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def print_rules_table(rules: list[TriggerRule]) -> None:
    """Print rules as a formatted table to stdout."""
    if not rules:
        print("No trigger rules found.")
        return

    # Column headers
    headers = ["#", "Name", "When", "Action", "Pri", "On", "Description"]
    rows = []
    for i, r in enumerate(rules, 1):
        desc = r.description
        if len(desc) > 50:
            desc = desc[:50] + "..."
        rows.append([
            str(i),
            r.name,
            r.when,
            r.action,
            str(r.priority),
            "yes" if r.enabled else "no",
            desc,
        ])

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for j, cell in enumerate(row):
            widths[j] = max(widths[j], len(cell))

    # Print table
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    separator = "  ".join("-" * w for w in widths)
    print(header_line)
    print(separator)
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def _run_rule_test(
    target: TriggerRule,
    event_data: dict,
    assessment: dict | None,
    dry_run: bool,
) -> None:
    """Execute a single rule test and print results."""
    condition_met = evaluate_condition(
        target.condition, event_data, assessment
    )
    print("Rule: {}".format(target.name))
    print("Event: {}".format(target.when))
    print("Condition met: {}".format(condition_met))

    if condition_met:
        if dry_run:
            result = TriggerResult(
                rule_name=target.name,
                action=target.action,
                suggestion="[DRY RUN] Would execute '{}'".format(
                    target.action
                ),
                model=select_model(target.model_preference, assessment),
                metadata={"dry_run": True},
            )
        else:
            result = execute_action(target, event_data, assessment)
        print("Action: {}".format(result.action))
        print("Suggestion: {}".format(result.suggestion))
        if result.model:
            print("Model: {}".format(result.model))
        print(json.dumps(asdict(result), indent=2))
    else:
        print("Condition not met -- no action taken.")


def main():
    parser = argparse.ArgumentParser(description="Trigger automation engine")
    parser.add_argument(
        "--event",
        type=str,
        help="Hook event name (reads event data from stdin JSON)",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="List all trigger rules",
    )
    parser.add_argument(
        "--test-rule",
        type=str,
        help="Test a specific rule by name (reads event data from stdin)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate without executing actions",
    )
    args = parser.parse_args()

    if args.list_rules:
        rules = load_rules()
        print_rules_table(rules)
        return

    if args.event:
        # Read event data from stdin
        event_data = {}
        if not sys.stdin.isatty():
            try:
                raw = sys.stdin.read()
                if raw.strip():
                    event_data = json.loads(raw)
            except json.JSONDecodeError:
                print(
                    "Warning: Could not parse stdin as JSON, "
                    "using empty event data",
                    file=sys.stderr,
                )

        results = process_event(
            args.event, event_data, dry_run=args.dry_run
        )
        output = [asdict(r) for r in results]
        print(json.dumps(output, indent=2))
        return

    if args.test_rule:
        # Read event data from stdin
        event_data = {}
        if not sys.stdin.isatty():
            try:
                raw = sys.stdin.read()
                if raw.strip():
                    event_data = json.loads(raw)
            except json.JSONDecodeError:
                print(
                    "Warning: Could not parse stdin as JSON, "
                    "using empty event data",
                    file=sys.stderr,
                )

        # Load assessment
        assessment: dict | None = None
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE) as f:
                    assessment = json.load(f)
            except (json.JSONDecodeError, OSError):
                assessment = None

        # Find and test the specific rule
        rules = load_rules()
        target: TriggerRule | None = None
        for r in rules:
            if r.name == args.test_rule:
                target = r
                break

        if target is None:
            print(
                "Rule '{}' not found.".format(args.test_rule),
                file=sys.stderr,
            )
            sys.exit(1)
            return  # unreachable, helps type checker

        _run_rule_test(target, event_data, assessment, args.dry_run)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
