"""Invokes a headless coding agent inside the CI runner — Gemini CLI first,
Claude Code as fallback (see runners.py). Kept as a thin, mockable wrapper
around subprocess so the instruction-building logic (prompt_builder) can be
unit tested without ever spawning a real process.
"""
from __future__ import annotations

import subprocess

from .models import Decision, ReviewComment, VulnTicket
from .prompt_builder import build_fix_instruction, build_review_instruction
from .runners import Runner, run_with_fallback


def run_fix(
    ticket: VulnTicket, repo_dir: str
) -> tuple[Runner, subprocess.CompletedProcess]:
    instruction = build_fix_instruction(ticket)
    return run_with_fallback(instruction, repo_dir)


def run_review(
    comment: ReviewComment, decision: Decision, repo_dir: str
) -> tuple[Runner, subprocess.CompletedProcess]:
    instruction = build_review_instruction(comment, decision)
    return run_with_fallback(instruction, repo_dir)
