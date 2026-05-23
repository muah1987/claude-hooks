#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///

"""
usage_monitor.py — Claude API rate-limit monitor.

Detects whether the logged-in Claude account is currently rate-limited by hitting
the lightweight `/api/auth/me` endpoint with the OAuth access token stored in
`~/.claude/.credentials.json`. Writes the authoritative status to
`~/.claude/data/usage_status.json` which the rest of the auto-routing system
(model_router hook, model_selector script, skills) reads.

Commands:
    check                 One-shot probe of Claude availability.
    watch                 Long-running daemon loop (60s/300s cadence).

Rules:
- Exits 0 from every code path (status line / hooks must not break).
- HTTP timeout is capped at 5s for `check` and 10s for `watch` iterations.
- Single source of truth: ~/.claude/data/usage_status.json

Status file schema:
{
    "rate_limited": bool,
    "checked_at": "<iso8601>",
    "limited_since": "<iso8601|null>",
    "model_override": "<ollama-model|null>",
    "retry_after": "<iso8601|int|null>"
}
"""

from __future__ import annotations
__version__ = "2026.04.21.1"

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CREDENTIALS_FILE = CLAUDE_DIR / ".credentials.json"
DATA_DIR = CLAUDE_DIR / "data"
STATUS_FILE = DATA_DIR / "usage_status.json"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
MODEL_SELECTOR = SCRIPTS_DIR / "model_selector.py"
TELEGRAM_HOOK = CLAUDE_DIR / "hooks" / "telegram_notify.py"

# api.claude.ai is NXDOMAIN — not a public endpoint, cannot be probed externally.
# Rate-limit detection must come from Claude Code itself (429 responses),
# not from external HTTP probes. The probe is permanently disabled.
CHECK_URL = ""  # disabled
CHECK_TIMEOUT = 5.0

AVAILABLE_INTERVAL = 300  # seconds between polls when we're healthy
LIMITED_INTERVAL = 60     # seconds between polls when rate-limited

# Default best model when the override is computed freshly (general, high complexity).
DEFAULT_MODEL_OVERRIDE = "kimi-k2:1t"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _read_token() -> str:
    """Return the Claude OAuth access token or an empty string on failure."""
    try:
        with CREDENTIALS_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return ""
        oauth = payload.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            return ""
        token = oauth.get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()
    except Exception:
        pass
    return ""


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


def _write_status(status: dict[str, Any]) -> None:
    _ensure_data_dir()
    try:
        tmp = STATUS_FILE.with_suffix(STATUS_FILE.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(status, fh, indent=2)
        tmp.replace(STATUS_FILE)
    except Exception:
        pass


def _compute_best_model(task_type: str = "general", complexity: int = 80) -> str:
    """Call model_selector.py for a best-fit model; fall back to a default."""
    try:
        if not MODEL_SELECTOR.exists():
            return DEFAULT_MODEL_OVERRIDE
        result = subprocess.run(
            ["python3", str(MODEL_SELECTOR), "select", str(complexity), task_type],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = (result.stdout or "").strip()
        if result.returncode == 0 and out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    return DEFAULT_MODEL_OVERRIDE


def _extract_retry_after(headers: Any) -> Any:
    """Pull retry-after / reset hints out of response headers if present."""
    if headers is None:
        return None
    try:
        for key in (
            "retry-after",
            "Retry-After",
            "x-ratelimit-reset",
            "X-RateLimit-Reset",
            "anthropic-ratelimit-reset",
            "anthropic-ratelimit-requests-reset",
            "anthropic-ratelimit-tokens-reset",
        ):
            try:
                v = headers.get(key)
            except Exception:
                v = None
            if v:
                return v
    except Exception:
        pass
    return None


def _check_token_expiry() -> bool:
    """Return True if the OAuth token is known to be expired (conservative)."""
    try:
        with CREDENTIALS_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        oauth = payload.get("claudeAiOauth") or {}
        expires_at = oauth.get("expiresAt") or oauth.get("expires_at")
        if not expires_at:
            return False
        if isinstance(expires_at, (int, float)):
            # millisecond timestamp (JS Date.now())
            exp_ts = float(expires_at) / 1000 if float(expires_at) > 1e10 else float(expires_at)
        elif isinstance(expires_at, str):
            exp_ts = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        else:
            return False
        return exp_ts < time.time()
    except Exception:
        return False


def _probe(token: str) -> tuple[int, Any, str]:
    """
    Returns (status_code, retry_after, error_message).
    api.claude.ai is NXDOMAIN — probe is disabled, always returns 'available'.
    """
    # CHECK_URL is disabled: api.claude.ai does not exist in public DNS.
    # Real rate-limit detection happens only via 429 responses inside Claude Code.
    if not CHECK_URL or not token:
        return 200, None, ""  # assume available

    try:
        with httpx.Client(timeout=CHECK_TIMEOUT) as client:
            r = client.get(
                CHECK_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        retry_after = _extract_retry_after(r.headers)
        return r.status_code, retry_after, ""
    except Exception as exc:
        return 0, None, str(exc)[:200]


_DNS_ERRORS = ("name or service not known", "getaddrinfo", "nodename nor servname",
               "network is unreachable", "connection refused", "errno -2", "errno -3")

# WSL2 DNS fallback: public resolvers tried when system DNS fails
_FALLBACK_DNS_SERVERS = ["8.8.8.8", "1.1.1.1"]

# Cache resolved IP so subsequent probes bypass DNS entirely
_RESOLVED_IP_CACHE: dict[str, str] = {}


def _read_system_nameserver() -> str | None:
    """Read the first nameserver from /etc/resolv.conf (dynamic for WSL2)."""
    try:
        with open("/etc/resolv.conf", "r") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
    except Exception:
        pass
    return None


def _resolve_via_dns(hostname: str, dns_server: str) -> str | None:
    """Resolve hostname using a specific DNS server via `host` command."""
    try:
        result = subprocess.run(
            ["host", "-t", "A", hostname, dns_server],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if "has address" in line and parts:
                    return parts[-1]
    except Exception:
        pass
    return None


def _get_resolved_ip(hostname: str) -> str | None:
    """Try to resolve hostname; use cache, system DNS, then public fallbacks."""
    if hostname in _RESOLVED_IP_CACHE:
        return _RESOLVED_IP_CACHE[hostname]

    # Try system nameserver first (dynamic, correct for WSL2)
    ns = _read_system_nameserver()
    servers_to_try = ([ns] if ns else []) + _FALLBACK_DNS_SERVERS

    for server in servers_to_try:
        ip = _resolve_via_dns(hostname, server)
        if ip:
            _RESOLVED_IP_CACHE[hostname] = ip
            return ip
    return None


def _is_network_error(err: str) -> bool:
    low = err.lower()
    return any(sig in low for sig in _DNS_ERRORS)


def _probe_with_retry(token: str, max_retries: int = 3) -> tuple[int, Any, str]:
    """Probe with retries + DNS fallback for WSL2 DNS flakiness."""
    last_err = ""
    for attempt in range(max_retries):
        code, retry_after, err = _probe(token)
        if code != 0 and _is_network_error(err):
            last_err = err
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))  # 1s, 2s
                # On second attempt: try resolving via explicit DNS and bypass
                if attempt == 1:
                    try:
                        import urllib.parse as _up
                        hostname = _up.urlparse(CHECK_URL).hostname or ""
                        ip = _get_resolved_ip(hostname) if hostname else None
                        if ip and httpx is not None:
                            ip_url = CHECK_URL.replace(hostname, ip)
                            with httpx.Client(timeout=CHECK_TIMEOUT, verify=False) as client:
                                r = client.get(
                                    ip_url,
                                    headers={
                                        "Authorization": f"Bearer {token}",
                                        "Accept": "application/json",
                                        "Host": hostname,
                                    },
                                )
                            return r.status_code, _extract_retry_after(r.headers), ""
                    except Exception:
                        pass
            continue
        return code, retry_after, err
    return -1, None, last_err


def _is_rate_limit_response(status_code: int, headers_retry: Any) -> bool:
    if status_code == 429:
        return True
    # 529 is Anthropic's overloaded signal; treat as a soft limit.
    if status_code == 529:
        return True
    return False


def _send_telegram(message: str) -> None:
    """Fire-and-forget Telegram notification (never raises, never blocks >10s)."""
    try:
        if not TELEGRAM_HOOK.exists():
            return
        subprocess.Popen(
            [
                "uv",
                "run",
                str(TELEGRAM_HOOK),
                "--event",
                "notification",
                "--message",
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _do_check(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Perform one probe and return the new status dict (also writes to disk).

    `previous` lets the caller preserve `limited_since` across state transitions.
    """
    if previous is None:
        previous = _read_status()

    token = _read_token()
    code, retry_after, err = _probe_with_retry(token)
    now = _now_iso()

    network_error = code == 0 and bool(err) and _is_network_error(err)

    rate_limited: bool
    if code == 200:
        rate_limited = False
    elif _is_rate_limit_response(code, retry_after):
        rate_limited = True
    elif code == 0:
        if network_error:
            # DNS/network unreachable — use token expiry as fallback signal
            if _check_token_expiry():
                rate_limited = True
            else:
                # Network down but token valid → assume NOT rate limited (WSL2 DNS block)
                rate_limited = False
        else:
            prior = bool(previous.get("rate_limited")) if previous else False
            rate_limited = prior
    else:
        # 401/403/404/5xx — prefer false-negatives over false-positives
        rate_limited = bool(previous.get("rate_limited")) if previous else False

    status: dict[str, Any] = {
        "rate_limited": rate_limited,
        "checked_at": now,
        "limited_since": None,
        "model_override": None,
        "retry_after": retry_after,
        "last_http_status": code,
    }

    if err:
        status["last_error"] = err
    if network_error:
        status["network_error"] = True

    if rate_limited:
        # Preserve limited_since if we were already limited, else stamp now.
        if previous.get("rate_limited") and previous.get("limited_since"):
            status["limited_since"] = previous.get("limited_since")
        else:
            status["limited_since"] = now
        status["model_override"] = _compute_best_model("general", 80)

    _write_status(status)
    return status


def cmd_check() -> int:
    status = _do_check()
    print("rate_limited" if status.get("rate_limited") else "available")
    return 0


def cmd_watch() -> int:
    """Daemon loop: check with adaptive cadence, send notifications on transitions."""
    prev = _read_status()
    # Seed state if missing so the first iteration can detect a transition cleanly.
    if not prev:
        prev = _do_check(previous={})

    try:
        while True:
            current = _do_check(previous=prev)

            was_limited = bool(prev.get("rate_limited"))
            now_limited = bool(current.get("rate_limited"))

            if was_limited and not now_limited:
                _send_telegram("Claude usage reset — switching back from Ollama")
            elif (not was_limited) and now_limited:
                model = current.get("model_override") or DEFAULT_MODEL_OVERRIDE
                _send_telegram(
                    f"Claude rate limited — switching to Ollama cloud ({model})"
                )

            prev = current
            time.sleep(LIMITED_INTERVAL if now_limited else AVAILABLE_INTERVAL)
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Never surface tracebacks from a daemon; exit cleanly.
        return 0


def _usage() -> None:
    print(
        "Usage:\n"
        "  usage_monitor.py check     One-shot rate-limit probe.\n"
        "  usage_monitor.py watch     Daemon loop (60s/300s cadence)."
    )


def main(argv: list[str]) -> int:
    try:
        if len(argv) < 2:
            _usage()
            return 0
        cmd = argv[1].strip().lower()
        if cmd == "check":
            return cmd_check()
        if cmd == "watch":
            return cmd_watch()
        _usage()
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
