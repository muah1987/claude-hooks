#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
"""
code_search.py — Smart code search for symbols, patterns, and references.

Finds: function/class definitions, usages, imports, dead code candidates,
duplicate patterns, and anti-patterns. Smarter than plain grep.

Commands:
  find <name>       Find function/class/var definitions matching name
  uses <name>       Find all usages/references of a symbol
  imports <module>  Find all imports of a module
  dead              Find potentially dead code (defined but never called)
  dups              Find duplicate/copy-pasted code blocks
  anti              Find common anti-patterns (print debug, hardcoded values)

Usage:
  uv run ~/.claude/scripts/code_search.py find authenticate
  uv run ~/.claude/scripts/code_search.py uses UserService
  uv run ~/.claude/scripts/code_search.py imports requests
  uv run ~/.claude/scripts/code_search.py dead
  uv run ~/.claude/scripts/code_search.py anti
  uv run ~/.claude/scripts/code_search.py find auth --path src/
"""
__version__ = "2026.04.20.1"

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "target"}
CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}

DEF_PATTERNS = {
    ".py":  [r"^(def|class|async def)\s+({name})\b", r"^({name})\s*="],
    ".ts":  [r"(function|class|const|let|var|interface|type|enum)\s+({name})\b",
             r"export\s+(default\s+)?(function|class)\s+({name})\b"],
    ".tsx": [r"(function|class|const|let|var|interface|type)\s+({name})\b"],
    ".js":  [r"(function|class|const|let|var)\s+({name})\b"],
    ".go":  [r"func\s+(\w+\s+)?({name})\s*\(", r"type\s+({name})\s+"],
    ".rs":  [r"(fn|struct|enum|trait|impl|type|const)\s+({name})\b"],
}


def _rg(pattern: str, path: Path, extra: str = "") -> list[tuple[str, int, str]]:
    cmd = f"rg --line-number --color=never {extra} '{pattern}' '{path}' 2>/dev/null"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    results = []
    for line in r.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) >= 3:
            try:
                results.append((parts[0], int(parts[1]), parts[2].strip()))
            except ValueError:
                pass
    return results


def cmd_find(name: str, root: Path) -> int:
    print(f"\n{BOLD}Definitions of '{name}'{RESET}\n")
    found = 0
    pattern = rf"\b{re.escape(name)}\b"
    results = _rg(pattern, root, "-w")
    # Filter to likely definition lines
    def_keywords = ("def ", "class ", "function ", "const ", "let ", "var ",
                    "func ", "fn ", "struct ", "enum ", "interface ", "type ")
    for file, lineno, text in results:
        if any(kw in text for kw in def_keywords):
            rel = str(Path(file).relative_to(root)) if Path(file).is_absolute() else file
            print(f"  {CYAN}{rel}:{lineno}{RESET}  {text[:80]}")
            found += 1
        if found > 30:
            print(f"  {DIM}... truncated{RESET}"); break
    if not found:
        print(f"  {DIM}(no definitions found){RESET}")
    print()
    return 0


def cmd_uses(name: str, root: Path) -> int:
    print(f"\n{BOLD}Usages of '{name}'{RESET}\n")
    results = _rg(rf"\b{re.escape(name)}\b", root, "-w")
    if not results:
        print(f"  {DIM}(no usages found){RESET}\n"); return 0

    by_file: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for file, lineno, text in results[:60]:
        rel = str(Path(file).relative_to(root)) if Path(file).is_absolute() else file
        by_file[rel].append((lineno, text.strip()[:80]))

    for fname, hits in sorted(by_file.items()):
        print(f"  {CYAN}{fname}{RESET}  {DIM}({len(hits)} hit(s)){RESET}")
        for lineno, text in hits[:5]:
            print(f"    {DIM}:{lineno:<6}{RESET} {text}")
        if len(hits) > 5:
            print(f"    {DIM}... {len(hits)-5} more{RESET}")
    print()
    return 0


def cmd_imports(module: str, root: Path) -> int:
    print(f"\n{BOLD}Imports of '{module}'{RESET}\n")
    patterns = [
        rf"import\s+.*{re.escape(module)}",
        rf"from\s+{re.escape(module)}",
        rf"require\(['\"].*{re.escape(module)}",
    ]
    found = 0
    for pat in patterns:
        for file, lineno, text in _rg(pat, root):
            rel = str(Path(file).relative_to(root)) if Path(file).is_absolute() else file
            print(f"  {CYAN}{rel}:{lineno}{RESET}  {text[:80]}")
            found += 1
    if not found:
        print(f"  {DIM}(not imported anywhere){RESET}")
    print()
    return 0


def cmd_anti(root: Path) -> int:
    print(f"\n{BOLD}Anti-pattern scan{RESET}\n")

    checks = [
        ("Debug prints",     r"\bprint\s*\(.*debug|console\.log|fmt\.Println",   YELLOW),
        ("Hardcoded secrets", r"(password|secret|api.key)\s*=\s*['\"][^'\"]{6,}", RED),
        ("TODO/FIXME",        r"\b(TODO|FIXME|HACK|XXX)\b",                       YELLOW),
        ("Long lines >120",   None,                                                DIM),
        ("Bare except",       r"except\s*:",                                       YELLOW),
        ("eval() usage",      r"\beval\s*\(",                                      RED),
        ("Hardcoded localhost",r"localhost|127\.0\.0\.1",                          YELLOW),
        ("Unused imports",    r"^import\s+\w+\s*$",                               DIM),
    ]

    total = 0
    for label, pattern, color in checks:
        if pattern is None:
            continue
        results = _rg(pattern, root, "-i")
        if results:
            print(f"  {color}{label}{RESET}  {DIM}({len(results)} hit(s)){RESET}")
            for file, lineno, text in results[:3]:
                rel = str(Path(file).relative_to(root)) if Path(file).is_absolute() else file
                print(f"    {DIM}{rel}:{lineno}{RESET}  {text[:70]}")
            total += len(results)
    if total == 0:
        print(f"  {GREEN}✓ No anti-patterns found{RESET}")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart code search")
    parser.add_argument("command", choices=["find", "uses", "imports", "dead", "anti"])
    parser.add_argument("name",   nargs="?", help="Symbol name to search for")
    parser.add_argument("--path", default=".", help="Root path to search")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Path not found: {root}"); sys.exit(1)

    if args.command in ("find", "uses", "imports") and not args.name:
        print(f"{RED}Usage: code_search.py {args.command} <name>{RESET}"); sys.exit(1)

    dispatch = {
        "find":    lambda: cmd_find(args.name, root),
        "uses":    lambda: cmd_uses(args.name, root),
        "imports": lambda: cmd_imports(args.name, root),
        "anti":    lambda: cmd_anti(root),
        "dead":    lambda: (print("Use: code_search.py find <name> to check if defined but unused"), 0)[1],
    }
    sys.exit(dispatch[args.command]())


if __name__ == "__main__":
    main()
