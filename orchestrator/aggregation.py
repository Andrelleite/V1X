"""Decides whether a new ticket should be aggregated into an existing
OPEN pipeline-created MR instead of opening a new one, when it's a
near-duplicate of what that MR already fixes — same root cause, not just
a related-but-distinct problem.

The similarity threshold is deliberately high (90% by default) so this
only catches genuine duplicates — e.g. the same finding reported twice
by a scanner — not broadly related tickets that happen to share a
vulnerability class. A lower threshold would start combining genuinely
different fixes into one MR, trading reviewability (one coherent diff)
for a larger blast radius per MR; that's a real tradeoff to make
deliberately via AGGREGATION_SIMILARITY_THRESHOLD, not a side effect of
a loose default.

Only MRs this pipeline itself opened are considered (branch name matches
fix/ai-<ISSUE_KEY>-<pipeline id>) — never a human's own open MR.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace

from .context import significant_words

SIMILARITY_THRESHOLD_PERCENT = float(
    os.environ.get("AGGREGATION_SIMILARITY_THRESHOLD", "90")
)
_TIMEOUT_SECONDS = 10
_BRANCH_RE = re.compile(r"^fix/ai-([A-Za-z][A-Za-z0-9]*-\d+)-\d+$")
_TITLE_KEYS_RE = re.compile(r"^\[([^\]]+)\](.*)$")


@dataclass(frozen=True)
class OpenFixMR:
    iid: int
    issue_key: str
    source_branch: str
    title: str
    description: str
    web_url: str = ""
    # Populated by enrich_with_jira_text before comparison — deliberately
    # NOT the MR's own title/description, which are mostly our own
    # rendered-report boilerplate (headers, table labels, footer
    # disclaimer) shared identically across every MR regardless of actual
    # content. Comparing against that would inflate similarity between
    # any two MRs and risk false-positive aggregation. Falls back to
    # title+description only if the Jira fetch itself fails.
    comparison_text: str = ""


def similarity_percent(text_a: str, text_b: str) -> float:
    """Jaccard similarity (shared significant words / all significant
    words across both) as a 0-100 percentage. 0 if either side has no
    significant words at all, rather than a divide-by-zero."""
    words_a = significant_words(text_a)
    words_b = significant_words(text_b)
    union = words_a | words_b
    if not union:
        return 0.0
    return 100.0 * len(words_a & words_b) / len(union)


def _get_json(url: str, headers: dict[str, str]):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None


def list_open_fix_mrs(api_base: str, project_path: str, token: str) -> list[OpenFixMR]:
    """Every currently-open MR this pipeline itself created, newest first.
    Newest-first is explicit (order_by/sort) rather than relying on
    GitLab's own default, so review_loop/review-watch always handle the
    MR a just-finished ai_fix run opened before working back through
    older ones. Paginated up to a few hundred open MRs — meant as a quick
    pre-check, not an exhaustive audit; a project with more open pipeline
    MRs than that has bigger problems than this function solves."""
    encoded = urllib.parse.quote(project_path, safe="")
    results: list[OpenFixMR] = []
    for page in range(1, 4):
        url = (
            f"{api_base}/projects/{encoded}/merge_requests"
            f"?state=opened&order_by=created_at&sort=desc&per_page=100&page={page}"
        )
        data = _get_json(url, {"PRIVATE-TOKEN": token})
        if not isinstance(data, list) or not data:
            break
        for mr in data:
            branch = mr.get("source_branch", "") or ""
            match = _BRANCH_RE.match(branch)
            if not match:
                continue
            results.append(OpenFixMR(
                iid=mr["iid"],
                issue_key=match.group(1),
                source_branch=branch,
                title=mr.get("title", "") or "",
                description=mr.get("description", "") or "",
                web_url=mr.get("web_url", "") or "",
            ))
        if len(data) < 100:
            break
    return results


def _jira_auth_header(email: str, token: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}


def get_jira_ticket_text(site_url: str, email: str, token: str, issue_key: str) -> str:
    """An issue's own summary+description — used instead of an MR's
    rendered description for similarity comparison (see OpenFixMR's
    comparison_text docstring)."""
    url = f"{site_url}/rest/api/2/issue/{issue_key}?fields=summary,description"
    data = _get_json(url, _jira_auth_header(email, token))
    if not isinstance(data, dict):
        return ""
    fields = data.get("fields", {}) or {}
    return f"{fields.get('summary', '') or ''}\n{fields.get('description', '') or ''}"


def enrich_with_jira_text(
    open_mrs: list[OpenFixMR], jira_site_url: str, jira_email: str, jira_token: str
) -> list[OpenFixMR]:
    """Returns a new list with comparison_text populated from each MR's
    own Jira ticket, falling back to the MR's title+description only if
    that specific fetch fails (e.g. the ticket was deleted) — a weaker
    signal, but better than refusing to compare at all."""
    enriched = []
    for mr in open_mrs:
        text = get_jira_ticket_text(jira_site_url, jira_email, jira_token, mr.issue_key)
        if not text.strip():
            text = f"{mr.title}\n{mr.description}"
        enriched.append(replace(mr, comparison_text=text))
    return enriched


def find_aggregation_target(
    ticket_text: str,
    exclude_issue_key: str,
    open_mrs: list[OpenFixMR],
    threshold: float = SIMILARITY_THRESHOLD_PERCENT,
) -> tuple[OpenFixMR, float] | None:
    """The best-matching open MR (and its score), if any clears the
    threshold — never the ticket's own MR, if it somehow already has one
    (shouldn't happen given idempotency, but cheap to guard anyway).
    Expects open_mrs to already have comparison_text populated (see
    enrich_with_jira_text) — falls back to title+description for any
    that don't, rather than scoring against an empty string."""
    best: tuple[OpenFixMR, float] | None = None
    for mr in open_mrs:
        if mr.issue_key == exclude_issue_key:
            continue
        candidate_text = mr.comparison_text or f"{mr.title}\n{mr.description}"
        score = similarity_percent(ticket_text, candidate_text)
        if score >= threshold and (best is None or score > best[1]):
            best = (mr, score)
    return best


def get_mr(api_base: str, project_path: str, token: str, mr_iid: int) -> dict | None:
    encoded = urllib.parse.quote(project_path, safe="")
    url = f"{api_base}/projects/{encoded}/merge_requests/{mr_iid}"
    data = _get_json(url, {"PRIVATE-TOKEN": token})
    return data if isinstance(data, dict) else None


def build_merged_title(current_title: str, new_issue_key: str) -> str:
    """'[VD-19] AI Automated Fix' + 'VD-20' -> '[VD-19, VD-20] AI Automated Fix'."""
    match = _TITLE_KEYS_RE.match(current_title)
    if not match:
        return f"[{new_issue_key}] {current_title}".strip()
    keys = [k.strip() for k in match.group(1).split(",") if k.strip()]
    if new_issue_key not in keys:
        keys.append(new_issue_key)
    return f"[{', '.join(keys)}]{match.group(2)}"


def build_merged_description(
    current_description: str, new_section: str, new_issue_key: str, similarity: float
) -> str:
    separator = (
        f"\n\n---\n\n## 🔗 Aggregated: also fixes {new_issue_key}\n"
        f"_Matched this MR at {similarity:.0f}% similarity "
        f"(threshold: {SIMILARITY_THRESHOLD_PERCENT:.0f}%) — same root cause, "
        "added as a second commit on this branch rather than a separate MR._\n\n"
    )
    return (current_description or "") + separator + new_section
