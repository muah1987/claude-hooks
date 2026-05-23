#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""
PreCompact Hook - Write session memory & changelog before compaction

Fires before every auto-compact or manual /compact. Writes:
  .github/memory/memory_claude-sonnet-4-6_session_{session_id[:16]}.md
  .github/changelogs/changelog_claude-sonnet-4-6_session_{session_id[:16]}.md

Then git-commits and git-pushes both files so they persist across the
compaction boundary and are visible to future sessions on GitHub.

Claude Code Hooks Specification:
- Input  (stdin): JSON with session_id, transcript_path, trigger, permission_mode
- Exit 0 : compaction proceeds
- Exit 2 : compaction blocked (we never do this — fail-open)
"""
__version__ = "2026.04.20.5"

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── constants ────────────────────────────────────────────────────────────────

AI_MODEL = os.environ.get("CLAUDE_MODEL_ID", "claude-sonnet-4-6")
# REPO_ROOT is set in main() from the hook input's `cwd` field so that docs
# land in the actual project directory, not in ~/.claude (which is where
# Path(__file__).resolve().parents[2] would resolve when this hook lives
# in ~/.claude/hooks/).
REPO_ROOT: Path = Path.home()  # placeholder — overridden in main()


# ─── transcript parsing ───────────────────────────────────────────────────────

def _text_from_content(content) -> str:
    """Pull plain text out of a content block (str or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "tool_result":
                    inner = item.get("content", "")
                    parts.append(_text_from_content(inner))
        return " ".join(parts)
    return ""


def parse_transcript(transcript_path: str) -> dict:
    """
    Read a JSONL transcript and return:
      user_requests  – first ~8 user messages (trimmed)
      actions        – Write/Edit/Bash tool-use summaries
      files_modified – unique file paths touched
      git_ops        – git commit / push commands seen
    """
    result = {
        "user_requests": [],
        "actions": [],
        "files_modified": set(),
        "git_ops": [],
        "msg_count": 0,
    }

    if not transcript_path or not os.path.exists(transcript_path):
        return result

    lines_parsed = 0
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                lines_parsed += 1

                # Unwrap envelope if present: {"type":"user","message":{...}}
                msg = obj.get("message", obj)
                role = msg.get("role", obj.get("type", ""))
                content = msg.get("content", obj.get("content", ""))

                # ── user messages ──────────────────────────────────────────
                if role == "user":
                    text = _text_from_content(content).strip()
                    if text and len(result["user_requests"]) < 8:
                        # Skip system-reminder injections
                        if not text.startswith("<system-reminder"):
                            result["user_requests"].append(text[:300])

                # ── assistant tool calls ───────────────────────────────────
                if role == "assistant" and isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") != "tool_use":
                            continue

                        tool = item.get("name", "")
                        inp = item.get("input", {})

                        if tool in ("Write", "Edit", "MultiEdit"):
                            fpath = inp.get("file_path", "")
                            if fpath:
                                result["files_modified"].add(fpath)
                                result["actions"].append(
                                    f"{tool}: {_short_path(fpath)}"
                                )

                        elif tool == "Bash":
                            cmd = inp.get("command", "")
                            desc = inp.get("description", "")
                            summary = (desc or cmd)[:120].replace("\n", " ")
                            # Only record interesting commands
                            interesting = any(
                                kw in cmd
                                for kw in (
                                    "git commit", "git push", "git merge",
                                    "npm test", "npm run", "docker", "ssh",
                                    "curl ", "gh run",
                                )
                            )
                            if interesting:
                                result["actions"].append(f"Bash: {summary}")
                            if "git commit" in cmd or "git push" in cmd:
                                result["git_ops"].append(summary)

    except Exception:
        pass

    result["msg_count"] = lines_parsed
    result["files_modified"] = sorted(result["files_modified"])
    result["actions"] = result["actions"][:25]
    return result


def _short_path(p: str) -> str:
    """Trim to last 3 path components."""
    parts = Path(p).parts
    return "/".join(parts[-3:]) if len(parts) >= 3 else p


def _git_info() -> dict[str, str]:
    """Return {remote, branch, last_commit} from the current REPO_ROOT. Best-effort."""
    def _run(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["git"] + args, cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    remote_url = _run(["remote", "get-url", "origin"])
    # Convert SSH → short "owner/repo" form, keep HTTPS as-is (trimmed)
    if remote_url.startswith("git@"):
        remote_url = remote_url.split(":")[-1].removesuffix(".git")
    elif "github.com/" in remote_url:
        remote_url = remote_url.split("github.com/")[-1].removesuffix(".git")

    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    last_commit = _run(["log", "-1", "--pretty=%h %s"]) or "none"

    return {
        "remote": remote_url or "unknown",
        "branch": branch,
        "last_commit": last_commit,
    }


# ─── file writers ─────────────────────────────────────────────────────────────

def write_memory(session_id: str, trigger: str, summary: dict, timestamp: str) -> Path:
    mem_dir = REPO_ROOT / ".github" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id[:16])
    filename = mem_dir / f"memory_{AI_MODEL}_session_{safe_id}.md"

    user_block = "\n".join(
        f"- {r}" for r in (summary["user_requests"] or ["(not captured)"])
    )
    files_block = "\n".join(
        f"- `{f}`" for f in (summary["files_modified"] or ["(none)"])
    )
    actions_block = "\n".join(
        f"{i+1}. {a}" for i, a in enumerate(summary["actions"] or ["(none)"])
    )

    git = _git_info()

    content = f"""\
### [{timestamp}] — {AI_MODEL}

**AI Model:** {AI_MODEL}
**Agent ID:** session_{safe_id}
**Task:** Auto-captured by PreCompact hook (trigger={trigger})

#### Context Loaded
- Repository: {git['remote']}
- Branch: {git['branch']}
- Last commit: {git['last_commit']}

#### User Requests This Session
{user_block}

#### Actions Taken
{actions_block}

#### Findings
- Session transcript had {summary['msg_count']} messages

#### Files Modified
{files_block}
"""

    tmp = filename.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, filename)
    return filename


def write_changelog(session_id: str, trigger: str, summary: dict, timestamp: str) -> Path:
    cl_dir = REPO_ROOT / ".github" / "changelogs"
    cl_dir.mkdir(parents=True, exist_ok=True)

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id[:16])
    filename = cl_dir / f"changelog_{AI_MODEL}_session_{safe_id}.md"

    date_str = timestamp[:10]  # YYYY-MM-DD

    # Guess description from first user request
    desc = "Session changes"
    if summary["user_requests"]:
        desc = summary["user_requests"][0][:80].rstrip()

    changed_block = "\n".join(
        f"- {_short_path(f)}" for f in (summary["files_modified"] or ["(none)"])
    )
    bash_block = "\n".join(
        f"- {op}" for op in (summary["git_ops"] or ["(none)"])
    )

    git = _git_info()

    content = f"""\
## [{date_str}] — {desc}

**AI Model:** {AI_MODEL} | **Agent ID:** session_{safe_id}
**Compact trigger:** {trigger}
**Branch:** {git['branch']} | **Last commit:** {git['last_commit']}

### Changed
{changed_block}

### Fixed
- (see session transcript)

### Removed
- (none recorded)

### Verified
- Git operations: {bash_block}
"""

    tmp = filename.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, filename)
    return filename


# ─── git helpers ──────────────────────────────────────────────────────────────

def git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd if cwd is not None else REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def commit_and_push(files: list[Path], session_id: str) -> bool:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id[:16])

    # Stage files
    for f in files:
        code, out = git(["add", str(f.relative_to(REPO_ROOT))])
        if code != 0:
            print(f"[PreCompact] git add failed for {f.name}: {out}", file=sys.stderr)
            return False

    # Check if there's anything to commit
    code, status = git(["status", "--porcelain"])
    if not status.strip():
        print("[PreCompact] Nothing to commit — docs already up to date.", file=sys.stderr)
        return True

    # Commit
    msg = f"docs: auto-save session memory/changelog before compact [{safe_id}]"
    code, out = git(["commit", "-m", msg])
    if code != 0:
        print(f"[PreCompact] git commit failed: {out}", file=sys.stderr)
        return False

    # Push
    code, out = git(["push"])
    if code != 0:
        print(f"[PreCompact] git push failed: {out}", file=sys.stderr)
        return False

    print(f"[PreCompact] Committed and pushed session docs ({safe_id[:8]})", file=sys.stderr)
    return True


# ─── logging ──────────────────────────────────────────────────────────────────

def log_event(input_data: dict, note: str = "") -> None:
    try:
        log_dir = Path.home() / ".claude" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "pre_compact.jsonl"  # JSONL — append-only, never read back
        entry = {
            **{k: v for k, v in input_data.items() if k != "transcript_path"},
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_compact_snapshot(session_id: str, trigger: str) -> None:
    """Append a compact event to ~/.claude/data/compact_log.jsonl.

    Records a tiny, append-only memory snapshot: timestamp + session_id + trigger.
    Lets us track when compactions happened across sessions.
    """
    try:
        data_dir = Path.home() / ".claude" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = data_dir / "compact_log.jsonl"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "trigger": trigger,
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─── backup (optional) ────────────────────────────────────────────────────────

def backup_transcript(transcript_path: str, trigger: str) -> None:
    try:
        if not transcript_path or not os.path.exists(transcript_path):
            return
        backup_dir = Path.home() / ".claude" / "logs" / "transcript_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = Path(transcript_path).stem
        dest = backup_dir / f"{stem}_pre_compact_{trigger}_{ts}.jsonl"
        shutil.copy2(transcript_path, dest)
    except Exception:
        pass


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    global REPO_ROOT
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    # Resolve repo root from the hook input's cwd (fall back to env var / cwd()).
    # This is CRITICAL — using Path(__file__).resolve().parents[2] would point
    # at ~/.claude (since this file lives in ~/.claude/hooks/), not the project.
    repo_root_str = (
        input_data.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    REPO_ROOT = Path(repo_root_str).resolve()

    session_id       = input_data.get("session_id", "unknown")
    transcript_path  = input_data.get("transcript_path", "")
    trigger          = input_data.get("trigger", "auto")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(
        f"[PreCompact] trigger={trigger} session={session_id[:8]}... "
        f"Writing session docs…",
        file=sys.stderr,
    )

    # Record a compact-event snapshot early so it's captured even if
    # transcript parsing or git ops later fail.
    log_compact_snapshot(session_id, trigger)

    try:
        # 1. Parse transcript
        summary = parse_transcript(transcript_path)

        # 2. Write memory + changelog
        mem_file = write_memory(session_id, trigger, summary, timestamp)
        cl_file  = write_changelog(session_id, trigger, summary, timestamp)

        # 3. Commit and push
        commit_and_push([mem_file, cl_file], session_id)

        # 4. Backup transcript
        backup_transcript(transcript_path, trigger)

        log_event(input_data, note="docs written and pushed")

    except Exception as exc:
        # Fail-open: never block compaction
        print(f"[PreCompact] Error writing session docs: {exc}", file=sys.stderr)
        log_event(input_data, note=f"error: {exc}")

    sys.exit(0)


if __name__ == "__main__":
    main()
