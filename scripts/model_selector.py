#!/usr/bin/env python3
"""
model_selector.py — Pick the best Ollama cloud model for a task.

Pure-stdlib helper used by both the rate-limit monitor and the UserPromptSubmit
router hook to answer the question: "Given a task type and complexity score,
which Ollama cloud model should we route this prompt to?"

Commands:
    select <score 0-100> <task_type>   Print the recommended model id.
    list                               Print every tier with its models.

Task types: coding | thinking | general | fast
"""

from __future__ import annotations
__version__ = "2026.04.20.4"

import sys

# Context window in thousands of tokens (k). Verified against api.ollama.com 2026-04-20.
# Models without an entry default to 32k (conservative).
MODEL_CONTEXT_K: dict[str, int] = {
    "kimi-k2.5":              128,
    "kimi-k2:1t":             128,
    "kimi-k2-thinking":       128,
    "mistral-large-3:675b":   128,
    "deepseek-v3.1:671b":     128,
    "deepseek-v3.2":           64,
    "cogito-2.1:671b":        128,
    "qwen3-coder:480b":       128,
    "qwen3-coder-next":        32,
    "qwen3-next:80b":          32,
    "qwen3.5:397b":            32,
    "qwen3-vl:235b":          128,
    "devstral-2:123b":        128,
    "devstral-small-2:24b":    32,
    "gpt-oss:120b":            32,
    "gemma4:31b":             128,
    "gemma3:27b":             128,
    "gemini-3-flash-preview": 128,
    "nemotron-3-super":        32,
    "ministral-3:14b":        128,
    "glm-5":                   32,
    "glm-5.1":                 32,
    "minimax-m2.7":            32,
}

TIERS: dict[str, dict[str, object]] = {
    "tier_1_heavy": {
        "label": "Tier 1 — Heavy / Complex (frontier)",
        "models": [
            "kimi-k2.5",
            "kimi-k2:1t",
            "mistral-large-3:675b",
            "deepseek-v3.1:671b",
            "cogito-2.1:671b",
            "qwen3.5:397b",
            "qwen3-coder:480b",
            "devstral-2:123b",
            "gpt-oss:120b",
        ],
        "use_cases": "Hard reasoning, large-context coding, research-grade synthesis.",
    },
    "tier_2_medium": {
        "label": "Tier 2 — Medium / Coding",
        "models": [
            "kimi-k2-thinking",
            "nemotron-3-super",
            "qwen3-coder-next",
            "deepseek-v3.2",
            "qwen3-next:80b",
            "gemma4:31b",
            "devstral-small-2:24b",
        ],
        "use_cases": "Everyday coding tasks, balanced cost/quality chat.",
    },
    "tier_3_fast": {
        "label": "Tier 3 — Fast / Simple",
        "models": [
            "gemini-3-flash-preview",
            "ministral-3:14b",
            "gemma3:27b",
            "glm-5.1",
            "minimax-m2.7",
        ],
        "use_cases": "Short prompts, quick answers, low-latency routing.",
    },
    "special_coding": {
        "label": "Special — Coding",
        "models": ["qwen3-coder:480b", "devstral-2:123b"],
        "use_cases": "Prefer when the prompt is explicitly about writing/fixing code.",
    },
    "special_thinking": {
        "label": "Special — Thinking",
        "models": ["kimi-k2-thinking", "kimi-k2.5", "deepseek-v3.1:671b"],
        "use_cases": "Prefer for multi-step reasoning, planning, or analysis.",
    },
}


def _clamp(score: int, low: int = 0, high: int = 100) -> int:
    if score < low:
        return low
    if score > high:
        return high
    return score


def select_model(score: int, task_type: str, min_context_k: int = 0) -> str:
    """Return the Ollama model id matching the routing rules.

    min_context_k: minimum required context window in thousands of tokens.
    When set, models whose window is smaller than this are skipped.
    """
    s = _clamp(int(score))
    t = (task_type or "general").strip().lower()

    def _ok(model: str) -> bool:
        """True if model has enough context window."""
        if min_context_k <= 0:
            return True
        return MODEL_CONTEXT_K.get(model, 32) >= min_context_k

    if t == "coding":
        if s >= 70 and _ok("qwen3-coder:480b"):
            return "qwen3-coder:480b"
        if s >= 70 and _ok("devstral-2:123b"):
            return "devstral-2:123b"
        if s >= 40 and _ok("qwen3-coder-next"):
            return "qwen3-coder-next"
        if _ok("devstral-small-2:24b"):
            return "devstral-small-2:24b"
        return "kimi-k2.5"

    if t == "thinking":
        # Always use dedicated thinking model regardless of score.
        if _ok("kimi-k2-thinking"):
            return "kimi-k2-thinking"
        if _ok("kimi-k2.5"):
            return "kimi-k2.5"
        if _ok("deepseek-v3.2"):
            return "deepseek-v3.2"
        return "kimi-k2.5"

    if t == "fast":
        if _ok("gemini-3-flash-preview"):
            return "gemini-3-flash-preview"
        if _ok("ministral-3:14b"):
            return "ministral-3:14b"
        return "gemma3:27b"

    # general / default — prefer kimi-k2.5 over kimi-k2:1t (k2:1t has 500 issues)
    if s >= 80 and _ok("kimi-k2.5"):
        return "kimi-k2.5"
    if s >= 50 and _ok("mistral-large-3:675b"):
        return "mistral-large-3:675b"
    if _ok("qwen3-next:80b"):
        return "qwen3-next:80b"
    return "kimi-k2.5"  # ultimate fallback (kimi-k2:1t has intermittent 500 on cloud)


def cmd_select(argv: list[str]) -> int:
    if len(argv) < 4:
        print("Usage: model_selector.py select <score 0-100> <task_type> [min_context_k]", file=sys.stderr)
        return 0
    try:
        score = int(argv[2])
    except ValueError:
        score = 50
    task_type = argv[3]
    try:
        min_ctx = int(argv[4]) if len(argv) >= 5 else 0
    except ValueError:
        min_ctx = 0
    print(select_model(score, task_type, min_context_k=min_ctx))
    return 0


def cmd_list() -> int:
    for _, tier in TIERS.items():
        label = tier.get("label", "")
        models = tier.get("models", [])
        use_cases = tier.get("use_cases", "")
        print(label)
        print("-" * len(str(label)) if label else "")
        if isinstance(models, list):
            for m in models:
                print(f"  - {m}")
        if use_cases:
            print(f"  Use: {use_cases}")
        print()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage:\n"
            "  model_selector.py select <score 0-100> <task_type>\n"
            "  model_selector.py list"
        )
        return 0
    cmd = argv[1].strip().lower()
    if cmd == "select":
        return cmd_select(argv)
    if cmd == "list":
        return cmd_list()
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
