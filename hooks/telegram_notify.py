#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
Telegram Notification Hook for Claude Code
Sends progress updates, completions, and alerts to Telegram.

Setup:
1. Get bot token from @BotFather on Telegram
2. Get your chat ID by messaging @userinfobot
3. Set in .claude/telegram.config:
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id

Or set as environment variables.

Can also receive screenshots: pass --screenshot /path/to/file.png
"""
__version__ = "2026.04.20.4"

import sys
import json
import os
import argparse
from pathlib import Path
from datetime import datetime

# Config file location
# User-level config is primary; a project-level override is checked if CLAUDE_PROJECT_DIR is set.
CONFIG_FILE = Path.home() / '.claude' / 'telegram.config'
_project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '')
# Fallback to user config path when no project dir is set (harmless duplicate).
PROJECT_CONFIG = (
    Path(_project_dir) / '.claude' / 'telegram.config'
    if _project_dir
    else CONFIG_FILE
)


def load_config():
    """Load Telegram credentials from config file or environment."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    # Accept both TELEGRAM_ADMIN_CHAT_ID (preferred) and TELEGRAM_CHAT_ID (legacy)
    chat_id = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '') or os.environ.get('TELEGRAM_CHAT_ID', '')

    for cfg_path in [PROJECT_CONFIG, CONFIG_FILE]:
        if cfg_path.exists():
            for line in cfg_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip()
                if k == 'TELEGRAM_BOT_TOKEN' and not token:
                    token = v
                elif k in ('TELEGRAM_ADMIN_CHAT_ID', 'TELEGRAM_CHAT_ID') and not chat_id:
                    chat_id = v
            break

    return token, chat_id


def send_message(token: str, chat_id: str, text: str, parse_mode: str = 'HTML') -> bool:
    """Send a text message to Telegram."""
    try:
        import httpx  # type: ignore[import-not-found]
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        resp = httpx.post(url, json={
            'chat_id': chat_id,
            'text': text[:4096],  # Telegram limit
            'parse_mode': parse_mode,
            'disable_web_page_preview': True,
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f'Telegram send error: {e}', file=sys.stderr)
        return False


def send_photo(token: str, chat_id: str, photo_path: str, caption: str = '') -> bool:
    """Send a photo to Telegram."""
    try:
        import httpx  # type: ignore[import-not-found]
        url = f'https://api.telegram.org/bot{token}/sendPhoto'
        with open(photo_path, 'rb') as f:
            resp = httpx.post(url, data={
                'chat_id': chat_id,
                'caption': caption[:1024],
            }, files={'photo': f}, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        print(f'Telegram photo error: {e}', file=sys.stderr)
        return False


def extract_summary(transcript_path: str, max_chars: int = 300) -> str:
    """Extract last assistant text message from transcript as summary."""
    try:
        if not transcript_path or not Path(transcript_path).exists():
            return ''
        lines = Path(transcript_path).read_text().splitlines()
        for line in reversed(lines):
            try:
                d = json.loads(line)
                if d.get('type') == 'assistant':
                    for c in d.get('message', {}).get('content', []):
                        if isinstance(c, dict) and c.get('type') == 'text':
                            text = c.get('text', '').strip()
                            if text and text != 'BRIDGE_TEST_OK':
                                # Strip markdown headers/bold for clean preview
                                import re
                                text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
                                text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
                                text = text.strip()
                                if len(text) > max_chars:
                                    text = text[:max_chars].rsplit(' ', 1)[0] + '…'
                                return text
            except Exception:
                continue
    except Exception:
        pass
    return ''


def save_last_session(session_id: str, cwd: str) -> None:
    """Save last session info so telegram bridge can offer resume on reply."""
    try:
        state_file = Path.home() / '.claude-telegram' / 'last_session.json'
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({
            'session_id': session_id,
            'cwd': cwd,
            'ts': datetime.now().isoformat(),
        }))
    except Exception:
        pass


def format_stop_message(hook_data: dict) -> str:
    """Format a task completion message with summary and follow-up hint."""
    ts = datetime.now().strftime('%H:%M')
    stop_reason = hook_data.get('stop_reason', 'end_turn')
    session_id = hook_data.get('session_id', '')
    session_short = session_id[:8]
    transcript_path = hook_data.get('transcript_path', '')

    # Derive project name from transcript_path (most reliable - always present in Stop hook)
    # Pattern: /home/.../.claude/projects/-mnt-d-Projects-PROJECTNAME/session.jsonl
    project_name = 'Unknown Project'
    if transcript_path:
        folder = Path(transcript_path).parent.name
        parts = folder.split('-')
        try:
            idx = next(i for i, p in enumerate(parts) if p.lower() == 'projects')
            raw = '-'.join(parts[idx + 1:])
        except StopIteration:
            raw = parts[-1] if parts else ''
        if raw:
            project_name = raw
    if project_name == 'Unknown Project':
        cwd = os.environ.get('CLAUDE_PROJECT_DIR', '') or os.getcwd()
        project_name = Path(cwd).name if cwd else 'Unknown Project'

    # Save for bridge resume
    cwd = os.environ.get('CLAUDE_PROJECT_DIR', '') or os.getcwd()
    save_last_session(session_id, cwd)

    # Extract summary from transcript
    summary = extract_summary(transcript_path)

    emoji = '\u2705' if stop_reason == 'end_turn' else '\u23f8\ufe0f'
    msg = (
        f'{emoji} <b>Claude Code \u2014 Task Complete</b>\n'
        f'<code>{ts}</code> | Session <code>{session_short}</code>\n'
        f'Reason: {stop_reason}\n'
        f'\U0001f4cd {project_name}'
    )
    if summary:
        msg += f'\n\n\U0001f4ac <i>{summary}</i>'
    msg += '\n\n\U0001f501 <i>Stuur een bericht om verder te gaan met deze sessie</i>'
    return msg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', help='Path to screenshot to send')
    parser.add_argument('--message', help='Custom message to send')
    parser.add_argument('--event', default='stop', help='Hook event type')
    args = parser.parse_args()

    token, chat_id = load_config()
    if not token or not chat_id:
        # Not configured yet - silent exit
        sys.exit(0)

    # Read hook data from stdin if available
    hook_data = {}
    if not sys.stdin.isatty():
        try:
            hook_data = json.loads(sys.stdin.read())
        except Exception:
            pass

    if args.screenshot and Path(args.screenshot).exists():
        caption = args.message or f'Screenshot \u2014 {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        send_photo(token, chat_id, args.screenshot, caption)
    elif args.message:
        send_message(token, chat_id, f'\U0001f916 <b>Claude Code</b>\n{args.message}')
    else:
        msg = format_stop_message(hook_data)
        send_message(token, chat_id, msg)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
