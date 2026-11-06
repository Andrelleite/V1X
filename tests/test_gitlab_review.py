from contextlib import contextmanager
from unittest.mock import patch

from orchestrator.aggregation import OpenFixMR
from orchestrator.gitlab_review import (
    is_coderabbit_author,
    is_coderabbit_note,
    list_all_unresolved_threads,
    list_unresolved_coderabbit_threads,
    reply_and_resolve,
    trigger_review,
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


def test_is_coderabbit_note_matches_by_username():
    assert is_coderabbit_note("coderabbitai", "anything at all")


def test_is_coderabbit_note_matches_by_content_when_posted_as_a_human_account():
    # Real case from a live MR: CodeRabbit connected via personal OAuth
    # posts every finding under the connecting human's own username, so
    # the username check alone misses it -- content markers are what
    # actually identify it.
    body = (
        "\U0001F512 Security & Privacy | \U0001F6E1️ Detected with Advanced Tier | "
        "\U0001F7E0 Major | ⚡ Quick win\n\n"
        "\U0001F9E9 Analysis chain\nSSRF\n\n"
        "\U0001F916 Prompt for AI Agents\nFix the SSRF in profileImageUrlUpload.js"
    )
    assert is_coderabbit_note("Andreloras", body)


def test_is_coderabbit_note_false_for_genuine_human_reply():
    assert not is_coderabbit_note("Andreloras", "Looks good, thanks for the quick fix!")
    assert not is_coderabbit_note("", "")


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


def test_list_unresolved_coderabbit_threads_catches_findings_posted_as_the_connecting_human():
    discussions = [
        _discussion(
            1, "Andreloras",
            "SSRF\n\n\U0001F916 Prompt for AI Agents\nBlock private IP ranges.",
            resolved=False,
        ),
        _discussion(2, "Andreloras", "A genuine human reply, not CodeRabbit.", resolved=False),
    ]
    with _mock_get_json(discussions):
        threads = list_unresolved_coderabbit_threads(
            "https://gitlab.com/api/v4", "group/repo", "tok", mr_iid=10
        )
    assert len(threads) == 1
    assert threads[0].discussion_id == "disc-1"


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


def test_trigger_review_posts_slash_command_note():
    with patch("orchestrator.gitlab_review._call", return_value=201) as call_mock:
        ok = trigger_review("https://gitlab.com/api/v4", "group/repo", "tok", 9)
    assert ok
    args, kwargs = call_mock.call_args
    assert args[0] == "https://gitlab.com/api/v4/projects/group%2Frepo/merge_requests/9/notes"
    assert args[2] == {"body": "@coderabbitai review"}


def test_trigger_review_false_on_failure():
    with patch("orchestrator.gitlab_review._call", return_value=500):
        ok = trigger_review("https://gitlab.com/api/v4", "group/repo", "tok", 9)
    assert not ok
