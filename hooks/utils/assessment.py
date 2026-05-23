#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
Assessment Utility -- System Capability Detection

Detects available CLIs, models, API keys, and system capabilities.
Produces a JSON capability profile used by the trigger system and hooks.

GOTCHA Layer: Context + Tools
  - Context: Discovers and documents the runtime environment
  - Tools: Provides deterministic capability detection functions

ATLAS Phase: Architect
  - Establishes the foundational knowledge of what's available
    before any work begins

Flags:
  --install-missing  After running the assessment, automatically install any
                     missing optional CLIs via tools/install_clis.py --only <missing>
"""
__version__ = "2026.04.20.3"

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

CACHE_DIR = Path(".claude/data")
CACHE_FILE = CACHE_DIR / "assessment_cache.json"
CACHE_TTL_SECONDS = 300  # 5 minutes

BLOCKING_CAPABLE_HOOKS = [
    "PreToolUse",
    "PermissionRequest",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
]

ASYNC_CAPABLE_HOOKS = [
    "PostToolUse",
    "Notification",
    "TeammateIdle",
    "TaskCompleted",
]

_CLI_DEFAULT: dict[str, Any] = {
    "installed": False,
    "version": None,
    "authenticated": False,
}

# -------------------------------------------------------------------
# CLI Detection Functions
# -------------------------------------------------------------------


def detect_claude_cli() -> dict[str, Any]:
    """Detect Claude CLI installation and auth.

    Returns:
        dict: installed, version, authenticated
    """
    result: dict[str, Any] = {**_CLI_DEFAULT}
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["installed"] = True
            out = proc.stdout.strip() or proc.stderr.strip()
            result["version"] = _parse_version(out)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    result["authenticated"] = bool(key)
    return result


def detect_gemini_cli() -> dict[str, Any]:
    """Detect Gemini CLI installation and auth.

    Returns:
        dict: installed, version, authenticated
    """
    result: dict[str, Any] = {**_CLI_DEFAULT}
    try:
        proc = subprocess.run(
            ["gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["installed"] = True
            out = proc.stdout.strip() or proc.stderr.strip()
            result["version"] = _parse_version(out)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    google = os.environ.get("GOOGLE_API_KEY", "").strip()
    gemini = os.environ.get("GEMINI_API_KEY", "").strip()
    result["authenticated"] = bool(google or gemini)
    return result


def detect_codex_cli() -> dict[str, Any]:
    """Detect Codex CLI installation and auth.

    Returns:
        dict: installed, version, authenticated
    """
    result: dict[str, Any] = {**_CLI_DEFAULT}
    try:
        proc = subprocess.run(
            ["codex", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["installed"] = True
            out = proc.stdout.strip() or proc.stderr.strip()
            result["version"] = _parse_version(out)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    result["authenticated"] = bool(key)
    return result


def detect_gh_cli() -> dict[str, Any]:
    """Detect GitHub CLI installation and auth.

    Returns:
        dict: installed, version, authenticated
    """
    result: dict[str, Any] = {**_CLI_DEFAULT}
    try:
        proc = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["installed"] = True
            out = proc.stdout.strip() or proc.stderr.strip()
            result["version"] = _parse_version(out)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Check authentication via gh auth status
    if result["installed"]:
        try:
            auth_proc = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            result["authenticated"] = (
                auth_proc.returncode == 0
            )
        except (
            FileNotFoundError,
            subprocess.TimeoutExpired,
            OSError,
        ):
            pass

    return result


def detect_ollama() -> dict[str, Any]:
    """Detect Ollama server availability, version, and models.

    Uses GET /api/tags and GET /api/version via urllib.

    Returns:
        dict: installed, version, host, models (list[str])
    """
    host = os.environ.get(
        "OLLAMA_HOST", "http://localhost:11434"
    ).rstrip("/")
    result: dict[str, Any] = {
        "installed": False,
        "version": None,
        "host": host,
        "models": [],
    }

    # Check version endpoint
    try:
        version_url = f"{host}/api/version"
        req = urllib.request.Request(version_url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result["installed"] = True
            result["version"] = data.get("version")
    except Exception:
        pass

    # Check tags endpoint for models
    try:
        tags_url = f"{host}/api/tags"
        req = urllib.request.Request(tags_url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result["installed"] = True
            models = data.get("models", [])
            result["models"] = [
                m.get("name", "")
                for m in models
                if m.get("name")
            ]
    except Exception:
        pass

    return result


# -------------------------------------------------------------------
# API Key Detection
# -------------------------------------------------------------------


def detect_api_keys() -> dict[str, bool]:
    """Detect which API keys are configured.

    Returns:
        dict mapping provider name to bool.
    """
    def _has(var: str) -> bool:
        return bool(os.environ.get(var, "").strip())

    return {
        "openai": _has("OPENAI_API_KEY"),
        "anthropic": _has("ANTHROPIC_API_KEY"),
        "elevenlabs": _has("ELEVENLABS_API_KEY"),
        "ollama": _has("OLLAMA_API_KEY"),
    }


# -------------------------------------------------------------------
# Active CLI Detection
# -------------------------------------------------------------------


def detect_active_cli() -> str:
    """Detect which coding CLI is currently active.

    Returns:
        One of: "claude", "gemini", "codex", "unknown"
    """
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude"
    if os.environ.get("GEMINI_PROJECT_DIR"):
        return "gemini"
    if Path(".codex").is_dir():
        return "codex"
    return "unknown"


# -------------------------------------------------------------------
# Capability Detection
# -------------------------------------------------------------------


def detect_capabilities(
    assessment_so_far: dict[str, Any],
) -> dict[str, Any]:
    """Detect high-level system capabilities.

    Args:
        assessment_so_far: Partial assessment with api_keys,
            ollama, and gh entries.

    Returns:
        dict: tts, github, subagent_optimization,
              cli_optimized_for
    """
    api_keys = assessment_so_far.get("api_keys", {})
    ollama = assessment_so_far.get("ollama", {})
    gh = assessment_so_far.get("gh", {})

    # TTS: available if any TTS provider is reachable
    has_tts = (
        api_keys.get("elevenlabs", False)
        or api_keys.get("openai", False)
        or _check_pyttsx3()
    )

    # GitHub: gh installed and authenticated
    has_github = (
        gh.get("installed", False)
        and gh.get("authenticated", False)
    )

    # Subagent optimization: Ollama with models
    ollama_models = ollama.get("models", [])
    has_subagent = (
        ollama.get("installed", False)
        and len(ollama_models) > 0
    )

    return {
        "tts": has_tts,
        "github": has_github,
        "subagent_optimization": has_subagent,
        "cli_optimized_for": detect_active_cli(),
    }


# -------------------------------------------------------------------
# Hook Detection
# -------------------------------------------------------------------


def detect_hooks() -> dict[str, Any]:
    """Detect configured hooks from .claude/settings.json.

    Returns:
        dict: total, blocking_capable, async_capable
    """
    total = 0
    settings_path = Path(".claude/settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        hooks = settings.get("hooks", {})
        for _hook_type, entries in hooks.items():
            if isinstance(entries, list):
                for entry in entries:
                    hook_list = entry.get("hooks", [])
                    if isinstance(hook_list, list):
                        total += len(hook_list)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    return {
        "total": total,
        "blocking_capable": BLOCKING_CAPABLE_HOOKS,
        "async_capable": ASYNC_CAPABLE_HOOKS,
    }


# -------------------------------------------------------------------
# Model Recommendations
# -------------------------------------------------------------------


def get_model_recommendations(
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Generate model recommendations.

    Args:
        assessment: Assessment dict with api_keys and ollama.

    Returns:
        dict with preferred providers, available models,
        and task-specific recommendations.
    """
    api_keys = assessment.get("api_keys", {})
    ollama = assessment.get("ollama", {})
    ollama_installed = ollama.get("installed", False)
    ollama_models: list[str] = ollama.get("models", [])

    # Determine preferred LLM provider
    if ollama_installed and ollama_models:
        preferred_llm = "ollama"
    elif api_keys.get("openai"):
        preferred_llm = "openai"
    elif api_keys.get("anthropic"):
        preferred_llm = "anthropic"
    else:
        preferred_llm = "none"

    # Determine preferred TTS provider
    if api_keys.get("elevenlabs"):
        preferred_tts = "elevenlabs"
    elif api_keys.get("openai"):
        preferred_tts = "openai"
    elif _check_pyttsx3():
        preferred_tts = "pyttsx3"
    else:
        preferred_tts = "none"

    # Determine default Ollama model
    ollama_default: Optional[str] = None
    if ollama_models:
        ollama_default = os.environ.get(
            "OLLAMA_MODEL", ollama_models[0]
        )

    # Task-specific model recommendations
    task_models = _build_task_models(
        preferred_llm, ollama_models
    )

    return {
        "preferred_llm": preferred_llm,
        "preferred_tts": preferred_tts,
        "available_ollama_models": ollama_models,
        "ollama_default_model": ollama_default,
        "task_models": task_models,
    }


# -------------------------------------------------------------------
# Main Orchestrator
# -------------------------------------------------------------------


def run_assessment(use_cache: bool = True) -> dict[str, Any]:
    """Run a full system capability assessment.

    Args:
        use_cache: If True, return cached result if < 5 min old.

    Returns:
        Complete assessment dict with all detection results.
    """
    if use_cache:
        cached = load_cache()
        if cached is not None:
            return cached

    # Run all detection functions
    claude = detect_claude_cli()
    gemini = detect_gemini_cli()
    codex = detect_codex_cli()
    gh = detect_gh_cli()
    ollama = detect_ollama()
    api_keys = detect_api_keys()
    active_cli = detect_active_cli()
    hooks = detect_hooks()

    # Build partial assessment for capability detection
    partial: dict[str, Any] = {
        "api_keys": api_keys,
        "ollama": ollama,
        "gh": gh,
    }
    capabilities = detect_capabilities(partial)

    # Build complete assessment
    now = datetime.now(tz=timezone.utc).isoformat()
    assessment: dict[str, Any] = {
        "timestamp": now,
        "active_cli": active_cli,
        "clis": {
            "claude": claude,
            "gemini": gemini,
            "codex": codex,
            "gh": gh,
        },
        "ollama": ollama,
        "api_keys": api_keys,
        "capabilities": capabilities,
        "hooks": hooks,
        "models": get_model_recommendations({
            "api_keys": api_keys,
            "ollama": ollama,
        }),
    }

    save_cache(assessment)
    return assessment


# -------------------------------------------------------------------
# Caching
# -------------------------------------------------------------------


def load_cache() -> Optional[dict[str, Any]]:
    """Load cached assessment if < 5 minutes old.

    Returns:
        Cached assessment dict, or None if stale/missing.
    """
    try:
        if not CACHE_FILE.exists():
            return None
        mtime = CACHE_FILE.stat().st_mtime
        if (time.time() - mtime) > CACHE_TTL_SECONDS:
            return None
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(assessment: dict[str, Any]) -> None:
    """Save assessment result to cache file.

    Creates the cache directory if it does not exist.

    Args:
        assessment: Complete assessment dict to cache.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(assessment, f, indent=2)
    except OSError:
        pass


# -------------------------------------------------------------------
# Internal Helpers
# -------------------------------------------------------------------


def _parse_version(output: str) -> Optional[str]:
    """Extract a version string from CLI output.

    Args:
        output: Raw CLI output text.

    Returns:
        Extracted version string, or first line as fallback.
    """
    import re

    if not output:
        return None
    # Try to find a semver-like pattern
    match = re.search(r"v?(\d+\.\d+[\.\d]*\S*)", output)
    if match:
        return match.group(1)
    # Fallback: return first non-empty line
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _check_pyttsx3() -> bool:
    """Check if pyttsx3 is importable."""
    try:
        import importlib.util

        return importlib.util.find_spec("pyttsx3") is not None
    except Exception:
        return False


def _best_ollama_model(
    models: list[str], *preferred: str,
) -> Optional[str]:
    """Pick the best matching model by name fragment.

    Tries each preferred name fragment in order.
    Returns first match, or None.
    """
    if not models:
        return None
    for pref in preferred:
        pref_lower = pref.lower()
        for model in models:
            if pref_lower in model.lower():
                return model
    return None


def _build_task_models(
    preferred_llm: str,
    ollama_models: list[str],
) -> dict[str, str]:
    """Build task-specific model recommendations.

    If Ollama is available with models, pick best matches.
    Otherwise fall back to cloud provider suggestions.
    """
    if preferred_llm == "ollama" and ollama_models:
        # Try to match models by name fragment
        code_review = (
            _best_ollama_model(
                ollama_models,
                "qwen2.5-coder", "coder",
                "code", "deepseek",
            )
            or ollama_models[0]
        )
        summarization = (
            _best_ollama_model(
                ollama_models,
                "llama3.3", "llama3",
                "llama", "mistral",
            )
            or ollama_models[0]
        )
        # Pick smallest: shortest name or small tags
        naming = (
            _best_ollama_model(
                ollama_models,
                "phi", "tinyllama",
                "gemma:2b", "small",
            )
            or _smallest_model(ollama_models)
            or ollama_models[0]
        )
        assessment_model = ollama_models[0]
    elif preferred_llm == "openai":
        code_review = "gpt-4.1-nano"
        summarization = "gpt-4.1-nano"
        naming = "gpt-4.1-nano"
        assessment_model = "gpt-4.1-nano"
    elif preferred_llm == "anthropic":
        code_review = "claude-haiku-4-5-20251001"
        summarization = "claude-haiku-4-5-20251001"
        naming = "claude-haiku-4-5-20251001"
        assessment_model = "claude-haiku-4-5-20251001"
    else:
        code_review = "none"
        summarization = "none"
        naming = "none"
        assessment_model = "none"

    return {
        "code_review": code_review,
        "summarization": summarization,
        "naming": naming,
        "assessment": assessment_model,
    }


def _smallest_model(models: list[str]) -> Optional[str]:
    """Pick model with shortest name (proxy for smallest)."""
    if not models:
        return None
    return sorted(models, key=lambda m: len(m))[0]


# -------------------------------------------------------------------
# Summary Formatting
# -------------------------------------------------------------------


def _format_summary(assessment: dict[str, Any]) -> str:
    """Format assessment as a human-readable summary."""
    parts: list[str] = []

    # CLIs
    cli_parts: list[str] = []
    clis = assessment.get("clis", {})
    for name, info in clis.items():
        if info.get("installed"):
            ver = info.get("version", "?")
            auth = " (auth)" if info.get("authenticated") else ""
            cli_parts.append(f"{name} v{ver}{auth}")
    if cli_parts:
        parts.append("CLIs: " + ", ".join(cli_parts))
    else:
        parts.append("CLIs: none detected")

    # Ollama
    ollama = assessment.get("ollama", {})
    if ollama.get("installed"):
        model_count = len(ollama.get("models", []))
        ver = ollama.get("version", "?")
        parts.append(
            f"Ollama: v{ver} ({model_count} models)"
        )
    else:
        parts.append("Ollama: offline")

    # API Keys
    api_keys = assessment.get("api_keys", {})
    active_keys = [k for k, v in api_keys.items() if v]
    if active_keys:
        parts.append("API Keys: " + ", ".join(active_keys))
    else:
        parts.append("API Keys: none")

    # Capabilities
    caps = assessment.get("capabilities", {})
    cap_list: list[str] = []
    if caps.get("tts"):
        cap_list.append("tts")
    if caps.get("github"):
        cap_list.append("github")
    if caps.get("subagent_optimization"):
        cap_list.append("subagent")
    if cap_list:
        parts.append("Capabilities: " + ", ".join(cap_list))

    # Active CLI
    active = assessment.get("active_cli", "unknown")
    parts.append(f"Active CLI: {active}")

    # Models
    models = assessment.get("models", {})
    preferred = models.get("preferred_llm", "none")
    parts.append(f"Preferred LLM: {preferred}")

    # Hooks
    hooks = assessment.get("hooks", {})
    parts.append(f"Hooks: {hooks.get('total', 0)} configured")

    return " | ".join(parts)


# -------------------------------------------------------------------
# CLI Interface
# -------------------------------------------------------------------


def main() -> None:
    """CLI entry point for system capability assessment."""
    parser = argparse.ArgumentParser(
        description="System capability assessment",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON profile",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Human-readable summary",
    )
    parser.add_argument(
        "--check",
        type=str,
        help="Check single capability (e.g., ollama)",
    )
    parser.add_argument(
        "--models",
        action="store_true",
        help="List available models",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip cache, run fresh assessment",
    )
    parser.add_argument(
        "--install-missing",
        action="store_true",
        help="After assessment, install any missing optional CLIs via tools/install_clis.py",
    )
    args = parser.parse_args()

    use_cache = not args.no_cache
    assessment = run_assessment(use_cache=use_cache)

    if args.summary:
        print(_format_summary(assessment))
    elif args.check:
        _handle_check(args.check, assessment)
    elif args.models:
        _handle_models(assessment)
    else:
        # Default: --json behavior
        print(json.dumps(assessment, indent=2))

    # After normal output, handle --install-missing if requested
    if args.install_missing:
        # Optional CLIs that can be installed via tools/install_clis.py
        optional_clis = ["claude", "gemini", "codex", "gh", "ollama", "uv"]

        # Collect missing CLIs from the assessment
        missing: list[str] = []
        clis = assessment.get("clis", {})
        for cli_name in optional_clis:
            if cli_name in clis:
                if not clis[cli_name].get("installed", False):
                    missing.append(cli_name)
            elif cli_name == "ollama":
                if not assessment.get("ollama", {}).get("installed", False):
                    missing.append(cli_name)
            elif cli_name == "uv":
                # uv is not in the clis dict; check by running the command
                try:
                    proc = subprocess.run(
                        ["uv", "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if proc.returncode != 0:
                        missing.append(cli_name)
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                    missing.append(cli_name)

        if missing:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            install_script = project_root / "tools" / "install_clis.py"
            comma_separated = ",".join(missing)
            print(f"\nInstalling missing CLIs: {comma_separated}")
            result = subprocess.run(
                [sys.executable, str(install_script), "--only", comma_separated],
                timeout=600, text=True,
            )
            if result.returncode != 0:
                print(f"Warning: install_clis.py exited with code {result.returncode}")
        else:
            print("\nAll optional CLIs are already installed.")


def _handle_check(
    name: str, assessment: dict[str, Any],
) -> None:
    """Handle --check: exit 0 if available, 1 if not."""
    name_lower = name.lower()

    # Check CLIs
    clis = assessment.get("clis", {})
    if name_lower in clis:
        if clis[name_lower].get("installed"):
            print(f"{name}: available")
            sys.exit(0)
        else:
            print(f"{name}: not available")
            sys.exit(1)

    # Check Ollama
    if name_lower == "ollama":
        if assessment.get("ollama", {}).get("installed"):
            print("ollama: available")
            sys.exit(0)
        else:
            print("ollama: not available")
            sys.exit(1)

    # Check capabilities
    caps = assessment.get("capabilities", {})
    if name_lower in caps:
        val = caps[name_lower]
        if isinstance(val, bool):
            if val:
                print(f"{name}: available")
                sys.exit(0)
            else:
                print(f"{name}: not available")
                sys.exit(1)
        else:
            print(f"{name}: {val}")
            sys.exit(0)

    # Check API keys
    api_keys = assessment.get("api_keys", {})
    if name_lower in api_keys:
        if api_keys[name_lower]:
            print(f"{name}: available")
            sys.exit(0)
        else:
            print(f"{name}: not available")
            sys.exit(1)

    print(f"{name}: unknown capability")
    sys.exit(1)


def _handle_models(assessment: dict[str, Any]) -> None:
    """Handle --models: list all available models."""
    models = assessment.get("models", {})
    ollama_models = models.get("available_ollama_models", [])
    api_keys = assessment.get("api_keys", {})

    print("Available Models:")
    print("-" * 40)

    if ollama_models:
        count = len(ollama_models)
        print(f"  Ollama ({count} models):")
        default = models.get("ollama_default_model")
        for m in ollama_models:
            tag = " (default)" if m == default else ""
            print(f"    - {m}{tag}")

    if api_keys.get("openai"):
        print("  OpenAI: API key configured")
    if api_keys.get("anthropic"):
        print("  Anthropic: API key configured")

    has_openai = api_keys.get("openai")
    has_anthropic = api_keys.get("anthropic")
    if not ollama_models and not has_openai and not has_anthropic:
        print("  No models available")

    print()
    print("Task Recommendations:")
    task_models = models.get("task_models", {})
    for task, model in task_models.items():
        print(f"  {task}: {model}")


if __name__ == "__main__":
    main()
