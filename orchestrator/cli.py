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
import os
import sys
from pathlib import Path

from . import context as context_module
from . import cost as cost_module
from .fixer import run_fix, run_review
from .models import Decision, ReviewComment, VulnTicket
from .prompt_builder import (
    build_fix_instruction,
    build_review_instruction,
    category_line,
    primary_category_keyword,
)
from .report import parse_fix_report, render_mr_description
from .review_loop import route
from .runners import build_command, claude_uses_subscription, select_runner

JIRA_SITE_URL = os.environ.get("JIRA_SITE_URL", "https://vixai.atlassian.net")
GITLAB_API_BASE = os.environ.get("GITLAB_API_BASE", "https://gitlab.com/api/v4")


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _issue_url(issue_key: str) -> str:
    return f"{JIRA_SITE_URL}/browse/{issue_key}"


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


def _gather_context(ticket: VulnTicket) -> str:
    keyword = primary_category_keyword(ticket.text)
    print(f"[context] searching Jira/Confluence/GitLab for: {keyword!r}")
    block = context_module.gather_all(
        keyword=keyword,
        exclude_key=ticket.key,
        jira_site_url=JIRA_SITE_URL,
        jira_email=os.environ.get("JIRA_EMAIL", ""),
        jira_token=os.environ.get("JIRA_API_TOKEN", ""),
        gitlab_api_base=GITLAB_API_BASE,
        gitlab_project_path=ticket.repo or "",
        gitlab_token=os.environ.get("TARGET_REPO_TOKEN", ""),
    )
    print(f"[context] {block}")
    return block


def cmd_fix(args: argparse.Namespace) -> int:
    payload = _load_json(args.payload)
    ticket = VulnTicket.from_jira_payload(payload)
    related_context = _gather_context(ticket)
    instruction = build_fix_instruction(ticket, related_context=related_context)

    print(f"[fix] ticket={ticket.key} repo={ticket.repo}")
    _report_selection(instruction)

    if not args.execute:
        print("[fix] dry run — pass --execute to actually invoke a backend")
        return 0

    runner, result = run_fix(ticket, repo_dir=args.repo_dir)
    print(f"[fix] ran with backend={runner.name}")
    print(result.stdout)
    print(result.stderr, file=sys.stderr)

    run_cost = cost_module.extract(
        runner.name, result.stdout, using_subscription=claude_uses_subscription()
    )
    report = parse_fix_report(run_cost.text)
    description = render_mr_description(
        ticket,
        category_line(ticket.text),
        report,
        backend=runner.name,
        issue_url=_issue_url(ticket.key),
        cost_usd=run_cost.cost_usd,
        cost_note=run_cost.cost_note,
    )
    Path(args.mr_description_out).write_text(description)
    print(f"[fix] wrote MR description to {args.mr_description_out} "
          f"(report found: {report.found}, confidence: {report.confidence}, "
          f"blast_radius: {report.blast_radius}, cost_usd: {run_cost.cost_usd})")

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
    fix_p.add_argument("--mr-description-out", default="mr_description.md")
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
