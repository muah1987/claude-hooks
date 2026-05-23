---
description: Interact with Ollama's cloud API (status, list models, chat) via the ollama_cloud.py helper
argument-hint: "[status | list | chat <model> <prompt>]"
allowed-tools: Bash, Read
---

# Ollama — Cloud-first Helper

Use the `~/.claude/scripts/ollama_cloud.py` helper to talk to Ollama's cloud
API (`https://api.ollama.com`) using `$OLLAMA_API_KEY`. No local Ollama
installation is required.

`OLLAMA_API_BASE` overrides the default endpoint (e.g. set it to
`http://localhost:11434` to target a local daemon instead).

## Commands

### Check cloud status

```bash
uv run ~/.claude/scripts/ollama_cloud.py status
```

Prints one of:
- `cloud` — `OLLAMA_API_KEY` is set and the cloud endpoint is reachable
- `local` — `OLLAMA_API_BASE` points at localhost
- `unavailable` — neither is configured / reachable

Always exits 0.

### List available models

```bash
uv run ~/.claude/scripts/ollama_cloud.py models
```

Fetches `GET /api/tags`, prints model names one per line, and caches the
response at `~/.claude/data/ollama_models_cache.json` (TTL: 1 hour).

### Inspect a model

```bash
uv run ~/.claude/scripts/ollama_cloud.py info <model>
```

Posts `{"model": "<model>"}` to `/api/show` and prints:

```
name: <model>
parameter_size: <e.g. 7B>
context_length: <tokens>
```

Cached at `~/.claude/data/ollama_model_info_<model>.json` (TTL: 6 hours).

### Chat with a model

```bash
uv run ~/.claude/scripts/ollama_cloud.py chat <model> <prompt>
```

Sends a one-shot non-streaming `/api/chat` request (timeout 30s) and prints
the assistant's reply text.

## Workflow

When the user asks about Ollama:

1. Run `status` first to confirm which backend is active.
2. If `cloud` or `local`, run `models` to see what's available.
3. Use `info <model>` before `chat` if you need to know the context window.
4. Use `chat <model> <prompt>` for one-shot generations.

All commands fail silently (exit 0) when the API is unreachable — check for
empty output rather than relying on exit codes.

## Example

```bash
uv run ~/.claude/scripts/ollama_cloud.py status
# cloud

uv run ~/.claude/scripts/ollama_cloud.py models
# llama3.1:70b
# qwen2.5:32b
# ...

uv run ~/.claude/scripts/ollama_cloud.py chat llama3.1:70b "Explain CRDTs in one sentence."
# Conflict-free replicated data types let multiple replicas converge...
```
