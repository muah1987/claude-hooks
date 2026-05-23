#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
__version__ = "2026.04.21.1"
WSL2 DNS diagnostic + fallback configurator.

Tests DNS resolution and HTTP connectivity, then optionally
patches /etc/resolv.conf to use Cloudflare (1.1.1.1 / 1.0.0.1).

Usage:
  test_dns.py              # run diagnostics only
  test_dns.py --fix        # run diagnostics + patch resolv.conf
  test_dns.py --check      # quick pass/fail check (exit 0 = ok)
"""
__version__ = "2026.04.21.1"
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

FALLBACK_DNS = ["1.1.1.1", "1.0.0.1"]  # Cloudflare
RESOLV_CONF = Path("/etc/resolv.conf")

TEST_HOSTS = [
    "api.claude.ai",
    "claude.ai",
    "google.com",
    "1.1.1.1",
]

TEST_URLS = [
    ("https://1.1.1.1/dns-query", {"name": "google.com", "type": "A"}),  # DoH fallback
    ("https://cloudflare-dns.com/dns-query", {"name": "api.claude.ai", "type": "A"}),
]


# ── DNS resolution test ────────────────────────────────────────────────────

def test_resolve(host: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        start = time.monotonic()
        addr = socket.getaddrinfo(host, None, socket.AF_INET, proto=socket.IPPROTO_TCP)
        elapsed = time.monotonic() - start
        ip = addr[0][4][0] if addr else "?"
        return True, f"{ip} ({elapsed*1000:.0f}ms)"
    except socket.gaierror as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def test_http(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    if not HAS_HTTPX:
        return False, "httpx not available"
    try:
        start = time.monotonic()
        r = httpx.get(url, timeout=timeout, follow_redirects=False)
        elapsed = time.monotonic() - start
        return True, f"HTTP {r.status_code} ({elapsed*1000:.0f}ms)"
    except Exception as e:
        return False, str(e)[:80]


# ── resolv.conf inspection ─────────────────────────────────────────────────

def read_resolv_conf() -> list[str]:
    try:
        lines = RESOLV_CONF.read_text().splitlines()
        return [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    except Exception:
        return []


def current_nameservers() -> list[str]:
    return [
        l.split()[1] for l in read_resolv_conf()
        if l.startswith("nameserver") and len(l.split()) >= 2
    ]


def patch_resolv_conf() -> bool:
    try:
        existing = RESOLV_CONF.read_text() if RESOLV_CONF.exists() else ""
        non_ns_lines = [l for l in existing.splitlines() if not l.strip().startswith("nameserver")]
        new_lines = (
            ["# Patched by test_dns.py — Cloudflare fallback DNS"]
            + [f"nameserver {ns}" for ns in FALLBACK_DNS]
            + non_ns_lines
        )
        new_content = "\n".join(new_lines) + "\n"

        # Write via sudo
        result = subprocess.run(
            ["sudo", "tee", str(RESOLV_CONF)],
            input=new_content, capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  patch failed: {e}", file=sys.stderr)
        return False


def make_resolv_immutable() -> bool:
    """chattr +i prevents WSL from overwriting resolv.conf on restart."""
    try:
        result = subprocess.run(
            ["sudo", "chattr", "+i", str(RESOLV_CONF)],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


# ── wsl.conf check ─────────────────────────────────────────────────────────

def check_wsl_conf() -> str:
    try:
        wsl_conf = Path("/etc/wsl.conf")
        if not wsl_conf.exists():
            return "missing — WSL auto-generates resolv.conf on restart"
        content = wsl_conf.read_text()
        if "generateResolvConf = false" in content or "generateResolvConf=false" in content:
            return "generateResolvConf=false ✓ (resolv.conf won't be overwritten)"
        return "generateResolvConf not set — WSL may overwrite resolv.conf on restart"
    except Exception:
        return "cannot read"


def suggest_wsl_conf_fix() -> str:
    return (
        "To permanently fix WSL2 DNS:\n"
        "  1. sudo nano /etc/wsl.conf\n"
        "  2. Add:\n"
        "       [network]\n"
        "       generateResolvConf = false\n"
        "  3. Run: wsl --shutdown  (from Windows PowerShell)\n"
        "  4. Restart WSL2\n"
        "  This prevents WSL from overwriting /etc/resolv.conf on each start."
    )


# ── Main ───────────────────────────────────────────────────────────────────

def run_diagnostics(verbose: bool = True) -> dict:
    results: dict = {"dns": {}, "http": {}, "nameservers": [], "wsl_conf": ""}

    if verbose:
        print("=== WSL2 DNS Diagnostic ===\n")

    # Current nameservers
    ns = current_nameservers()
    results["nameservers"] = ns
    if verbose:
        print(f"Current nameservers: {ns or ['none found']}")
        print()

    # DNS resolution tests
    if verbose:
        print("DNS resolution:")
    dns_ok_count = 0
    for host in TEST_HOSTS:
        ok, msg = test_resolve(host)
        results["dns"][host] = {"ok": ok, "msg": msg}
        if ok:
            dns_ok_count += 1
        if verbose:
            status = "✓" if ok else "✗"
            print(f"  {status} {host:<30} {msg}")

    if verbose:
        print()
        print("HTTP connectivity:")
    http_ok = False
    for url, _ in TEST_URLS:
        ok, msg = test_http(url)
        results["http"][url] = {"ok": ok, "msg": msg}
        if ok:
            http_ok = True
        if verbose:
            status = "✓" if ok else "✗"
            print(f"  {status} {url:<50} {msg}")

    # WSL conf
    wsl_conf_status = check_wsl_conf()
    results["wsl_conf"] = wsl_conf_status
    if verbose:
        print()
        print(f"wsl.conf: {wsl_conf_status}")

    # Summary
    results["overall_ok"] = dns_ok_count >= 2  # at least 2 hosts resolve
    if verbose:
        print()
        if results["overall_ok"]:
            print("✓ DNS is working (≥2 hosts resolved)")
        else:
            print("✗ DNS is NOT working — most hosts failed to resolve")
            print()
            if FALLBACK_DNS[0] not in ns:
                print(f"Recommendation: switch to Cloudflare DNS ({', '.join(FALLBACK_DNS)})")
                print("Run:  python3 test_dns.py --fix")
            print()
            print(suggest_wsl_conf_fix())

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="WSL2 DNS diagnostic + Cloudflare fallback fixer")
    parser.add_argument("--fix", action="store_true", help="Patch /etc/resolv.conf to use Cloudflare DNS")
    parser.add_argument("--immutable", action="store_true", help="Also chattr +i resolv.conf after patching")
    parser.add_argument("--check", action="store_true", help="Quick pass/fail (exit 0=ok, 1=broken)")
    args = parser.parse_args()

    if args.check:
        ok, _ = test_resolve("google.com")
        sys.exit(0 if ok else 1)

    results = run_diagnostics(verbose=True)

    if args.fix:
        print("\n=== Applying Fix: Cloudflare DNS ===")
        ns_before = current_nameservers()
        print(f"Before: {ns_before}")

        ok = patch_resolv_conf()
        if ok:
            print(f"After:  {current_nameservers()}")
            print("✓ /etc/resolv.conf patched")
        else:
            print("✗ Failed to patch resolv.conf — try running with sudo")
            sys.exit(1)

        if args.immutable:
            imm = make_resolv_immutable()
            print(f"chattr +i: {'✓ applied' if imm else '✗ failed'}")

        print()
        print("Re-testing after patch:")
        run_diagnostics(verbose=True)

        print()
        if "generateResolvConf = false" not in Path("/etc/wsl.conf").read_text() if Path("/etc/wsl.conf").exists() else True:
            print(suggest_wsl_conf_fix())

    sys.exit(0 if results["overall_ok"] else 1)


if __name__ == "__main__":
    main()
