#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///
"""
Issue Notifier Hook

A Stop/PreCompact hook that scans the last 50 lines of the session transcript
for error patterns and sends a Telegram notification summarising any issues.

Patterns detected:
- Non-zero exit codes (e.g., "exit code 1", "exited with 2")
- Common error markers: "Error:", "Failed:", "Exception:", "Traceback"

Behavior:
- Always exits 0 (never blocks the parent event chain).
- Silent exit when no issues are found.
- Writes diagnostic logs to ~/.claude/logs/ (never the caller's cwd).
- Full try/except around every I/O path.
"""

from __future__ import annotations
__version__ = "2026.04.20.3"

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


LOG_DIR = Path.home() / '.claude' / 'logs'
LOG_FILE = LOG_DIR / 'issue_notifier.jsonl'

# Case-insensitive regex patterns for issue detection
ISSUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('exit_code_nonzero', re.compile(r'\bexit(?:\s*code)?\s*[:=]?\s*([1-9]\d*)', re.IGNORECASE)),
    ('exited_with', re.compile(r'exited\s+with\s+(?:code\s+)?([1-9]\d*)', re.IGNORECASE)),
    ('error_marker', re.compile(r'\bError:', re.IGNORECASE)),
    ('failed_marker', re.compile(r'\bFailed:', re.IGNORECASE)),
    ('exception_marker', re.compile(r'\bException:', re.IGNORECASE)),
    ('traceback_marker', re.compile(r'\bTraceback\b', re.IGNORECASE)),
]


def _safe_log(entry: dict) -> None:
    """Append a diagnostic log entry. Silent on failure."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _read_last_lines(path: str, n: int = 50) -> list[str]:
    """Return the last N lines of a text file; empty list on any failure."""
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return []
        # Simple approach — transcripts are JSONL and usually reasonable in size
        with p.open('r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


def _extract_text_from_transcript_line(line: str) -> str:
    """Each transcript line is a JSON object. Flatten into scannable text."""
    try:
        obj = json.loads(line)
    except Exception:
        return line  # fall back to raw
    try:
        # Common structured shapes in Claude Code transcripts
        pieces: list[str] = []
        msg = obj.get('message') if isinstance(obj, dict) else None
        if isinstance(msg, dict):
            content = msg.get('content')
            if isinstance(content, str):
                pieces.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        t = c.get('text') or c.get('content') or ''
                        if isinstance(t, str):
                            pieces.append(t)
        # tool_use_result-like shapes
        if isinstance(obj, dict):
            for key in ('error', 'stderr', 'stdout', 'output', 'result'):
                v = obj.get(key)
                if isinstance(v, str):
                    pieces.append(v)
        if not pieces:
            return json.dumps(obj, ensure_ascii=False)
        return '\n'.join(pieces)
    except Exception:
        return line


def scan_for_issues(lines: list[str]) -> list[dict]:
    """Scan lines for issue patterns; return a list of findings."""
    findings: list[dict] = []
    for i, raw in enumerate(lines):
        try:
            text = _extract_text_from_transcript_line(raw)
            for name, pat in ISSUE_PATTERNS:
                m = pat.search(text)
                if m:
                    # Capture a short snippet around the match
                    start = max(0, m.start() - 40)
                    end = min(len(text), m.end() + 120)
                    snippet = text[start:end].replace('\n', ' ').strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + '…'
                    findings.append({
                        'pattern': name,
                        'match': m.group(0),
                        'snippet': snippet,
                        'line_offset': i,
                    })
                    break  # one finding per transcript line is enough
        except Exception:
            continue
    return findings


def build_summary(findings: list[dict], project_name: str, session_id: str) -> str:
    """Format a concise Telegram summary of the findings."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = "\u26a0\ufe0f <b>Session Issues Detected</b>"
    meta = (
        f"<b>Project:</b> {project_name}\n"
        f"<b>Session:</b> <code>{session_id[:8]}</code>\n"
        f"<b>Time:</b> {ts}\n"
        f"<b>Findings:</b> {len(findings)}"
    )

    # Show up to 5 findings; collapse duplicates by pattern
    seen: set[str] = set()
    shown: list[dict] = []
    for f in findings:
        key = f.get('pattern', '') + '|' + f.get('match', '')
        if key in seen:
            continue
        seen.add(key)
        shown.append(f)
        if len(shown) >= 5:
            break

    items = []
    for f in shown:
        items.append(f"\u2022 <b>{f['pattern']}</b>: <code>{f['snippet']}</code>")
    body = '\n'.join(items) if items else '(no details)'

    return f"{header}\n{meta}\n\n{body}"


def send_telegram(message: str) -> None:
    """Invoke telegram_notify.py to deliver the message. Never blocks."""
    try:
        script = Path.home() / '.claude' / 'hooks' / 'telegram_notify.py'
        if not script.exists():
            return
        uv = Path.home() / '.local' / 'bin' / 'uv'
        subprocess.run(
            [
                str(uv),
                'run',
                str(script),
                '--event', 'error',
                '--message', message,
            ],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ''
        input_data: dict = {}
        if raw.strip():
            try:
                input_data = json.loads(raw)
            except Exception:
                input_data = {}

        transcript_path = str(input_data.get('transcript_path', '') or '')
        session_id = str(input_data.get('session_id', '') or 'unknown')
        cwd = str(input_data.get('cwd', '') or os.environ.get('CLAUDE_PROJECT_DIR', '') or '')
        project_name = Path(cwd).name if cwd else 'unknown'

        lines = _read_last_lines(transcript_path, 50)
        if not lines:
            # Nothing to scan — exit silently.
            return 0

        findings = scan_for_issues(lines)
        if not findings:
            return 0

        message = build_summary(findings, project_name, session_id)
        send_telegram(message)

        _safe_log({
            'timestamp': datetime.now().isoformat(),
            'session_id': session_id,
            'project': project_name,
            'finding_count': len(findings),
            'findings': findings[:10],
        })
        return 0
    except Exception as e:
        _safe_log({
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
        })
        return 0


if __name__ == '__main__':
    sys.exit(main())
