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
from pathlib import Path
from typing import Callable

# Linux (GitHub Actions runners) stores the Claude Code subscription OAuth
# session as a JSON file at this path — restored from the
# CLAUDE_CODE_OAUTH_CREDS secret by the workflow before this ever runs. On
# macOS the equivalent lives in the system Keychain instead, which is
# irrelevant here since the pipeline only ever runs this check on Linux.
CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"


@dataclass(frozen=True)
class Runner:
    name: str
    binary: str
    build_args: Callable[[str], list[str]]
    is_configured: Callable[[], bool]
    config_hint: str

    def available(self) -> bool:
        return shutil.which(self.binary) is not None and self.is_configured()

    def unavailable_reason(self) -> str:
        missing = []
        if shutil.which(self.binary) is None:
            missing.append(f"'{self.binary}' binary not on PATH")
        if not self.is_configured():
            missing.append(self.config_hint)
        return ", ".join(missing) or "available"


def _gemini_args(instruction: str, binary: str = "gemini") -> list[str]:
    # gemini-2.5-pro and gemini-2.5-flash were both retired for new API
    # users within days of each other in real CI runs (404
    # ModelNotFoundError each time) — pro-tier models left the free tier
    # entirely in April 2026, and flash model names keep rotating too.
    # gemini-3.8-flash is the current free-tier-eligible default; override
    # via GEMINI_MODEL the moment this drifts again (it will).
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    # --skip-trust bypasses Gemini CLI's workspace-trust gate, which is a
    # SEPARATE check from --approval-mode: without it, in a headless/CI
    # environment with no TTY to grant trust interactively, Gemini silently
    # downgrades approval-mode back to "default" (observed in a real CI
    # run) and then fails outright since nothing can approve its tool calls.
    # --output-format json gets a single structured result (response text +
    # token-usage stats) instead of mixed progress/warning noise on stdout —
    # see orchestrator/cost.py, which parses it for both the agent's actual
    # text (for FIX_REPORT) and an estimated run cost (Gemini's CLI doesn't
    # report a dollar figure directly, so cost.py computes one from the
    # token counts here).
    return [
        binary, "-p", instruction, "-m", model,
        "--approval-mode=yolo", "--skip-trust", "--output-format", "json",
    ]


def _claude_args(instruction: str, binary: str = "claude") -> list[str]:
    # acceptEdits only auto-approves the Edit/Write tools, NOT Bash — a real
    # CI run showed Claude write the fix to disk successfully but then get
    # stuck asking for approval on `git add`/`git commit` (nobody's there to
    # approve it in headless CI), so the branch got pushed with zero actual
    # changes. Rather than bypassing ALL permissions (which a safety check
    # correctly flagged as configuring an unattended agent with no approval
    # gate on anything, including arbitrary Bash), pre-approve only the
    # specific commands this job needs: `git add`/`git commit` to finish
    # the fix, plus read-only git history inspection (log/blame/show/grep)
    # so the agent can dig into prior related changes itself if useful —
    # safe to allow since none of these have side effects. Our own script
    # handles `git push` and MR creation deterministically after this
    # runs — Claude never needs those itself.
    # --output-format json: see orchestrator/cost.py — Claude Code may
    # report a real cost_usd/total_cost_usd figure directly (unlike
    # Gemini), which is strictly more accurate than any estimate we could
    # compute ourselves (it correctly accounts for prompt-cache discounts).
    return [
        binary,
        "-p",
        instruction,
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(git log:*)",
        "Bash(git blame:*)",
        "Bash(git show:*)",
        "Bash(git grep:*)",
        "--output-format",
        "json",
    ]


def _gemini_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _claude_configured() -> bool:
    # Either a billed API key, OR a restored subscription (Pro/Max) OAuth
    # session file — see CLAUDE_CODE_OAUTH_CREDS in the workflows.
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or CLAUDE_CREDENTIALS_FILE.exists()


def claude_uses_subscription() -> bool:
    """True when Claude ran on the restored Pro/Max OAuth session rather
    than a billed API key — used by cost.py, since a subscription run has
    no marginal per-request dollar cost to report at all."""
    return not bool(os.environ.get("ANTHROPIC_API_KEY"))


GEMINI = Runner(
    "gemini", "gemini", _gemini_args, _gemini_configured, "GEMINI_API_KEY not set"
)
CLAUDE = Runner(
    "claude",
    "claude",
    _claude_args,
    _claude_configured,
    "ANTHROPIC_API_KEY not set and no restored subscription session at "
    f"{CLAUDE_CREDENTIALS_FILE} (run `claude login` locally, or restore "
    "CLAUDE_CODE_OAUTH_CREDS in CI)",
)

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
