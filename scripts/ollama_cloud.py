#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///

"""
ollama_cloud.py - Helper that authenticates with Ollama's cloud API.

Commands:
    models                 List cloud models (one per line)
    info <model>           Show model metadata (name, parameter_size, context_length)
    status                 Print `cloud` / `local` / `unavailable` (always exit 0)
    chat <model> <prompt> [--timeout SEC]
                           One-shot chat completion (default 60s, 180s for large models)
    parallel               Fan-out multiple chat requests concurrently.
                           Stdin: JSON array of {"model", "prompt", "id"}.
                           Stdout: JSON array of {"id", "model", "response", "error"}.

The default endpoint is https://api.ollama.com, but the OLLAMA_API_BASE env var
overrides it. Auth uses `Authorization: Bearer $OLLAMA_API_KEY`.

All HTTP calls use timeout=10s (chat uses 60s (180s for large models) via _default_timeout_for_model()) and are wrapped in try/except;
the script exits 0 even on failure so callers (status line, skills, etc.) stay
resilient.
"""

from __future__ import annotations
__version__ = "2026.04.20.2"

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
DEFAULT_CLOUD_BASE = "https://api.ollama.com"
DATA_DIR = Path.home() / ".claude" / "data"
MODELS_CACHE = DATA_DIR / "ollama_models_cache.json"
MODELS_CACHE_TTL = 3600  # 1 hour
MODEL_INFO_TTL = 6 * 3600  # 6 hours
HTTP_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _api_base() -> str:
    try:
        env_base = (os.environ.get("OLLAMA_API_BASE") or "").strip()
        if env_base:
            return env_base.rstrip("/")
    except Exception:
        pass
    return DEFAULT_CLOUD_BASE


def _api_key() -> str:
    try:
        return (os.environ.get("OLLAMA_API_KEY") or "").strip()
    except Exception:
        return ""


def _auth_headers() -> dict[str, str]:
    key = _api_key()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _read_cache(path: Path, ttl: float) -> Any | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return None
        cached_at = float(payload.get("cached_at") or 0)
        if time.time() - cached_at > ttl:
            return None
        return payload.get("data")
    except Exception:
        return None


def _write_cache(path: Path, data: Any) -> None:
    try:
        _ensure_data_dir()
        payload = {"cached_at": time.time(), "data": data}
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(path)
    except Exception:
        pass


def _safe_model_slug(model: str) -> str:
    """Convert a model id into a filename-safe slug for the info cache."""
    try:
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in model)
    except Exception:
        return "unknown"


def _model_info_cache_path(model: str) -> Path:
    return DATA_DIR / f"ollama_model_info_{_safe_model_slug(model)}.json"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_models() -> int:
    """GET /api/tags. Print model names, cache for 1h."""
    try:
        cached = _read_cache(MODELS_CACHE, MODELS_CACHE_TTL)
        if cached is not None:
            names = _extract_model_names(cached)
            for n in names:
                print(n)
            return 0

        if httpx is None:
            return 0

        url = f"{_api_base()}/api/tags"
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                r = client.get(url, headers=_auth_headers())
            if r.status_code != 200:
                return 0
            payload = r.json()
        except Exception:
            return 0

        _write_cache(MODELS_CACHE, payload)
        names = _extract_model_names(payload)
        for n in names:
            print(n)
        return 0
    except Exception:
        return 0


def _extract_model_names(payload: Any) -> list[str]:
    try:
        if not isinstance(payload, dict):
            return []
        models = payload.get("models")
        if not isinstance(models, list):
            return []
        out: list[str] = []
        for m in models:
            if isinstance(m, dict):
                name = m.get("name") or m.get("model")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip())
            elif isinstance(m, str) and m.strip():
                out.append(m.strip())
        return out
    except Exception:
        return []


def cmd_info(model: str) -> int:
    """POST /api/show with {"model": ...}. Print name, parameter_size, context_length."""
    try:
        cache_path = _model_info_cache_path(model)
        cached = _read_cache(cache_path, MODEL_INFO_TTL)
        payload: Any = cached

        if payload is None:
            if httpx is None:
                return 0
            url = f"{_api_base()}/api/show"
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.post(
                        url,
                        headers=_auth_headers(),
                        json={"model": model},
                    )
                if r.status_code != 200:
                    return 0
                payload = r.json()
            except Exception:
                return 0
            _write_cache(cache_path, payload)

        name, parameter_size, context_length = _extract_model_info(payload, model)
        print(f"name: {name}")
        print(f"parameter_size: {parameter_size}")
        print(f"context_length: {context_length}")
        return 0
    except Exception:
        return 0


def _extract_model_info(payload: Any, fallback_name: str) -> tuple[str, str, str]:
    """Return (name, parameter_size, context_length) as best-effort strings."""
    name = fallback_name
    parameter_size = "unknown"
    context_length = "unknown"
    try:
        if not isinstance(payload, dict):
            return name, parameter_size, context_length

        # Name may live at top level, details, or model_info.
        for key in ("name", "model"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                name = v.strip()
                break

        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}

        # parameter_size: details.parameter_size OR model_info.<arch>.parameter_count
        ps = details.get("parameter_size") if isinstance(details, dict) else None
        if isinstance(ps, str) and ps.strip():
            parameter_size = ps.strip()
        elif isinstance(model_info, dict):
            for k, v in model_info.items():
                if isinstance(k, str) and k.endswith(".parameter_count") and v is not None:
                    parameter_size = str(v)
                    break

        # context_length: top-level, details, model_info.<arch>.context_length
        ctx: Any = None
        for source in (payload, details, model_info):
            if not isinstance(source, dict):
                continue
            if "context_length" in source and source["context_length"] is not None:
                ctx = source["context_length"]
                break
            for k, v in source.items():
                if isinstance(k, str) and k.endswith(".context_length") and v is not None:
                    ctx = v
                    break
            if ctx is not None:
                break
        if ctx is not None:
            try:
                context_length = str(int(ctx))
            except Exception:
                context_length = str(ctx)
        return name, parameter_size, context_length
    except Exception:
        return name, parameter_size, context_length


def cmd_status() -> int:
    """Print `cloud` / `local` / `unavailable`. Always exit 0."""
    try:
        env_base = (os.environ.get("OLLAMA_API_BASE") or "").strip()
        has_key = bool(_api_key())

        # Cloud if API key is set and base (when set) points at a non-localhost host.
        if has_key:
            base_for_check = env_base or DEFAULT_CLOUD_BASE
            if not _is_localhost(base_for_check):
                if _probe_cloud(base_for_check):
                    print("cloud")
                    return 0

        # Local if OLLAMA_API_BASE looks like localhost.
        if env_base and _is_localhost(env_base):
            print("local")
            return 0

        print("unavailable")
        return 0
    except Exception:
        try:
            print("unavailable")
        except Exception:
            pass
        return 0


def _is_localhost(url: str) -> bool:
    try:
        low = url.lower()
        return "localhost" in low or "127.0.0.1" in low or "://0.0.0.0" in low
    except Exception:
        return False


def _probe_cloud(base: str) -> bool:
    """GET <base>/ with auth. Treat any 2xx/401/403 response as 'reachable'."""
    if httpx is None:
        # Without httpx we can't probe, but we still treat a configured key as 'cloud'.
        return True
    try:
        url = f"{base.rstrip('/')}/"
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(url, headers=_auth_headers())
        # Cloud endpoint may return 200, 401 (bad/expired key still proves reachability),
        # or 404 on the bare root. Any HTTP response counts as "cloud reachable".
        return 200 <= r.status_code < 600
    except Exception:
        return False


def _default_timeout_for_model(model: str) -> float:
    """Heuristic: large models get 180s, small models get 60s."""
    try:
        low = (model or "").lower()
        # Large-parameter markers (1t, 405b, 480b, 675b, 235b, 120b, 80b, 70b, 72b).
        if any(tag in low for tag in ("1t", "405b", "480b", "675b", "235b", "120b", "80b", "70b", "72b")):
            return 180.0
        # Explicit cloud-only flagship models.
        if any(tag in low for tag in ("kimi-k2", "deepseek-v3", "mistral-large", "qwen3-coder:480b")):
            return 180.0
        return 60.0
    except Exception:
        return 60.0


def cmd_chat(model: str, prompt: str, timeout: float | None = None) -> int:
    """POST /api/chat with a single user message. Print assistant reply text.

    On timeout or HTTP failure, print a JSON error blob to stdout so callers
    can detect and handle it programmatically.
    """
    effective_timeout = float(timeout) if timeout is not None else _default_timeout_for_model(model)
    try:
        if httpx is None:
            print(json.dumps({"error": "httpx_missing", "model": model, "elapsed": effective_timeout}))
            return 0
        url = f"{_api_base()}/api/chat"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            with httpx.Client(timeout=effective_timeout) as client:
                r = client.post(url, headers=_auth_headers(), json=body)
            if r.status_code != 200:
                print(json.dumps({
                    "error": f"http_{r.status_code}",
                    "model": model,
                    "elapsed": effective_timeout,
                }))
                return 0
            payload = r.json()
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "timeout" in name:
                print(json.dumps({"error": "timeout", "model": model, "elapsed": effective_timeout}))
            else:
                print(json.dumps({
                    "error": f"request_failed:{type(exc).__name__}",
                    "model": model,
                    "elapsed": effective_timeout,
                }))
            return 0

        text = _extract_chat_text(payload)
        if text:
            print(text)
        return 0
    except Exception:
        try:
            print(json.dumps({"error": "unknown", "model": model, "elapsed": effective_timeout}))
        except Exception:
            pass
        return 0


def cmd_parallel() -> int:
    """Fan-out multiple chat requests concurrently.

    Stdin: JSON array of {"model", "prompt", "id"}.
    Stdout: JSON array of {"id", "model", "response", "error"}.
    Uses ThreadPoolExecutor with max_workers=5, per-task timeout=120s.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        print(json.dumps([]))
        return 0

    try:
        tasks = json.loads(raw) if raw.strip() else []
    except Exception:
        print(json.dumps([]))
        return 0

    if not isinstance(tasks, list) or not tasks:
        print(json.dumps([]))
        return 0

    # Normalize and collect valid tasks.
    normalized: list[dict[str, str]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        model = str(t.get("model") or "").strip()
        prompt = str(t.get("prompt") or "")
        tid = str(t.get("id") or "") or model
        if not model:
            continue
        normalized.append({"id": tid, "model": model, "prompt": prompt})

    if not normalized:
        print(json.dumps([]))
        return 0

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
    except Exception:
        print(json.dumps([]))
        return 0

    def _one_call(task: dict[str, str]) -> dict[str, Any]:
        model = task["model"]
        prompt = task["prompt"]
        tid = task["id"]
        result: dict[str, Any] = {"id": tid, "model": model, "response": None, "error": None}
        if httpx is None:
            result["error"] = "httpx_missing"
            return result
        try:
            url = f"{_api_base()}/api/chat"
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            with httpx.Client(timeout=_default_timeout_for_model(model)) as client:
                r = client.post(url, headers=_auth_headers(), json=body)
            if r.status_code != 200:
                result["error"] = f"http_{r.status_code}"
                return result
            payload = r.json()
            text = _extract_chat_text(payload)
            result["response"] = text
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "timeout" in name:
                result["error"] = "timeout"
            else:
                result["error"] = f"request_failed:{type(exc).__name__}"
        return result

    results: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {pool.submit(_one_call, t): t for t in normalized}
            for fut in as_completed(future_map, timeout=150.0):
                try:
                    results.append(fut.result(timeout=125.0))
                except Exception as exc:
                    src = future_map.get(fut, {})
                    results.append({
                        "id": src.get("id", ""),
                        "model": src.get("model", ""),
                        "response": None,
                        "error": f"future_failed:{type(exc).__name__}",
                    })
    except Exception:
        # Partial results still useful.
        pass

    try:
        print(json.dumps(results))
    except Exception:
        print("[]")
    return 0


def _extract_chat_text(payload: Any) -> str:
    try:
        if not isinstance(payload, dict):
            return ""
        msg = payload.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                return content
        # Fallback: some variants return `response` at the top level.
        resp = payload.get("response")
        if isinstance(resp, str):
            return resp
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _usage() -> None:
    print(
        "Usage:\n"
        "  ollama_cloud.py models\n"
        "  ollama_cloud.py info <model>\n"
        "  ollama_cloud.py status\n"
        "  ollama_cloud.py chat <model> <prompt> [--timeout SEC]\n"
        "  ollama_cloud.py parallel     # stdin: JSON array of {model, prompt, id}"
    )


def _parse_chat_args(rest: list[str]) -> tuple[str, str, float | None]:
    """Extract model, prompt, and optional --timeout from the chat args."""
    model = rest[0]
    timeout: float | None = None
    tokens: list[str] = []
    i = 1
    while i < len(rest):
        tok = rest[i]
        if tok == "--timeout" and i + 1 < len(rest):
            try:
                timeout = float(rest[i + 1])
            except Exception:
                timeout = None
            i += 2
            continue
        if tok.startswith("--timeout="):
            try:
                timeout = float(tok.split("=", 1)[1])
            except Exception:
                timeout = None
            i += 1
            continue
        tokens.append(tok)
        i += 1
    prompt = " ".join(tokens)
    return model, prompt, timeout


def main(argv: list[str]) -> int:
    try:
        if len(argv) < 2:
            _usage()
            return 0
        cmd = argv[1].strip().lower()

        if cmd == "models":
            return cmd_models()
        if cmd == "status":
            return cmd_status()
        if cmd == "info":
            if len(argv) < 3:
                _usage()
                return 0
            return cmd_info(argv[2])
        if cmd == "chat":
            if len(argv) < 4:
                _usage()
                return 0
            model, prompt, timeout = _parse_chat_args(argv[2:])
            return cmd_chat(model, prompt, timeout)
        if cmd == "parallel":
            return cmd_parallel()

        _usage()
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
