#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///

"""
Claude.ai profile cacher.

Reads the OAuth access token from ~/.claude/.credentials.json, fetches the
user's profile from https://api.claude.ai/api/auth/me, and writes the result
to ~/.claude/data/profile_cache.json along with a `cached_at` timestamp.

Designed to be run as an async SessionStart hook. On ANY failure we exit 0
silently and we never overwrite a pre-existing cache with a bad payload.
"""

from __future__ import annotations
__version__ = "2026.04.20.1"

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _load_access_token() -> str | None:
    try:
        cred_path = Path.home() / ".claude" / ".credentials.json"
        if not cred_path.exists():
            return None
        with cred_path.open("r", encoding="utf-8") as fh:
            cred = json.load(fh)
        if not isinstance(cred, dict):
            return None
        oauth = cred.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            return None
        token = oauth.get("accessToken") or oauth.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        return None
    except Exception:
        return None


def _fetch_profile(token: str) -> dict[str, Any] | None:
    # httpx is declared in the uv inline metadata above; we import it via
    # importlib so that static type-checkers that don't resolve uv-installed
    # deps don't fail the file.
    try:
        import importlib

        httpx = importlib.import_module("httpx")
    except Exception:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "claude-code-profile-cacher/1.0",
        }
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(
                "https://api.claude.ai/api/auth/me", headers=headers
            )
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        return body
    except Exception:
        return None


def _write_cache(profile: dict[str, Any]) -> bool:
    try:
        data_dir = Path.home() / ".claude" / "data"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
        cache_path = data_dir / "profile_cache.json"
        payload = {
            "cached_at": time.time(),
            "profile": profile,
        }
        # Write via temp file then rename so we never leave a half-written
        # JSON blob behind.
        tmp_path = cache_path.with_suffix(".json.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            tmp_path.replace(cache_path)
            return True
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return False
    except Exception:
        return False


def _refresh_usage_limits() -> None:
    """Fire-and-forget call to fetch_usage.py so usage cache refreshes
    alongside the profile at SessionStart. All errors swallowed."""
    try:
        script = Path.home() / ".claude" / "scripts" / "fetch_usage.py"
        if not script.exists():
            return
        try:
            subprocess.run(
                ["uv", "run", str(script), "fetch"],
                capture_output=True,
                timeout=8,
                check=False,
            )
        except Exception:
            return
    except Exception:
        return


def main() -> None:
    try:
        token = _load_access_token()
        if not token:
            _refresh_usage_limits()
            sys.exit(0)
        profile = _fetch_profile(token)
        if not profile:
            # Silent exit -- never overwrite an existing cache with garbage.
            _refresh_usage_limits()
            sys.exit(0)
        _write_cache(profile)
        _refresh_usage_limits()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
