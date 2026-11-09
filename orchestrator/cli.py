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
import time
from pathlib import Path

from . import aggregation as aggregation_module
from . import context as context_module
from . import cost as cost_module
from . import cost_report as cost_report_module
from . import gitlab_review as gitlab_review_module
from .fixer import run_fix, run_review
from .gitlab_review import OpenThread
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


def _print_attempts(label: str, attempts: list) -> None:
    """Prints every backend actually attempted, not just the final one —
    a Gemini failure that falls through to Claude used to be completely
    invisible in the job log (only Claude's unrelated failure ever
    printed), which defeats the point of readable CI logs."""
    for runner, result in attempts[:-1]:
        print(f"[{label}] {runner.name} failed (exit {result.returncode}), falling back")
        if result.stdout.strip():
            print(f"[{label}] {runner.name} stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            print(f"[{label}] {runner.name} stderr: {result.stderr.strip()}")
    final_runner, final_result = attempts[-1]
    print(f"[{label}] ran with backend={final_runner.name} (exit {final_result.returncode})")
    print(final_result.stdout)
    print(final_result.stderr, file=sys.stderr)


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

    runner, result, attempts = run_fix(ticket, repo_dir=args.repo_dir)
    _print_attempts("fix", attempts)

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

    runner, result, attempts = run_review(comment, decision, repo_dir=args.repo_dir)
    _print_attempts("review", attempts)
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


def _handle_review_thread(
    label: str, t: OpenThread, repo: str, repo_dir: str, token: str
) -> bool:
    """Routes one CodeRabbit thread through review_loop.route(), runs the
    Fixer, and pushes a fix or posts a defense, then replies and resolves
    the thread either way. Shared by review-loop (sweeps every open MR
    once) and review-watch (loops on one MR until it's actually settled).
    Returns False on any failure — the thread is deliberately left
    unresolved so a later pass retries it rather than silently dropping it.
    """
    print(f"[{label}] handling MR !{t.mr_iid} discussion {t.discussion_id}")
    decision: Decision = route(t.comment)
    print(f"[{label}] decision.path={decision.path} reason={decision.reason!r}")

    branch = _checkout_mr_branch(repo_dir, repo, token, t.mr_iid)
    if branch is None:
        print(f"[{label}] could not check out MR !{t.mr_iid}'s branch — skipping")
        return False

    runner, result, attempts = run_review(t.comment, decision, repo_dir=repo_dir)
    _print_attempts(label, attempts)

    # result.stdout is the raw --output-format json blob (its real
    # newlines are JSON-escaped, all on one line) -- must decode it to
    # get the agent's actual response text before line-parsing it for
    # the ===REVIEW_RESPONSE=== block, same as cmd_fix does via
    # cost_module.extract() before parse_fix_report().
    run_cost = cost_module.extract(
        runner.name, result.stdout, using_subscription=claude_uses_subscription()
    )
    # Printed unconditionally, even on an otherwise-failed thread below --
    # a thread that fails to parse or push still spent real money on the
    # backend call that was attempted, and a cost pilot that only sees the
    # successful threads undercounts the true spend per ticket.
    print(f"[{label}] MR !{t.mr_iid} thread cost_usd: {run_cost.cost_usd} ({run_cost.cost_note})")
    response = parse_review_response(run_cost.text)
    if not response.found:
        print(f"[{label}] no parseable ===REVIEW_RESPONSE=== block for "
              f"MR !{t.mr_iid} — leaving thread unresolved")
        return False

    if response.path == "FIXED":
        if not _push_current_branch(repo_dir, repo, token, branch):
            print(f"[{label}] fix committed but push failed for "
                  f"MR !{t.mr_iid} — leaving thread unresolved")
            return False
        reply = f"FIXED: {response.message}"
        # Don't rely on "Incremental review" auto-firing within our wait
        # window -- explicitly ask for a fresh review so the next poll
        # round has something real to check instead of hoping.
        if not gitlab_review_module.trigger_review(GITLAB_API_BASE, repo, token, t.mr_iid):
            print(f"[{label}] pushed the fix but failed to trigger a re-review on MR !{t.mr_iid}")
    else:
        reply = f"FALSE POSITIVE DEFENSE: {response.message}"

    if not gitlab_review_module.reply_and_resolve(
        GITLAB_API_BASE, repo, token, t.mr_iid, t.discussion_id, reply
    ):
        print(f"[{label}] responded but failed to reply/resolve on MR !{t.mr_iid}")
        return False

    return True


def cmd_review_loop(args: argparse.Namespace) -> int:
    """Polls every currently-open pipeline-created MR for unresolved
    CodeRabbit discussion threads and handles each one. The backstop for
    whatever review-watch (below) didn't catch live — an MR opened before
    this existed, or one that hit review-watch's round cap. Runs on every
    trigger-sourced pipeline (see .gitlab-ci.yml) and, if available, on a
    GitLab CI/CD Pipeline Schedule too (docs/gitlab-review-loop-schedule.md)."""
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
        if not _handle_review_thread("review-loop", t, args.repo, args.repo_dir, token):
            exit_code = 1
    return exit_code


def cmd_review_watch(args: argparse.Namespace) -> int:
    """Watches ONE just-opened MR live, right after ai_fix creates it:
    waits for CodeRabbit's first review, handles every unresolved thread,
    waits again for CodeRabbit's incremental re-review (it re-reviews on
    each push), and repeats until a poll finds nothing left unresolved —
    CodeRabbit has approved or every remaining comment was defended with
    evidence — or --max-rounds is hit, whichever comes first. A round-cap
    exit does NOT fail the job: the MR already exists, which is the real
    deliverable: periodic review_loop sweeps keep trying from there."""
    token = os.environ.get("TARGET_REPO_TOKEN", "")
    if not token or not args.repo:
        print("[review-watch] no TARGET_REPO_TOKEN/--repo — nothing to do")
        return 0

    if not args.execute:
        print(f"[review-watch] (dry run) would watch MR !{args.mr_iid} "
              f"for up to {args.max_rounds} round(s)")
        return 0

    print(f"[review-watch] waiting {args.initial_wait_seconds}s for "
          f"CodeRabbit's first review of MR !{args.mr_iid}")
    time.sleep(args.initial_wait_seconds)

    exit_code = 0
    for round_num in range(1, args.max_rounds + 1):
        threads = gitlab_review_module.list_unresolved_coderabbit_threads(
            GITLAB_API_BASE, args.repo, token, args.mr_iid
        )
        if not threads:
            print(f"[review-watch] round {round_num}: no unresolved CodeRabbit "
                  f"threads on MR !{args.mr_iid} — done")
            return exit_code

        print(f"[review-watch] round {round_num}: {len(threads)} unresolved thread(s)")
        for t in threads:
            if not _handle_review_thread("review-watch", t, args.repo, args.repo_dir, token):
                exit_code = 1

        if round_num < args.max_rounds:
            print(f"[review-watch] waiting {args.poll_interval_seconds}s for "
                  f"CodeRabbit's next review")
            time.sleep(args.poll_interval_seconds)

    print(f"[review-watch] hit max rounds ({args.max_rounds}) — MR !{args.mr_iid} "
          "may still have unresolved threads; the periodic review_loop sweep will keep trying")
    return exit_code


def cmd_cost_report(args: argparse.Namespace) -> int:
    """Turns a hand-filled JSON file of per-ticket cost figures (copied
    from real job logs -- see docs/cost-pilot.md) into the cost/ROI
    summary for the "is this worth it" pilot. Each entry:
    {"issue_key": "VD-30", "fix_cost_usd": 0.41, "review_cost_usd": 0.18}."""
    entries_data = _load_json(args.entries)
    entries = [
        (
            e["issue_key"],
            float(e["fix_cost_usd"]),
            float(e.get("review_cost_usd", 0.0)),
        )
        for e in entries_data
    ]
    report = cost_report_module.build_report(
        entries,
        baseline_hourly_usd=args.baseline_hourly_usd,
        baseline_hours_per_ticket=args.baseline_hours_per_ticket,
    )
    text = cost_report_module.render_report(report)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0


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

    review_watch_p = sub.add_parser(
        "review-watch",
        help="Watch one just-opened MR live until CodeRabbit settles or --max-rounds is hit",
    )
    review_watch_p.add_argument("--repo", required=True, help="TARGET_REPO, e.g. group/name")
    review_watch_p.add_argument("--mr-iid", required=True, type=int)
    review_watch_p.add_argument("--repo-dir", default="target")
    review_watch_p.add_argument("--execute", action="store_true")
    review_watch_p.add_argument("--initial-wait-seconds", type=int, default=90)
    review_watch_p.add_argument("--poll-interval-seconds", type=int, default=60)
    review_watch_p.add_argument("--max-rounds", type=int, default=5)
    review_watch_p.set_defaults(func=cmd_review_watch)

    cost_report_p = sub.add_parser(
        "cost-report",
        help="Turn a hand-filled per-ticket cost JSON file into a cost/ROI report",
    )
    cost_report_p.add_argument(
        "--entries", required=True,
        help="Path to a JSON file: list of {issue_key, fix_cost_usd, review_cost_usd}",
    )
    cost_report_p.add_argument(
        "--baseline-hourly-usd", type=float, default=cost_report_module.DEFAULT_BASELINE_HOURLY_USD,
    )
    cost_report_p.add_argument(
        "--baseline-hours-per-ticket", type=float,
        default=cost_report_module.DEFAULT_BASELINE_HOURS_PER_TICKET,
    )
    cost_report_p.add_argument("--out", default=None, help="Optional path to also write the report")
    cost_report_p.set_defaults(func=cmd_cost_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
