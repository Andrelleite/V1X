import json
from contextlib import contextmanager
from unittest.mock import patch

from orchestrator.aggregation import (
    OpenFixMR,
    build_merged_description,
    build_merged_title,
    enrich_with_jira_text,
    find_aggregation_target,
    get_jira_ticket_text,
    get_mr,
    list_open_fix_mrs,
    similarity_percent,
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
    with patch(
        "orchestrator.aggregation.urllib.request.urlopen", return_value=_FakeResponse(payload)
    ):
        yield


def test_similarity_percent_identical_text_is_100():
    text = "SQL Injection allows authentication bypass via login query CWE-89"
    assert similarity_percent(text, text) == 100.0


def test_similarity_percent_unrelated_text_is_low():
    score = similarity_percent(
        "SQL Injection in login query CWE-89",
        "Unrelated completely different topic about cats",
    )
    assert score < 20.0


def test_similarity_percent_empty_input_is_zero():
    assert similarity_percent("", "anything") == 0.0
    assert similarity_percent("the a an", "the a an") == 0.0  # all stopwords


def test_list_open_fix_mrs_filters_by_branch_pattern():
    payload = [
        {"iid": 1, "source_branch": "fix/ai-VD-1-42", "title": "[VD-1] AI Automated Fix",
         "description": "desc", "web_url": "http://x/1"},
        {"iid": 2, "source_branch": "some-human-branch", "title": "unrelated",
         "description": "", "web_url": "http://x/2"},
    ]
    with _mock_urlopen(payload):
        mrs = list_open_fix_mrs("https://gitlab.com/api/v4", "group/repo", "tok")
    assert len(mrs) == 1
    assert mrs[0].issue_key == "VD-1"
    assert mrs[0].iid == 1


def test_list_open_fix_mrs_returns_empty_on_bad_response():
    with patch("orchestrator.aggregation.urllib.request.urlopen", side_effect=OSError("boom")):
        mrs = list_open_fix_mrs("https://gitlab.com/api/v4", "group/repo", "tok")
    assert mrs == []


def test_find_aggregation_target_matches_above_threshold():
    # comparison_text is what gets scored -- NOT title/description, which
    # are the MR's rendered-report boilerplate (see enrich_with_jira_text).
    open_mrs = [
        OpenFixMR(
            iid=5, issue_key="VD-5", source_branch="fix/ai-VD-5-1",
            title="[VD-5] AI Automated Fix", description="(rendered report boilerplate)",
            comparison_text="SQL Injection allows authentication bypass via login query CWE-89",
        ),
    ]
    ticket_text = "SQL Injection allows authentication bypass via login query CWE-89"
    match = find_aggregation_target(ticket_text, "VD-9", open_mrs, threshold=90.0)
    assert match is not None
    mr, score = match
    assert mr.iid == 5
    assert score >= 90.0


def test_find_aggregation_target_falls_back_to_title_description_without_comparison_text():
    open_mrs = [
        OpenFixMR(
            iid=5, issue_key="VD-5", source_branch="fix/ai-VD-5-1",
            title="x", description="SQL Injection allows authentication bypass via login query CWE-89",
        ),
    ]
    match = find_aggregation_target(
        "SQL Injection allows authentication bypass via login query CWE-89",
        "VD-9", open_mrs, threshold=50.0,
    )
    assert match is not None


def test_find_aggregation_target_excludes_same_ticket():
    open_mrs = [
        OpenFixMR(iid=9, issue_key="VD-9", source_branch="fix/ai-VD-9-1", title="x", description="x"),
    ]
    match = find_aggregation_target("anything", "VD-9", open_mrs, threshold=1.0)
    assert match is None


def test_find_aggregation_target_no_match_below_threshold():
    open_mrs = [
        OpenFixMR(
            iid=5, issue_key="VD-5", source_branch="fix/ai-VD-5-1", title="[VD-5] Fix",
            description="(boilerplate)",
            comparison_text="Something about SSRF in a webhook handler, totally different code.",
        ),
    ]
    match = find_aggregation_target(
        "SQL Injection allows authentication bypass via login query CWE-89",
        "VD-9", open_mrs, threshold=90.0,
    )
    assert match is None


def test_find_aggregation_target_picks_best_of_multiple_matches():
    ticket_text = "SQL Injection allows authentication bypass via login query CWE-89"
    open_mrs = [
        OpenFixMR(iid=1, issue_key="VD-1", source_branch="fix/ai-VD-1-1", title="x",
                  description="(boilerplate)", comparison_text="SQL Injection login query CWE-89"),
        OpenFixMR(iid=2, issue_key="VD-2", source_branch="fix/ai-VD-2-1", title="x",
                  description="(boilerplate)",
                  comparison_text="SQL Injection allows authentication bypass via login query CWE-89 exact"),
    ]
    match = find_aggregation_target(ticket_text, "VD-9", open_mrs, threshold=10.0)
    assert match is not None
    assert match[0].iid == 2  # the closer match


def test_get_jira_ticket_text_concatenates_summary_and_description():
    payload = {"fields": {"summary": "SQLi in login", "description": "CWE-89 details here"}}
    with _mock_urlopen(payload):
        text = get_jira_ticket_text("https://x.atlassian.net", "a@b.com", "tok", "VD-5")
    assert "SQLi in login" in text
    assert "CWE-89 details here" in text


def test_get_jira_ticket_text_returns_empty_on_failure():
    with patch("orchestrator.aggregation.urllib.request.urlopen", side_effect=OSError("boom")):
        text = get_jira_ticket_text("https://x.atlassian.net", "a@b.com", "tok", "VD-5")
    assert text == ""


def test_enrich_with_jira_text_populates_comparison_text():
    mr = OpenFixMR(iid=5, issue_key="VD-5", source_branch="fix/ai-VD-5-1",
                    title="[VD-5] AI Automated Fix", description="(boilerplate)")
    payload = {"fields": {"summary": "SQLi in login", "description": "CWE-89 details"}}
    with _mock_urlopen(payload):
        enriched = enrich_with_jira_text(
            [mr], "https://x.atlassian.net", "a@b.com", "tok"
        )
    assert "SQLi in login" in enriched[0].comparison_text
    assert enriched[0].title == mr.title  # unrelated fields untouched


def test_enrich_with_jira_text_falls_back_when_fetch_fails():
    mr = OpenFixMR(iid=5, issue_key="VD-5", source_branch="fix/ai-VD-5-1",
                    title="[VD-5] AI Automated Fix", description="fallback description text")
    with patch("orchestrator.aggregation.urllib.request.urlopen", side_effect=OSError("boom")):
        enriched = enrich_with_jira_text(
            [mr], "https://x.atlassian.net", "a@b.com", "tok"
        )
    assert "fallback description text" in enriched[0].comparison_text


def test_get_mr_returns_dict():
    with _mock_urlopen({"iid": 5, "title": "[VD-5] AI Automated Fix", "description": "old"}):
        mr = get_mr("https://gitlab.com/api/v4", "group/repo", "tok", 5)
    assert mr["title"] == "[VD-5] AI Automated Fix"


def test_get_mr_returns_none_on_failure():
    with patch("orchestrator.aggregation.urllib.request.urlopen", side_effect=OSError("boom")):
        mr = get_mr("https://gitlab.com/api/v4", "group/repo", "tok", 5)
    assert mr is None


def test_build_merged_title_adds_new_key():
    assert build_merged_title("[VD-19] AI Automated Fix", "VD-20") == (
        "[VD-19, VD-20] AI Automated Fix"
    )


def test_build_merged_title_does_not_duplicate_existing_key():
    assert build_merged_title("[VD-19, VD-20] AI Automated Fix", "VD-20") == (
        "[VD-19, VD-20] AI Automated Fix"
    )


def test_build_merged_title_handles_title_with_no_brackets():
    assert build_merged_title("AI Automated Fix", "VD-20") == "[VD-20] AI Automated Fix"


def test_build_merged_description_appends_new_section():
    merged = build_merged_description("original report", "new report section", "VD-20", 95.4)
    assert "original report" in merged
    assert "new report section" in merged
    assert "VD-20" in merged
    assert "95%" in merged
