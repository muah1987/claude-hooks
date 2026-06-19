---
name: autoresearch
description: Autonomous iterative optimization of a project based on empirical metrics.
---

# Autoresearch Skill

You are now in **Autonomous Research Mode**. Your goal is to improve a specific metric in the codebase through a closed-loop iterative process.

## 1. Initialization (The Discovery Phase)
Before starting the loop, you MUST:
- **Identify the Metric**: Find the quantitative measure of success (e.g., a test suite, a benchmark, a loss function, or a performance metric). If none exists, create a `metric.sh` script to measure it.
- **Establish Baseline**: Run the metric and record the current value in `research/ la experiment_log.md`.
- **Define the Program**: Create or update `research/program.md`. This file defines the "Research Org's" goals, constraints, and the current hypothesis.

## 2. The Iterative Loop
Repeat the following steps until the metric plateaus or the goal is reached:

### Step A: Hypothesis (The "What and Why")
- Analyze the current state and the metric.
- Propose a specific, narrow change. 
- **Example**: "Changing the similarity weight $w_{self}$ from 0.3 to 0.4 will increase the stability of proprioceptive memories in high-thermal environments."

### Step B: Implementation (The "How")
- Apply the change surgically.
- Ensure the code still compiles (`cargo check`, `npm run type-check`, etc.).

### Step C: Measurement (The "Truth")
- Run the metric.
- Capture the result.

### Step D: Decision (The "Keep or Discard")
- **Improvement**: If the metric is better, KEEP the change and update the baseline.
- **Regression**: If the metric is worse, REVERT the change and refine the hypothesis.
- **Neutral**: If the change is negligible, DISCARD and try a different direction.

## 3. Logging & Provenance
Every iteration MUST be logged in `research/experiment_log.md` with the following format:
| Iteration | Hypothesis | Change | Result | Decision | Note |
|-----------|------------|--------|--------|-----------|------|

## 4. Termination Criteria
Exit the loop when:
- The target metric is achieved.
- The metric has not improved for N consecutive iterations (Local Optimum).
- The user interrupts the process.
