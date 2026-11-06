from contextlib import contextmanager
from unittest.mock import patch

from orchestrator.aggregation import OpenFixMR
from orchestrator.gitlab_review import (
    is_coderabbit_author,
    list_all_unresolved_threads,
    list_unresolved_coderabbit_threads,
    reply_and_resolve,
)


def _discussion(note_id, username, body, resolved=False, resolvable=True, position=None):
    return {
        "id": f"disc-{note_id}",
        "notes": [{
            "author": {"username": username},
            "body": body,
            "resolved": resolved,
            "resolvable": resolvable,
            "position": position or {},
        }],
    }


@contextmanager
def _mock_get_json(payload):
    with patch("orchestrator.gitlab_review._get_json", return_value=payload):
        yield


def test_is_coderabbit_author_matches_case_insensitively():
    assert is_coderabbit_author("CodeRabbitAI")
    assert is_coderabbit_author("coderabbit[bot]")
    assert not is_coderabbit_author("Andreloras")
    assert not is_coderabbit_author("")


def test_list_unresolved_coderabbit_threads_filters_resolved_and_non_coderabbit():
    discussions = [
        _discussion(1, "coderabbitai", "Please validate this input.", resolved=False),
        _discussion(2, "coderabbitai", "Already resolved thread.", resolved=True),
        _discussion(3, "Andreloras", "A human's own comment.", resolved=False),
        _discussion(4, "coderabbitai", "Non-resolvable status note.", resolvable=False),
    ]
    with _mock_get_json(discussions):
        threads = list_unresolved_coderabbit_threads(
            "https://gitlab.com/api/v4", "group/repo", "tok", mr_iid=9
        )
    assert len(threads) == 1
    assert threads[0].discussion_id == "disc-1"
    assert threads[0].comment.body == "Please validate this input."
    assert threads[0].mr_iid == 9


def test_list_unresolved_coderabbit_threads_extracts_file_position():
    discussions = [
        _discussion(
            1, "coderabbitai", "SQLi here.",
            position={"new_path": "routes/login.ts", "new_line": 34},
        ),
    ]
    with _mock_get_json(discussions):
        threads = list_unresolved_coderabbit_threads(
            "https://gitlab.com/api/v4", "group/repo", "tok", mr_iid=9
        )
    assert threads[0].comment.file_path == "routes/login.ts"
    assert threads[0].comment.line == 34


def test_list_unresolved_coderabbit_threads_returns_empty_on_bad_response():
    with patch("orchestrator.gitlab_review._get_json", return_value=None):
        threads = list_unresolved_coderabbit_threads(
            "https://gitlab.com/api/v4", "group/repo", "tok", mr_iid=9
        )
    assert threads == []


def test_list_all_unresolved_threads_combines_every_open_mr():
    open_mrs = [
        OpenFixMR(iid=1, issue_key="VD-1", source_branch="fix/ai-VD-1-1", title="x", description="x"),
        OpenFixMR(iid=2, issue_key="VD-2", source_branch="fix/ai-VD-2-1", title="x", description="x"),
    ]
    with patch("orchestrator.gitlab_review.list_open_fix_mrs", return_value=open_mrs):
        with patch(
            "orchestrator.gitlab_review.list_unresolved_coderabbit_threads",
            side_effect=lambda api, repo, tok, mr_iid: [f"thread-for-{mr_iid}"],
        ):
            threads = list_all_unresolved_threads("https://gitlab.com/api/v4", "group/repo", "tok")
    assert threads == ["thread-for-1", "thread-for-2"]


def test_reply_and_resolve_true_when_both_calls_succeed():
    with patch("orchestrator.gitlab_review._call", side_effect=[201, 200]):
        ok = reply_and_resolve(
            "https://gitlab.com/api/v4", "group/repo", "tok", 9, "disc-1", "FIXED: done"
        )
    assert ok


def test_reply_and_resolve_false_when_reply_fails():
    with patch("orchestrator.gitlab_review._call", side_effect=[403, 200]) as mocked:
        ok = reply_and_resolve(
            "https://gitlab.com/api/v4", "group/repo", "tok", 9, "disc-1", "FIXED: done"
        )
    assert not ok
    assert mocked.call_count == 1  # never attempts to resolve after a failed reply


def test_reply_and_resolve_false_when_resolve_fails():
    with patch("orchestrator.gitlab_review._call", side_effect=[201, 500]):
        ok = reply_and_resolve(
            "https://gitlab.com/api/v4", "group/repo", "tok", 9, "disc-1", "FIXED: done"
        )
    assert not ok
