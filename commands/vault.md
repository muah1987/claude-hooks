---
description: Manage the per-project secrets vault (add, get, list, delete, show, projects). Trigger on phrases like "add secret to vault", "vault get X", "list vault secrets", "show vault", "delete secret from vault", "list vault projects".
allowed-tools: Bash, Read, Write
---

# /vault — project-linked secrets vault

Use this skill to manage secrets stored in the per-project encrypted vault
at `~/.claude/vault/`. Each value is encrypted with a Fernet master key
(`~/.claude/vault/.key`, chmod 600). Secrets are scoped to the current
project, identified by a SHA256 hash of the absolute project path (first
12 chars). Project dir is taken from `CLAUDE_PROJECT_DIR` if set,
otherwise the current working directory.

## How to invoke

Always shell out to the CLI via the Bash tool. Never read `secrets.json`
or `.key` directly.

```bash
uv run ~/.claude/vault/vault.py <command> [args]
```

Supported commands:

| User intent | Command |
| --- | --- |
| "initialize the vault" | `uv run ~/.claude/vault/vault.py init` |
| "add secret FOO=bar" / "store secret FOO value bar" | `uv run ~/.claude/vault/vault.py add FOO bar` |
| "get secret FOO" / "what is FOO" | `uv run ~/.claude/vault/vault.py get FOO` |
| "list vault secrets" / "what secrets do I have" | `uv run ~/.claude/vault/vault.py list` |
| "delete secret FOO" / "remove FOO from vault" | `uv run ~/.claude/vault/vault.py delete FOO` |
| "show all vault secrets" (debugging, prints values) | `uv run ~/.claude/vault/vault.py show` |
| "list vault projects" / "which projects have vaults" | `uv run ~/.claude/vault/vault.py projects` |

## Usage patterns

### Adding a secret
If the user says "add secret `STRIPE_KEY=sk_test_abc` to the vault",
run:

```bash
uv run ~/.claude/vault/vault.py add STRIPE_KEY sk_test_abc
```

Important: pass the value as a **single shell argument**. Quote values
containing spaces or shell metacharacters.

### Retrieving a secret for use in another command
Substitute `$(uv run ~/.claude/vault/vault.py get KEY)` wherever the
value is needed:

```bash
curl -H "Authorization: Bearer $(uv run ~/.claude/vault/vault.py get STRIPE_KEY)" https://api.stripe.com/v1/charges
```

### Listing keys
`list` prints only the key names, one per line — no values. Use this
whenever the user asks "what secrets do I have" so values are not
echoed into the transcript.

### Showing everything (debug)
`show` prints `KEY=value` pairs with values in plaintext. Only use this
when the user explicitly asks to reveal all secrets.

### Project listing
`projects` prints one line per project: `<id>  <name>  <path>`.

## Safety rules

- Never read or dump `~/.claude/vault/.key` or `secrets.json`.
- Prefer `list` over `show` unless the user explicitly asks for values.
- For `get`, print only the single value the user asked for.
- The vault is auto-initialized on first use; you do **not** need to run
  `init` before `add`/`get`/etc.
