#!/usr/bin/env node
/**
 * ESLint Validator for Claude Code PostToolUse Hook
 *
 * Runs ESLint on individual TypeScript/JavaScript files after Write operations.
 *
 * GOTCHA Framework Integration:
 * - Pushes reliability into deterministic code (Tools layer)
 * - Enforces code quality standards without requiring LLM attention
 * - Implements guardrails for consistent code style
 *
 * For MuAlhashimi Platform - enforces code quality and module boundary rules.
 *
 * Outputs JSON decision for Claude Code PostToolUse hook:
 * - {"decision": "block", "reason": "..."} to block and retry
 * - {} to allow completion
 *
 * See CLAUDE.md for full GOTCHA framework documentation.
 */

import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Logging
const LOG_FILE = join(__dirname, 'eslint_validator.log');
const log = (message: string) => {
  const timestamp = new Date().toISOString();
  console.log(`[ESLint Validator] ${timestamp} | ${message}`);
  if (process.env.HOOK_LOGGING !== 'false') {
    // Append to log file if logging enabled
    require('fs').appendFileSync(LOG_FILE, `${timestamp} | ${message}\n`);
  }
};

function main() {
  log('='.repeat(50));
  log('ESLINT VALIDATOR POSTTOOLUSE HOOK TRIGGERED');

  // Read hook input from environment variables (Claude Code passes via env)
  const hookInputStr = process.env.HOOK_INPUT || '{}';
  let hookInput: any = {};

  try {
    if (hookInputStr) {
      hookInput = JSON.parse(hookInputStr);
      log(`hook_input keys: ${Object.keys(hookInput).join(', ')}`);
    }
  } catch (e) {
    // Invalid JSON, ignore
  }

  // Extract file_path from input
  const file_path = hookInput?.tool_input?.file_path || '';
  log(`file_path: ${file_path}`);

  // Check if this is a TypeScript/JavaScript file in our workspace
  const workspaceRoot = process.cwd();
  const fullPath = file_path.startsWith('/') ? file_path : join(workspaceRoot, file_path);

  // Only check TS/JS files in apps/ and packages/
  if (!fullPath.match(/\.(ts|tsx|js|jsx)$/)) {
    log('Skipping non-TS/JS file');
    console.log(JSON.stringify({}));
    return;
  }

  if (!fullPath.includes('/apps/') && !fullPath.includes('/packages/')) {
    log('Skipping file outside apps/ and packages/');
    console.log(JSON.stringify({}));
    return;
  }

  // Check if eslint config exists
  const eslintConfig = join(workspaceRoot, '.eslintrc.js');
  if (!existsSync(eslintConfig) && !existsSync(eslintConfig.replace('.js', '.mjs'))) {
    log('RESULT: PASS (ESLint config not found, skipping)');
    console.log(JSON.stringify({}));
    return;
  }

  // Run ESLint on the single file
  log(`Running: pnpm eslint "${fullPath}"`);

  try {
    const result = execSync(
      `pnpm eslint --format=json "${fullPath}"`,
      {
        cwd: workspaceRoot,
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe'],
        timeout: 60000, // 60 seconds
      }
    );

    log('RESULT: PASS - ESLint check successful');
    console.log(JSON.stringify({}));

  } catch (error: any) {
    const stdout = error.stdout || '';
    const stderr = error.stderr || '';

    if (stdout) {
      try {
        const eslintOutput = JSON.parse(stdout);
        if (Array.isArray(eslintOutput) && eslintOutput.length > 0) {
          for (const issue of eslintOutput.slice(0, 10)) {
            log(`  ${issue.ruleId}: ${issue.message} (${issue.line}:${issue.column})`);
          }
        }
      } catch {
        // Not JSON, just log as-is
        log(`  ${stdout.split('\n').slice(0, 5).join('\n  ')}`);
      }
    }

    if (stderr) {
      log(`  stderr: ${stderr.split('\n').slice(0, 5).join('\n  ')}`);
    }

    const errorLines = stdout.split('\n').filter((l: string) => l.trim());
    const errorOutput = errorLines.length > 0 ? stdout : stderr || 'ESLint check failed';

    log(`RESULT: BLOCK (exit code ${error.status})`);
    console.log(JSON.stringify({
      decision: 'block',
      reason: `ESLint check failed:\n${errorOutput.slice(0, 500)}`
    }));
  }
}

main();