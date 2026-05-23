---
name: all_tools
description: Complete reference for all Claude Code tools with TypeScript-style signatures and usage notes. Use this to discover what's available before planning a task.
argument-hint: "[tool-name | category]"
allowed-tools: Read, Agent, ToolSearch
---

# All Available Claude Code Tools

## File & Code Tools

```typescript
Read(file_path: string, offset?: number, limit?: number, pages?: string): string
// Read files, images, PDFs, notebooks. Supports page ranges for large PDFs.

Write(file_path: string, content: string): void
// Create/overwrite files. Always Read first if file exists.

Edit(file_path: string, old_string: string, new_string: string, replace_all?: boolean): void
// Targeted in-place edits. Preferred over Write for modifications.

Glob(pattern: string, path?: string): string[]
// File pattern matching. Sorted by modification time.

Grep(pattern: string, path?: string, glob?: string, type?: string,
     output_mode?: 'content'|'files_with_matches'|'count',
     context?: number): string
// Ripgrep-powered search. Use instead of Bash grep.

Bash(command: string, timeout?: number, run_in_background?: boolean): string
// Shell commands. Reserve for operations Glob/Grep/Read can't do.

NotebookEdit(notebook_path: string, cell_id: string, ...): void
// Edit Jupyter notebook cells.
```

## LSP (Code Intelligence)

```typescript
LSP(operation: 'definition'|'references'|'hover'|'document_symbols'
              |'workspace_symbols'|'rename'|'document_diagnostics'
              |'workspace_diagnostics'|'call_hierarchy',
    filePath: string, line?: number, character?: number,
    newName?: string, query?: string): object
// Language server protocol — jump to definitions, find references,
// rename symbols, get diagnostics, call hierarchy. Filters gitignored results.
```

## Agent & Task Tools

```typescript
Agent(description: string, prompt: string,
      subagent_type?: string, model?: 'sonnet'|'opus'|'haiku',
      run_in_background?: boolean, isolation?: 'worktree'): object
// Spawn specialist sub-agents. Use run_in_background=true for parallel work.

TaskCreate(subject: string, description?: string, activeForm?: string): string
// Create a task in the shared task list. Returns task ID.

TaskUpdate(taskId: string, status?: string, owner?: string,
           addBlockedBy?: string[], removeBlockedBy?: string[]): void
// Update task status, ownership, or dependencies.

TaskList(filter?: object): object[]
// List all tasks, optionally filtered by status/owner.

TaskGet(taskId: string): object
// Get a single task with full details.

TaskOutput(taskId: string): string
// Stream task output (use for background agent monitoring).

TaskStop(taskId: string): void
// Stop a running task.
```

## Team / Swarm Tools

```typescript
TeamCreate(team_name: string, description: string, agent_type: string): string
// Create a named multi-agent swarm team. Auto-generates unique name on conflict.
// Returns team ID. Each team gets its own task list.

TeamDelete(action: 'keep'|'remove', discard_changes?: boolean): void
// Dismantle a team. Validates no active members. Auto-restores worktrees.

SendMessage(to: string, message: string|object, summary?: string): void
// Send messages to: agent name, "*" (broadcast), "uds:<path>", "bridge:<session>".
// Supports structured protocol: shutdown requests, plan approvals.
// Auto-resumes stopped agents.
```

## Planning & Worktree Tools

```typescript
EnterPlanMode(): void
// Enter read-only exploration mode. Disables tool writes for safe planning.
// Use before /plan to explore without side effects.

ExitPlanMode(allowedPrompts?: string[]): void
// Exit plan mode. Optionally specify prompts that are allowed to proceed.

EnterWorktree(name: string): string
// Create isolated git worktree for safe parallel work.
// Returns worktree path. Auto-cleaned if no changes made.

ExitWorktree(action: 'keep'|'remove', discard_changes?: boolean): void
// Exit and optionally clean worktree. Counts uncommitted files/commits.
```

## Scheduling Tools

```typescript
CronCreate(cron: string, prompt: string,
           recurring?: boolean, durable?: boolean): string
// Schedule prompts. One-shot (recurring=false) or repeating.
// Durable=true persists across restarts. Validates against next-year calendar.
// Auto-expires after 7 days.

CronDelete(cron_id: string): void
// Cancel a scheduled cron job.

CronList(): object[]
// List all active cron jobs with next-run times.

RemoteTrigger(action: 'list'|'get'|'create'|'update'|'run',
              trigger_id?: string, body?: object): object
// HTTP-based scheduled remote agent triggers. Persist across sessions.
// OAuth-authenticated. 20s timeout. Use for durable cross-session tasks.
```

## User Interaction Tools

```typescript
AskUserQuestion(questions: Array<{
  question: string, answers: string[],
  preview?: string, descriptions?: string[]
}>, multiSelect?: boolean, annotations?: object): string[]
// Present multiple-choice questions with optional previews (mockups, code).
// Per-option descriptions. Disabled in --channels mode.
// Use when input has 2+ clear options rather than free-text.
```

## Web & Search Tools

```typescript
WebSearch(query: string): string
// Search the web. Use for research, docs lookup.

WebFetch(url: string, prompt?: string): string
// Fetch and extract content from a URL.
```

## Memory & Configuration

```typescript
ToolSearch(query: string, max_results?: number): object
// Discover deferred tools by keyword. Use "select:<name>" for direct lookup.
// Required before calling any tool from <available-deferred-tools> list.
// Memoizes descriptions. Example: ToolSearch("select:LSP,TeamCreate")

ConfigTool(setting: string, value?: string): string
// Get or set settings: theme, model, permissions.defaultMode, etc.
// Supports nested paths. Syncs AppState immediately.
```

## MCP Tools

```typescript
MCPTool(server: string, tool: string, params: object): object
// Call any MCP server tool directly. Deferred tools need ToolSearch first.

McpAuthTool(): string
// Start OAuth flow for an MCP server. Returns auth URL immediately.
// Completes auth in background, auto-reconnects with real tools.

ListMcpResourcesTool(server?: string): object[]
// List available MCP resources.

ReadMcpResourceTool(server: string, uri: string): string
// Read content from an MCP resource.
```

## Output Tools

```typescript
SyntheticOutputTool(data: object): object
// Return structured JSON with schema validation.
// Only available in non-interactive SDK mode.

BriefTool(message: string, attachments?: string[], status?: 'normal'|'proactive'): void
// Send user-facing message with optional file attachments.
// Only available when --brief flag or /config brief is enabled.
```

---

## Key Patterns

**Discover deferred tools before using them:**
```typescript
ToolSearch({ query: "select:LSP,TeamCreate,AskUserQuestion" })
// Then call the tool normally
```

**Safe isolated work:**
```typescript
EnterWorktree({ name: "feature-x" })
// ... do work ...
ExitWorktree({ action: "keep" })
```

**Parallel agent swarm:**
```typescript
// All 3 in one message:
Agent({ prompt: "task A", run_in_background: true })
Agent({ prompt: "task B", run_in_background: true })
Agent({ prompt: "task C", run_in_background: true })
// Then wait with TaskOutput or agent_results.py wait-all
```

**Code navigation:**
```typescript
LSP({ operation: "definition", filePath: "/abs/path/file.ts", line: 42, character: 15 })
LSP({ operation: "references", filePath: "/abs/path/file.ts", line: 42, character: 15 })
LSP({ operation: "call_hierarchy", filePath: "/abs/path/file.ts", line: 42, character: 15 })
```
