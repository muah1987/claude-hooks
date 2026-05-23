#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///

"""
Claude.ai plan usage limits cacher.

Fetches session / weekly-all-models / weekly-Sonnet usage percentages
from claude.ai and writes them to ~/.claude/data/usage_limits.json.

Three subcommands:

    fetch_usage.py fetch          # try a list of endpoints, cache result
    fetch_usage.py update <text>  # parse free-text usage string, cache it
    fetch_usage.py show           # pretty-print the current cache

Everything is wrapped in try/except; the script always exits 0.
"""

from __future__ import annotations
__version__ = "2026.04.20.2"

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_CLAUDE_DIR = Path.home() / ".claude"
_DATA_DIR = _CLAUDE_DIR / "data"
_CACHE_PATH = _DATA_DIR / "usage_limits.json"
_CRED_PATH = _CLAUDE_DIR / ".credentials.json"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def _load_access_token() -> str | None:
    try:
        if not _CRED_PATH.exists():
            return None
        with _CRED_PATH.open("r", encoding="utf-8") as fh:
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


def _load_org_id() -> str | None:
    """Best-effort: pull an organization_id out of cached profile data."""
    try:
        prof_path = _DATA_DIR / "profile_cache.json"
        if not prof_path.exists():
            return None
        with prof_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return None
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            return None

        # Common shapes: account.organization_uuid, organizations[0].uuid, etc.
        for key in ("organization_id", "organization_uuid", "org_id"):
            v = profile.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        account = profile.get("account")
        if isinstance(account, dict):
            for key in ("organization_id", "organization_uuid", "org_id"):
                v = account.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        orgs = profile.get("organizations")
        if isinstance(orgs, list) and orgs:
            first = orgs[0]
            if isinstance(first, dict):
                for key in ("uuid", "id", "organization_id"):
                    v = first.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------
def _write_cache(payload: dict[str, Any]) -> bool:
    try:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
        tmp_path = _CACHE_PATH.with_suffix(".json.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            tmp_path.replace(_CACHE_PATH)
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


def _read_cache() -> dict[str, Any] | None:
    try:
        if not _CACHE_PATH.exists():
            return None
        with _CACHE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _walk(obj: Any):
    """Yield every dict encountered in a nested JSON structure."""
    try:
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk(v)
    except Exception:
        return


def _as_pct(v: Any) -> int | None:
    """Coerce a value to a 0-100 integer percent, rejecting nonsense."""
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        n = float(v)
        # If the server sent a 0-1 fraction, scale it.
        # Use strict inequalities so that the literal value 1 means "1 percent"
        # (not "100 percent") and 0 means "0 percent" (not scaled).
        if 0.0 < n < 1.0:
            n *= 100.0
        n = max(0.0, min(100.0, n))
        return int(round(n))
    except Exception:
        return None


def _parse_api_response(body: Any) -> dict[str, Any] | None:
    """Walk the response for session / weekly / sonnet pct fields.

    We accept many possible key names since the endpoint shape isn't stable.
    Returns a usage dict if at least one percentage was found, else None.
    """
    try:
        session_pct: int | None = None
        weekly_all_pct: int | None = None
        weekly_sonnet_pct: int | None = None
        resets_in_mins: int | None = None
        weekly_resets_at: str | None = None

        session_keys = (
            "session_used_percentage",
            "session_usage_percent",
            "session_percent",
            "five_hour_usage_percent",
            "five_hour_percent",
            "current_session_percent",
        )
        weekly_all_keys = (
            "weekly_used_percentage",
            "weekly_usage_percent",
            "weekly_all_percent",
            "weekly_percent",
            "seven_day_percent",
            "week_percent",
        )
        weekly_sonnet_keys = (
            "weekly_sonnet_percent",
            "weekly_sonnet_used_percentage",
            "sonnet_weekly_percent",
            "sonnet_percent",
        )
        reset_in_keys = (
            "session_resets_in_seconds",
            "session_resets_in",
            "resets_in_seconds",
            "resets_in",
            "session_resets_in_minutes",
            "five_hour_resets_in_seconds",
        )
        weekly_reset_keys = (
            "weekly_resets_at",
            "weekly_reset_at",
            "week_resets_at",
            "seven_day_resets_at",
        )

        for d in _walk(body):
            if not isinstance(d, dict):
                continue
            if session_pct is None:
                for k in session_keys:
                    if k in d:
                        p = _as_pct(d[k])
                        if p is not None:
                            session_pct = p
                            break
            if weekly_all_pct is None:
                for k in weekly_all_keys:
                    if k in d:
                        p = _as_pct(d[k])
                        if p is not None:
                            weekly_all_pct = p
                            break
            if weekly_sonnet_pct is None:
                for k in weekly_sonnet_keys:
                    if k in d:
                        p = _as_pct(d[k])
                        if p is not None:
                            weekly_sonnet_pct = p
                            break
            if resets_in_mins is None:
                for k in reset_in_keys:
                    if k in d:
                        try:
                            raw = float(d[k])
                            if "minute" in k:
                                resets_in_mins = int(round(raw))
                            else:
                                resets_in_mins = int(round(raw / 60.0))
                            break
                        except Exception:
                            continue
            if weekly_resets_at is None:
                for k in weekly_reset_keys:
                    if k in d:
                        v = d[k]
                        if isinstance(v, str) and v.strip():
                            weekly_resets_at = v.strip()
                            break

        if session_pct is None and weekly_all_pct is None and weekly_sonnet_pct is None:
            return None

        usage: dict[str, Any] = {}
        if session_pct is not None:
            entry: dict[str, Any] = {"pct": session_pct}
            if resets_in_mins is not None:
                entry["resets_in_mins"] = resets_in_mins
            usage["session"] = entry
        if weekly_all_pct is not None:
            entry = {"pct": weekly_all_pct}
            if weekly_resets_at:
                entry["resets_at"] = weekly_resets_at
            usage["weekly_all"] = entry
        if weekly_sonnet_pct is not None:
            entry = {"pct": weekly_sonnet_pct}
            if weekly_resets_at:
                entry["resets_at"] = weekly_resets_at
            usage["weekly_sonnet"] = entry
        return usage
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Network fetch
# ---------------------------------------------------------------------------
def _iso_now() -> str:
    try:
        return datetime.now().replace(microsecond=0).isoformat()
    except Exception:
        return ""


def _plan_from_credentials() -> str:
    try:
        if not _CRED_PATH.exists():
            return ""
        with _CRED_PATH.open("r", encoding="utf-8") as fh:
            cred = json.load(fh)
        if not isinstance(cred, dict):
            return ""
        oauth = cred.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            return ""
        sub = str(oauth.get("subscriptionType") or "").strip().lower()
        tier = str(oauth.get("rateLimitTier") or "").strip().lower()
        if "20x" in tier:
            return "max_20x"
        if "5x" in tier:
            return "max_5x"
        if sub:
            return sub
        return ""
    except Exception:
        return ""


def cmd_fetch() -> int:
    """Try a list of endpoints, cache any usable response."""
    try:
        token = _load_access_token()
        if not token:
            print("unavailable")
            return 0

        try:
            import importlib

            httpx = importlib.import_module("httpx")
        except Exception:
            print("unavailable")
            return 0

        org_id = _load_org_id() or ""

        endpoints: list[str] = [
            "https://api.claude.ai/api/rate_limits",
            "https://api.claude.ai/api/usage_limits",
            "https://api.claude.ai/api/account/usage",
            "https://claude.ai/api/rate_limits",
            "https://claude.ai/api/usage_limits",
        ]
        if org_id:
            endpoints.append(
                f"https://api.claude.ai/api/organizations/{org_id}/usage"
            )
            endpoints.append(
                f"https://api.claude.ai/api/organizations/{org_id}/rate_limits"
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-client-version": "claude-code",
            "User-Agent": "Claude-Code/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        usage: dict[str, Any] | None = None
        for url in endpoints:
            try:
                with httpx.Client(timeout=5.0, follow_redirects=True) as client:
                    resp = client.get(url, headers=headers)
                status = resp.status_code
                # Try to parse body regardless of status for diagnostics.
                body: Any = None
                try:
                    body = resp.json()
                except Exception:
                    body = None
                # Stderr log; keeps stdout clean.
                try:
                    preview = (
                        json.dumps(body)[:160]
                        if isinstance(body, (dict, list))
                        else str(body)[:160] if body is not None else ""
                    )
                    sys.stderr.write(
                        f"[fetch_usage] {status} {url} {preview}\n"
                    )
                except Exception:
                    pass
                if status != 200:
                    continue
                parsed = _parse_api_response(body)
                if parsed:
                    usage = parsed
                    break
            except Exception as exc:
                try:
                    sys.stderr.write(
                        f"[fetch_usage] err {url} {type(exc).__name__}: {exc}\n"
                    )
                except Exception:
                    pass
                continue

        if not usage:
            print("unavailable")
            return 0

        payload: dict[str, Any] = {
            "fetched_at": _iso_now(),
            "plan": _plan_from_credentials(),
            "source": "api",
        }
        payload.update(usage)
        _write_cache(payload)
        print("fetched")
        return 0
    except Exception:
        try:
            print("unavailable")
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# Manual update (free-text parsing)
# ---------------------------------------------------------------------------
def _parse_free_text(text: str) -> dict[str, Any]:
    """Extract session / weekly / sonnet pct and optional reset from free text.

    Handles many shapes, e.g.:
        "Current session: 15% used, resets in 3h 56m. Weekly all: 31%. Sonnet: 26%"
        "15% session, 31% weekly, 26% sonnet"
        "session=15 weekly=31 sonnet=26 resets=3h56m"
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        if not isinstance(text, str) or not text.strip():
            return dict(out)
        lo = text.lower()

        def _find_pct(keywords: tuple[str, ...]) -> int | None:
            # Prefer "keyword ... number": "session=15", "session: 15%",
            # "session 15%". Only allow a small gap of symbols/spaces so
            # trailing numbers from the next bucket don't leak in.
            for kw in keywords:
                pat_after = rf"{kw}[\s:=]{{0,3}}(\d{{1,3}})\s*%?"
                m = re.search(pat_after, lo)
                if m:
                    try:
                        n = int(m.group(1))
                        if 0 <= n <= 100:
                            return n
                    except Exception:
                        continue
            # Fallback: "number-before-keyword" but only whitespace / % in
            # between, so "15% session" matches but "session=15 weekly"
            # does not re-steal the 15 for "weekly".
            for kw in keywords:
                pat_before = rf"(\d{{1,3}})\s*%\s*{kw}"
                m = re.search(pat_before, lo)
                if m:
                    try:
                        n = int(m.group(1))
                        if 0 <= n <= 100:
                            return n
                    except Exception:
                        continue
            return None

        sonnet_pct = _find_pct(("sonnet",))
        # For "weekly" and "session", make sure we don't double-match Sonnet's number.
        weekly_pct = _find_pct(("weekly all", "weekly_all", "weekly"))
        session_pct = _find_pct(("current session", "session"))

        if session_pct is not None:
            out["session"] = {"pct": session_pct}
        if weekly_pct is not None:
            out["weekly_all"] = {"pct": weekly_pct}
        if sonnet_pct is not None:
            out["weekly_sonnet"] = {"pct": sonnet_pct}

        # Session reset: "resets in 3h 56m" / "resets=3h56m" / "resets in 45m"
        m = re.search(
            r"reset[s]?\s*(?:in)?\s*[:=]?\s*(?:(\d+)\s*h)?\s*(\d+)?\s*m",
            lo,
        )
        if m:
            try:
                h = int(m.group(1)) if m.group(1) else 0
                mm = int(m.group(2)) if m.group(2) else 0
                total = h * 60 + mm
                if total > 0:
                    if "session" not in out:
                        out["session"] = {}
                    out["session"]["resets_in_mins"] = total
            except Exception:
                pass

        # Weekly reset: "resets Thu 9:00 PM" -> capture short phrase
        m = re.search(
            r"reset[s]?\s+(?:at\s+)?((?:mon|tue|wed|thu|fri|sat|sun)\w*\s+[^.,;]+)",
            lo,
        )
        if m:
            val = m.group(1).strip()
            if val and "weekly_all" in out:
                out["weekly_all"]["resets_at"] = val
            if val and "weekly_sonnet" in out:
                out["weekly_sonnet"]["resets_at"] = val
    except Exception:
        return dict(out)
    return dict(out)


def cmd_update(args: list[str]) -> int:
    try:
        text = " ".join(args).strip()
        if not text:
            print("updated: session=?, weekly=?, sonnet=?")
            return 0
        parsed = _parse_free_text(text)
        if not parsed:
            print("updated: session=?, weekly=?, sonnet=?")
            return 0

        payload: dict[str, Any] = {
            "fetched_at": _iso_now(),
            "plan": _plan_from_credentials(),
            "source": "manual",
        }
        payload.update(parsed)
        _write_cache(payload)

        def _fmt(key: str) -> str:
            entry = parsed.get(key)
            if isinstance(entry, dict):
                pct = entry.get("pct")
                if isinstance(pct, int):
                    return f"{pct}%"
            return "?"

        print(
            f"updated: session={_fmt('session')}, "
            f"weekly={_fmt('weekly_all')}, "
            f"sonnet={_fmt('weekly_sonnet')}"
        )
        return 0
    except Exception:
        try:
            print("updated: session=?, weekly=?, sonnet=?")
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------
def cmd_show() -> int:
    try:
        cache = _read_cache()
        if not cache:
            print("no usage cache")
            return 0
        try:
            print(json.dumps(cache, indent=2, ensure_ascii=False))
        except Exception:
            print(str(cache))
        return 0
    except Exception:
        try:
            print("no usage cache")
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        argv = sys.argv[1:]
        cmd = argv[0].lower() if argv else "fetch"
        rest = argv[1:]
        if cmd == "fetch":
            cmd_fetch()
        elif cmd == "update":
            cmd_update(rest)
        elif cmd == "show":
            cmd_show()
        else:
            print(f"Unknown command: {cmd}. Valid: fetch, status, watch", file=sys.stderr)
            cmd_fetch()  # keep backward-compat default
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
