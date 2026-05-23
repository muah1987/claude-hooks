---
description: Security audit of code for vulnerabilities, secrets, and compliance issues
argument-hint: [file-path, directory, or 'all' for full codebase scan]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebSearch
---

# Security Audit

Perform a security audit on the specified `TARGET`.

## Variables

TARGET: $ARGUMENTS

## Instructions

- If no `TARGET` is provided, audit recent changes (`git diff HEAD~5`).
- If `TARGET` is 'all', scan the full codebase for common vulnerability patterns.
- Focus on actionable findings with specific file:line references.

## Workflow

1. **Scope** - Determine what to audit based on TARGET
2. **Scan** - Systematically check each vulnerability category
3. **Classify** - Rate findings by severity (CRITICAL/HIGH/MEDIUM/LOW/INFO)
4. **Report** - Provide findings with remediation guidance

## Audit Categories

### Secrets & Credentials
- Hardcoded passwords, API keys, tokens
- Credentials in config files
- Private keys committed to repo
- `.env` files with sensitive data

### Injection Vulnerabilities
- SQL injection (string concatenation in queries)
- Command injection (unsanitized shell commands)
- XSS (unescaped user input in HTML)
- Path traversal (unsanitized file paths)

### Authentication & Authorization
- Missing auth checks on endpoints
- Broken access control (privilege escalation)
- Weak session management
- Insecure token storage

### Data Protection
- Sensitive data in logs
- Missing encryption for data at rest/transit
- PII exposure in error messages
- Insecure random number generation

### Configuration
- Debug mode enabled in production configs
- Overly permissive CORS/CSP
- Missing security headers
- Insecure defaults

### Dependencies
- Known vulnerable dependencies
- Outdated packages with security patches
- Unnecessary dependencies expanding attack surface

## Report

```
## Security Audit Report

**Scope**: [what was audited]
**Date**: [date]
**Severity Summary**: [N] Critical, [N] High, [N] Medium, [N] Low

### Findings

#### [SEVERITY] [Finding Title]
- **Location**: [file:line]
- **Description**: [what the vulnerability is]
- **Impact**: [what an attacker could do]
- **Remediation**: [how to fix it]

### Recommendations
- [prioritized list of actions]
```
