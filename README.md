# Claude-Hooks — Specification Archive

This folder is the **version archive** for the "Token-Efficient Hook Automation System
for Claude Code" specification: a user-level (`~/.claude/`) hook layer that offloads
deterministic work (formatting, guarding, testing, validation, cleanup, limit
monitoring) from the LLM to shell scripts, returning only compact ≤500-token reports
to the model.

## Canonical vs. archive

The **canonical spec lives with the implementation**: `~/.claude/hooks/SPEC.md`
(currently **v15**). The copies here are archives — when a copy and the canonical
file differ, the canonical file wins. The archive is refreshed on every version bump.

The **reference implementation** (built July 2026 on Claude Code 2.1.208,
Alpine/BusyBox under WSL2) lives in `~/.claude/hooks/`: 13 hook scripts, a 7-module
shared library, 5 validators, layered config, fixtures with captured real payloads,
and a 66-assertion test suite (`~/.claude/hooks/test/run.sh`).

## Files

| File | What it is |
|---|---|
| `Improved Hooks .md` | Base version — compact prose spec. Had the statusline-bridge limit architecture **right**. |
| `Improved Hooks v2 .md` … `v5.md` | Formalization passes: executive summary, report contract, merge rules, project keys, portability. |
| `Improved Hooks v6.md` | Added failure/compaction events; **regressed** statusline output to stderr. |
| `Improved Hooks v7.md` | Reverted to stdout; full event catalog; settings schema detail. |
| `Improved Hooks v9 .md` | Added dynamic LLM-maintained context files (contains `[cite]` generation artifacts). |
| `Improved Hooks v10.md` | Formal spec structure — and **inverted** the limit architecture the base had right. |
| `Improved Hooks V11.md` | file_map, last_status.json, merge rules; **regressed** `if` syntax to regex. |
| `Improved Hooks V12.md` | Incremental fixes; carried forward the v10/v11 defects. |
| `Improved Hooks spec review.md` | **Review of base + v10–v12** (2026-07-14): found the inverted architecture, regex `if`, misplaced format.sh, unwired bridge, unsafe `.env` sourcing → produced the v13 fix list. |
| `Improved Hooks v13.md` | Correctness pass executing that fix list, verified against live docs. |
| `Improved Hooks v14.md` | Post-implementation fixes: guard `if`-filter coverage, statusline performance split; empirical confirmations (`stop_hook_active`, statusline payload shape). |
| `Improved Hooks v14 spec review.md` | **Review of v14** against all prior versions + the running implementation → produced the v15 fix list. |
| `Improved Hooks v15.md` | **Current.** All eight review items: verified `Bash(*/dev/*)` filter, executable §10.E coverage test, canonical-location declaration, `[live-session]` tags, min/full validator probe split, cold-start budget, cited history, and the rule-14 evidence-tag convention. |

## The lesson this series encodes

Three independent correct claims were each "corrected" into wrong ones by revision
passes working from memory (stdout→stderr→stdout across v5→v6→v7; the limit
architecture inverted in v10; `if` regressed to regex in v11). A spec claim without
recorded evidence had a half-life of about two revisions. The cycle stopped when
claims became **cited or executable**: v13 verified against live docs, v14 against
captured payloads and a built system, v15 made the conventions themselves rules —
every schema claim carries `[docs YYYY-MM-DD]`, `[captured <fixture/probe>]`, or
`[UNVERIFIED]`, and wiring-coverage rules are enforced by a test, not a reviewer.
