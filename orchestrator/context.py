"""Gathers related context from other company systems (Jira, Confluence,
the target repo's own GitLab history) before the Fixer patches anything,
so it isn't working from the Jira ticket's text in isolation. Extensible
to more sources later (Slack, Sourcegraph, etc.) — not wired in yet since
there are no credentials for those.

Every source is best-effort and independent: a failure, timeout, or empty
result from one never blocks the others or the pipeline. This trades a
small amount of extra context for a real token-cost increase on every
run (more input tokens per fix) — kept deliberately bounded (a handful of
items, short excerpts) rather than open-ended, per the project's own
token-discipline rule (security/knowledge/README.md).
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

MAX_ITEMS_PER_SOURCE = 5
MAX_EXCERPT_CHARS = 300
MIN_RELEVANCE_SCORE = 2  # shared significant words required to keep a result
_TIMEOUT_SECONDS = 10

_CWE_RE = re.compile(r"CWE-\d+", re.IGNORECASE)
_FILE_PATH_RE = re.compile(
    r"\b[\w./-]+\.(?:ts|tsx|js|jsx|py|go|java|rb|php|c|cpp|h|cs|rs|kt|swift)\b"
)
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "of", "for",
    "is", "this", "that", "with", "from", "via", "not", "be", "as", "by",
    "it", "its", "was", "were", "are", "can", "could", "would", "will",
})


@dataclass(frozen=True)
class ContextItem:
    source: str  # "jira" | "confluence" | "gitlab"
    title: str
    url: str = ""
    excerpt: str = ""


def extract_search_terms(ticket_text: str, fallback: str) -> list[str]:
    """Most-specific-first search terms for finding genuinely similar past
    tickets/commits. A CWE id or an exact file path is a much stronger
    "same problem" signal than a broad OWASP category name alone — two
    injection tickets in unrelated files aren't really a similar problem,
    but two tickets both citing CWE-89, or both touching the same file,
    almost certainly are. Callers try these in order and stop at the
    first one that returns any result."""
    terms: list[str] = []
    cwe = _CWE_RE.search(ticket_text)
    if cwe:
        terms.append(cwe.group(0).upper())
    path = _FILE_PATH_RE.search(ticket_text)
    if path:
        terms.append(path.group(0))
    if fallback and fallback not in terms:
        terms.append(fallback)
    return terms


def significant_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-zA-Z0-9_]{3,}", text.lower())
        if w not in _STOPWORDS
    }


def _relevance_score(ticket_text: str, item: ContextItem) -> int:
    """Shared significant words between the current ticket and a
    candidate result — used to drop results that only matched a fallback
    search term in passing, not because they're actually a similar
    problem (e.g. two unrelated tickets that both happen to say
    "Injection" somewhere)."""
    candidate_text = f"{item.title} {item.excerpt}"
    return len(significant_words(ticket_text) & significant_words(candidate_text))


def _get_json(url: str, headers: dict[str, str]) -> dict | list | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None


def _basic_auth_header(email: str, token: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}


def search_jira(
    site_url: str, email: str, token: str, keyword: str, exclude_key: str,
    max_results: int = MAX_ITEMS_PER_SOURCE,
) -> list[ContextItem]:
    """Past tickets already marked sec-ai-fix-done that mention the same
    vulnerability category — "how did we fix something like this before."
    """
    jql = (
        f'labels = "sec-ai-fix-done" AND key != "{exclude_key}" '
        f'AND text ~ "{keyword}" ORDER BY created DESC'
    )
    url = (
        f"{site_url}/rest/api/2/search?jql={urllib.parse.quote(jql)}"
        f"&maxResults={max_results}&fields=summary,description"
    )
    data = _get_json(url, _basic_auth_header(email, token))
    if not isinstance(data, dict):
        return []

    items = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {}) or {}
        key = issue.get("key", "?")
        items.append(ContextItem(
            source="jira",
            title=f"{key}: {fields.get('summary', '')}",
            url=f"{site_url}/browse/{key}",
            excerpt=(fields.get("description") or "")[:MAX_EXCERPT_CHARS],
        ))
    return items


def search_confluence(
    site_url: str, email: str, token: str, keyword: str,
    max_results: int = MAX_ITEMS_PER_SOURCE,
) -> list[ContextItem]:
    """Confluence pages (runbooks, postmortems, architecture docs) that
    mention the same vulnerability category. Returns [] cleanly if
    Confluence isn't actually provisioned on this Atlassian site."""
    cql = f'type = page AND text ~ "{keyword}"'
    url = f"{site_url}/wiki/rest/api/content/search?cql={urllib.parse.quote(cql)}&limit={max_results}"
    data = _get_json(url, _basic_auth_header(email, token))
    if not isinstance(data, dict):
        return []

    items = []
    for page in data.get("results", []):
        webui = ((page.get("_links") or {}).get("webui")) or ""
        items.append(ContextItem(
            source="confluence",
            title=page.get("title", "(untitled)"),
            url=f"{site_url}/wiki{webui}" if webui else "",
        ))
    return items


def search_gitlab_commits(
    api_base: str, project_path: str, token: str, keyword: str,
    max_results: int = MAX_ITEMS_PER_SOURCE,
) -> list[ContextItem]:
    """Past commits in the TARGET repo's own history mentioning the same
    vulnerability category — "has this exact codebase been patched for
    something like this before." Scoped to the one project, not the whole
    GitLab instance, since that's all TARGET_REPO_TOKEN is expected to need."""
    encoded_path = urllib.parse.quote(project_path, safe="")
    url = (
        f"{api_base}/projects/{encoded_path}/search?scope=commits"
        f"&search={urllib.parse.quote(keyword)}&per_page={max_results}"
    )
    data = _get_json(url, {"PRIVATE-TOKEN": token})
    if not isinstance(data, list):
        return []

    items = []
    for commit in data:
        message = commit.get("message", "") or commit.get("title", "")
        items.append(ContextItem(
            source="gitlab",
            title=message.splitlines()[0][:120] if message else "(no message)",
            excerpt=message[:MAX_EXCERPT_CHARS],
        ))
    return items


def gather_all(
    ticket_text: str,
    fallback_keyword: str,
    exclude_key: str,
    jira_site_url: str,
    jira_email: str,
    jira_token: str,
    gitlab_api_base: str,
    gitlab_project_path: str,
    gitlab_token: str,
) -> str:
    """Queries every available source and returns the rendered block to
    drop straight into the Fixer's instruction. Any credential passed as
    an empty string skips that source entirely (so this works the same
    whether called locally with nothing configured, or in CI with all
    three wired up) rather than making a doomed request.

    For each source, search terms are tried most-specific-first (CWE id,
    then the ticket's own file path, then the broad OWASP category name
    as a last resort — see extract_search_terms), stopping at the first
    term that returns anything. Results are then relevance-scored against
    the ticket's own text: anything with a real excerpt to score (Jira
    descriptions, GitLab commit messages) that doesn't share enough
    vocabulary with the ticket is dropped, so a coincidental fallback-term
    match doesn't masquerade as a genuinely similar problem. Confluence
    results (title only, no body fetched) aren't scored — there's not
    enough text to judge, so they pass through on the search match alone.
    """
    terms = extract_search_terms(ticket_text, fallback_keyword)
    sources_tried: list[str] = []
    items: list[ContextItem] = []

    def _first_nonempty(search_one_term) -> list[ContextItem]:
        for term in terms:
            result = search_one_term(term)
            if result:
                return result
        return []

    if jira_email and jira_token:
        sources_tried.append("jira")
        items += _first_nonempty(
            lambda term: search_jira(jira_site_url, jira_email, jira_token, term, exclude_key)
        )
    if jira_email and jira_token:  # Confluence Cloud reuses the same Atlassian creds
        sources_tried.append("confluence")
        items += _first_nonempty(
            lambda term: search_confluence(jira_site_url, jira_email, jira_token, term)
        )
    if gitlab_token and gitlab_project_path:
        sources_tried.append("gitlab")
        items += _first_nonempty(
            lambda term: search_gitlab_commits(
                gitlab_api_base, gitlab_project_path, gitlab_token, term
            )
        )

    scored = [(item, _relevance_score(ticket_text, item)) for item in items]
    relevant = [
        item for item, score in scored
        if not item.excerpt or score >= MIN_RELEVANCE_SCORE
    ]
    relevant.sort(key=lambda item: _relevance_score(ticket_text, item), reverse=True)

    return render_context_block(relevant, tuple(sources_tried))


def render_context_block(items: list[ContextItem], sources_tried: tuple[str, ...]) -> str:
    """`sources_tried` names every source actually queried (even ones that
    returned nothing), so the agent — and a human reading the MR — knows
    this is partial context from specific systems, not a claim of
    completeness."""
    header = f"(searched: {', '.join(sources_tried)})"
    if not items:
        return f"No related context found. {header}"

    lines = [header, ""]
    for item in items:
        line = f"- [{item.source}] {item.title}"
        if item.url:
            line += f" ({item.url})"
        lines.append(line)
        if item.excerpt:
            lines.append(f"  {item.excerpt.strip()}")
    return "\n".join(lines)
