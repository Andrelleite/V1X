"""Headless coding-agent backends, tried in priority order with fallback.

Gemini is tried first (cost reasons — Anthropic credits are paid for,
Gemini usage is cheaper/already covered), falling back to Claude Code only
if Gemini isn't configured or its run fails. Both backends get the exact
same instruction text; see prompt_builder.py for why the instructions tell
the agent to read CLAUDE.md itself rather than relying on either CLI's own
auto-loaded-context-file convention (CLAUDE.md vs GEMINI.md).

NOTE: the Gemini CLI's exact flags have shifted across releases (--yolo is
reportedly being deprecated in favor of --approval-mode=yolo). Verify
`_gemini_args` against `gemini --help` on the actual CI runner before the
first real end-to-end test, and fix it here if it's drifted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Runner:
    name: str
    binary: str
    api_key_env: str
    build_args: Callable[[str], list[str]]

    def available(self) -> bool:
        return shutil.which(self.binary) is not None and bool(
            os.environ.get(self.api_key_env)
        )

    def unavailable_reason(self) -> str:
        missing = []
        if shutil.which(self.binary) is None:
            missing.append(f"'{self.binary}' binary not on PATH")
        if not os.environ.get(self.api_key_env):
            missing.append(f"{self.api_key_env} not set")
        return ", ".join(missing) or "available"


def _gemini_args(instruction: str, binary: str = "gemini") -> list[str]:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
    return [binary, "-p", instruction, "-m", model, "--approval-mode=yolo"]


def _claude_args(instruction: str, binary: str = "claude") -> list[str]:
    return [binary, "-p", instruction, "--permission-mode", "acceptEdits"]


GEMINI = Runner("gemini", "gemini", "GEMINI_API_KEY", _gemini_args)
CLAUDE = Runner("claude", "claude", "ANTHROPIC_API_KEY", _claude_args)

DEFAULT_PRIORITY: tuple[Runner, ...] = (GEMINI, CLAUDE)


def build_command(instruction: str, runner: Runner) -> list[str]:
    return runner.build_args(instruction)


def select_runner(
    priority: tuple[Runner, ...] = DEFAULT_PRIORITY,
) -> tuple[Runner | None, list[str]]:
    """Pick the first available runner without running anything. Returns
    (runner_or_None, skip_reasons) — used by the dry-run CLI path so you can
    see which backend would actually be used before spending any tokens."""
    skipped = []
    for runner in priority:
        if runner.available():
            return runner, skipped
        skipped.append(f"{runner.name}: {runner.unavailable_reason()}")
    return None, skipped


def run_with_fallback(
    instruction: str,
    repo_dir: str,
    priority: tuple[Runner, ...] = DEFAULT_PRIORITY,
) -> tuple[Runner, subprocess.CompletedProcess]:
    """Try each runner in priority order. A runner that's unavailable
    (binary missing or its API key env var unset) is skipped silently; a
    runner that IS available but exits non-zero counts as a real attempt —
    its result is remembered and returned if nothing later succeeds, never
    swallowed.
    """
    last_attempt: tuple[Runner, subprocess.CompletedProcess] | None = None
    skip_reasons: list[str] = []

    for runner in priority:
        if not runner.available():
            skip_reasons.append(f"{runner.name}: {runner.unavailable_reason()}")
            continue

        cmd = build_command(instruction, runner)
        result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
        if result.returncode == 0:
            return runner, result
        last_attempt = (runner, result)

    if last_attempt:
        return last_attempt

    raise RuntimeError(
        "No coding-agent backend is available. " + "; ".join(skip_reasons)
    )
