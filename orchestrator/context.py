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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

MAX_ITEMS_PER_SOURCE = 5
MAX_EXCERPT_CHARS = 300
_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ContextItem:
    source: str  # "jira" | "confluence" | "gitlab"
    title: str
    url: str = ""
    excerpt: str = ""


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
    keyword: str,
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
    three wired up) rather than making a doomed request."""
    items: list[ContextItem] = []
    sources_tried: list[str] = []

    if jira_email and jira_token:
        sources_tried.append("jira")
        items += search_jira(jira_site_url, jira_email, jira_token, keyword, exclude_key)
    if jira_email and jira_token:  # Confluence Cloud reuses the same Atlassian creds
        sources_tried.append("confluence")
        items += search_confluence(jira_site_url, jira_email, jira_token, keyword)
    if gitlab_token and gitlab_project_path:
        sources_tried.append("gitlab")
        items += search_gitlab_commits(gitlab_api_base, gitlab_project_path, gitlab_token, keyword)

    return render_context_block(items, tuple(sources_tried))


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
