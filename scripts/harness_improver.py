#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
harness_improver.py — 7-phase harness self-improvement cycle.
__version__ = "2026.04.21.2"

Runs every 20 minutes via crontab. Each phase asks kimi-k2-thinking a focused
question, collects answers, and writes actionable items to MIP.md.

Phases:
  1. THINK   — improve reasoning: what thoughts/patterns are missing?
  2. GAPS    — audit hooks/scripts/skills for capability gaps
  3. SCRIPTS — what new scripts would fill top-3 gaps?
  4. AGENTS  — what agents are missing or underused?
  5. QUALITY — human-style questionnaire: what would break? what's annoying?
  6. CONSOLIDATE — is anything redundant? can two things become one?
  7. FLOW    — can the human workflow be any smoother?

Output: appends findings to MIP.md cycle log + backlog.
Exits 0 always (safe for cron).
"""
from __future__ import annotations
__version__ = "2026.04.21.2"

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
CLAUDE_DIR = Path.home() / ".claude"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
HOOKS_DIR = CLAUDE_DIR / "hooks"
COMMANDS_DIR = CLAUDE_DIR / "commands"
DATA_DIR = CLAUDE_DIR / "data"
LOG_PATH = DATA_DIR / "harness_improver.log"
OLLAMA_SCRIPT = SCRIPTS_DIR / "ollama_cloud.py"

MODEL = "kimi-k2-thinking:cloud"
TIMEOUT = 90  # seconds per Ollama call


def _project_mip_path() -> Path:
    """Derive MIP.md path from CLAUDE_PROJECT_DIR (same slug formula as session_init.py)."""
    cwd = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", "-".join(cwd.strip("/").replace("\\", "/").split("/")))
    return CLAUDE_DIR / "projects" / f"-{slug}" / "memory" / "MIP.md"


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{_now()}] {msg}\n")
    except Exception:
        pass


def _snapshot() -> dict:
    """Collect a compact snapshot of current harness state."""
    hooks = sorted(p.name for p in HOOKS_DIR.glob("*.py") if not p.name.startswith("_"))
    scripts = sorted(p.name for p in SCRIPTS_DIR.glob("*.py") if not p.name.startswith("_"))
    skills = sorted(p.stem for p in COMMANDS_DIR.glob("*.md"))

    # Read MIP backlog items
    backlog: list[str] = []
    try:
        mip_text = _project_mip_path().read_text(encoding="utf-8")
        for line in mip_text.splitlines():
            if line.startswith("- [ ]"):
                backlog.append(line.strip())
    except Exception:
        pass

    # Read usage status
    rate_limited = False
    try:
        status = json.loads((DATA_DIR / "usage_status.json").read_text())
        rate_limited = bool(status.get("rate_limited"))
    except Exception:
        pass

    return {
        "hooks": hooks,
        "scripts": scripts,
        "skills": skills,
        "backlog": backlog,
        "rate_limited": rate_limited,
    }


def _ask(prompt: str) -> str:
    """Send prompt to kimi-k2-thinking via ollama_cloud.py. Returns response text."""
    if not OLLAMA_SCRIPT.exists():
        return ""
    try:
        result = subprocess.run(
            ["uv", "run", str(OLLAMA_SCRIPT), "chat", MODEL, prompt,
             "--timeout", str(TIMEOUT)],
            capture_output=True, text=True, timeout=TIMEOUT + 10,
        )
        out = (result.stdout or "").strip()
        return out
    except Exception as e:
        _log(f"ollama call failed: {e}")
        return ""


def _extract_items(text: str, prefix: str, max_items: int = 3) -> list[str]:
    """Pull numbered/bulleted items from LLM response, return up to max_items."""
    items: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Match: "1.", "-", "•", "*", or just non-empty lines after stripping bullets
        if line[:2] in ("1.", "2.", "3.", "4.", "5.", "- ", "• ", "* ") or line.startswith("- "):
            clean = line.lstrip("0123456789.-•* ").strip()
            if len(clean) > 20:
                items.append(f"- [ ] **[{prefix}]** {clean}")
        if len(items) >= max_items:
            break
    return items


def _default_mip_template() -> str:
    return (
        "---\nname: Harness MIP\ndescription: Living improvement plan. Updated every 20 min.\ntype: project\n---\n\n"
        "# MIP — Harness Managed Improvement Plan\n\n"
        "## Active Backlog\n\n---\n\n## Completed\n\n---\n\n## Cycle Log\n\n"
    )


def _append_to_mip(new_items: list[str], cycle_entry: str) -> None:
    """Append new backlog items and cycle log entry to MIP.md."""
    try:
        mip = _project_mip_path()
        mip.parent.mkdir(parents=True, exist_ok=True)
        text = mip.read_text(encoding="utf-8") if mip.exists() else _default_mip_template()

        # Add new backlog items (deduplicate by first 60 chars of content)
        existing_lower = text.lower()
        to_add = [item for item in new_items
                  if item[10:70].lower() not in existing_lower]

        if to_add:
            # Insert inside Active Backlog section, before the closing ---
            backlog_end = text.find("\n---\n\n## Completed")
            if backlog_end == -1:
                backlog_end = text.find("\n## Completed")
            if backlog_end == -1:
                backlog_end = len(text)
            text = text[:backlog_end] + "\n" + "\n".join(to_add) + text[backlog_end:]

        # Append cycle log entry at end of file
        text = text.rstrip() + f"\n{cycle_entry}\n"

        mip.write_text(text, encoding="utf-8")
    except Exception as e:
        _log(f"mip write failed: {e}")


# ── 7 Phases ───────────────────────────────────────────────────────────────

def phase_think(snap: dict) -> list[str]:
    """Phase 1: What reasoning/thought patterns are missing from the harness?"""
    prompt = textwrap.dedent(f"""
        You are auditing a Claude Code AI harness. Current hooks: {snap['hooks']}.
        Current skills: {snap['skills'][:20]}.

        Question: What chain-of-thought or reasoning improvements are MISSING?
        Think about: pre-reasoning before tool calls, self-checking patterns,
        thought injection before complex tasks, meta-cognition about task complexity.

        Give exactly 3 specific, actionable improvements (one per line, starting with a dash).
        Be concrete — name the hook/script/skill to modify or create.
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "THINK")


def phase_gaps(snap: dict) -> list[str]:
    """Phase 2: What capability gaps exist in hooks/scripts/skills?"""
    prompt = textwrap.dedent(f"""
        You are auditing a Claude Code AI harness.
        Hooks: {snap['hooks']}
        Scripts: {snap['scripts']}
        Skills: {snap['skills'][:20]}
        Open backlog: {snap['backlog'][:5]}

        Question: What important capabilities are MISSING entirely?
        Think about: error recovery, observability, testing, workflow automation,
        context management, cost control, human handoff.

        Give exactly 3 specific gaps (one per line, starting with a dash).
        Name what hook/script/skill would fill each gap.
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "GAP")


def phase_scripts(snap: dict) -> list[str]:
    """Phase 3: What new scripts would fill the top gaps?"""
    prompt = textwrap.dedent(f"""
        You are reviewing a Claude Code harness improvement plan.
        Current scripts: {snap['scripts']}
        Current backlog gaps: {snap['backlog'][:3]}

        Question: What NEW Python script (in ~/.claude/scripts/) would have the
        highest impact right now? For each, describe: filename, what it does in
        one sentence, and which problem it solves.

        Give exactly 2 script ideas (one per line, starting with a dash).
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "SCRIPT", max_items=2)


def phase_agents(snap: dict) -> list[str]:
    """Phase 4: What agent patterns or new agents are missing?"""
    prompt = textwrap.dedent(f"""
        You are reviewing a Claude Code multi-agent harness.
        Current agent skills: {[s for s in snap['skills'] if 'agent' in s.lower() or 'cook' in s.lower() or 'orchestrat' in s.lower()]}
        Current hooks that manage agents: {[h for h in snap['hooks'] if 'agent' in h or 'subagent' in h]}

        Question: What agent patterns are MISSING or UNDERUSED?
        Think about: background monitoring agents, parallel audit agents,
        agent result aggregation, self-healing agents, agent communication.

        Give exactly 2 missing agent capabilities (one per line, starting with a dash).
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "AGENT", max_items=2)


def phase_quality(snap: dict) -> list[str]:
    """Phase 5: Human-style quality questionnaire."""
    prompt = textwrap.dedent(f"""
        You are a senior engineer doing a quality review of an AI coding assistant harness.
        Hooks: {snap['hooks']}
        Skills count: {len(snap['skills'])}
        Scripts count: {len(snap['scripts'])}

        Answer these questions honestly, then give 2 actionable quality improvements:
        - What would ANNOY a human using this daily?
        - What would BREAK silently without anyone noticing?
        - What takes too many steps that should be automatic?

        Give exactly 2 quality improvements (one per line, starting with a dash).
        Be direct and specific.
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "QUALITY", max_items=2)


def phase_consolidate(snap: dict) -> list[str]:
    """Phase 6: Is anything redundant or can things be combined?"""
    prompt = textwrap.dedent(f"""
        You are reviewing a Claude Code harness for bloat and redundancy.
        Hooks: {snap['hooks']}
        Scripts: {snap['scripts']}
        Skills: {snap['skills']}

        Question: What is REDUNDANT or OVERLAPPING?
        Think about: two hooks doing similar things, a script duplicating a skill,
        a skill that wraps a script that wraps another script.

        Give exactly 2 consolidation opportunities (one per line, starting with a dash).
        Format: "Merge X into Y because Z"
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "CONSOLIDATE", max_items=2)


def phase_flow(snap: dict) -> list[str]:
    """Phase 7: Can the human workflow be smoother?"""
    prompt = textwrap.dedent(f"""
        You are optimizing the daily workflow of a developer using Claude Code with
        a custom harness. They use it for: coding, debugging, git operations,
        multi-agent tasks, and harness self-improvement.

        Current session flow:
          SessionStart → memory load → stop analysis → codebase scan → ready
          UserPrompt → model routing → hook chain → response
          Stop → memory tracking → notifications

        Question: What ONE change to the FLOW would make the human's day noticeably
        smoother? Think about: reducing friction, reducing waiting, surfacing
        information earlier, removing steps that shouldn't exist.

        Give exactly 1 flow improvement (one line, starting with a dash).
        Be specific about WHICH hook/step to change and HOW.
    """).strip()
    response = _ask(prompt)
    return _extract_items(response, "FLOW", max_items=1)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    _log("=== harness_improver cycle start ===")
    snap = _snapshot()

    if snap["rate_limited"]:
        _log("Claude rate-limited — skipping (Ollama used for routing, not improvement)")
        return 0

    now = _now()
    all_items: list[str] = []
    phase_results: list[str] = []

    phases = [
        ("THINK",       phase_think),
        ("GAPS",        phase_gaps),
        ("SCRIPTS",     phase_scripts),
        ("AGENTS",      phase_agents),
        ("QUALITY",     phase_quality),
        ("CONSOLIDATE", phase_consolidate),
        ("FLOW",        phase_flow),
    ]

    for name, fn in phases:
        _log(f"  phase {name}...")
        try:
            items = fn(snap)
            all_items.extend(items)
            phase_results.append(f"    {name}: {len(items)} item(s)")
        except Exception as e:
            _log(f"  phase {name} failed: {e}")
            phase_results.append(f"    {name}: error")

    cycle_entry = (
        f"\n### [{now}] — Cycle run\n"
        + "\n".join(phase_results)
        + f"\n    New items: {len(all_items)}"
    )

    _append_to_mip(all_items, cycle_entry)
    _log(f"=== done: {len(all_items)} new items added to MIP.md ===")
    print(f"[harness_improver] {len(all_items)} improvements → MIP.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
