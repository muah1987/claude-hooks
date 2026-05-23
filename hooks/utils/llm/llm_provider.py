#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai",
#     "anthropic",
#     "python-dotenv",
# ]
# ///

"""
Unified LLM Provider - GOTCHA Framework Tools Layer

Provides a single interface to access the best available LLM provider.
Priority order: Ollama (local) > OpenAI > Anthropic > fallback.

GOTCHA Layer: Tools (deterministic LLM access interface)
ATLAS Phase: Assemble (provides LLM capabilities for building workflows)

Environment Variables:
- OLLAMA_HOST: Ollama server URL (default: http://localhost:11434)
- OLLAMA_API_KEY: Ollama API key (default: ollama)
- OLLAMA_MODEL: Ollama model name (default: gpt-oss:20b)
- OPENAI_API_KEY: OpenAI API key
- ANTHROPIC_API_KEY: Anthropic API key
- ENGINEER_NAME: Engineer's name for personalized messages
"""
__version__ = "2026.04.20.3"

import os
import sys
import json
from typing import Optional
from dotenv import load_dotenv


def _check_ollama_available(host: str, timeout: float = 2.0) -> bool:
    """Check if Ollama server is reachable via GET /api/tags with a 2-second timeout."""
    import urllib.request
    import urllib.error
    try:
        url = f"{host.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, method='GET')
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def get_available_providers() -> list[str]:
    """Return list of available LLM providers in priority order."""
    load_dotenv()
    providers = []

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    if _check_ollama_available(ollama_host):
        providers.append("ollama")

    if os.getenv("OPENAI_API_KEY"):
        providers.append("openai")

    if os.getenv("ANTHROPIC_API_KEY"):
        providers.append("anthropic")

    return providers


def get_llm_client(provider: Optional[str] = None):
    """
    Get an LLM client for the best available (or specified) provider.

    Returns a tuple of (provider_name, client_object).
    For ollama and openai, returns an OpenAI client.
    For anthropic, returns an Anthropic client.
    """
    load_dotenv()

    if provider is None:
        available = get_available_providers()
        if not available:
            return None, None
        provider = available[0]

    if provider == "ollama":
        from openai import OpenAI
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        api_key = os.getenv("OLLAMA_API_KEY", "ollama")
        client = OpenAI(
            base_url=f"{host.rstrip('/')}/v1",
            api_key=api_key,
        )
        return "ollama", client

    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return "openai", client

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return "anthropic", client

    return None, None


def prompt_llm(text: str, provider: Optional[str] = None, max_tokens: int = 200) -> Optional[str]:
    """
    Prompt the best available LLM with the given text.

    Args:
        text: The prompt text
        provider: Force a specific provider ("ollama", "openai", "anthropic")
        max_tokens: Maximum response tokens

    Returns:
        Response text, or None if all providers fail
    """
    load_dotenv()

    provider_name, client = get_llm_client(provider)
    if not client:
        return None

    try:
        if provider_name in ("ollama", "openai"):
            model = os.getenv("OLLAMA_MODEL", "gpt-oss:20b") if provider_name == "ollama" else "gpt-4.1-nano"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": text}],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()

        elif provider_name == "anthropic":
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": text}],
            )
            return message.content[0].text.strip()

    except Exception:
        return None


def generate_completion_message() -> str:
    """Generate a friendly completion message using the best available LLM."""
    import random

    engineer_name = os.getenv("ENGINEER_NAME", "").strip()

    if engineer_name:
        name_instruction = f"Sometimes (about 30% of the time) include the engineer's name '{engineer_name}' in a natural way."
    else:
        name_instruction = ""

    prompt = f"""Generate a short, friendly completion message for when an AI coding assistant finishes a task.

Requirements:
- Keep it under 10 words
- Make it positive and future focused
- Use natural, conversational language
- Focus on completion/readiness
- Do NOT include quotes, formatting, or explanations
- Return ONLY the completion message text
{name_instruction}

Generate ONE completion message:"""

    response = prompt_llm(prompt)
    if response:
        response = response.strip().strip('"').strip("'").strip()
        response = response.split("\n")[0].strip()
        return response

    # Fallback
    fallback = ["Work complete!", "All done!", "Task finished!", "Ready for next task!", "Job complete!"]
    return random.choice(fallback)


def generate_agent_name() -> str:
    """Generate a one-word agent name using the best available LLM."""
    import random

    example_names = [
        "Phoenix", "Sage", "Nova", "Echo", "Atlas", "Cipher", "Nexus",
        "Oracle", "Quantum", "Zenith", "Aurora", "Vortex", "Nebula",
        "Catalyst", "Prism", "Axiom", "Helix", "Flux", "Synth", "Vertex",
    ]

    prompt_text = """Generate exactly ONE unique agent/assistant name.

Requirements:
- Single word only (no spaces, hyphens, or punctuation)
- Abstract and memorable
- Professional sounding
- Easy to pronounce

Generate a NEW name. Respond with ONLY the name, nothing else.

Name:"""

    try:
        response = prompt_llm(prompt_text, max_tokens=20)
        if response:
            name = response.strip().split()[0]
            name = "".join(c for c in name if c.isalnum())
            name = name.capitalize() if name else "Agent"
            if name and 3 <= len(name) <= 20:
                return name
    except Exception:
        pass

    return random.choice(example_names)


def main():
    """CLI interface with --test flag for diagnostics."""
    import argparse

    parser = argparse.ArgumentParser(description="Unified LLM Provider")
    parser.add_argument("--test", action="store_true", help="Test all available providers")
    parser.add_argument("--completion", action="store_true", help="Generate completion message")
    parser.add_argument("--agent-name", action="store_true", help="Generate agent name")
    parser.add_argument("prompt", nargs="*", help="Prompt text")
    args = parser.parse_args()

    if args.test:
        load_dotenv()
        providers = get_available_providers()
        diagnostics = {
            "available_providers": providers,
            "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            "ollama_model": os.getenv("OLLAMA_MODEL", "gpt-oss:20b"),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        }

        # Test each available provider
        for p in providers:
            try:
                result = prompt_llm("Say 'hello' in one word.", provider=p, max_tokens=10)
                diagnostics[f"{p}_test"] = result or "no response"
            except Exception as e:
                diagnostics[f"{p}_test"] = f"error: {e}"

        print(json.dumps(diagnostics, indent=2))
        sys.exit(0)

    if args.completion:
        print(generate_completion_message())
    elif args.agent_name:
        print(generate_agent_name())
    elif args.prompt:
        result = prompt_llm(" ".join(args.prompt))
        print(result or "No LLM providers available")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
