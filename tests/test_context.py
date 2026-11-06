import json
from contextlib import contextmanager
from unittest.mock import patch

from orchestrator.context import (
    ContextItem,
    gather_all,
    render_context_block,
    search_confluence,
    search_gitlab_commits,
    search_jira,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _mock_urlopen(payload):
    with patch("orchestrator.context.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        yield


def test_search_jira_parses_issues():
    payload = {
        "issues": [
            {"key": "VD-3", "fields": {"summary": "Old SQLi fix", "description": "details here"}},
        ]
    }
    with _mock_urlopen(payload):
        items = search_jira("https://x.atlassian.net", "a@b.com", "tok", "Injection", "VD-9")
    assert len(items) == 1
    assert items[0].source == "jira"
    assert "VD-3" in items[0].title
    assert items[0].url == "https://x.atlassian.net/browse/VD-3"


def test_search_jira_returns_empty_on_bad_response():
    with patch("orchestrator.context.urllib.request.urlopen", side_effect=OSError("boom")):
        items = search_jira("https://x.atlassian.net", "a@b.com", "tok", "Injection", "VD-9")
    assert items == []


def test_search_confluence_parses_results():
    payload = {"results": [{"title": "SQLi Runbook", "_links": {"webui": "/spaces/SEC/pages/1"}}]}
    with _mock_urlopen(payload):
        items = search_confluence("https://x.atlassian.net", "a@b.com", "tok", "Injection")
    assert items[0].title == "SQLi Runbook"
    assert items[0].url == "https://x.atlassian.net/wiki/spaces/SEC/pages/1"


def test_search_gitlab_commits_parses_list_response():
    payload = [{"message": "fix: parameterize auth query\n\nSee VD-1"}]
    with _mock_urlopen(payload):
        items = search_gitlab_commits(
            "https://gitlab.com/api/v4", "mumbo-jumbo/juice-shop-revamped", "tok", "Injection"
        )
    assert items[0].title == "fix: parameterize auth query"
    assert "VD-1" in items[0].excerpt


def test_render_context_block_empty():
    block = render_context_block([], ("jira", "confluence"))
    assert "No related context found" in block
    assert "jira" in block and "confluence" in block


def test_render_context_block_with_items():
    items = [ContextItem(source="jira", title="VD-3: old fix", url="http://x/VD-3", excerpt="did X")]
    block = render_context_block(items, ("jira",))
    assert "[jira] VD-3: old fix" in block
    assert "did X" in block


def test_gather_all_skips_sources_with_no_credentials():
    # No jira/gitlab creds passed -> no network calls attempted at all,
    # and the rendered block says nothing was searched.
    block = gather_all(
        keyword="Injection",
        exclude_key="VD-9",
        jira_site_url="https://x.atlassian.net",
        jira_email="",
        jira_token="",
        gitlab_api_base="https://gitlab.com/api/v4",
        gitlab_project_path="",
        gitlab_token="",
    )
    assert "searched: " in block
    assert "No related context found" in block
