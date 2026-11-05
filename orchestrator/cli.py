"""Entry point used by the GitHub Actions workflows (.github/workflows/).

Defaults to a dry run (shows which backend WOULD be used and the instruction
it would receive) so this is safe to execute locally or in a smoke-test job
without either CLI installed or any API key set. Pass --execute to actually
invoke the selected coding agent (Gemini CLI first, Claude Code fallback).

Usage:
    python -m orchestrator.cli fix --payload path/to/jira_payload.json
    python -m orchestrator.cli review --payload path/to/review_payload.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fixer import run_fix, run_review
from .models import Decision, ReviewComment, VulnTicket
from .prompt_builder import build_fix_instruction, build_review_instruction
from .review_loop import route
from .runners import build_command, select_runner


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _report_selection(instruction: str) -> None:
    runner, skipped = select_runner()
    for note in skipped:
        print(f"[skip] {note}")
    if runner is None:
        print("[select] no backend available (set GEMINI_API_KEY and/or "
              "ANTHROPIC_API_KEY, and make sure the matching CLI is on PATH)")
        return
    cmd = build_command(instruction, runner)
    print(f"[select] would run: {runner.name}")
    print(f"[select] command={cmd!r}")


def cmd_fix(args: argparse.Namespace) -> int:
    payload = _load_json(args.payload)
    ticket = VulnTicket.from_jira_payload(payload)
    instruction = build_fix_instruction(ticket)

    print(f"[fix] ticket={ticket.key} repo={ticket.repo}")
    _report_selection(instruction)

    if not args.execute:
        print("[fix] dry run — pass --execute to actually invoke a backend")
        return 0

    runner, result = run_fix(ticket, repo_dir=args.repo_dir)
    print(f"[fix] ran with backend={runner.name}")
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    return result.returncode


def cmd_review(args: argparse.Namespace) -> int:
    payload = _load_json(args.payload)
    comment = ReviewComment(
        body=payload["body"],
        file_path=payload.get("file_path"),
        line=payload.get("line"),
        author=payload.get("author", "coderabbitai"),
    )
    decision: Decision = route(comment, evidence=payload.get("evidence"))
    instruction = build_review_instruction(comment, decision)

    print(f"[review] decision.path={decision.path} reason={decision.reason!r}")
    _report_selection(instruction)

    if not args.execute:
        print("[review] dry run — pass --execute to actually invoke a backend")
        return 0

    runner, result = run_review(comment, decision, repo_dir=args.repo_dir)
    print(f"[review] ran with backend={runner.name}")
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    fix_p = sub.add_parser("fix", help="Handle a new Jira vulnerability ticket")
    fix_p.add_argument("--payload", required=True, help="Path to a JSON payload file")
    fix_p.add_argument("--repo-dir", default=".")
    fix_p.add_argument("--execute", action="store_true")
    fix_p.set_defaults(func=cmd_fix)

    review_p = sub.add_parser("review", help="Handle a CodeRabbit review comment")
    review_p.add_argument("--payload", required=True, help="Path to a JSON payload file")
    review_p.add_argument("--repo-dir", default=".")
    review_p.add_argument("--execute", action="store_true")
    review_p.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
