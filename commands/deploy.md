---
description: Pre-deployment checklist and guided deployment workflow
argument-hint: [environment: staging|production|preview]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Deploy

Run the deployment checklist and guide the deployment to `ENVIRONMENT`.

## Variables

ENVIRONMENT: $ARGUMENTS

## Instructions

- If no `ENVIRONMENT` is provided, default to 'staging'.
- Run through the pre-deployment checklist before any deployment action.
- Stop and warn the user if any critical check fails.

## Pre-Deployment Checklist

### 1. Code Quality
- [ ] All tests pass
- [ ] No linting errors or warnings
- [ ] No type errors
- [ ] Code compiles cleanly

### 2. Git Status
- [ ] Working directory is clean (no uncommitted changes)
- [ ] Branch is up to date with remote
- [ ] All changes are committed and pushed
- [ ] PR is approved (if applicable)

### 3. Configuration
- [ ] Environment variables are set for target environment
- [ ] No hardcoded dev/test values in production config
- [ ] Database migrations are ready (if applicable)
- [ ] Feature flags are configured correctly

### 4. Security
- [ ] No secrets in code or config files committed
- [ ] Dependencies are up to date (no known CVEs)
- [ ] HTTPS/TLS configured for production

### 5. Documentation
- [ ] CHANGELOG updated (if applicable)
- [ ] README reflects current state
- [ ] API docs updated (if API changed)

## Workflow

1. **Check** - Run all pre-deployment checks above
2. **Report** - Show checklist results, block if critical failures
3. **Confirm** - Ask user to confirm deployment target
4. **Execute** - Run deployment commands
5. **Verify** - Confirm deployment was successful (health checks)

## Report

```
## Deployment Report

**Environment**: [target]
**Branch**: [branch name]
**Commit**: [short hash]

**Pre-Deployment Checklist**:
- [x] Tests pass
- [x] Clean build
- [x] Git clean
- [ ] [any failures]

**Status**: Ready to deploy | Blocked (see failures above)
```
