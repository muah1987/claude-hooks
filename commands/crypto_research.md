---
allowed-tools: Bash, Write, Agent, WebSearch
argument-hint: [crypto_ticker_symbol] [--quick|--fast]
description: Execute cryptocurrency research; auto-selects best-available model (sonnet/opus) by default or haiku-only when --quick/--fast
---

# Crypto Research Command

Think hard and execute cryptocurrency research by calling crypto-analysis agents in parallel.

Two modes:

- **Default (comprehensive):** run every tier (haiku + sonnet + opus) across all four agent groups — 12 agents total.
- **Quick / fast:** if the user passes `--quick`, `--fast`, or says "quick" / "fast", run only the haiku variants — 4 agents total.

## Variables

- **TICKER**: `$ARGUMENTS` or `BTC` if not specified
  - The cryptocurrency ticker symbol to analyze (e.g., BTC, ETH, SOL)
  - Used by: crypto-coin-analyzer agents
- **MODE**: `quick` if args contain `--quick` / `--fast` or the user says so, otherwise `full`

## Agent Groups

### Market Data Agents
- @agent-crypto-market-agent-haiku
- @agent-crypto-market-agent-sonnet   *(full mode only)*
- @agent-crypto-market-agent-opus     *(full mode only)*

### Coin Analysis Agents
- @agent-crypto-coin-analyzer-haiku (analyze TICKER)
- @agent-crypto-coin-analyzer-sonnet (analyze TICKER)   *(full mode only)*
- @agent-crypto-coin-analyzer-opus (analyze TICKER)     *(full mode only)*

### Macro Correlation Agents
- @agent-macro-crypto-correlation-scanner-haiku
- @agent-macro-crypto-correlation-scanner-sonnet   *(full mode only)*
- @agent-macro-crypto-correlation-scanner-opus     *(full mode only)*

### Investment Plays Agents
- @agent-crypto-investment-plays-haiku
- @agent-crypto-investment-plays-sonnet   *(full mode only)*
- @agent-crypto-investment-plays-opus     *(full mode only)*

## Execution Instructions

1. Detect MODE from arguments/user phrasing.
2. Run `date +"%Y-%m-%d_%H-%M-%S"` to get a human-readable timestamp (e.g. `2025-01-08_14-30-45`).
3. Create base output directory:
   - Full mode: `outputs/<timestamp>/`
   - Quick mode: `outputs/<timestamp>/haiku/`
4. Set the TICKER variable to the desired cryptocurrency (e.g., BTC, ETH, SOL). Default to BTC if empty.
5. Call all selected agents in parallel (12 for full, 4 for quick).
6. Coin analyzer agents receive the TICKER parameter for focused analysis.
7. Each agent executes its specialized prompt.
8. IMPORTANT: Write the complete, unmodified output from each agent to its designated file.
9. Write outputs to organized directory structure:

**Full mode**
- `outputs/<timestamp>/crypto_market/<agent-name>.md`
- `outputs/<timestamp>/crypto_analysis/<agent-name>.md`
- `outputs/<timestamp>/crypto_macro/<agent-name>.md`
- `outputs/<timestamp>/crypto_plays/<agent-name>.md`

**Quick mode**
- `outputs/<timestamp>/haiku/crypto_market/crypto-market-agent-haiku.md`
- `outputs/<timestamp>/haiku/crypto_analysis/crypto-coin-analyzer-haiku.md`
- `outputs/<timestamp>/haiku/crypto_macro/macro-crypto-correlation-scanner-haiku.md`
- `outputs/<timestamp>/haiku/crypto_plays/crypto-investment-plays-haiku.md`

## Output Format

IMPORTANT: Write each agent's complete response directly to its respective file with NO modifications, NO summarization, and NO changes to the output whatsoever. The exact response from each agent must be preserved.

**Full mode layout**
```
outputs/
└── 2025-01-08_14-30-45/
    ├── crypto_market/
    │   ├── crypto-market-agent-haiku.md
    │   ├── crypto-market-agent-sonnet.md
    │   └── crypto-market-agent-opus.md
    ├── crypto_analysis/
    │   ├── crypto-coin-analyzer-haiku.md
    │   ├── crypto-coin-analyzer-sonnet.md
    │   └── crypto-coin-analyzer-opus.md
    ├── crypto_macro/
    │   ├── macro-crypto-correlation-scanner-haiku.md
    │   ├── macro-crypto-correlation-scanner-sonnet.md
    │   └── macro-crypto-correlation-scanner-opus.md
    └── crypto_plays/
        ├── crypto-investment-plays-haiku.md
        ├── crypto-investment-plays-sonnet.md
        └── crypto-investment-plays-opus.md
```

**Quick mode layout**
```
outputs/
└── 2025-01-08_14-30-45/
    └── haiku/
        ├── crypto_market/crypto-market-agent-haiku.md
        ├── crypto_analysis/crypto-coin-analyzer-haiku.md
        ├── crypto_macro/macro-crypto-correlation-scanner-haiku.md
        └── crypto_plays/crypto-investment-plays-haiku.md
```

## Report

When all agents are complete: give the path to the `outputs/<timestamp>/` (or `.../haiku/`) directory and report the number of successful/total agents based on the existence of their respective files.
