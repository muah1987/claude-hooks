---
description: Schedule a one-shot task or check to run at a future time in this session
argument-hint: <task description> in <N mins|hours> | at <HH:MM>
allowed-tools: Bash, Read
---

# Trigger (Scheduled Task)

Schedule `TASK` as a one-shot reminder or automated check at the specified future time.

## Variables

TASK: $ARGUMENTS

## Instructions

- Parse `TASK` to extract:
  1. **What** to do (e.g., "check deploy.yml", "run tests", "verify the server is healthy")
  2. **When** to do it (e.g., "in 10 mins", "in 1 hour", "at 15:30")

- If no time is specified, ask the user when they want it triggered.

- Calculate the cron expression for a **one-shot job** (`recurring: false`):
  - Get the current local time (use `date '+%M %H %d %m'` via Bash)
  - Add the offset to get the target minute, hour, day-of-month, month
  - Format as `"M H D Mon *"` with all four fields pinned
  - Avoid :00 and :30 minutes — offset by ±1 minute if the target lands on those

- Use CronCreate with:
  - `cron`: the calculated expression
  - `recurring: false` (fires once then auto-deletes)
  - `prompt`: a clear, actionable instruction for what Claude should do at fire time
    - Include enough context so Claude can act without prior conversation
    - For workflow checks: "Check GitHub Actions workflow status for muah1987/Alhashimifoundation — run `gh run list --repo muah1987/Alhashimifoundation --limit 5` and report the result"
    - For deploy checks: "Check if the deploy workflow completed — run `gh run list --repo muah1987/Alhashimifoundation --workflow deploy.yml --limit 3` and report status"
    - For VPS health: "SSH to the VPS at 51.195.86.239 (ubuntu / paramiko) and check container health via `docker ps`"

- After creating the job, confirm to the user:
  - What will run
  - Exactly when (human-readable time, e.g., "at 14:37 today")
  - The job ID (so they can cancel it with `/cron-cancel <id>` if needed)

## Example Parses

| Input | What | When | Cron |
|-------|------|------|------|
| `check deploy.yml in 10 mins` | check deploy.yml workflow status | +10 min | `<now+10>M H D Mon *` |
| `verify server health in 30 mins` | check VPS docker ps | +30 min | `<now+30>M H D Mon *` |
| `run tests in 1 hour` | run `npm test` in backend dir | +60 min | `<now+60>M H D Mon *` |
| `check ci in 15 mins` | check latest CI workflow run | +15 min | `<now+15>M H D Mon *` |

---

## Durable Cross-Session Triggers

For tasks that must persist **across session restarts** (cron jobs die when the session ends), use `RemoteTrigger` instead:

```typescript
// Create a durable remote trigger (OAuth-authenticated, HTTP-based)
RemoteTrigger({ action: "create", body: {
  cron: "0 9 * * 1",          // every Monday 09:00
  prompt: "...",
  recurring: true
}})

// List all remote triggers
RemoteTrigger({ action: "list" })

// Run one immediately
RemoteTrigger({ action: "run", trigger_id: "<id>" })
```

Or use the `/schedule` skill for a guided workflow.
