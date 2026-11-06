"""Closes the review loop with CodeRabbit on GitLab: finds unresolved
discussion threads CodeRabbit left on every open pipeline-created MR, so
the CLI's `review-loop` command (see cli.py) can route each one through
review_loop.route(), have the Fixer either patch the code or write a
defense, then reply and resolve.

This is deliberately poll-based rather than a live webhook — GitLab CI
has no native "run a job when someone comments on an MR" trigger, and a
real-time webhook receiver would need its own always-on host outside
this pipeline's existing all-GitLab-CI architecture. A GitLab CI/CD
Pipeline Schedule (configured once in the GitLab UI, not in this repo)
runs the `review_loop` job on a fixed interval instead — see
docs/gitlab-review-loop-schedule.md. Once a thread is replied to and
resolved, it naturally drops out of "unresolved" on the next poll, so no
separate "already handled" bookkeeping is needed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .aggregation import list_open_fix_mrs
from .models import ReviewComment

_TIMEOUT_SECONDS = 10

# Substring match against a note's author username, case-insensitive.
# Override via env if CodeRabbit's actual GitLab bot username differs
# from the default assumption.
CODERABBIT_USERNAME_HINT = os.environ.get("CODERABBIT_USERNAME_HINT", "coderabbit")


@dataclass(frozen=True)
class OpenThread:
    mr_iid: int
    discussion_id: str
    comment: ReviewComment


def is_coderabbit_author(username: str) -> bool:
    return CODERABBIT_USERNAME_HINT.lower() in (username or "").lower()


def _get_json(url: str, headers: dict[str, str]):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None


def _call(url: str, headers: dict[str, str], data: dict | None, method: str) -> int | None:
    body = json.dumps(data).encode("utf-8") if data is not None else b""
    req = urllib.request.Request(
        url, data=body, headers={**headers, "Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def list_unresolved_coderabbit_threads(
    api_base: str, project_path: str, token: str, mr_iid: int
) -> list[OpenThread]:
    """Unresolved discussion threads on one MR whose latest note is from
    CodeRabbit — a thread we've already replied to (and resolved) drops
    out on its own, so this needs no separate "already handled" state."""
    encoded = urllib.parse.quote(project_path, safe="")
    url = f"{api_base}/projects/{encoded}/merge_requests/{mr_iid}/discussions?per_page=100"
    data = _get_json(url, {"PRIVATE-TOKEN": token})
    if not isinstance(data, list):
        return []

    threads: list[OpenThread] = []
    for discussion in data:
        notes = discussion.get("notes") or []
        if not notes:
            continue
        last = notes[-1]
        if last.get("resolvable") is False or last.get("resolved"):
            continue
        author = (last.get("author") or {}).get("username", "")
        if not is_coderabbit_author(author):
            continue
        position = last.get("position") or {}
        threads.append(OpenThread(
            mr_iid=mr_iid,
            discussion_id=discussion["id"],
            comment=ReviewComment(
                body=last.get("body", "") or "",
                file_path=position.get("new_path"),
                line=position.get("new_line"),
                author=author or "coderabbitai",
            ),
        ))
    return threads


def list_all_unresolved_threads(
    api_base: str, project_path: str, token: str
) -> list[OpenThread]:
    """Across every currently-open pipeline-created MR."""
    open_mrs = list_open_fix_mrs(api_base, project_path, token)
    threads: list[OpenThread] = []
    for mr in open_mrs:
        threads.extend(
            list_unresolved_coderabbit_threads(api_base, project_path, token, mr.iid)
        )
    return threads


def reply_and_resolve(
    api_base: str,
    project_path: str,
    token: str,
    mr_iid: int,
    discussion_id: str,
    body: str,
) -> bool:
    """Posts `body` as a reply on the thread, then marks it resolved.
    True only if both calls succeeded — on partial failure the thread is
    deliberately left unresolved so the next poll retries rather than
    silently dropping it."""
    encoded = urllib.parse.quote(project_path, safe="")
    base = f"{api_base}/projects/{encoded}/merge_requests/{mr_iid}/discussions/{discussion_id}"
    headers = {"PRIVATE-TOKEN": token}

    status = _call(f"{base}/notes", headers, {"body": body}, "POST")
    if status is None or status >= 300:
        return False

    status = _call(f"{base}?resolved=true", headers, None, "PUT")
    return status is not None and status < 300


def trigger_review(api_base: str, project_path: str, token: str, mr_iid: int) -> bool:
    """Posts CodeRabbit's `@coderabbitai review` slash-command as a plain
    MR-level note, forcing a fresh review deterministically rather than
    relying on "Incremental review" auto-firing on its own timing after a
    push — review-watch calls this right after pushing a fix, so the next
    poll round has something real to find instead of hoping CodeRabbit
    noticed the new commit within the wait window."""
    encoded = urllib.parse.quote(project_path, safe="")
    url = f"{api_base}/projects/{encoded}/merge_requests/{mr_iid}/notes"
    status = _call(url, {"PRIVATE-TOKEN": token}, {"body": "@coderabbitai review"}, "POST")
    return status is not None and status < 300
