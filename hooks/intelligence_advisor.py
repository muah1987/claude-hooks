#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""
Intelligence Advisor Hook — UserPromptSubmit

Fires when the user submits a prompt. Detects genuinely complex or
production-risk tasks and injects a one-line skill recommendation.

Design:
- Tight keyword list to minimize false positives
- 5-minute cooldown so it never fires twice in quick succession
- Suppressed when user is already using a skill, or is in bypassPermissions mode
- Advisory is a single terse line, not a wall of text

GOTCHA Layer: Orchestration  |  ATLAS Phase: Link
"""
__version__ = "2026.04.20.6"

import json
import re
import sys
import time
from pathlib import Path


# ── Cooldown ──────────────────────────────────────────────────────────────────
COOLDOWN_SECS = 300  # 5 minutes between advisories
_LAST_FIRE_FILE = Path.home() / ".claude" / "data" / "advisor_last_fire.txt"


def _within_cooldown() -> bool:
    """True if an advisory was fired less than COOLDOWN_SECS ago."""
    try:
        ts = float(_LAST_FIRE_FILE.read_text().strip())
        return (time.time() - ts) < COOLDOWN_SECS
    except Exception:
        return False


def _mark_fired() -> None:
    """Record the current time as the last advisory fire."""
    try:
        _LAST_FIRE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_FIRE_FILE.write_text(str(time.time()))
    except Exception:
        pass


# ── Keyword lists ─────────────────────────────────────────────────────────────
# Tight: only phrases that unambiguously signal a multi-step / high-risk task.
COMPLEXITY_KEYWORDS = [
    # Structural overhaul
    'rewrite', 'rebuild', 'from scratch', 'from the ground up', 'greenfield', 'overhaul',
    'redesign', 'refactor the entire', 'refactor all', 'complete rewrite', 'full rewrite',
    # Production / risk
    'deploy to production', 'ship to prod', 'go live', 'rollout',
    'database migration', 'schema migration', 'data migration',
    'infrastructure', 'provision',
    # Security & auth (common complex system patterns)
    'security audit', 'pen test', 'penetration test',
    'vulnerability scan', 'threat model',
    'authentication system', 'auth system', 'oauth', 'oauth2',
    'jwt', 'json web token', 'session management',
    'access control', 'rbac', 'permission system',
    # API / backend systems
    'rest api', 'graphql api', 'api gateway', 'api design',
    'middleware', 'rate limiting', 'webhook',
    # Scale / reliability
    'high availability', 'load test', 'stress test',
    'redis', 'message queue', 'event-driven', 'pub/sub',
    # Multi-service
    'microservice', 'multi-service', 'distributed system', 'monorepo refactor',
    # Scope anchors (must be paired with action verb — handled by multi-verb path)
    'end-to-end', 'full stack',
]

# Any prompt starting with / or @ is already an intentional command — stay silent.
BYPASS_PREFIXES = ('/', '@')

# Explicit /command invocations anywhere in the prompt also signal intent.
# Match only /word patterns, not the words themselves in prose.
_BYPASS_CMD_RE = re.compile(
    r'/(?:intelligence|orchestrate|cook|plan|prime|build|deploy|debug|'
    r'test|audit|review|git_status|security.review|commit|review|'
    r'lint_all|test_runner|pr_prep|todo_scanner|cost_tracker|'
    r'context_stats|code_search|commit_msg)\b',
    re.IGNORECASE,
)

MULTI_VERB_PATTERN = re.compile(
    r'\b(build|create|fix|deploy|test|write|implement|set up|configure|'
    r'optimize|migrate|refactor|connect|integrate|redesign|overhaul|'
    r'rewrite|rebuild|audit|review|monitor|provision|orchestrate|scaffold)\b',
    re.IGNORECASE,
)

# Skill recommendation: first matching entry wins.
SKILL_TRIGGERS: list[tuple[tuple[str, ...], str]] = [
    # Parallelism
    (('parallel', 'simultaneously', 'concurrently', 'in parallel',
      'at the same time', 'multiple tasks'), '/orchestrate'),
    # Security
    (('security', 'vulnerability', 'pen test', 'penetration',
      'audit', 'threat model', 'sensitive data'), '/audit'),
    # Debugging
    (('bug', 'broken', 'failing', 'traceback', 'exception',
      'crash', 'stack trace', 'regression'), '/debug'),
    # Linting — must come before /test so "ruff"/"eslint" route here
    (('lint', 'linter', 'eslint', 'ruff', 'shellcheck', 'yamllint',
      'linting', 'run linters', 'run lint'), '/lint_all'),
    # Test execution — must come before /test (which handles *writing* tests)
    (('run tests', 'run the tests', 'run pytest', 'run jest',
      'run vitest', 'run cargo test', 'run go test', 'execute tests',
      'test runner', 'rerun tests', 'run the test suite',
      'run test suite'), '/test_runner'),
    # Testing (writing tests)
    (('unit test', 'integration test', 'e2e', 'pytest', 'jest',
      'vitest', 'test coverage', 'write tests'), '/test'),
    # PR prep — before /review so "before merge" routes to prep checklist
    (('pr', 'pull request', 'before merge', 'ready to merge',
      'pre-pr', 'pr checklist', 'open a pr', 'raise a pr'), '/pr_prep'),
    # Deployment
    (('deploy', 'release', 'rollout', 'go live', 'prod push'), '/deploy'),
    # Review
    (('pr review', 'code review', 'pull request review'), '/review'),
    # TODO / technical debt scan
    (('todo', 'fixme', 'technical debt', 'tech debt', 'hack marker',
      'xxx marker'), '/todo_scanner'),
    # Cost / spend
    (('cost', 'spending', 'how much', 'usd spend', 'spend tracking',
      'token cost', 'api cost'), '/cost_tracker'),
    # Context window
    (('context window', 'context usage', 'compaction', 'cache hit',
      'cache hits', 'context stats'), '/context_stats'),
    # Code search / navigation
    (('where is', 'find definition', 'find usage', 'find usages',
      'find the definition', 'where defined', 'locate definition',
      'find references', 'dead code'), '/code_search'),
    # Commit message generation
    (('commit message', 'conventional commit', 'conventional commits',
      'generate commit', 'write a commit'), '/commit_msg'),
    # Build — general fallback
    (('implement', 'build', 'scaffold', 'create the'), '/build'),
]


# ── Decision logic ────────────────────────────────────────────────────────────

def _already_using_skill(prompt: str) -> bool:
    """True when the prompt is a slash command or explicitly invokes a known skill."""
    stripped = prompt.strip()
    if stripped.startswith(BYPASS_PREFIXES):
        return True
    # Match explicit /command patterns anywhere in the text (user is being deliberate)
    return bool(_BYPASS_CMD_RE.search(stripped))


def is_complex_task(prompt: str, permission_mode: str = '') -> tuple[bool, str]:
    """Return (is_complex, reason) for genuinely complex / high-risk prompts."""
    if permission_mode in ('bypassPermissions', 'dontAsk'):
        return False, ''

    if _already_using_skill(prompt):
        return False, ''

    # Very short prompts are never complex enough to warrant an advisory
    word_count = len(prompt.split())
    if word_count < 10:
        return False, ''

    lower = prompt.lower()

    # Unambiguous high-risk keywords
    for kw in COMPLEXITY_KEYWORDS:
        if kw in lower:
            return True, f'keyword: "{kw}"'

    # 3+ distinct action verbs in long prompts, 4+ in shorter ones
    verb_threshold = 3 if word_count >= 15 else 4
    verbs = MULTI_VERB_PATTERN.findall(prompt)
    unique_verbs = set(v.lower() for v in verbs)
    if len(unique_verbs) >= verb_threshold:
        return True, f'{len(unique_verbs)} action verbs: {", ".join(sorted(unique_verbs)[:4])}'

    return False, ''


def recommend_skill(prompt: str) -> str | None:
    """Return the best-fit skill command, or None."""
    lower = prompt.lower()
    for keywords, skill in SKILL_TRIGGERS:
        if any(kw in lower for kw in keywords):
            return skill
    return None


# ── Output ────────────────────────────────────────────────────────────────────

def build_advisory(recommended: str | None, reason: str = '') -> str:
    """Terse one-block advisory — not a wall of text."""
    reason_suffix = f" ({reason})" if reason else ""
    skill_hint = (
        f" Suggested skill: `{recommended}` (or run `/intelligence` first for a full plan)."
        if recommended
        else " Run `/intelligence` first to match this task to the best tools and produce a plan."
    )
    return (
        f"⚡ COMPLEXITY SIGNAL: multi-step or production-risk task detected{reason_suffix}."
        + skill_hint
    )


def _write_complexity_signal(is_complex: bool, task_type: str) -> None:
    """Share complexity signal with model_router via data file."""
    try:
        sig_path = Path.home() / ".claude" / "data" / "last_complexity_signal.json"
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        sig_path.write_text(json.dumps({
            "is_complex": is_complex,
            "task_type": task_type,
            "written_at": time.time(),
        }))
    except Exception:
        pass


def _emit(context: str = '') -> None:
    try:
        print(json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'UserPromptSubmit',
                'additionalContext': context,
            }
        }), flush=True)
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        raw = sys.stdin.read()
        input_data = json.loads(raw) if raw.strip() else {}
    except Exception:
        input_data = {}

    if not isinstance(input_data, dict):
        input_data = {}

    prompt = str(input_data.get('prompt') or '')
    permission_mode = str(input_data.get('permission_mode') or '')

    complex_flag, reason = is_complex_task(prompt, permission_mode)

    # Infer task_type for model_router signal — mirrors model_router's CODING_KEYWORDS
    task_type = "general"
    lower = prompt.lower()
    if any(k in lower for k in (
        "code", "function", "class", "implement", "fix", "debug",
        "typescript", "python", "rust", "refactor", "compile", "test",
        "write a", "write the", "create a", "generate a",
        "auth", "jwt", "redis", "api", "server", "deploy", "migration",
        "database", "schema", "endpoint", "service", "module", "component",
    )):
        task_type = "coding"
    elif any(k in lower for k in (
        "think", "reason", "analyze", "analyse", "explain", "compare",
        "plan", "strategy", "summarize", "review", "assess", "evaluate",
    )):
        task_type = "thinking"

    _write_complexity_signal(complex_flag, task_type)

    if complex_flag and not _within_cooldown():
        recommended = recommend_skill(prompt)
        _emit(build_advisory(recommended, reason))
        _mark_fired()
    else:
        _emit()

    sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(0)
