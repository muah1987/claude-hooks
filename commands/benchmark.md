---
description: Profile and benchmark code for performance bottlenecks
argument-hint: [file-path, function name, or 'build' for build time analysis]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Benchmark

Analyze performance of the specified `TARGET` and identify optimization opportunities.

## Variables

TARGET: $ARGUMENTS

## Instructions

- If no `TARGET` is provided, analyze overall build/compile time.
- If `TARGET` is 'build', profile the build process.
- If `TARGET` is a file, analyze that file's code for performance issues.
- Focus on measurable, actionable improvements.

## Workflow

1. **Baseline** - Measure current performance (time command, profiling output)
2. **Analyze** - Identify hotspots and bottlenecks in the code
3. **Recommend** - Suggest specific optimizations ranked by impact
4. **Estimate** - Provide expected improvement for each recommendation

## Analysis Categories

### Algorithmic Complexity
- O(n^2) or worse loops
- Unnecessary sorting or searching
- Missing data structure optimizations (hash maps vs arrays)

### Memory
- Excessive allocations in hot paths
- Large stack allocations
- Missing buffer reuse
- Memory fragmentation patterns

### I/O
- Synchronous I/O in critical paths
- Missing buffering
- Excessive file opens/closes
- Network round-trips that could be batched

### Build Performance
- Unnecessary recompilation
- Header dependency chains
- Missing precompiled headers
- Parallel build opportunities

## Report

```
## Benchmark Report

**Target**: [what was analyzed]
**Baseline**: [current performance measurement]

### Bottlenecks Found (ranked by impact)

1. **[Location]**: [description]
   - Impact: [estimated improvement]
   - Fix: [specific recommendation]

2. **[Location]**: [description]
   - Impact: [estimated improvement]
   - Fix: [specific recommendation]

### Quick Wins
- [low-effort, immediate improvements]

### Long-term Optimizations
- [higher-effort structural changes]
```
