---
description: Creates a concise engineering implementation plan (solo by default; auto-spawns team orchestration when the task is complex or the user asks for "with team")
argument-hint: [user prompt] [--team] [orchestration prompt]
model: inherit
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, ToolSearch
---

# Plan

Create a concise engineering implementation plan based on the user's requirements, then save it to `PLAN_OUTPUT_DIRECTORY/<name-of-plan>.md`. This single command covers both solo planning and team-orchestrated planning.

## Variables

- `USER_PROMPT`: `$1`
- `ORCHESTRATION_PROMPT`: `$2` — optional guidance for team assembly, task granularity, and execution strategy (only consumed in team mode)
- `PLAN_OUTPUT_DIRECTORY`: `specs/`
- `TEAM_MEMBERS`: `.claude/agents/team/*.md`
- `GENERAL_PURPOSE_AGENT`: `general-purpose`

## Mode Selection

Run in **solo mode** by default. Switch to **team mode** when ANY of these are true:

1. The user passes `--team`, `-t`, or explicitly says "with team" / "w/ team" / "plan w team" / "orchestrated" / "multi-agent".
2. The task complexity is judged `complex` AND scope crosses multiple domains (backend + frontend + infra, etc.).
3. An `ORCHESTRATION_PROMPT` (`$2`) is provided.

In solo mode, skip the Team Orchestration sections and produce a simple plan. In team mode, include the Team Orchestration + Team Members sections and fully elaborate task IDs, dependencies, and owners.

## Instructions

- **PLANNING ONLY**: Do NOT build, write code, or deploy agents. Your only output is a plan document saved to `PLAN_OUTPUT_DIRECTORY`.
- IMPORTANT: If no `USER_PROMPT` is provided, stop and ask the user to provide it.
- Carefully analyze the user's requirements in `USER_PROMPT`.
- Determine task type (`chore|feature|refactor|fix|enhancement`) and complexity (`simple|medium|complex`).
- Think deeply (ultrathink) about the best approach.
- Understand the codebase directly (no sub-agents) to match existing patterns and architecture.
- Follow the Plan Format below, including conditional sections based on task type, complexity, and mode.
- Generate a descriptive, kebab-case filename based on the main topic.
- Save the plan to `PLAN_OUTPUT_DIRECTORY/<descriptive-name>.md`.
- Ensure the plan is detailed enough that another developer could follow it.
- Include code examples or pseudo-code where helpful.
- Consider edge cases, error handling, and scalability.
- In team mode, understand your role as the team lead — refer to the Team Orchestration section.

### Team Orchestration (team mode only)

As the team lead you never write code directly — you orchestrate via tools.

#### Task Management Tools

**TaskCreate** — create tasks in the shared list:
```typescript
TaskCreate({
  subject: "Implement user authentication",
  description: "Create login/logout endpoints with JWT tokens. See specs/auth-plan.md for details.",
  activeForm: "Implementing authentication"
})
```

**TaskUpdate** — update status, assignment, or dependencies:
```typescript
TaskUpdate({ taskId: "1", status: "in_progress", owner: "builder-auth" })
```

**TaskList / TaskGet** — inspect tasks.

#### Dependencies & Owners

```typescript
TaskUpdate({ taskId: "2", addBlockedBy: ["1"] })
TaskUpdate({ taskId: "3", addBlockedBy: ["1", "2"] })
TaskUpdate({ taskId: "1", owner: "builder-api" })
```

#### Agent Deployment (Task tool)

```typescript
Task({
  description: "Implement auth endpoints",
  prompt: "...",
  subagent_type: "general-purpose",
  model: "inherit",
  run_in_background: false
})
```

Use `resume: "<agentId>"` to continue with preserved context, and `run_in_background: true` plus `TaskOutput` for parallel execution.

#### Orchestration Workflow

1. `TaskCreate` each step.
2. `TaskUpdate` + `addBlockedBy` for dependencies.
3. `TaskUpdate` + `owner` for assignments.
4. `Task` to deploy agents.
5. Monitor with `TaskList` / `TaskOutput`.
6. Resume via `Task` + `resume`.
7. Close with `TaskUpdate` + `status: "completed"`.

## Workflow

IMPORTANT: **PLANNING ONLY** — no execution, no builds, no deploys.

1. Analyze Requirements — parse `USER_PROMPT`.
2. Understand Codebase — review existing patterns and relevant files directly.
3. Decide Mode — solo vs. team (see Mode Selection).
4. Design Solution — architecture decisions + implementation strategy.
5. Team mode only: Define Team Members from `TEAM_MEMBERS` or fall back to `GENERAL_PURPOSE_AGENT`. Use `ORCHESTRATION_PROMPT` if present.
6. Define Step by Step Tasks — solo lists actions; team mode adds Task ID / Depends On / Assigned To / Agent Type / Parallel.
7. Generate Filename — kebab-case.
8. Save Plan — write to `PLAN_OUTPUT_DIRECTORY/<filename>.md`.
9. Report — follow the Report section.

## Plan Format

IMPORTANT: Replace `<requested content>` with the requested content. Everything else must appear verbatim.

```md
# Plan: <task name>

## Task Description
<describe the task in detail based on the prompt>

## Objective
<clearly state what will be accomplished when this plan is complete>

<if task_type is feature or complexity is medium/complex, include these sections:>
## Problem Statement
<clearly define the specific problem or opportunity this task addresses>

## Solution Approach
<describe the proposed solution approach and how it addresses the objective>
</if>

## Relevant Files
Use these files to complete the task:

<list files relevant to the task with bullet points explaining why. Include new files to be created under an h3 'New Files' section if needed>

<if complexity is medium/complex, include this section:>
## Implementation Phases
### Phase 1: Foundation
<describe any foundational work needed>

### Phase 2: Core Implementation
<describe the main implementation work>

### Phase 3: Integration & Polish
<describe integration, testing, and final touches>
</if>

<if mode is team, include these sections:>
## Team Orchestration

- You operate as the team lead and orchestrate the team to execute the plan.
- You NEVER operate directly on the codebase. You use `Task` and `Task*` tools to deploy team members.
- Your role is high-level director: validate work, keep the team on track, communicate via `Task*` tools.
- Take note of the session id of each team member — that's how you reference them.

### Team Members
<list the team members used to execute the plan>

- Builder
  - Name: <unique name — other members reference this builder by name>
  - Role: <single focus of this builder>
  - Agent Type: <subagent type from TEAM_MEMBERS or GENERAL_PURPOSE_AGENT>
  - Resume: <default true>
- <continue with additional team members as needed>
</if>

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom. <if team mode> Each task maps directly to a `TaskCreate` call. Before starting, run `TaskCreate` to seed the shared task list. </if>

<list step by step tasks as h3 headers. Start with foundational changes then move to specific changes. Last step should validate the work.>

### 1. <First Task Name>
<if team mode:>
- **Task ID**: <unique kebab-case identifier>
- **Depends On**: <Task IDs or "none">
- **Assigned To**: <team member name>
- **Agent Type**: <subagent type>
- **Parallel**: <true/false>
</if>
- <specific action>
- <specific action>

### 2. <Second Task Name>
<if team mode: include the same metadata block>
- <specific action>
- <specific action>

<continue with additional tasks as needed>

<if task_type is feature or complexity is medium/complex, include this section:>
## Testing Strategy
<describe testing approach, including unit tests and edge cases as applicable>
</if>

## Acceptance Criteria
<list specific, measurable criteria that must be met for the task to be considered complete>

## Validation Commands
Execute these commands to validate the task is complete:

<list specific commands to validate the work. Be precise about what to run>
- Example: `uv run python -m py_compile apps/*.py` - Test to ensure the code compiles

## Notes
<optional additional context, considerations, or dependencies. If new libraries are needed, specify using `uv add`>
```

## Report

After creating and saving the implementation plan, provide a concise report:

```
Implementation Plan Created

File: PLAN_OUTPUT_DIRECTORY/<filename>.md
Mode: <solo | team>
Topic: <brief description of what the plan covers>
Key Components:
- <main component 1>
- <main component 2>
- <main component 3>

<if team mode:>
Team Task List:
- <list of tasks and owners (concise)>

Team members:
- <list of team members and roles (concise)>
</if>

When you're ready, execute the plan in a new agent by running:
/build <path to plan>
```
