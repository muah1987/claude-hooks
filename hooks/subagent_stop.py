#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
# ]
# ///

"""
SubagentStop Hook - GOTCHA Framework Integration (Lean Edition)

This hook runs when a Claude Code subagent finishes responding. It:

1. Logs subagent completion to ~/.claude/logs/subagent_stop.jsonl
2. Extracts a result summary from the subagent transcript
3. Appends an entry to ~/.claude/data/agent_registry.jsonl
4. Optionally announces completion via TTS (--notify)
5. Optionally runs the trigger engine (--trigger)
6. Optionally assesses output quality via CCE (--cognitive)

Design goals:
- Always exits 0 — never blocks the harness
- Writes results to ~/.claude/ (never to project directories)
- Fast and lean — short timeouts, no lock systems, no retries
- All optional features are wrapped in try/except ImportError and fail open

Input JSON schema (from stdin):
- session_id: Current session identifier
- agent_id: Unique identifier for the subagent
- agent_type: Type of subagent (e.g., "builder", "validator")
- agent_transcript_path: Path to the subagent's conversation transcript (JSONL)
- stop_hook_active: Boolean indicating if stop hook is currently active
- transcript_path: Path to the main conversation transcript

GOTCHA Layer: Orchestration + Improvement
ATLAS Phase: Stress-test (results evaluation)
"""
__version__ = "2026.04.20.5"

import argparse
import json
import os
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv  # ty: ignore[unresolved-import]
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# ---------------------------------------------------------------------------
# Paths (all rooted under ~/.claude/)
# ---------------------------------------------------------------------------
CLAUDE_HOME = Path.home() / ".claude"
LOG_DIR = CLAUDE_HOME / "logs"
DATA_DIR = CLAUDE_HOME / "data"
STOP_LOG_PATH = LOG_DIR / "subagent_stop.jsonl"
DEBUG_LOG_PATH = LOG_DIR / "subagent_debug.log"
AGENT_REGISTRY_PATH = DATA_DIR / "agent_registry.jsonl"
QUALITY_LOG_PATH = DATA_DIR / "quality_scores.jsonl"

# Add hooks directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))


def _ensure_dirs() -> None:
    """Ensure ~/.claude/logs and ~/.claude/data directories exist."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def debug_log(message: str) -> None:
    """Write a debug message to ~/.claude/logs/subagent_debug.log."""
    try:
        _ensure_dirs()
        timestamp = datetime.now().isoformat()
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record as one line to a JSONL file."""
    try:
        _ensure_dirs()
        with open(path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def _rotate_registry_if_needed() -> None:
    """Keep agent_registry.jsonl under 2500 lines — trim to last 1500 on overflow."""
    try:
        if not AGENT_REGISTRY_PATH.exists():
            return
        lines = AGENT_REGISTRY_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > 2500:
            tmp = AGENT_REGISTRY_PATH.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(lines[-1500:]), encoding="utf-8")
            os.replace(tmp, AGENT_REGISTRY_PATH)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Git state capture (silent, fast, best-effort)
# ---------------------------------------------------------------------------
def _get_git_diff_stat(cwd: str) -> Optional[str]:
    """
    Run `git diff --stat HEAD` in the given cwd and return up to 300 chars of output.

    Returns None if cwd is missing, not a git repo, the command fails, or times out.
    All failures are silent.
    """
    try:
        if not cwd or not os.path.isdir(cwd):
            return None
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return None
        output = (result.stdout or "").strip()
        if not output:
            return None
        return output[:300]
    except Exception:
        return None


def _get_git_status_summary(cwd: str) -> Optional[str]:
    """
    Run `git status --porcelain` in the given cwd and return a compact summary
    like "3 files changed" or "clean". Never returns the full file list.

    Returns None if cwd is missing, not a git repo, the command fails, or times out.
    All failures are silent.
    """
    try:
        if not cwd or not os.path.isdir(cwd):
            return None
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return None
        output = (result.stdout or "").strip()
        if not output:
            return "clean"
        count = sum(1 for line in output.splitlines() if line.strip())
        return f"{count} files changed" if count != 1 else "1 file changed"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Transcript extraction
# ---------------------------------------------------------------------------
def _tail_lines(path: str, n: int = 20) -> list:
    """Return the last n non-empty lines of a file (memory-efficient via deque)."""
    try:
        with open(path, "r") as f:
            return list(deque((line for line in f if line.strip()), maxlen=n))
    except OSError:
        return []


def extract_result_summary(transcript_path: str, max_chars: int = 500) -> str:
    """
    Read the last ~20 lines of the subagent transcript (JSONL) and extract
    text from the most recent assistant message.

    Returns up to max_chars of plain text, or "" if nothing found.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    lines = _tail_lines(transcript_path, n=20)

    # Walk backwards through the last lines to find the latest assistant message
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        entry_type = entry.get("type", "")
        message = entry.get("message") if isinstance(entry.get("message"), dict) else None

        # Claude Code transcript style: {"type": "assistant", "message": {"content": [...]}}
        if entry_type == "assistant" and message:
            content = message.get("content", "")
            text = _content_to_text(content)
            if text:
                return text[:max_chars]

        # Anthropic API style: {"role": "assistant", "content": ...}
        if entry.get("role") == "assistant":
            content = entry.get("content", "")
            text = _content_to_text(content)
            if text:
                return text[:max_chars]

    return ""


def _content_to_text(content) -> str:
    """Flatten Anthropic-style content (str | list[block]) into plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def _extract_result_block(text: str) -> dict:
    """Parse the ## RESULT block from a sub-agent final message into structured fields."""
    result = {"status": "unknown", "output": "", "files_changed": "", "next": ""}
    if not text or "## RESULT" not in text:
        return result
    try:
        # Find the ## RESULT section
        idx = text.find("## RESULT")
        block = text[idx:]
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- Status:"):
                result["status"] = line[9:].strip()
            elif line.startswith("- Output:"):
                result["output"] = line[9:].strip()
            elif line.startswith("- Files changed:"):
                result["files_changed"] = line[16:].strip()
            elif line.startswith("- Next:"):
                result["next"] = line[7:].strip()
    except Exception:
        pass
    return result


def extract_task_context(input_data: dict, max_chars: int = 200) -> str:
    """Extract the initial user prompt from the transcript for TTS context."""
    transcript_path = (
        input_data.get("agent_transcript_path")
        or input_data.get("transcript_path")
        or ""
    )
    if not transcript_path or not os.path.exists(transcript_path):
        return "completed a task"

    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if entry.get("type") == "user" or entry.get("role") == "user":
                    message = entry.get("message") if isinstance(entry.get("message"), dict) else None
                    content = message.get("content", "") if message else entry.get("content", "")
                    text = _content_to_text(content)
                    if text:
                        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except OSError:
        pass

    return "completed a task"


# ---------------------------------------------------------------------------
# TTS (simplified: no lock, short timeout, always best-effort)
# ---------------------------------------------------------------------------
def get_tts_script_path() -> Optional[str]:
    """Pick a TTS script based on available API keys. Priority: ElevenLabs > OpenAI > pyttsx3."""
    tts_dir = Path(__file__).parent / "utils" / "tts"

    if os.getenv("ELEVENLABS_API_KEY"):
        script = tts_dir / "elevenlabs_tts.py"
        if script.exists():
            return str(script)

    if os.getenv("OPENAI_API_KEY"):
        script = tts_dir / "openai_tts.py"
        if script.exists():
            return str(script)

    script = tts_dir / "pyttsx3_tts.py"
    if script.exists():
        return str(script)

    return None


def announce(message: str) -> None:
    """Best-effort TTS announcement with a 5-second timeout. Never raises."""
    try:
        tts_script = get_tts_script_path()
        if not tts_script:
            return
        subprocess.run(
            ["uv", "run", tts_script, message],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        parser = argparse.ArgumentParser(
            description="SubagentStop hook — logs completion, extracts result summary, optional TTS/trigger/CCE."
        )
        parser.add_argument("--notify", action="store_true", help="Announce completion via TTS")
        parser.add_argument("--trigger", action="store_true", help="Run the trigger engine")
        parser.add_argument("--cognitive", action="store_true", help="Run CCE quality assessment")
        # Kept for backwards compatibility with settings.json, but ignored:
        parser.add_argument("--chat", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument("--summarize", action="store_true", default=True, help=argparse.SUPPRESS)
        parser.add_argument("--no-summarize", dest="summarize", action="store_false", help=argparse.SUPPRESS)
        args = parser.parse_args()

        _ensure_dirs()
        _rotate_registry_if_needed()

        # Read JSON input from stdin
        try:
            input_data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            input_data = {}

        session_id = input_data.get("session_id", "")
        stop_hook_active = input_data.get("stop_hook_active", False)
        agent_id = input_data.get("agent_id", "unknown")
        agent_type = input_data.get("agent_type", "unknown")
        agent_transcript_path = input_data.get("agent_transcript_path", "")
        transcript_path = input_data.get("transcript_path", "")
        duration_hint = input_data.get("duration", input_data.get("duration_hint", ""))
        cwd = input_data.get("cwd") or os.getcwd()

        # Capture git state (best-effort, silent, 4s timeout each)
        git_diff_stat = _get_git_diff_stat(cwd)
        git_status = _get_git_status_summary(cwd)

        now_iso = datetime.now().isoformat()

        debug_log("=== SubagentStop Hook Triggered ===")
        debug_log(f"agent_id={agent_id} agent_type={agent_type} session_id={session_id}")
        debug_log(f"agent_transcript_path={agent_transcript_path or 'NOT FOUND'}")

        # ---- 1. Extract result summary from subagent transcript ----
        result_summary = extract_result_summary(agent_transcript_path, max_chars=500)
        debug_log(f"result_summary[{len(result_summary)} chars]: {result_summary[:100]}...")

        # Parse structured ## RESULT block so orchestrator retains Status/Output/Files/Next.
        result_block = _extract_result_block(result_summary)

        # ---- 2. Append to subagent stop log (JSONL) ----
        stop_record = {
            "event": "subagent_stop",
            "timestamp": now_iso,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "stop_hook_active": stop_hook_active,
            "agent_transcript_path": agent_transcript_path,
            "transcript_path": transcript_path,
            "result_summary": result_summary,
            "result_block": result_block,
            "git_diff_stat": git_diff_stat,
            "git_status": git_status,
        }
        append_jsonl(STOP_LOG_PATH, stop_record)

        # ---- 3. Append to agent registry (JSONL) ----
        # If SubagentStart hook missed this agent (hook not active at spawn time),
        # write a synthetic start entry so the registry always has matched pairs.
        try:
            if AGENT_REGISTRY_PATH.exists():
                existing_ids = set()
                for raw_line in AGENT_REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
                    try:
                        rec = json.loads(raw_line)
                        if rec.get("event") == "start" and rec.get("agent_id"):
                            existing_ids.add(str(rec["agent_id"]))
                    except Exception:
                        pass
                if agent_id not in existing_ids:
                    synthetic_start = {
                        "event": "start",
                        "agent_id": agent_id,
                        "agent_type": agent_type,
                        "session_id": session_id,
                        "cwd": cwd,
                        "backend": "claude",
                        "timestamp": now_iso,
                        "synthetic": True,
                    }
                    append_jsonl(AGENT_REGISTRY_PATH, synthetic_start)
                    debug_log(f"Wrote synthetic start for {agent_id} (SubagentStart hook missed)")
        except Exception:
            pass

        registry_record = {
            "event": "stop",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "result_summary": result_summary,
            "result_block": result_block,
            "duration_hint": duration_hint,
            "timestamp": now_iso,
            "git_diff_stat": git_diff_stat,
            "git_status": git_status,
        }
        append_jsonl(AGENT_REGISTRY_PATH, registry_record)

        # ---- 3b. Store result via agent_results.py (best-effort) ----
        try:
            # Detect failure heuristically from summary content.
            _lower = (result_summary or "").lower()[:200]
            _fail_markers = (
                "error",
                "failed",
                "exception",
                "traceback",
                "## result\n- status: failed",
            )
            _inferred_status = "failed" if (not result_summary or any(m in _lower for m in _fail_markers)) else "completed"
            # Prefer explicit status from parsed ## RESULT block when present.
            if result_block.get("status") in ("failed", "partial"):
                _inferred_status = result_block["status"]
            elif result_block.get("status") == "completed":
                _inferred_status = "completed"

            subprocess.run(
                [
                    "uv",
                    "run",
                    str(CLAUDE_HOME / "scripts/agent_results.py"),
                    "store",
                    agent_id,
                    _inferred_status,
                    result_summary,
                ],
                timeout=3,
                capture_output=True,
            )
        except Exception:
            pass

        # ---- 4. TTS announcement (best-effort, short timeout) ----
        if args.notify:
            try:
                summary_message = "Subagent Complete"
                try:
                    from utils.llm.task_summarizer import summarize_subagent_task  # ty: ignore[unresolved-import]
                    task_context = extract_task_context(input_data)
                    summary_message = summarize_subagent_task(task_context, agent_name=agent_id) or summary_message
                except ImportError:
                    pass
                except Exception:
                    pass
                debug_log(f"TTS announce: {summary_message}")
                announce(summary_message)
            except Exception:
                pass

        # ---- 5. Trigger engine (best-effort, 5s timeout) ----
        if args.trigger and os.getenv("TRIGGER_ENABLED", "true").lower() != "false":
            try:
                trigger_script = Path(__file__).parent / "utils" / "trigger.py"
                if trigger_script.exists():
                    trigger_input = json.dumps({
                        "hook_event_name": "SubagentStop",
                        "agent_id": agent_id,
                        "agent_type": agent_type,
                        "session_id": session_id,
                        "stop_hook_active": stop_hook_active,
                        "result_summary": result_summary,
                    })
                    subprocess.run(
                        ["uv", "run", str(trigger_script), "--event", "SubagentStop"],
                        input=trigger_input,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
            except Exception:
                pass

        # ---- 6. Cognitive Control Engine quality assessment ----
        if args.cognitive and os.getenv("CCE_ENABLED", "true").lower() != "false":
            try:
                from utils.cognitive.quality_assessor import assess_agent_output  # noqa: E402  # ty: ignore[unresolved-import]

                task_context = extract_task_context(input_data)
                quality = assess_agent_output(
                    agent_name=agent_id,
                    task_description=task_context,
                    output_summary=result_summary or task_context,
                )

                quality_record = {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "session_id": session_id,
                    "quality_score": getattr(quality, "overall", None),
                    "verdict": getattr(quality, "verdict", None),
                    "timestamp": now_iso,
                }
                append_jsonl(QUALITY_LOG_PATH, quality_record)

                try:
                    threshold = int(os.getenv("QUALITY_AUTO_VALIDATE", "60"))
                except ValueError:
                    threshold = 60
                overall = getattr(quality, "overall", None)
                if isinstance(overall, (int, float)) and overall < threshold:
                    print(
                        f"[CCE Quality] Agent {agent_id} scored {overall}/100 "
                        f"({getattr(quality, 'verdict', 'unknown')}). Consider deploying a validator.",
                        file=sys.stderr,
                    )
            except ImportError:
                pass
            except Exception:
                pass

        sys.exit(0)

    except Exception:
        # Always exit 0 — this hook must never block the harness
        sys.exit(0)


if __name__ == "__main__":
    main()
