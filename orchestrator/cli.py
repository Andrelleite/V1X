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
import subprocess
import sys
from pathlib import Path

from . import aggregation as aggregation_module
from . import context as context_module
from . import cost as cost_module
from . import gitlab_review as gitlab_review_module
from .fixer import run_fix, run_review
from .models import Decision, ReviewComment, VulnTicket
from .prompt_builder import (
    build_fix_instruction,
    build_review_instruction,
    category_line,
    primary_category_keyword,
)
from .report import parse_fix_report, render_mr_description
from .review_loop import parse_review_response, route
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
    terms = context_module.extract_search_terms(ticket.text, keyword)
    print(f"[context] search terms, most specific first: {terms!r}")
    block = context_module.gather_all(
        ticket_text=ticket.text,
        fallback_keyword=keyword,
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

    print(f"[fix] ticket={ticket.key} repo={ticket.repo}")

    if not args.execute:
        # Dry run stays side-effect-free: context gathering makes real
        # network calls (Jira/Confluence/GitLab), so it's skipped here and
        # only happens once we're actually about to invoke a backend.
        instruction = build_fix_instruction(ticket)
        _report_selection(instruction)
        print("[fix] dry run — pass --execute to actually invoke a backend "
              "(context search is skipped in dry runs too)")
        return 0

    related_context = _gather_context(ticket)
    instruction = build_fix_instruction(ticket, related_context=related_context)
    _report_selection(instruction)

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


def cmd_aggregate_check(args: argparse.Namespace) -> int:
    """Checks whether this ticket is a near-duplicate of an already-open
    pipeline-created MR (see orchestrator/aggregation.py) and, if so,
    writes AGGREGATE_MR_IID/AGGREGATE_BRANCH to a shell-sourceable file
    for the CI script to pick up. Writes nothing (empty file) when there's
    no match, or when there's no TARGET_REPO_TOKEN/repo to check against
    — read-only, never fails the job."""
    payload = _load_json(args.payload)
    ticket = VulnTicket.from_jira_payload(payload)
    token = os.environ.get("TARGET_REPO_TOKEN", "")

    if not token or not ticket.repo:
        print("[aggregate] no TARGET_REPO_TOKEN/repo — skipping aggregation check")
        Path(args.out).write_text("")
        return 0

    open_mrs = aggregation_module.list_open_fix_mrs(GITLAB_API_BASE, ticket.repo, token)
    print(f"[aggregate] found {len(open_mrs)} open pipeline-created MR(s) to compare against")
    open_mrs = aggregation_module.enrich_with_jira_text(
        open_mrs, JIRA_SITE_URL,
        os.environ.get("JIRA_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", ""),
    )

    match = aggregation_module.find_aggregation_target(ticket.text, ticket.key, open_mrs)
    if match is None:
        print("[aggregate] no match above "
              f"{aggregation_module.SIMILARITY_THRESHOLD_PERCENT:.0f}% similarity — will open a new MR")
        Path(args.out).write_text("")
        return 0

    mr, score = match
    print(f"[aggregate] matched !{mr.iid} ({mr.source_branch}) at {score:.1f}% similarity — aggregating")
    Path(args.out).write_text(
        f"AGGREGATE_MR_IID={mr.iid}\n"
        f"AGGREGATE_BRANCH={mr.source_branch}\n"
        f"AGGREGATE_SIMILARITY={score:.1f}\n"
    )
    return 0


def cmd_prepare_mr_update(args: argparse.Namespace) -> int:
    """Fetches the target MR's current title/description and writes the
    MERGED versions to files the CI script's curl PUT then uses — keeps
    the actual mutating API call in the YAML (consistent with how MR
    creation/push already work) while the text-merging logic stays here,
    tested."""
    payload = _load_json(args.payload)
    ticket = VulnTicket.from_jira_payload(payload)
    token = os.environ.get("TARGET_REPO_TOKEN", "")

    current = aggregation_module.get_mr(GITLAB_API_BASE, ticket.repo or "", token, args.mr_iid)
    if current is None:
        print(f"[aggregate] could not fetch MR !{args.mr_iid} to update")
        return 1

    new_section = Path(args.mr_description).read_text()
    merged_title = aggregation_module.build_merged_title(current.get("title", ""), ticket.key)
    merged_description = aggregation_module.build_merged_description(
        current.get("description", ""), new_section, ticket.key, args.similarity
    )

    Path(args.title_out).write_text(merged_title)
    Path(args.description_out).write_text(merged_description)
    print(f"[aggregate] prepared merged title/description for MR !{args.mr_iid}: {merged_title!r}")
    return 0


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


def _run_git(repo_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True)


def _checkout_mr_branch(repo_dir: str, repo: str, token: str, mr_iid: int) -> str | None:
    """Fetches an MR's source branch and checks it out in the already-
    cloned `repo_dir`. Returns the branch name on success, None if the MR
    can't be found or the fetch/checkout fails."""
    mr = aggregation_module.get_mr(GITLAB_API_BASE, repo, token, mr_iid)
    branch = (mr or {}).get("source_branch")
    if not branch:
        return None
    url = f"https://oauth2:{token}@gitlab.com/{repo}.git"
    if _run_git(repo_dir, "fetch", url, branch).returncode != 0:
        return None
    if _run_git(repo_dir, "checkout", "FETCH_HEAD", "-B", branch).returncode != 0:
        return None
    return branch


def _push_current_branch(repo_dir: str, repo: str, token: str, branch: str) -> bool:
    url = f"https://oauth2:{token}@gitlab.com/{repo}.git"
    return _run_git(repo_dir, "push", url, f"HEAD:{branch}").returncode == 0


def cmd_review_loop(args: argparse.Namespace) -> int:
    """Polls every currently-open pipeline-created MR for unresolved
    CodeRabbit discussion threads, routes each through review_loop.route(),
    and either pushes a fix or posts a false-positive defense — closing
    the loop CLAUDE.md's Phase 2(b) describes. Meant to run on a GitLab
    CI/CD Pipeline Schedule (see docs/gitlab-review-loop-schedule.md), not
    on the Jira-triggered pipeline source."""
    token = os.environ.get("TARGET_REPO_TOKEN", "")
    if not token or not args.repo:
        print("[review-loop] no TARGET_REPO_TOKEN/--repo — nothing to do")
        return 0

    threads = gitlab_review_module.list_all_unresolved_threads(
        GITLAB_API_BASE, args.repo, token
    )
    print(f"[review-loop] found {len(threads)} unresolved CodeRabbit thread(s)")

    if not args.execute:
        for t in threads:
            print(f"[review-loop] (dry run) would handle MR !{t.mr_iid} "
                  f"discussion {t.discussion_id}: {t.comment.body[:80]!r}")
        return 0

    exit_code = 0
    for t in threads:
        print(f"[review-loop] handling MR !{t.mr_iid} discussion {t.discussion_id}")
        decision: Decision = route(t.comment)
        print(f"[review-loop] decision.path={decision.path} reason={decision.reason!r}")

        branch = _checkout_mr_branch(args.repo_dir, args.repo, token, t.mr_iid)
        if branch is None:
            print(f"[review-loop] could not check out MR !{t.mr_iid}'s branch — skipping")
            exit_code = 1
            continue

        runner, result = run_review(t.comment, decision, repo_dir=args.repo_dir)
        print(f"[review-loop] ran with backend={runner.name}")
        print(result.stdout)
        print(result.stderr, file=sys.stderr)

        response = parse_review_response(result.stdout)
        if not response.found:
            print(f"[review-loop] no parseable ===REVIEW_RESPONSE=== block for "
                  f"MR !{t.mr_iid} — leaving thread unresolved")
            exit_code = 1
            continue

        if response.path == "FIXED":
            if not _push_current_branch(args.repo_dir, args.repo, token, branch):
                print(f"[review-loop] fix committed but push failed for "
                      f"MR !{t.mr_iid} — leaving thread unresolved")
                exit_code = 1
                continue
            reply = f"FIXED: {response.message}"
        else:
            reply = f"FALSE POSITIVE DEFENSE: {response.message}"

        if not gitlab_review_module.reply_and_resolve(
            GITLAB_API_BASE, args.repo, token, t.mr_iid, t.discussion_id, reply
        ):
            print(f"[review-loop] responded but failed to reply/resolve on MR !{t.mr_iid}")
            exit_code = 1

    return exit_code


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

    agg_check_p = sub.add_parser(
        "aggregate-check",
        help="Check whether this ticket near-duplicates an already-open pipeline MR",
    )
    agg_check_p.add_argument("--payload", required=True, help="Path to a JSON payload file")
    agg_check_p.add_argument("--out", default="aggregate.env")
    agg_check_p.set_defaults(func=cmd_aggregate_check)

    agg_update_p = sub.add_parser(
        "prepare-mr-update",
        help="Compute the merged title/description for an aggregated MR update",
    )
    agg_update_p.add_argument("--payload", required=True, help="Path to a JSON payload file")
    agg_update_p.add_argument("--mr-iid", required=True, type=int)
    agg_update_p.add_argument("--mr-description", required=True, help="This run's rendered report")
    agg_update_p.add_argument("--similarity", required=True, type=float)
    agg_update_p.add_argument("--title-out", default="mr_title.txt")
    agg_update_p.add_argument("--description-out", default="mr_description_merged.md")
    agg_update_p.set_defaults(func=cmd_prepare_mr_update)

    review_loop_p = sub.add_parser(
        "review-loop",
        help="Poll open fix MRs for unresolved CodeRabbit threads and respond to each",
    )
    review_loop_p.add_argument("--repo", required=True, help="TARGET_REPO, e.g. group/name")
    review_loop_p.add_argument("--repo-dir", default="target")
    review_loop_p.add_argument("--execute", action="store_true")
    review_loop_p.set_defaults(func=cmd_review_loop)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
