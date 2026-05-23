#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
model_router.py — UserPromptSubmit hook that injects Ollama routing guidance
when Claude is rate-limited.

Flow:
1. Read the prompt from stdin (hook input JSON).
2. Consult ~/.claude/data/usage_status.json. If rate_limited=false, do nothing.
3. Otherwise, classify the prompt (coding/thinking/fast/general), estimate
   complexity, and pick the best Ollama cloud model.
4. Inject `additionalContext` telling Claude how to run the request through
   ollama_cloud.py.

Design rules:
- Never block the prompt; always exit 0.
- Always emit valid hookSpecificOutput JSON so downstream hooks keep working.
- All subprocess calls use timeout<=10s and are fully guarded.
"""

from __future__ import annotations
__version__ = "2026.04.20.7"

import json
import math
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import importlib
    _dotenv = importlib.import_module("dotenv")
    _dotenv.load_dotenv()
except Exception:
    pass


HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
STATUS_FILE = CLAUDE_DIR / "data" / "usage_status.json"
MODEL_SELECTOR = CLAUDE_DIR / "scripts" / "model_selector.py"
OLLAMA_SCRIPT = CLAUDE_DIR / "scripts" / "ollama_cloud.py"
USAGE_MONITOR = CLAUDE_DIR / "scripts" / "usage_monitor.py"


CODING_KEYWORDS = (
    "code", "function", "class", "bug", "implement", "fix", "test",
    "refactor", "compile", "typescript", "python", "rust", "debug",
    "write a", "write the", "create a", "generate a",
)
THINKING_KEYWORDS = (
    "think", "reason", "analyze", "analyse", "why", "explain", "how",
    "compare", "evaluate", "decide", "strategy", "plan",
    "summarize", "review", "assess",
)

# Proactive routing: suggest a model even when Claude is available.
# Only fires when score >= threshold AND Claude is NOT rate-limited.
PROACTIVE_THRESHOLDS: dict[str, int] = {
    "coding": 55,    # lowered from 75 — short complex prompts (<120 chars) top out at ~62
    "thinking": 60,  # lowered from 80
    "general": 72,   # lowered from 88
}

# Rough tokens-per-char for estimating context window requirement
_CHARS_PER_TOKEN = 4
# Flag large-context need when estimated prompt tokens exceed this
_LARGE_CONTEXT_THRESHOLD_K = 40  # tokens (k)


def _emit_empty() -> None:
    """Emit a valid but empty UserPromptSubmit hookSpecificOutput payload."""
    try:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": "",
                    }
                }
            )
        )
    except Exception:
        pass


def _emit_context(context: str) -> None:
    try:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": context,
                    }
                }
            )
        )
    except Exception:
        pass


def _read_status() -> dict[str, Any]:
    try:
        if not STATUS_FILE.exists():
            return {}
        with STATUS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _classify_task(prompt: str) -> tuple[str, int]:
    """
    Returns (task_type, keyword_hits).

    Priority: coding > thinking > fast (for tiny prompts) > general.
    """
    lowered = (prompt or "").lower()
    coding_hits = sum(1 for k in CODING_KEYWORDS if k in lowered)
    thinking_hits = sum(1 for k in THINKING_KEYWORDS if k in lowered)

    if coding_hits:
        return "coding", coding_hits
    if thinking_hits:
        return "thinking", thinking_hits
    if len(prompt.strip()) < 50:
        return "fast", 0
    return "general", 0


def _estimate_complexity(prompt: str, keyword_hits: int) -> int:
    """Heuristic complexity score in [0, 100].

    Uses log1p for keyword component to prevent short keyword-dense prompts
    from over-triggering proactive routing (e.g. "fix bug test code" = 4 hits
    but only ~30 chars → was scoring 48+48=96, now ~17+24=41).
    """
    length_component = min((len(prompt) / 300.0) * 50.0, 50.0)
    keyword_component = min(math.log1p(keyword_hits) * 15.0, 50.0)
    score = int(round(length_component + keyword_component))
    if score < 0:
        return 0
    if score > 100:
        return 100
    return score


def _estimate_token_k(prompt: str) -> int:
    """Rough estimate of prompt size in thousands of tokens."""
    chars = len(prompt or "")
    # Bonus for structural complexity: code fences, large newline count
    code_fences = prompt.count("```")
    newlines = prompt.count("\n")
    adjusted = chars + code_fences * 200 + max(0, newlines - 20) * 10
    return max(1, adjusted // (_CHARS_PER_TOKEN * 1000))


def _select_model(task_type: str, score: int, min_context_k: int = 0) -> str:
    """Ask model_selector.py for the best model; fall back sensibly on failure."""
    try:
        if MODEL_SELECTOR.exists():
            args = ["uv", "run", str(MODEL_SELECTOR), "select", str(score), task_type]
            if min_context_k > 0:
                args.append(str(min_context_k))
            result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            out = (result.stdout or "").strip()
            if result.returncode == 0 and out:
                return out.splitlines()[0].strip()
    except Exception:
        pass

    # Fallback — prefer large-context models when needed
    def _has_ctx(model: str) -> bool:
        from pathlib import Path as _P
        return min_context_k <= 0 or min_context_k <= {
            "kimi-k2:1t": 128, "qwen3-coder:480b": 128,
            "kimi-k2-thinking": 128, "mistral-large-3:675b": 128,
        }.get(model, 32)

    if task_type == "coding":
        for m, threshold in [("qwen3-coder:480b", 70), ("qwen3-coder-next", 40), ("devstral-small-2:24b", 0)]:
            if score >= threshold and _has_ctx(m):
                return m
    if task_type == "thinking":
        return "kimi-k2-thinking" if score >= 60 and _has_ctx("kimi-k2-thinking") else "deepseek-v3.2"
    if task_type == "fast":
        return "ministral-3:14b"
    if score >= 80 and _has_ctx("kimi-k2:1t"):
        return "kimi-k2:1t"
    if score >= 50 and _has_ctx("mistral-large-3:675b"):
        return "mistral-large-3:675b"
    return "qwen3-next:80b"


def _summarize_prompt(prompt: str, max_chars: int = 240) -> str:
    text = " ".join((prompt or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _build_context(model: str, task_type: str, score: int, prompt_summary: str) -> str:
    ollama = str(OLLAMA_SCRIPT)
    monitor = str(USAGE_MONITOR)
    # Use shlex.quote to safely escape the prompt for the shell command shown
    # to Claude. This prevents prompt-injection via embedded quotes/backticks.
    quoted_prompt = shlex.quote(prompt_summary[:200])
    return (
        "\u26a0\ufe0f CLAUDE USAGE LIMIT ACTIVE\n"
        "\n"
        "Claude API is currently rate-limited. Route this task through Ollama cloud:\n"
        "\n"
        f"Selected model: {model} (chosen for {task_type} at complexity {score})\n"
        "\n"
        f"To execute: uv run {ollama} chat {model} {quoted_prompt}\n"
        "\n"
        "Available commands:\n"
        f"- Chat: uv run {ollama} chat <model> \"your prompt\"\n"
        f"- List models: uv run {ollama} models\n"
        f"- Check status: uv run {monitor} check\n"
        "\n"
        "When you receive the response from Ollama, present it to the user normally.\n"
        f"Note: Claude API limit resets automatically. Monitor: uv run {monitor} check"
    )


def _read_advisor_signal() -> dict:
    """Read complexity signal written by intelligence_advisor (if present)."""
    try:
        sig_path = CLAUDE_DIR / "data" / "last_complexity_signal.json"
        if sig_path.exists():
            import time as _t
            # Only trust signal if written in last 30 seconds
            if _t.time() - sig_path.stat().st_mtime < 30:
                return json.loads(sig_path.read_text())
    except Exception:
        pass
    return {}


def _build_proactive_context(model: str, task_type: str, score: int) -> str:
    """Lightweight advisory hint for proactive routing (Claude is available)."""
    return (
        f"💡 ROUTING HINT: This looks like a {task_type} task (complexity {score}/100). "
        f"For best results consider: `uv run {OLLAMA_SCRIPT} chat {model} '<your prompt>'` "
        f"— {model} specialises in this task type."
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        _emit_empty()
        return 0

    try:
        input_data = json.loads(raw) if raw.strip() else {}
    except Exception:
        input_data = {}

    prompt = ""
    if isinstance(input_data, dict):
        prompt = str(input_data.get("prompt", "") or "")

    status = _read_status()
    rate_limited = bool(status.get("rate_limited"))

    task_type, keyword_hits = _classify_task(prompt)
    score = _estimate_complexity(prompt, keyword_hits)

    # Boost score if intelligence_advisor already flagged this as complex
    advisor = _read_advisor_signal()
    if advisor.get("is_complex"):
        score = min(100, score + 15)
        # Prefer advisor's task classification if we got one
        adv_type = advisor.get("task_type")
        if adv_type and adv_type in ("coding", "thinking", "fast", "general"):
            task_type = adv_type

    # Estimate context window requirement
    token_k = _estimate_token_k(prompt)
    min_ctx_k = token_k if token_k >= _LARGE_CONTEXT_THRESHOLD_K else 0

    if rate_limited:
        # Full routing mode — Claude unavailable, must use Ollama
        override = status.get("model_override")
        if isinstance(override, str) and override.strip():
            model = override.strip()
        else:
            model = _select_model(task_type, score, min_context_k=min_ctx_k)
        context = _build_context(model, task_type, score, _summarize_prompt(prompt))
        _emit_context(context)
    else:
        # Proactive mode — Claude available but task may benefit from a specialist
        threshold = PROACTIVE_THRESHOLDS.get(task_type, 90)
        large_ctx = min_ctx_k >= _LARGE_CONTEXT_THRESHOLD_K
        if score >= threshold or large_ctx:
            model = _select_model(task_type, score, min_context_k=min_ctx_k)
            _emit_context(_build_proactive_context(model, task_type, score))
        else:
            _emit_empty()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Hooks must never raise.
        _emit_empty()
        sys.exit(0)
