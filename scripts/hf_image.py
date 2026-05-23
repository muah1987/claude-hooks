#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface_hub>=0.23.0", "Pillow>=10.0.0"]
# ///
"""
hf_image.py — HuggingFace InferenceClient image generation helper.
__version__ = "2026.04.21.1"

Cascade: Recraft V3 → FLUX 1.1 Pro → FLUX.1-dev (first success wins).
Token from HF_TOKEN env var (set in ~/.claude/settings.json).

Usage:
  hf_image.py "a serene mosque at sunset"
  hf_image.py "logo for a tech startup" --model recraft --out /tmp/logo.png
  hf_image.py "portrait" --model flux-pro --style realistic_image
"""
from __future__ import annotations
__version__ = "2026.04.21.1"

import argparse
import os
import sys
import time
from pathlib import Path

try:
    from huggingface_hub import InferenceClient
    from PIL import Image  # noqa: F401 — verify Pillow is available
    HAS_HF = True
except ImportError:
    HAS_HF = False


MODELS = {
    "recraft": ("recraft-ai/recraft-v3", "fal-ai"),
    "flux-pro": ("black-forest-labs/FLUX.1-pro", "fal-ai"),
    "flux-dev": ("black-forest-labs/FLUX.1-dev:fastest", "auto"),
    "sd35": ("stabilityai/stable-diffusion-3.5-large", "auto"),
}

CASCADE = ["recraft", "flux-pro", "flux-dev"]


def generate(
    prompt: str,
    model_key: str | None = None,
    out: str | None = None,
    style: str | None = None,
) -> str | None:
    """
    Generate image from prompt. Returns saved file path or None on failure.
    model_key: one of MODELS keys, or None to cascade through all.
    """
    if not HAS_HF:
        print("ERROR: huggingface_hub not installed. Run: uv add huggingface_hub Pillow")
        return None

    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print("ERROR: HF_TOKEN not set in environment.")
        return None

    client = InferenceClient(api_key=token)
    outfile = out or f"/tmp/hf_image_{int(time.time())}.png"
    keys_to_try = [model_key] if model_key else CASCADE

    for key in keys_to_try:
        model_id, provider = MODELS.get(key, MODELS["flux-dev"])
        print(f"  Trying {key} ({model_id})...")
        try:
            kwargs: dict = {"model": model_id, "provider": provider}
            if style and key == "recraft":
                kwargs["parameters"] = {"style": style}
            image = client.text_to_image(prompt, **kwargs)
            image.save(outfile)
            print(f"  ✅ Saved to {outfile}")
            return outfile
        except Exception as e:
            print(f"  ✗ {key} failed: {e}")

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="HF image generation cascade")
    parser.add_argument("prompt", nargs="?", default="", help="Image prompt")
    parser.add_argument("--model", choices=list(MODELS.keys()), default=None,
                        help="Force a specific model (default: cascade)")
    parser.add_argument("--out", default=None, help="Output file path (.png)")
    parser.add_argument("--style", default=None,
                        help="Recraft style: realistic_image | digital_illustration | vector_illustration | anime")
    args = parser.parse_args()

    prompt = args.prompt.strip()
    if not prompt:
        # Read from stdin if no prompt arg
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
    if not prompt:
        parser.print_help()
        return 1

    result = generate(prompt, model_key=args.model, out=args.out, style=args.style)
    if result:
        print(result)  # last line = path, easy to capture
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
