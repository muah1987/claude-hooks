#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tenacity"]
# ///

"""
Parallel Tool Call Executor

Executes multiple Bash commands with:
- Concurrency limiting (semaphore-based)
- Retry with exponential backoff
- Timeout per command
- Ordered result aggregation

Usage:
    uv run .claude/scripts/parallel_executor.py -- cmd1 -- cmd2 -- cmd3 --limit 3 --retry 3 --timeout 30000
"""
__version__ = "2026.04.20.2"

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
        RetryError,
    )
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False
    RetryError = Exception


@dataclass
class CommandResult:
    """Result of a single command execution."""
    index: int
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    success: bool = False
    error: Optional[str] = None
    retries: int = 0


@dataclass
class ParallelConfig:
    """Configuration for parallel execution."""
    concurrency_limit: int = 3
    max_retries: int = 3
    timeout_ms: int = 30000
    base_delay_ms: int = 1000
    max_delay_ms: int = 10000


class ParallelExecutor:
    """Executes commands in parallel with rate limiting and retry."""

    def __init__(self, config: ParallelConfig):
        self.config = config
        self.semaphore = asyncio.Semaphore(config.concurrency_limit)
        self.results: List[CommandResult] = []

    async def execute_command(
        self,
        index: int,
        command: str,
    ) -> CommandResult:
        """Execute a single command with retry logic."""
        result = CommandResult(index=index, command=command)

        async def _run_once():
            timeout_s = self.config.timeout_ms / 1000
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_s,
                )
                result.stdout = stdout.decode("utf-8", errors="replace")
                result.stderr = stderr.decode("utf-8", errors="replace")
                result.returncode = process.returncode
                result.success = process.returncode == 0

                if not result.success:
                    # Check for 500 errors that should be retried
                    if "500" in result.stderr or "Internal Server Error" in result.stderr:
                        raise ConnectionError(f"API error (500): {result.stderr[:200]}")

            except asyncio.TimeoutError:
                result.error = f"Timeout after {timeout_s}s"
                result.success = False
                raise subprocess.TimeoutExpired(command, timeout_s)

        if _HAS_TENACITY:
            @retry(
                stop=stop_after_attempt(self.config.max_retries),
                wait=wait_exponential(
                    multiplier=1,
                    min=self.config.base_delay_ms / 1000,
                    max=self.config.max_delay_ms / 1000,
                ),
                retry=retry_if_exception_type((subprocess.TimeoutExpired, ConnectionError)),
                reraise=True,
            )
            async def run_with_retry():
                await _run_once()

            async with self.semaphore:
                try:
                    await run_with_retry()
                except RetryError:
                    result.retries = self.config.max_retries
                    result.error = "Max retries exceeded"
                except (subprocess.TimeoutExpired, ConnectionError) as e:
                    result.retries = self.config.max_retries
                    result.error = str(e)
                except Exception as e:
                    result.error = str(e)
        else:
            # No tenacity — simple retry loop
            async with self.semaphore:
                attempt = 0
                while attempt < self.config.max_retries:
                    try:
                        await _run_once()
                        break
                    except (subprocess.TimeoutExpired, ConnectionError) as e:
                        attempt += 1
                        result.retries = attempt
                        if attempt >= self.config.max_retries:
                            result.error = str(e)
                        else:
                            await asyncio.sleep(
                                min(
                                    self.config.base_delay_ms / 1000 * (2 ** (attempt - 1)),
                                    self.config.max_delay_ms / 1000,
                                )
                            )
                    except Exception as e:
                        result.error = str(e)
                        break

        return result

    async def execute_all(
        self,
        commands: List[str],
    ) -> List[CommandResult]:
        """Execute all commands in parallel with concurrency limit."""
        tasks = [
            self.execute_command(index, command)
            for index, command in enumerate(commands)
        ]
        self.results = await asyncio.gather(*tasks)
        # Sort by original index to preserve order
        self.results.sort(key=lambda r: r.index)
        return self.results


def parse_commands(args: List[str]) -> tuple[List[str], ParallelConfig]:
    """Parse command line arguments."""
    commands = []
    current_cmd = []
    config = ParallelConfig()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--limit" and i + 1 < len(args):
            config.concurrency_limit = int(args[i + 1])
            i += 2
        elif arg == "--retry" and i + 1 < len(args):
            config.max_retries = int(args[i + 1])
            i += 2
        elif arg == "--timeout" and i + 1 < len(args):
            config.timeout_ms = int(args[i + 1])
            i += 2
        elif arg == "--":
            if current_cmd:
                commands.append(" ".join(current_cmd))
                current_cmd = []
            i += 1
        else:
            current_cmd.append(arg)
            i += 1

    if current_cmd:
        commands.append(" ".join(current_cmd))

    return commands, config


def main() -> None:
    """Main entry point."""
    # Skip script name if present
    args = sys.argv[1:]
    if args and args[0].endswith("parallel_executor.py"):
        args = args[1:]

    commands, config = parse_commands(args)

    if not commands:
        print("Usage: parallel_executor.py -- cmd1 -- cmd2 -- cmd3 [options]")
        print("Options:")
        print("  --limit N     Max concurrent commands (default: 3)")
        print("  --retry N     Max retries per command (default: 3)")
        print("  --timeout N   Timeout in ms per command (default: 30000)")
        sys.exit(1)

    executor = ParallelExecutor(config)
    results = asyncio.run(executor.execute_all(commands))

    # Output results as JSON array
    output = []
    for result in results:
        output.append({
            "index": result.index,
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "retries": result.retries,
            "error": result.error,
        })

    print(json.dumps(output, indent=2))

    # Always exit 0 — callers should inspect the JSON `success` fields instead
    sys.exit(0)


if __name__ == "__main__":
    main()
