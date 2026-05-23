---
description: Check or update Claude.ai plan usage limits (session %, weekly all-models %, weekly Sonnet %). Trigger on phrases like "show usage", "check plan limits", "update usage", "how much of my plan have I used", "session limit", "weekly limit", "sonnet limit".
allowed-tools: Bash, Read
---

# /usage — Claude.ai plan usage limits

Use this skill to inspect or refresh the cached plan-usage percentages that
power the status line segment `S:… W:… Sn:…`. The cache lives at
`~/.claude/data/usage_limits.json` and is normally refreshed on every
SessionStart via `fetch_profile.py`.

Three shapes of data are tracked:

| Key | Meaning |
| --- | --- |
| `session.pct` | Current 5-hour session usage (%). |
| `weekly_all.pct` | Rolling 7-day usage across all models (%). |
| `weekly_sonnet.pct` | Rolling 7-day usage specifically for Sonnet (%). |

## How to invoke

Always shell out via the Bash tool — never edit the JSON by hand.

### Show the current cache

```bash
uv run ~/.claude/scripts/fetch_usage.py show
```

Pretty-prints the cache as JSON. If nothing has been cached yet prints
`no usage cache`.

### Manually update from a free-text paste

When the user pastes numbers from the claude.ai web UI (the network API
is often unreachable from WSL2), feed the text to `update`:

```bash
uv run ~/.claude/scripts/fetch_usage.py update "Current session: 15% used, resets in 3h 56m. Weekly all: 31%. Sonnet: 26%"
```

Other accepted shapes:

```bash
uv run ~/.claude/scripts/fetch_usage.py update "15% session, 31% weekly, 26% sonnet"
uv run ~/.claude/scripts/fetch_usage.py update "session=15 weekly=31 sonnet=26 resets=3h56m"
```

Prints a single line like `updated: session=15%, weekly=31%, sonnet=26%`.
The cache is written with `"source": "manual"`.

### Force a network re-fetch

```bash
uv run ~/.claude/scripts/fetch_usage.py fetch
```

Tries the documented claude.ai rate-limit endpoints. Prints `fetched` if
usable data was received, else `unavailable`. Always exits 0. Diagnostic
HTTP statuses and response snippets are logged to stderr.

## Status-line integration

The v7 status line renders a compact segment:

```
S:15% W:31% Sn:26% ↻3h56m
```

- `S` = session, `W` = weekly all models, `Sn` = weekly Sonnet.
- Color: green <50%, yellow 50-75%, red 75-90%, bright red >90%.
- Trailing `↻…` shows session reset countdown (yellow if <60m, dim otherwise).
- If the cache is missing or >30 min stale the segment is silently omitted.

## Safety rules

- Do NOT attempt to read or write `~/.claude/data/usage_limits.json` directly;
  always go through `fetch_usage.py` so the schema stays in sync with the
  status line.
- Never echo the OAuth access token — the fetcher reads it from
  `~/.claude/.credentials.json` internally.
- `fetch` may fail silently in restricted network environments (WSL2,
  corporate proxies). In that case ask the user to paste their current
  numbers from the claude.ai web UI and use `update`.
