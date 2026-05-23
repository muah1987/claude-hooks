#!/usr/bin/env node
/**
 * TypeScript Type Check Validator for Claude Code PostToolUse Hook
 *
 * Runs `pnpm tsc --noEmit` on individual TypeScript files after Write operations.
 *
 * GOTCHA Framework Integration:
 * - Pushes reliability into deterministic code (Tools layer)
 * - Enforces type safety without requiring LLM attention
 * - Implements guardrails for consistent type checking
 *
 * For MuAlhashimi Platform - enforces type safety across the monorepo.
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
const LOG_FILE = join(__dirname, 'tsc_validator.log');
const log = (message: string) => {
  const timestamp = new Date().toISOString();
  console.log(`[TSC Validator] ${timestamp} | ${message}`);
  if (process.env.HOOK_LOGGING !== 'false') {
    require('fs').appendFileSync(LOG_FILE, `${timestamp} | ${message}\n`);
  }
};

function main() {
  log('='.repeat(50));
  log('TSC VALIDATOR POSTTOOLUSE HOOK TRIGGERED');

  // Read hook input from environment variables
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

  const file_path = hookInput?.tool_input?.file_path || '';
  log(`file_path: ${file_path}`);

  // Only check TypeScript files
  if (!file_path.match(/\.(ts|tsx)$/)) {
    log('Skipping non-TS file');
    console.log(JSON.stringify({}));
    return;
  }

  // Check if tsconfig exists
  const workspaceRoot = process.cwd();
  const tsconfig = join(workspaceRoot, 'tsconfig.json');

  if (!existsSync(tsconfig)) {
    log('RESULT: PASS (tsconfig.json not found, skipping)');
    console.log(JSON.stringify({}));
    return;
  }

  log(`Running: pnpm tsc --noEmit "${file_path}"`);

  try {
    // Build affected packages first for type checking
    const fullPath = file_path.startsWith('/') ? file_path : join(workspaceRoot, file_path);
    const relativePath = fullPath.replace(workspaceRoot + '/', '');

    // Determine which package this file belongs to
    let targetPackage = '';
    if (relativePath.startsWith('apps/api')) {
      targetPackage = '--filter=@mualhashimi/api';
    } else if (relativePath.startsWith('apps/web')) {
      targetPackage = '--filter=@mualhashimi/web';
    } else if (relativePath.startsWith('packages/')) {
      const pkgName = relativePath.split('/')[1];
      targetPackage = `--filter=@mualhashimi/${pkgName}`;
    }

    if (targetPackage) {
      log(`Building package: pnpm build ${targetPackage}`);
      execSync(`pnpm build ${targetPackage}`, { cwd: workspaceRoot, stdio: 'pipe' });
    }

    // Run type check
    execSync('pnpm typecheck', {
      cwd: workspaceRoot,
      stdio: 'pipe',
      timeout: 120000, // 2 minutes
    });

    log('RESULT: PASS - Type check successful');
    console.log(JSON.stringify({}));

  } catch (error: any) {
    const stderr = error.stderr || error.stdout || '';
    log(`RESULT: BLOCK (exit code ${error.status})`);
    log(`  ERROR: ${stderr.split('\n').slice(0, 5).join('\n  ')}`);

    console.log(JSON.stringify({
      decision: 'block',
      reason: `Type check failed:\n${stderr.slice(0, 500)}`
    }));
  }
}

main();