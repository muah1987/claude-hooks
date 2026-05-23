# Claude Code Hooks Documentation

This document provides comprehensive documentation for all hooks in this project, following the GOTCHA Framework integration patterns.

## Table of Contents

- [Overview](#overview)
- [Hook Events](#hook-events)
- [Input/Output Specification](#inputoutput-specification)
- [Individual Hook Documentation](#individual-hook-documentation)
  - [PreToolUse](#pretooluse)
  - [PostToolUse](#posttooluse)
  - [PostToolUseFailure](#posttoolusefailure)
  - [PermissionRequest](#permissionrequest)
  - [Notification](#notification)
  - [UserPromptSubmit](#userpromptsubmit)
  - [Stop](#stop)
  - [SubagentStart](#subagentstart)
  - [SubagentStop](#subagentstop)
  - [PreCompact](#precompact)
  - [Setup](#setup)
  - [SessionStart](#sessionstart)
  - [SessionEnd](#sessionend)
  - [TeammateIdle](#teammateidle)
  - [TaskCompleted](#taskcompleted)
- [Status Lines Documentation](#status-lines-documentation)
- [settings.json Configuration Examples](#settingsjson-configuration-examples)

---

## Overview

Claude Code hooks are Python scripts that run at specific points during Claude Code's execution lifecycle. They enable:

- **Logging and auditing** - Track all tool usage, sessions, and events
- **Security guardrails** - Block dangerous operations before execution
- **Automation** - Auto-approve safe operations, inject context
- **Notifications** - TTS announcements when user input is needed
- **Session management** - Track session state and memory

All hooks in this project follow the **GOTCHA Framework** principles:
- **Goals** - What needs to happen
- **Orchestration** - AI coordination
- **Tools** - Deterministic script execution
- **Context** - Reference material
- **Hard prompts** - Instruction templates
- **Args** - Behavior settings

### Exit Code Behavior

| Exit Code | Behavior |
|-----------|----------|
| 0 | Success - JSON output (if any) is processed |
| 2 | Blocking error - stderr shown to Claude, operation blocked |
| Other | Non-blocking error - stderr shown in verbose mode only |

---

## Hook Events

| Hook Event | When It Runs |
|------------|--------------|
| **PreToolUse** | Before a tool executes |
| **PostToolUse** | After a tool completes successfully |
| **PostToolUseFailure** | After a tool execution fails |
| **PermissionRequest** | When user is shown a permission dialog |
| **Notification** | When Claude Code sends notifications |
| **UserPromptSubmit** | Before Claude processes user prompt |
| **Stop** | When Claude finishes responding |
| **SubagentStart** | When a subagent is spawned |
| **SubagentStop** | When a subagent finishes |
| **PreCompact** | Before context compaction |
| **Setup** | When invoked with --init or --maintenance flags |
| **SessionStart** | When a session starts or resumes |
| **SessionEnd** | When a session ends |
| **TeammateIdle** | When a teammate agent becomes idle (multi-agent sessions) |
| **TaskCompleted** | When an async task completes |

---

## Input/Output Specification

### Common Input Fields (All Hooks)

All hooks receive JSON via stdin with these common fields:

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "HookName"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique session identifier |
| `transcript_path` | string | Path to conversation transcript JSON |
| `cwd` | string | Current working directory |
| `permission_mode` | string | One of: "default", "plan", "acceptEdits", "dontAsk", "bypassPermissions" |
| `hook_event_name` | string | Name of the hook event |

### Common Output Fields

```json
{
  "continue": true,
  "stopReason": "...",
  "suppressOutput": false,
  "systemMessage": "...",
  "hookSpecificOutput": {
    "hookEventName": "HookName",
    "additionalContext": "..."
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `continue` | boolean | If false, stops Claude |
| `stopReason` | string | Message shown when continue is false |
| `suppressOutput` | boolean | Hide stdout from transcript mode |
| `systemMessage` | string | Warning message shown to user |
| `hookSpecificOutput` | object | Hook-specific output data |

---

## Individual Hook Documentation

### PreToolUse

**File:** `pre_tool_use.py`

**Purpose:** Validates tool use before execution, enforcing security guardrails and optionally auto-approving safe operations.

**When it runs:** Before any tool executes

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "ls -la"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of the tool being called (Bash, Read, Write, etc.) |
| `tool_input` | object | Tool-specific input parameters |

**Output JSON Format:**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "permissionDecisionReason": "Read-only operation auto-approved",
    "updatedInput": {},
    "additionalContext": "..."
  }
}
```

| Output Field | Values | Description |
|--------------|--------|-------------|
| `permissionDecision` | "allow" / "deny" / "ask" | Controls whether tool executes |
| `permissionDecisionReason` | string | Explanation for the decision |
| `updatedInput` | object | Modified tool inputs before execution |
| `additionalContext` | string | Context added before tool executes |

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--auto-approve` | Auto-approve safe read operations (Glob, Grep, safe Read) |
| `--add-context` | Add additional context information to tool execution |
| `--context-message <msg>` | Custom context message (used with --add-context) |
| `--strict` | Enable strict mode - ask confirmation on risky operations |

**Example Usage:**

```bash
# Auto-approve safe operations
echo '{"tool_name": "Glob", "tool_input": {"pattern": "*.py"}}' | python pre_tool_use.py --auto-approve

# Strict mode for all writes
echo '{"tool_name": "Write", "tool_input": {}}' | python pre_tool_use.py --strict
```

**Guardrails Enforced:**
- Blocks .env file access (sensitive data protection)
- Blocks dangerous `rm -rf` commands (prevents data loss)

---

### PostToolUse

**File:** `post_tool_use.py`

**Purpose:** Runs after a tool completes successfully, logging execution and optionally providing feedback to Claude.

**When it runs:** After a tool completes successfully

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_use_id": "tool_123",
  "tool_input": {},
  "tool_response": {}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of the executed tool |
| `tool_use_id` | string | Unique identifier for this tool use |
| `tool_input` | object | The tool's input parameters |
| `tool_response` | object | The tool's response/output |

**Output JSON Format:**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "decision": "proceed",
    "reason": "...",
    "additionalContext": "..."
  }
}
```

| Output Field | Values | Description |
|--------------|--------|-------------|
| `decision` | "proceed" / "block" | Whether to proceed with the result |
| `reason` | string | Required if decision is "block" |
| `additionalContext` | string | Optional feedback to Claude |

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--feedback <msg>` | Custom feedback message to provide to Claude |
| `--block-on-error` | Block tool results that contain error indicators |
| `--log-response` | Log the tool response data (default: True) |
| `--max-response-log-size <n>` | Maximum characters to log from response (default: 1000) |

**Example Usage:**

```bash
# Add feedback after tool execution
echo '{"tool_name": "Bash", "tool_response": {}}' | python post_tool_use.py --feedback "Check output for errors"

# Block on error responses
echo '{"tool_name": "Bash", "tool_response": {"error": "failed"}}' | python post_tool_use.py --block-on-error
```

---

### PostToolUseFailure

**File:** `post_tool_use_failure.py`

**Purpose:** Runs when a tool execution fails, logging detailed error information for debugging and continuous improvement.

**When it runs:** After a tool execution fails

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "Bash",
  "tool_use_id": "tool_123",
  "tool_input": {},
  "error": {
    "message": "Command failed with exit code 1"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of the failed tool |
| `tool_use_id` | string | Unique identifier for this tool use |
| `tool_input` | object | The tool's input parameters |
| `error` | object | Error details from the failure |

**Output JSON Format:** None - this hook only logs failures

**Command Line Arguments:** None

**Example Usage:**

```bash
echo '{"tool_name": "Bash", "error": {"message": "Failed"}}' | python post_tool_use_failure.py
```

---

### PermissionRequest

**File:** `permission_request.py`

**Purpose:** Triggered when the user is shown a permission dialog, can automatically allow or deny requests.

**When it runs:** When user is shown a permission dialog

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": {
    "command": "ls -la"
  },
  "tool_use_id": "tool_123"
}
```

**Output JSON Format:**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedInput": {},
      "message": "...",
      "interrupt": false
    }
  }
}
```

| Decision Field | Type | Description |
|----------------|------|-------------|
| `behavior` | "allow" / "deny" | Allow or deny the permission |
| `updatedInput` | object | (allow only) Modified tool input |
| `message` | string | (deny only) Explanation shown to Claude |
| `interrupt` | boolean | (deny only) If true, stops Claude after denying |

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--auto-allow` | Auto-allow read-only operations (Read, Glob, Grep, safe Bash) |
| `--log-only` | Only log permission requests, do not make decisions |

**Example Usage:**

```bash
# Auto-allow read operations
echo '{"tool_name": "Read", "tool_input": {"file_path": "README.md"}}' | python permission_request.py --auto-allow

# Log only mode
echo '{"tool_name": "Bash", "tool_input": {}}' | python permission_request.py --log-only
```

**Safe Bash Commands Auto-Allowed:**
- `ls`, `pwd`, `echo`, `cat` (without redirection)
- `head`, `tail`, `wc`, `which`, `whereis`, `type`, `file`, `stat`
- `git status/log/diff/show/branch/tag`
- `npm list/ls/outdated/view`
- `pip list/show/freeze`
- Version commands (`python --version`, etc.)

---

### Notification

**File:** `notification.py`

**Purpose:** Runs when Claude Code sends notifications, providing TTS feedback at key interaction points.

**When it runs:** When Claude Code sends notifications

**Notification Types:**
- `permission_prompt` - Permission requests from Claude Code
- `idle_prompt` - When Claude is waiting for user input (60+ seconds idle)
- `auth_success` - Authentication success notifications
- `elicitation_dialog` - MCP tool elicitation dialogs

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "Notification",
  "message": "Claude needs your permission to use Bash",
  "notification_type": "permission_prompt"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | The notification message text |
| `notification_type` | string | Type of notification |

**Output JSON Format:** None - this hook only logs and announces

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--notify` | Enable TTS notifications for user feedback |
| `--filter-type <types>` | Only process specific notification types (comma-separated) |

**Example Usage:**

```bash
# Enable TTS for permission prompts
echo '{"notification_type": "permission_prompt", "message": "Permission needed"}' | python notification.py --notify

# Filter to specific types
echo '{"notification_type": "idle_prompt"}' | python notification.py --filter-type permission_prompt,idle_prompt
```

---

### UserPromptSubmit

**File:** `user_prompt_submit.py`

**Purpose:** Processes user prompts before Claude processes them, supporting the memory protocol and prompt validation.

**When it runs:** Before Claude processes user prompt

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "User's input text"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `prompt` | string | The user's submitted prompt |

**Output JSON Format:**

Block prompt:
```json
{
  "decision": "block",
  "reason": "Prompt blocked: security violation"
}
```

Add context:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Current time: 2024-01-15 10:30:00"
  }
}
```

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--validate` | Enable prompt validation |
| `--log-only` | Only log prompts, no validation or blocking |
| `--store-last-prompt` | Store the last prompt for status line display |
| `--name-agent` | Generate an agent name for the session |
| `--add-context <msg>` | Inject additional context via JSON output |

**Example Usage:**

```bash
# Validate and potentially block prompts
echo '{"prompt": "rm -rf /", "session_id": "abc"}' | python user_prompt_submit.py --validate

# Add context to prompt
echo '{"prompt": "Hello"}' | python user_prompt_submit.py --add-context "User is in production environment"
```

---

### Stop

**File:** `stop.py`

**Purpose:** Runs when Claude Code finishes responding, providing completion feedback and optional stop prevention.

**When it runs:** When Claude finishes responding

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "stop_hook_active": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `stop_hook_active` | boolean | True if a stop hook is currently running (CRITICAL for preventing infinite loops) |

**Output JSON Format:**

Allow stop:
```json
{}
```

Block stop:
```json
{
  "decision": "block",
  "reason": "Please confirm task completion"
}
```

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--chat` | Copy transcript to chat.json |
| `--notify` | Enable TTS completion announcement |
| `--prevent-stop` | Enable decision control to potentially block stopping |
| `--prevent-stop-reason <msg>` | Custom reason when blocking stop |

**Example Usage:**

```bash
# Announce completion via TTS
echo '{"session_id": "abc", "stop_hook_active": false}' | python stop.py --notify

# Prevent stop (requires confirmation)
echo '{"session_id": "abc", "stop_hook_active": false}' | python stop.py --prevent-stop
```

**Important:** Always check `stop_hook_active` when using `--prevent-stop` to prevent infinite loops.

---

### SubagentStart

**File:** `subagent_start.py`

**Purpose:** Runs when a Claude Code subagent is spawned, logging subagent creation for transparency.

**When it runs:** When a subagent is spawned

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "agent_id": "subagent-456",
  "agent_type": "task",
  "cwd": "/path/to/project",
  "permission_mode": "default"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Unique identifier for this subagent |
| `agent_type` | string | Type of subagent (e.g., "task", "research", "code") |

**Output JSON Format:** None - this hook only logs

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--notify` | Enable TTS announcement when subagent starts |

**Example Usage:**

```bash
echo '{"agent_id": "sub-1", "agent_type": "task"}' | python subagent_start.py --notify
```

---

### SubagentStop

**File:** `subagent_stop.py`

**Purpose:** Runs when a Claude Code subagent finishes responding, with AI-generated task summaries and TTS.

**When it runs:** When a subagent finishes responding

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "agent_id": "subagent-456",
  "agent_type": "task",
  "agent_transcript_path": "/path/to/subagent/transcript.jsonl",
  "stop_hook_active": false,
  "transcript_path": "/path/to/main/transcript.jsonl"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Unique identifier for the subagent |
| `agent_type` | string | Type of subagent |
| `agent_transcript_path` | string | Path to subagent's conversation transcript |
| `stop_hook_active` | boolean | True if stop hook is currently active |

**Output JSON Format:**

Block subagent stop:
```json
{
  "decision": "block",
  "reason": "Subagent stop prevented by hook"
}
```

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--chat` | Copy transcript to chat.json |
| `--notify` | Enable TTS completion announcement |
| `--summarize` | Generate AI summary of subagent task (default: on with --notify) |
| `--no-summarize` | Disable AI summary, use generic message |
| `--prevent-stop` | Enable decision control to prevent subagent stopping |
| `--prevent-reason <msg>` | Reason message when --prevent-stop is active |

**Example Usage:**

```bash
# Announce with AI summary
echo '{"agent_id": "sub-1", "stop_hook_active": false}' | python subagent_stop.py --notify --summarize

# Prevent subagent from stopping
echo '{"agent_id": "sub-1", "stop_hook_active": false}' | python subagent_stop.py --prevent-stop
```

---

### PreCompact

**File:** `pre_compact.py`

**Purpose:** Runs before Claude Code performs a compact operation, logging and optionally backing up transcripts.

**When it runs:** Before compaction occurs

**Triggers:**
- `manual` - User explicitly requested compaction via /compact
- `auto` - System triggered compaction due to context window limits

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "trigger": "manual",
  "custom_instructions": "Focus on code changes",
  "permission_mode": "default"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `trigger` | string | "manual" or "auto" |
| `custom_instructions` | string | User-provided instructions for compaction summary |

**Output JSON Format:** None - this hook only logs

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--backup` | Create backup of transcript before compaction |
| `--verbose` | Print verbose output |

**Example Usage:**

```bash
# Backup transcript before compaction
echo '{"trigger": "manual", "transcript_path": "/path/to/transcript.jsonl"}' | python pre_compact.py --backup --verbose
```

---

### Setup

**File:** `setup.py`

**Purpose:** Runs when Claude Code is invoked with --init or --maintenance flags for repository initialization.

**When it runs:** With --init, --init-only, or --maintenance flags

**Triggers:**
- `init` - Repository initialization (--init or --init-only flags)
- `maintenance` - Periodic maintenance (--maintenance flag)

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/path/to/project",
  "permission_mode": "default",
  "hook_event_name": "Setup",
  "trigger": "init"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `trigger` | string | "init" or "maintenance" |

**Output JSON Format:**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "Setup",
    "additionalContext": "Setup triggered: init\nSession: abc123...\n..."
  }
}
```

**Environment Variables:**
- `CLAUDE_PROJECT_DIR` - Absolute path to the project root directory
- `CLAUDE_ENV_FILE` - File path for persisting environment variables

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--install-deps` | Install project dependencies |
| `--verbose` | Print verbose output |
| `--install-clis` | Install all missing CLI tools (runs `tools/install_clis.py --all`) |
| `--upgrade-clis` | Upgrade all installed CLI tools to latest versions (runs `tools/upgrade_clis.py --all`) |

#### CLI Installation & Upgrade Flags

The setup hook supports automated CLI management:

- `--install-clis` — Install all missing CLI tools (runs `tools/install_clis.py --all`)
- `--upgrade-clis` — Upgrade all installed CLI tools to latest versions (runs `tools/upgrade_clis.py --all`)

The assessment system also supports:
- `--install-missing` — After running assessment, automatically install any missing CLIs

**Example Usage:**

```bash
# Initialize with dependency installation
echo '{"trigger": "init", "cwd": "/project"}' | python setup.py --install-deps --verbose

# Run maintenance
echo '{"trigger": "maintenance", "cwd": "/project"}' | python setup.py --verbose
```

---

### SessionStart

**File:** `session_start.py`

**Purpose:** Runs when a Claude Code session starts or resumes, loading development context.

**When it runs:** When a session starts or resumes

**Sources:**
- `startup` - New session started
- `resume` - Session resumed via --resume, --continue, or /resume
- `clear` - Session cleared via /clear
- `compact` - Session compacted

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/path/to/project",
  "permission_mode": "default",
  "hook_event_name": "SessionStart",
  "source": "startup",
  "model": "claude-sonnet-4-20250514",
  "agent_type": "custom-agent"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | How session started: "startup", "resume", "clear", "compact" |
| `model` | string | Model identifier (optional) |
| `agent_type` | string | Present when started with --agent (optional) |

**Output JSON Format:**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Session started at: 2024-01-15 10:30:00\nGit branch: main\n..."
  }
}
```

**Environment Variables:**
- `CLAUDE_ENV_FILE` - Path to file for persisting environment variables for Bash commands

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--load-context` | Load development context at session start |
| `--announce` | Announce session start via TTS |

**Example Usage:**

```bash
# Load development context
echo '{"source": "startup", "session_id": "abc"}' | python session_start.py --load-context

# Announce via TTS
echo '{"source": "resume"}' | python session_start.py --announce
```

---

### SessionEnd

**File:** `session_end.py`

**Purpose:** Runs when a Claude Code session ends, logging termination for transparency.

**When it runs:** When a session ends

**Reasons:**
- `clear` - User cleared the session (/clear command)
- `logout` - User logged out
- `prompt_input_exit` - User exited via Ctrl+C, Ctrl+D, or quit command
- `other` - Any other termination (timeout, crash, etc.)

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "cwd": "/path/to/project",
  "reason": "prompt_input_exit",
  "permission_mode": "default",
  "transcript": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `reason` | string | Why session ended: "clear", "logout", "prompt_input_exit", "other" |
| `transcript` | array | Conversation turns (if available) |

**Output JSON Format:** None - this hook only logs

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--cleanup` | Perform cleanup tasks at session end |

**Example Usage:**

```bash
# Log session end
echo '{"reason": "prompt_input_exit", "session_id": "abc"}' | python session_end.py

# With cleanup
echo '{"reason": "clear"}' | python session_end.py --cleanup
```

---

### TeammateIdle

**File:** `teammate_idle.py`

**Purpose:** Logs teammate idle events in multi-agent sessions. Supports --log-only and --notify flags.

**When it runs:** When a teammate agent becomes idle in multi-agent sessions

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "TeammateIdle",
  "teammate_id": "teammate-789",
  "teammate_name": "CodeReviewer",
  "idle_reason": "waiting_for_input"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `teammate_id` | string | Unique identifier for the idle teammate |
| `teammate_name` | string | Display name of the teammate agent |
| `idle_reason` | string | Reason the teammate became idle |

**Output JSON Format:** JSON log entry to `logs/teammate_idle.json`

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--log-only` | Only log the idle event, no other actions |
| `--notify` | Enable TTS notification when teammate becomes idle |

**Example Usage:**

```bash
# Log only
echo '{"teammate_id": "t-1", "teammate_name": "Reviewer", "idle_reason": "waiting"}' | python teammate_idle.py --log-only

# With TTS notification
echo '{"teammate_id": "t-1", "teammate_name": "Reviewer", "idle_reason": "waiting"}' | python teammate_idle.py --notify
```

---

### TaskCompleted

**File:** `task_completed.py`

**Purpose:** Logs async task completion events. Supports --log-only and --notify flags.

**When it runs:** When an async task completes

**Input JSON Fields:**

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory",
  "permission_mode": "default",
  "hook_event_name": "TaskCompleted",
  "task_id": "task-456",
  "task_name": "lint_check",
  "task_result": "success"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique identifier for the completed task |
| `task_name` | string | Name/description of the task |
| `task_result` | string | Result of the task (e.g., "success", "failure", details) |

**Output JSON Format:** JSON log entry to `logs/task_completed.json`

**Command Line Arguments:**

| Argument | Description |
|----------|-------------|
| `--log-only` | Only log the task completion, no other actions |
| `--notify` | Enable TTS notification when task completes |

**Example Usage:**

```bash
# Log only
echo '{"task_id": "t-456", "task_name": "lint_check", "task_result": "success"}' | python task_completed.py --log-only

# With TTS notification
echo '{"task_id": "t-456", "task_name": "build", "task_result": "failure"}' | python task_completed.py --notify
```

---

## Status Lines Documentation

Status lines provide real-time information in the Claude Code interface. The following status line scripts are available in `.claude/status_lines/`:

### Status Line v10 - Cost Tracker Style

**File:** `status_line_v10.py`

**Display:** `[Model] $0.05 | +156/-23 | 2m 30s | 42%`

**Focus:** Cost tracking, lines changed, duration, and context usage

| Segment | Description | Colors |
|---------|-------------|--------|
| Model | Model name in brackets | Cyan |
| Cost | Session cost in USD | Green < $0.10, Yellow < $0.50, Magenta < $1.00, Red >= $1.00 |
| Lines | Lines added/removed | Green for added, Red for removed |
| Duration | Session elapsed time | Blue |
| Context | Context window usage % | Green < 50%, Yellow < 75%, Magenta < 90%, Red >= 90% |

---

### Status Line v11 - Context Progress Bar

**File:** `status_line_v11.py`

**Display:** `[Model] [========----] 67% (134k/200k tokens)`

**Focus:** Visual progress bar showing context window usage with Unicode blocks

| Segment | Description | Colors |
|---------|-------------|--------|
| Model | Model name in brackets | Cyan |
| Progress Bar | Visual bar using Unicode blocks | Green < 50%, Yellow < 75%, Red >= 75% |
| Percentage | Context usage percentage | Same as progress bar |
| Tokens | Used/total token count | Dim gray |

---

### Status Line v12 - Minimal Emoji Style

**File:** `status_line_v12.py`

**Display:** `[robot] model | [branch] branch | [chart] context% | [money] $cost`

**Focus:** Compact emoji-based display for quick scanning

| Segment | Emoji | Description |
|---------|-------|-------------|
| Model | Robot | Current model name |
| Branch | Plant | Git branch (if in repo) |
| Context | Chart | Context usage percentage |
| Cost | Money Bag | Session cost |

---

### Status Line v13 - Developer Dashboard

**File:** `status_line_v13.py`

**Display:** `[Opus] [folder] project | [timer] 5m | [refresh] 2.3s API | [files] 3 files | [disk] 60% cache`

**Focus:** Multiple detailed segments with project info, timing, and git status

| Segment | Description |
|---------|-------------|
| Model | Model name in brackets |
| Project | Current directory name |
| Duration | Session elapsed time |
| API | API response duration |
| Files | Uncommitted file count (if > 0) |
| Cache | Cache hit percentage |

---

### Status Line v14 - Gradient Color Coding

**File:** `status_line_v14.py`

**Display:** Professional minimal status with true color (24-bit) gradient backgrounds

**Focus:** Context usage shown with color intensity - smooth transitions from green to red

| Segment | Description |
|---------|-------------|
| Model | Dark background with light text |
| Percentage | Gradient background (green -> yellow -> red) |
| Tokens | Accent background with token counts |
| Cost | Dark background with green-tinted cost |

**Color Gradient:**
- 0% context: Green (#28a745)
- 50% context: Yellow (#ffc107)
- 100% context: Red (#dc3545)

---

### Status Line v15 - Conversation Metrics

**File:** `status_line_v15.py`

**Focus:** Conversation metrics including message counts, token rates, and conversation depth

---

### Status Line v16 - Nerd Stats

**File:** `status_line_v16.py`

**Focus:** Detailed technical statistics for power users - tokens/sec, cache hit ratios, API latency

---

### Status Line v17 - Compact Multi-Metric

**File:** `status_line_v17.py`

**Focus:** Maximum information density in minimal space - multiple metrics in a single compact line

---

### Status Line v18 - Emoji-Coded Indicators

**File:** `status_line_v18.py`

**Focus:** Emoji-based status indicators for at-a-glance system health and activity monitoring

---

### Status Line v19 - Dual-Line Compact

**File:** `status_line_v19.py`

**Focus:** Two-line display for additional detail while remaining compact

---

### Status Line v20 - GitHub-Aware

**File:** `status_line_v20.py`

**Focus:** GitHub-aware status showing PR status, CI pipeline state, and issue counts from gh CLI

---

### Shared Utility Module - status_utils.py

**File:** `status_utils.py`

**Purpose:** Shared utility module imported by all v21-v25 status line scripts. Provides consistent, reusable functions so that each status line variant focuses only on layout and presentation.

**Key Functions:**
- **CLI detection** -- Detects which AI coding CLI is active (Claude Code, Gemini CLI, Codex CLI)
- **Provider health checks** -- Probes LLM provider availability (Ollama, Gemini, Codex, OpenAI) with cached results
- **GitHub context** -- Gathers branch, PR, and CI status via `gh` CLI with graceful fallback
- **Formatting helpers** -- ANSI color utilities, powerline segment builders, cost/token formatters, context bar rendering

All v21-v25 status lines import from this module to ensure consistent behavior across variants.

---

### Status Line v21 - Unified Provider Health

**File:** `status_line_v21.py`

**Focus:** Displays active CLI badge alongside health indicators for all LLM providers (Ollama, Gemini, Codex, OpenAI), plus current model, context usage, and session cost. Provides a unified view of your entire LLM infrastructure at a glance.

---

### Status Line v22 - GitHub + Provider Compact

**File:** `status_line_v22.py`

**Focus:** Combines GitHub context (branch, PR count, CI status) with the best available LLM provider and model/context metrics. Degrades gracefully when `gh` CLI is not installed or not authenticated, falling back to provider-only display.

---

### Status Line v23 - Full Dashboard

**File:** `status_line_v23.py`

**Focus:** Maximum information density status line. Packs CLI identity, GitHub context (branch/PR/CI), all provider health indicators, current model, session cost, and context usage into pipe-separated segments. Designed for wide terminals and power users who want everything visible.

---

### Status Line v24 - Powerline GitHub + Provider

**File:** `status_line_v24.py`

**Focus:** Uses Nerd Font powerline separator characters with 24-bit true-color backgrounds for a polished, terminal-native look. Segments cover CLI identity, Git branch, GitHub PR/CI, provider health, and model info. Requires a Nerd Font-compatible terminal for correct rendering.

---

### Status Line v25 - Minimal Multi-Provider

**File:** `status_line_v25.py`

**Focus:** Ultra-compact display using the model name followed by colored dot indicators (filled circle for healthy, empty circle for unavailable) for each LLM provider, plus context percentage and session cost. Minimal terminal width required while still showing multi-provider health.

---

## settings.json Configuration Examples

### Basic Hook Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python .claude/hooks/pre_tool_use.py --auto-approve"
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "python .claude/hooks/post_tool_use.py"
      }
    ]
  }
}
```

### Matcher-Based Configuration

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/notification.py --notify"
          }
        ]
      },
      {
        "matcher": "idle_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/notification.py --notify"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "manual",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/pre_compact.py --backup --verbose"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/session_start.py --load-context"
          }
        ]
      }
    ],
    "Setup": [
      {
        "matcher": "init",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/setup.py --install-deps"
          }
        ]
      },
      {
        "matcher": "maintenance",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/setup.py"
          }
        ]
      }
    ]
  }
}
```

### Full Production Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "python .claude/hooks/pre_tool_use.py --auto-approve --strict"
      }
    ],
    "PostToolUse": [
      {
        "type": "command",
        "command": "python .claude/hooks/post_tool_use.py --block-on-error"
      }
    ],
    "PostToolUseFailure": [
      {
        "type": "command",
        "command": "python .claude/hooks/post_tool_use_failure.py"
      }
    ],
    "PermissionRequest": [
      {
        "type": "command",
        "command": "python .claude/hooks/permission_request.py --auto-allow"
      }
    ],
    "Notification": [
      {
        "type": "command",
        "command": "python .claude/hooks/notification.py --notify"
      }
    ],
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "python .claude/hooks/user_prompt_submit.py --validate --name-agent"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python .claude/hooks/stop.py --notify --chat"
      }
    ],
    "SubagentStart": [
      {
        "type": "command",
        "command": "python .claude/hooks/subagent_start.py --notify"
      }
    ],
    "SubagentStop": [
      {
        "type": "command",
        "command": "python .claude/hooks/subagent_stop.py --notify --summarize"
      }
    ],
    "PreCompact": [
      {
        "type": "command",
        "command": "python .claude/hooks/pre_compact.py --backup"
      }
    ],
    "Setup": [
      {
        "type": "command",
        "command": "python .claude/hooks/setup.py --install-deps"
      }
    ],
    "SessionStart": [
      {
        "type": "command",
        "command": "python .claude/hooks/session_start.py --load-context --announce"
      }
    ],
    "SessionEnd": [
      {
        "type": "command",
        "command": "python .claude/hooks/session_end.py --cleanup"
      }
    ],
    "TeammateIdle": [
      {
        "type": "command",
        "command": "python .claude/hooks/teammate_idle.py --log-only --notify"
      }
    ],
    "TaskCompleted": [
      {
        "type": "command",
        "command": "python .claude/hooks/task_completed.py --log-only --notify"
      }
    ]
  },
  "status_line": {
    "command": "python .claude/status_lines/status_line_v14.py"
  }
}
```

### Status Line Configuration

```json
{
  "status_line": {
    "command": "python .claude/status_lines/status_line_v10.py"
  }
}
```

Available status lines:
- `status_line_v10.py` - Cost Tracker Style
- `status_line_v11.py` - Context Progress Bar
- `status_line_v12.py` - Minimal Emoji Style
- `status_line_v13.py` - Developer Dashboard
- `status_line_v14.py` - Gradient Color Coding
- `status_line_v15.py` - Conversation Metrics
- `status_line_v16.py` - Nerd Stats
- `status_line_v17.py` - Compact Multi-Metric
- `status_line_v18.py` - Emoji-Coded Indicators
- `status_line_v19.py` - Dual-Line Compact
- `status_line_v20.py` - GitHub-Aware (PR status, CI, issues from gh CLI)
- `status_line_v21.py` - Unified Provider Health (CLI badge + all LLM providers + model/context/cost)
- `status_line_v22.py` - GitHub + Provider Compact (Branch/PR/CI + best provider + model/context)
- `status_line_v23.py` - Full Dashboard (CLI, GitHub, all providers, model, cost, context)
- `status_line_v24.py` - Powerline GitHub + Provider (Nerd Font powerline + 24-bit true-color)
- `status_line_v25.py` - Minimal Multi-Provider (model + colored dot indicators + context + cost)

All v21-v25 status lines use the shared `status_utils.py` utility module for consistent CLI detection, provider health checks, GitHub context, and formatting.

---

## Log Files

All hooks log to JSON files in the `logs/` directory:

| Hook | Log File |
|------|----------|
| PreToolUse | `logs/pre_tool_use.json` |
| PostToolUse | `logs/post_tool_use.json` |
| PostToolUseFailure | `logs/post_tool_use_failure.json` |
| PermissionRequest | `logs/permission_request.json` |
| Notification | `logs/notification.json` |
| UserPromptSubmit | `logs/user_prompt_submit.json` |
| Stop | `logs/stop.json` |
| SubagentStart | `logs/subagent_start.json` |
| SubagentStop | `logs/subagent_stop.json` |
| PreCompact | `logs/pre_compact.json` |
| Setup | `logs/setup.json` |
| SessionStart | `logs/session_start.json` |
| SessionEnd | `logs/session_end.json` |
| TeammateIdle | `logs/teammate_idle.json` |
| TaskCompleted | `logs/task_completed.json` |

Debug logs for subagents: `logs/subagent_debug.log`

---

## TTS (Text-to-Speech) Support

Hooks with `--notify` flags support TTS via scripts in `utils/tts/`:

**Priority Order:**
1. ElevenLabs (requires `ELEVENLABS_API_KEY`)
2. OpenAI (requires `OPENAI_API_KEY`)
3. pyttsx3 (no API key required, local TTS)

**Environment Variables:**
- `ELEVENLABS_API_KEY` - For ElevenLabs TTS
- `OPENAI_API_KEY` - For OpenAI TTS
- `ENGINEER_NAME` - Optional personalization in notification messages

---

## GitHub CLI Integration

The project includes a suite of GitHub CLI (`gh`) helper scripts in `.github/hooks/` that provide seamless GitHub operations from within the Claude Code hook ecosystem. All scripts are built on a shared foundation (`gh_detect.py`) and degrade gracefully when `gh` is not installed or not authenticated.

### Helper Scripts in `.github/hooks/`

| Script | Purpose |
|--------|---------|
| `gh_detect.py` | Shared detection utility -- provides `run_gh_command()`, `is_gh_installed()`, `is_gh_authenticated()`, `get_gh_version()`, `get_repo_context()`, `get_current_branch()` |
| `gh_pr_helper.py` | Pull request operations: list, create, status, CI checks |
| `gh_issue_helper.py` | Issue management: list, create, comment, assigned issues |
| `gh_ci_status.py` | CI/CD workflow status: run list, branch status, PR checks (includes summary field) |
| `gh_release_helper.py` | Release management: latest, create, list |
| `gh_session_context.py` | Session-level aggregator: gathers repo, branch, PR, issues, and failing CI into one JSON object |

### How gh_detect.py Provides the Foundation

Every helper script imports from `gh_detect.py` and follows the same guard pattern:

1. Check `is_gh_installed()` -- if False, output `{"status": "skipped"}` and exit 0
2. Check `is_gh_authenticated()` -- if False, output `{"status": "skipped"}` and exit 0
3. Execute the operation via `run_gh_command()` with timeout protection
4. Return structured JSON to stdout and log to `logs/gh_*.json`

All `gh_detect.py` functions return `None` or `False` on failure and never raise exceptions.

### Integration with Existing Hooks

Four hooks in `.claude/hooks/` have been extended with optional GitHub awareness:

- **session_start.py** (`--load-context`) -- Gathers branch, open PRs, and assigned issues during context loading
- **stop.py** (`--gh-summary`) -- Logs branch, uncommitted changes, and current PR info at stop time
- **session_end.py** (`--gh-log`) -- Captures branch and PR state when the session ends
- **post_tool_use.py** -- Automatically detects `gh` commands in Bash tool usage and tags them as `gh_command` in logs

### Status Line v20

The GitHub-aware status line (`status_line_v20.py`) displays PR status, CI status, branch name, and assigned issue count alongside standard model/cost/context metrics. Falls back to basic display when `gh` is not available.

### Full Documentation

See [ai_docs/gh_hooks_integration.md](../../ai_docs/gh_hooks_integration.md) for complete documentation including all flags, output formats, configuration examples, and troubleshooting.

---

## Assessment System

**File:** `utils/assessment.py`

The assessment module probes the local environment to detect available CLI tools, API keys, Ollama models, installed hooks, and system capabilities. It produces a structured JSON report that hooks and orchestration logic can use to make informed decisions about which features are available.

**What It Detects:**
- CLI tools (git, gh, uv, node, npm, ollama, etc.)
- API keys (checks which environment variables are set, not their values)
- Ollama models (lists locally available models)
- Installed hooks (scans `.claude/hooks/` for configured hook scripts)
- System capabilities (TTS availability, LLM provider priority)

**CLI Flags:**

| Flag | Description |
|------|-------------|
| `--json` | Output full assessment as JSON |
| `--summary` | Output a human-readable summary |
| `--check` | Exit 0 if core dependencies are met, exit 1 otherwise |
| `--models` | List available Ollama models only |
| `--no-cache` | Bypass the cache and force a fresh assessment |

**Caching:** Results are cached for 5 minutes to `.claude/data/assessment_cache.json` to avoid redundant probing on repeated calls within the same session.

---

## Trigger System

**Files:** `utils/trigger.py`, `utils/trigger_rules.json`

The trigger system is an event-driven automation engine that evaluates rules after specific hook events fire. Rules are defined declaratively in `trigger_rules.json` and evaluated by `trigger.py` at runtime.

**How Rules Are Evaluated:**
1. A hook event fires (e.g., SubagentStop, TaskCompleted, Stop, SessionStart)
2. The trigger engine loads rules from `trigger_rules.json`
3. Each rule specifies an event match, optional conditions, and one or more actions
4. Matching rules execute their actions in order

**Actions:**

| Action | Description |
|--------|-------------|
| `suggest_next` | Suggest the next task to work on |
| `validate` | Suggest running validation on completed work |
| `notify` | Send a notification (TTS or log) |
| `log` | Write an entry to the trigger log |

**Environment Variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TRIGGER_ENABLED` | `true` | Enable or disable the trigger engine globally |
| `TRIGGER_AUTO_NEXT` | `false` | Auto-suggest the next task after completion |
| `TRIGGER_AUTO_VALIDATE` | `false` | Auto-suggest validation after task completion |
| `TRIGGER_LOG_LEVEL` | `info` | Log verbosity: debug, info, warn, error |

**Hook Integration:** The trigger system integrates with SubagentStop, TaskCompleted, Stop, and SessionStart hooks. When enabled, these hooks invoke `trigger.py` after their primary logic completes, passing the event name and payload for rule evaluation.

---

## GOTCHA Framework Integration

All hooks implement specific layers of the GOTCHA Framework. Each hook's docstring includes `GOTCHA Layer:` and `ATLAS Phase:` sections identifying its role.

### GOTCHA Layer Mapping

| Hook | GOTCHA Layer | Description |
|------|-------------|-------------|
| Setup | Goals + Context | Establishes project foundation and initial context |
| SessionStart | Context + Args | Loads development context and applies session settings |
| UserPromptSubmit | Goals | Captures user intent and validates prompt requirements |
| PreToolUse | Orchestration + Guardrails | Validates tool operations before execution |
| PermissionRequest | Guardrails | Enforces permission boundaries and security gates |
| PostToolUse | Tools + Context | Processes tool outputs and updates context |
| PostToolUseFailure | Guardrails + Improvement | Captures failures and feeds improvement loop |
| Notification | Orchestration | Coordinates user notifications during assembly |
| SubagentStart | Orchestration | Plans and delegates work to subagents |
| SubagentStop | Orchestration + Improvement | Evaluates subagent results and quality |
| TeammateIdle | Orchestration | Monitors resource availability and scheduling |
| TaskCompleted | Goals + Improvement | Validates task completion against goals |
| PreCompact | Context | Preserves critical context before compaction |
| Stop | Orchestration + Transparency | Manages final state verification and completion |
| SessionEnd | Context + Transparency | Creates session summary and persists learnings |

### ATLAS Workflow Integration

Hooks also map to phases of the ATLAS workflow (Architect, Trace, Link, Assemble, Stress-test):

| ATLAS Phase | Hooks | Purpose |
|-------------|-------|---------|
| Architect | Setup, SessionStart, UserPromptSubmit | Establish foundation, load context, capture intent |
| Trace | SubagentStart, TeammateIdle | Plan delegation, monitor resources |
| Link (validation) | PreToolUse, PermissionRequest | Validate connections and permissions before execution |
| Assemble | PostToolUse, Notification | Process outputs, coordinate during assembly |
| Stress-test | PostToolUseFailure, SubagentStop, TaskCompleted, Stop, SessionEnd | Validate results, evaluate quality, verify completion |

### Framework Principles

1. **Reliability** — Pushed into deterministic code (tools/hooks)
2. **Flexibility** — LLM handles reasoning and decision-making
3. **Transparency** — All operations are logged
4. **Guardrails** — Dangerous operations are blocked
5. **Continuous Improvement** — Failures are logged and used to improve

### References

- `CLAUDE.md` — Full GOTCHA framework documentation
- `build_app.md` — ATLAS workflow detailed definition
- `ai_docs/gotcha_atlas_reference.md` — Comprehensive framework reference

---

## Cognitive Control Engine (CCE)

The Cognitive Control Engine adds intelligent decision-making to hooks. It lives in `.claude/hooks/utils/cognitive/` and is activated by `--cognitive` flags.

### Modules

| Module | Lines | Purpose |
|--------|-------|---------|
| `risk_scorer.py` | ~310 | 4-factor risk scoring (0-100) |
| `policy_selector.py` | ~210 | STRICT/BALANCED/PERMISSIVE selection |
| `confidence_estimator.py` | ~195 | Decision confidence (0.0-1.0) |
| `perspective_debater.py` | ~456 | 4-faculty debate with Guardian VETO |
| `context_analyzer.py` | ~390 | Session state + anomaly detection |
| `pattern_learner.py` | ~435 | Adaptive pattern learning |
| `quality_assessor.py` | ~586 | Multi-dimensional quality scoring |
| `__init__.py` | ~307 | Unified `cognitive_decide()` entry point |

### Decision Flow

```
Hook Event → Perceive (context) → Score (risk) → Policy (select) → Pattern (check)
  → Confidence (estimate) → Debate (if needed) → Decide → Act → Record
```

### Hook Integration

| Hook | Flag | Cognitive Behavior |
|------|------|--------------------|
| `pre_tool_use.py` | `--cognitive` | Risk-scored allow/ask/deny decisions |
| `permission_request.py` | `--cognitive` | Pattern learning + cognitive scoring |
| `task_completed.py` | `--cognitive` | Quality assessment before completion |
| `subagent_stop.py` | `--cognitive` | Agent output quality evaluation |
| `trigger.py` | (built-in) | Compound conditions (AND/OR/NOT) + risk-based triggers |

### Configuration

All CCE features are opt-in via `CCE_ENABLED=true` (default) and `--cognitive` flags in settings.json. Set `CCE_ENABLED=false` to disable completely.

See `.env.sample` for all 16 CCE environment variables.
