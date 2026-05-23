#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
SessionStart hook — Launch Telegram Bridge
Starts the bidirectional Telegram ↔ Claude Code CLI bridge on every boot.
Kills any stale bridge process first, then starts fresh.

Registered in settings.json under SessionStart hooks.
"""
__version__ = "2026.04.20.4"

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Resolve project dir from env (set by the Claude Code harness) with cwd fallback.
PROJECT_DIR   = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
CLAUDE_DIR    = Path.home() / '.claude'
PID_FILE      = CLAUDE_DIR / 'data' / 'telegram_bridge.pid'
BRIDGE_SCRIPT = CLAUDE_DIR / 'scripts' / 'telegram_bridge.py'
LOG_FILE      = CLAUDE_DIR / 'logs' / 'telegram_bridge.log'

# Resolve `uv` from PATH, with a $HOME-based fallback if not on PATH.
UV_BIN = shutil.which('uv') or str(Path.home() / '.local' / 'bin' / 'uv')


def _load_token() -> str:
    cfg_path = CLAUDE_DIR / 'telegram.config'
    if cfg_path.exists():
        for line in cfg_path.read_text().splitlines():
            line = line.strip()
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                return line.split('=', 1)[1].strip()
    return os.environ.get('TELEGRAM_BOT_TOKEN', '')


def _clear_webhook():
    """Delete any active webhook so long-polling works."""
    token = _load_token()
    if not token:
        return
    try:
        url = f'https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=false'
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


def main():
    # Drain any stdin payload from the harness but ignore its contents —
    # this hook does not branch on SessionStart `source`.
    if not sys.stdin.isatty():
        try:
            _ = sys.stdin.read()
        except Exception:
            pass

    # Always clear webhook so polling bridge works
    _clear_webhook()

    # Kill any stale bridge
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Check if running
            # Already running — leave it alone
            print(json.dumps({
                'hookSpecificOutput': {
                    'hookEventName': 'SessionStart',
                    'additionalContext': f'Telegram bridge already running (PID {pid})'
                }
            }))
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            # Stale PID — clean up
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # Start the bridge
    if not BRIDGE_SCRIPT.exists():
        print(json.dumps({
            'hookSpecificOutput': {
                'hookEventName': 'SessionStart',
                'additionalContext': 'WARNING: Telegram bridge script not found'
            }
        }))
        sys.exit(0)

    with open(LOG_FILE, 'a') as log:
        proc = subprocess.Popen(
            [UV_BIN, 'run', str(BRIDGE_SCRIPT)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(PROJECT_DIR),
        )

    import time
    time.sleep(1)

    if proc.poll() is None:
        try:
            PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(proc.pid))
        except Exception:
            pass
        context = f'Telegram bridge started (PID {proc.pid}) — bidirectional chat active on @muah1987_bot'
    else:
        context = 'WARNING: Telegram bridge failed to start'

    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'SessionStart',
            'additionalContext': context
        }
    }))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never block Claude on a bridge-launch failure.
        sys.exit(0)
