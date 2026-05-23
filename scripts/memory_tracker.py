#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
__version__ = "2026.04.21.1"
Memory tracker — runs at Stop, scans transcript for memory-worthy items,
writes them to ~/.claude/projects/<project>/memory/.

Short-term items: session actions, fixes, decisions (overwrite per session).
Long-term items: preferences, behaviors, architecture facts (append/update).

Usage: memory_tracker.py [--transcript <path>] [--project <dir>] [--dry-run]
"""
__version__ = "2026.04.21.1"
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"


def project_memory_dir(project_path: str) -> Path:
    h = hashlib.sha256(project_path.encode()).hexdigest()
    slug = "-".join(project_path.strip("/").replace("\\", "/").split("/"))
    slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", slug)
    return PROJECTS_DIR / f"-{slug}" / "memory"


# ── Transcript parsing ─────────────────────────────────────────────────────
def load_transcript(path: str) -> list[dict]:
    messages = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return messages


def extract_text(messages: list[dict]) -> list[tuple[str, str]]:
    """Return [(role, text), ...] from transcript messages."""
    pairs = []
    for msg in messages:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
            )
        elif isinstance(content, str):
            text = content
        else:
            continue
        text = text.strip()
        if text:
            pairs.append((role, text))
    return pairs


# ── Pattern matchers ───────────────────────────────────────────────────────
LONG_TERM_TRIGGERS = [
    r"\b(always|never|from now on|in future|each time|every time|whenever|prefer|don't|stop doing|keep doing)\b",
    r"\b(remember that|note that|important:|rule:)\b",
    r"\b(i('m| am) a |i work |my role|my stack|i use |i prefer)\b",
]
FIX_TRIGGERS = [
    r"\b(fixed|resolved|bug|issue|error|broke|broken|crash|fail)\b",
]
ARCH_TRIGGERS = [
    r"\b(architecture|design|pattern|schema|hook|pipeline|service|agent|module)\b",
    r"\b(added|created|updated|refactored|migrated|rewrote)\b.{0,60}\b(hook|script|file|class|function|service)\b",
]
PREF_TRIGGERS = [
    r"\b(don't|do not|stop|avoid|never)\b.{0,60}\b(use|add|do|make|create|write)\b",
    r"\b(always|prefer|want|like|need)\b.{0,60}\b(to|you to)\b",
]


def score_line(text: str) -> tuple[str | None, int]:
    """Return (category, score) for a text snippet."""
    lo = text.lower()
    for pat in LONG_TERM_TRIGGERS:
        if re.search(pat, lo):
            return "feedback", 3
    for pat in PREF_TRIGGERS:
        if re.search(pat, lo):
            return "feedback", 2
    for pat in ARCH_TRIGGERS:
        if re.search(pat, lo):
            return "project", 2
    for pat in FIX_TRIGGERS:
        if re.search(pat, lo):
            return "project", 1
    return None, 0


def extract_candidates(pairs: list[tuple[str, str]]) -> list[dict]:
    """Score each user/assistant turn and return high-scoring candidates."""
    candidates = []
    for role, text in pairs:
        # Only look at reasonably short utterances (not walls of code)
        sentences = re.split(r"[.!?]\s+|\n", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 300:
                continue
            cat, score = score_line(sentence)
            if score >= 2:
                candidates.append({
                    "role": role,
                    "text": sentence,
                    "category": cat,
                    "score": score,
                })
    # Deduplicate by similarity
    seen: set[str] = set()
    unique = []
    for c in sorted(candidates, key=lambda x: -x["score"]):
        key = re.sub(r"\W+", " ", c["text"].lower())[:60]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:15]  # cap


# ── Session summary (short-term) ───────────────────────────────────────────
ACTION_VERBS = re.compile(
    r"\b(created|added|fixed|removed|deleted|updated|installed|configured|"
    r"refactored|migrated|deployed|enabled|disabled|reset|cleared)\b",
    re.IGNORECASE,
)


def extract_actions(pairs: list[tuple[str, str]], limit: int = 8) -> list[str]:
    """Pull assistant sentences that describe concrete actions taken."""
    actions = []
    for role, text in reversed(pairs):
        if role != "assistant":
            continue
        for sentence in re.split(r"[.!\n]", text):
            sentence = sentence.strip()
            if ACTION_VERBS.search(sentence) and 20 < len(sentence) < 200:
                actions.append(sentence)
            if len(actions) >= limit:
                break
        if len(actions) >= limit:
            break
    return list(reversed(actions))


# ── Memory file writers ────────────────────────────────────────────────────
def ensure_memory_index(mem_dir: Path) -> None:
    index = mem_dir / "MEMORY.md"
    if not index.exists():
        index.write_text("# Memory Index\n\n", encoding="utf-8")


def update_memory_index(mem_dir: Path, filename: str, title: str, hook: str) -> None:
    index = mem_dir / "MEMORY.md"
    content = index.read_text(encoding="utf-8") if index.exists() else "# Memory Index\n\n"
    entry = f"- [{title}]({filename}) — {hook}"
    # Replace existing entry for same file, else append
    lines = content.splitlines()
    new_lines = [l for l in lines if f"]({filename})" not in l]
    new_lines.append(entry)
    index.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def write_session_summary(mem_dir: Path, session_id: str, actions: list[str], project: str) -> None:
    fname = "session_latest.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        "name: Latest Session Summary",
        "description: Short-term — what happened in the most recent session",
        "type: project",
        f"originSessionId: {session_id}",
        "---",
        "",
        f"**Session:** {now}  **Project:** {project}",
        "",
        "## Actions taken",
    ] + [f"- {a}" for a in actions]
    (mem_dir / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_memory_index(mem_dir, fname, "Latest Session Summary", f"What happened {now[:10]}")


def append_longterm_memory(mem_dir: Path, category: str, items: list[dict]) -> int:
    """Append new long-term memory items to feedback.md or project.md. Returns count added."""
    fname = f"auto_{category}.md"
    fpath = mem_dir / fname
    existing = fpath.read_text(encoding="utf-8") if fpath.exists() else ""

    if not existing:
        existing = (
            f"---\nname: Auto-{category.title()} Memory\n"
            f"description: Auto-captured {category} items from sessions\n"
            f"type: {category}\n---\n\n"
        )

    added = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for item in items:
        text = item["text"]
        # Skip if very similar content already in file
        key = re.sub(r"\W+", " ", text.lower())[:40]
        if key in existing.lower():
            continue
        existing += f"\n**[{now}]** {text}\n"
        added += 1

    if added:
        fpath.write_text(existing, encoding="utf-8")
        update_memory_index(mem_dir, fname, f"Auto {category.title()} Memory", f"Auto-captured {category} notes")
    return added


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Auto memory tracker at session stop")
    parser.add_argument("--transcript", help="Path to transcript file")
    parser.add_argument("--project", help="Project directory path")
    parser.add_argument("--session-id", default="", help="Session ID")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be saved, don't write")
    args = parser.parse_args()

    # Allow input from stdin (Stop hook format) or direct args
    transcript_path = args.transcript
    project_path = args.project
    session_id = args.session_id

    if not transcript_path or not project_path:
        try:
            data = json.loads(sys.stdin.read())
            transcript_path = transcript_path or data.get("transcript_path", "")
            project_path = project_path or data.get("cwd", "")
            session_id = session_id or data.get("session_id", "")
        except Exception:
            pass

    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    project_path = project_path or str(Path.cwd())
    mem_dir = project_memory_dir(project_path)

    if not mem_dir.exists():
        try:
            mem_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            sys.exit(0)

    # Parse transcript
    messages = load_transcript(transcript_path)
    if not messages:
        sys.exit(0)

    pairs = extract_text(messages)
    if len(pairs) < 2:
        sys.exit(0)

    # Extract data
    actions = extract_actions(pairs)
    candidates = extract_candidates(pairs)

    feedback_items = [c for c in candidates if c["category"] == "feedback"]
    project_items = [c for c in candidates if c["category"] == "project"]

    if args.dry_run:
        print(f"=== DRY RUN — project: {project_path} ===")
        print(f"Actions ({len(actions)}): {actions[:3]}")
        print(f"Feedback candidates ({len(feedback_items)}): {[c['text'][:60] for c in feedback_items[:3]]}")
        print(f"Project candidates ({len(project_items)}): {[c['text'][:60] for c in project_items[:3]]}")
        sys.exit(0)

    # Write short-term session summary
    project_name = Path(project_path).name
    if actions:
        write_session_summary(mem_dir, session_id, actions, project_name)

    # Write long-term items
    fb_added = append_longterm_memory(mem_dir, "feedback", feedback_items) if feedback_items else 0
    proj_added = append_longterm_memory(mem_dir, "project", project_items) if project_items else 0

    ensure_memory_index(mem_dir)

    total = (1 if actions else 0) + fb_added + proj_added
    if total:
        print(f"[memory_tracker] saved: session={bool(actions)} feedback={fb_added} project={proj_added}")

    sys.exit(0)


if __name__ == "__main__":
    main()
