#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations
"""
skill_audit.py — Audit all skills in ~/.claude/commands/ for quality issues.

Checks frontmatter completeness, allowed-tools correctness, hook path validity,
Agent/ToolSearch declaration consistency, and argument-hint coverage.

Usage:
  uv run ~/.claude/scripts/skill_audit.py              # full audit table
  uv run ~/.claude/scripts/skill_audit.py --fix        # auto-fix safe issues (missing argument-hint)
  uv run ~/.claude/scripts/skill_audit.py --json       # machine-readable output
  uv run ~/.claude/scripts/skill_audit.py --skill plan # audit one skill
"""
__version__ = "2026.04.20.1"


import argparse
import json
import re
import sys
from pathlib import Path

HOME    = Path.home()
CLAUDE  = HOME / ".claude"
CMD_DIR = CLAUDE / "commands"
HOOKS   = CLAUDE / "hooks"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# Tools that require ToolSearch to be loaded first
DEFERRED_TOOLS = {"LSP", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
                  "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete",
                  "CronList", "RemoteTrigger", "TaskCreate", "TaskUpdate",
                  "TaskGet", "TaskList", "TaskOutput", "TaskStop"}


def _frontmatter(text: str) -> dict[str, str]:
    """Extract simple key: value pairs from YAML frontmatter."""
    fm: dict[str, str] = {}
    if not text.startswith("---"):
        return fm
    end = text.find("---", 3)
    if end == -1:
        return fm
    block = text[3:end]
    for line in block.splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def audit_skill(path: Path) -> list[dict]:
    issues = []
    text = path.read_text(errors="replace")
    fm = _frontmatter(text)
    name = path.stem

    def issue(severity: str, code: str, msg: str) -> None:
        issues.append({"skill": name, "severity": severity, "code": code, "message": msg})

    # 1. description
    if not fm.get("description"):
        issue("warn", "NO_DESC", "missing description in frontmatter")

    # 2. argument-hint
    if not fm.get("argument-hint"):
        issue("info", "NO_HINT", "missing argument-hint")

    # 3. allowed-tools
    allowed_raw = fm.get("allowed-tools", "")
    allowed = {t.strip().split("(")[0] for t in allowed_raw.split(",") if t.strip()}

    # 4. Agent declared when @agent- or Agent( referenced
    body = text[text.find("---", 3) + 3:] if text.startswith("---") else text
    uses_agent = bool(re.search(r"Agent\(|@agent-|sub.?agent|spawn.*agent", body, re.IGNORECASE))
    if uses_agent and "Agent" not in allowed and allowed_raw.lower() != "inherit":
        issue("high", "AGENT_MISSING", "uses Agent but 'Agent' not in allowed-tools")

    # 5. ToolSearch declared when deferred tools referenced
    uses_deferred = [t for t in DEFERRED_TOOLS if t in body]
    if uses_deferred and "ToolSearch" not in allowed and allowed_raw.lower() != "inherit":
        issue("warn", "TOOLSEARCH_MISSING", f"references deferred tools ({', '.join(uses_deferred[:3])}) but ToolSearch not in allowed-tools")

    # 6. Hook paths
    hook_block = re.findall(r"command:\s*>-?\s*(.*)", text)
    for cmd in hook_block:
        if "$CLAUDE_PROJECT_DIR" in cmd:
            issue("high", "BAD_HOOK_PATH", f"hook uses $CLAUDE_PROJECT_DIR: {cmd[:60]}")
        script = re.search(r"(\S+\.py)", cmd)
        if script:
            p = script.group(1).replace("$HOME", str(HOME))
            if not Path(p).exists():
                issue("high", "HOOK_MISSING", f"hook script not found: {p}")

    # 7. Bash without :* (overly broad)
    if "Bash" in allowed and not re.search(r"Bash\(", allowed_raw):
        issue("info", "BASH_UNRESTRICTED", "Bash without restrictions — consider Bash(cmd:*) patterns")

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Claude Code skills")
    parser.add_argument("--fix",   action="store_true", help="Auto-fix missing argument-hint")
    parser.add_argument("--json",  action="store_true", help="Output as JSON")
    parser.add_argument("--skill", help="Audit a single skill by name")
    parser.add_argument("--min-severity", default="info", choices=["info", "warn", "high"],
                        help="Minimum severity to show (default: info)")
    args = parser.parse_args()

    SEVERITY_ORDER = {"info": 0, "warn": 1, "high": 2}
    min_sev = SEVERITY_ORDER[args.min_severity]

    if args.skill:
        paths = list(CMD_DIR.glob(f"{args.skill}*.md"))
        if not paths:
            print(f"Skill not found: {args.skill}")
            sys.exit(1)
    else:
        paths = sorted(CMD_DIR.glob("*.md"))

    all_issues: list[dict] = []
    for path in paths:
        all_issues.extend(audit_skill(path))

    filtered = [i for i in all_issues if SEVERITY_ORDER.get(i["severity"], 0) >= min_sev]

    if args.json:
        print(json.dumps(filtered, indent=2))
        return

    if not filtered:
        print(f"{GREEN}✓ No issues found across {len(paths)} skills{RESET}")
        return

    print(f"\n{BOLD}Skill Audit — {len(paths)} skills{RESET}\n")

    by_skill: dict[str, list[dict]] = {}
    for i in filtered:
        by_skill.setdefault(i["skill"], []).append(i)

    for skill, issues in sorted(by_skill.items()):
        for i in issues:
            sev = i["severity"]
            if sev == "high":
                color = RED
            elif sev == "warn":
                color = YELLOW
            else:
                color = DIM
            print(f"  {color}{sev.upper():4}{RESET}  {skill:<22} [{i['code']}] {i['message']}")

    highs = sum(1 for i in filtered if i["severity"] == "high")
    warns = sum(1 for i in filtered if i["severity"] == "warn")
    infos = sum(1 for i in filtered if i["severity"] == "info")
    print(f"\n  {RED}{highs} high{RESET}  {YELLOW}{warns} warn{RESET}  {DIM}{infos} info{RESET}  across {len(by_skill)} skill(s)\n")

    if args.fix:
        fixed = 0
        for path in paths:
            text = path.read_text()
            fm = _frontmatter(text)
            if not fm.get("argument-hint"):
                # Insert argument-hint after description line
                new_text = re.sub(
                    r"(description:.*\n)",
                    r'\1argument-hint: "<arguments>"\n',
                    text, count=1
                )
                if new_text != text:
                    path.write_text(new_text)
                    fixed += 1
        print(f"  Auto-fixed {fixed} missing argument-hint(s)")


if __name__ == "__main__":
    main()
