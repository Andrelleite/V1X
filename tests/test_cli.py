import os
from pathlib import Path
from unittest.mock import patch

from orchestrator.cli import main
from orchestrator.gitlab_review import OpenThread
from orchestrator.models import ReviewComment
from orchestrator.review_loop import ReviewResponse

FIXTURES = Path(__file__).parent / "fixtures"


def test_fix_dry_run_prints_command_and_does_not_require_claude_binary(capsys):
    rc = main(["fix", "--payload", str(FIXTURES / "jira_sqli.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SEC-101" in out
    assert "dry run" in out


def test_review_dry_run_reports_decision(capsys):
    rc = main(["review", "--payload", str(FIXTURES / "coderabbit_fix_comment.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "decision.path=fix" in out


def test_review_dry_run_with_evidence_reports_defend(capsys):
    rc = main(
        ["review", "--payload", str(FIXTURES / "coderabbit_false_positive_comment.json")]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "decision.path=defend" in out


def test_fix_execute_prints_every_attempted_backend_not_just_the_last(capsys, tmp_path):
    gemini_result = type("R", (), {
        "stdout": "", "stderr": "Not logged in", "returncode": 1,
    })()
    claude_result = type("R", (), {
        "stdout": "no structured report here", "stderr": "", "returncode": 0,
    })()
    gemini_runner = type("Runner", (), {"name": "gemini"})()
    claude_runner = type("Runner", (), {"name": "claude"})()
    attempts = [(gemini_runner, gemini_result), (claude_runner, claude_result)]
    out_path = tmp_path / "mr_description.md"

    with patch("orchestrator.cli._gather_context", return_value="(not gathered)"), \
         patch("orchestrator.cli.run_fix", return_value=(claude_runner, claude_result, attempts)):
        rc = main([
            "fix", "--payload", str(FIXTURES / "jira_sqli.json"),
            "--execute", "--mr-description-out", str(out_path),
        ])

    out = capsys.readouterr().out
    assert rc == 0
    assert "gemini failed (exit 1), falling back" in out
    assert "gemini stderr: Not logged in" in out
    assert "ran with backend=claude (exit 0)" in out


def test_review_loop_without_token_is_a_noop(capsys, monkeypatch):
    monkeypatch.delenv("TARGET_REPO_TOKEN", raising=False)
    rc = main(["review-loop", "--repo", "group/repo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing to do" in out


def test_review_loop_dry_run_lists_threads_without_acting(capsys, monkeypatch):
    monkeypatch.setenv("TARGET_REPO_TOKEN", "tok")
    thread = OpenThread(
        mr_iid=9, discussion_id="disc-1",
        comment=ReviewComment(body="please validate this input"),
    )
    with patch("orchestrator.cli.gitlab_review_module.list_all_unresolved_threads", return_value=[thread]):
        rc = main(["review-loop", "--repo", "group/repo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "found 1 unresolved" in out
    assert "(dry run) would handle MR !9" in out


def test_review_loop_execute_fixes_pushes_and_resolves(capsys, monkeypatch):
    monkeypatch.setenv("TARGET_REPO_TOKEN", "tok")
    thread = OpenThread(
        mr_iid=9, discussion_id="disc-1",
        comment=ReviewComment(body="please validate this input"),
    )
    fake_result = type("R", (), {"stdout": (
        "===REVIEW_RESPONSE===\nPATH: FIXED\nMESSAGE: Added validation.\n"
        "===END_REVIEW_RESPONSE==="
    ), "stderr": "", "returncode": 0})()
    fake_runner = type("Runner", (), {"name": "claude"})()

    with patch("orchestrator.cli.gitlab_review_module.list_all_unresolved_threads", return_value=[thread]), \
         patch("orchestrator.cli._checkout_mr_branch", return_value="fix/ai-VD-9-1"), \
         patch("orchestrator.cli.run_review", return_value=(fake_runner, fake_result, [(fake_runner, fake_result)])), \
         patch("orchestrator.cli._push_current_branch", return_value=True) as push_mock, \
         patch("orchestrator.cli.gitlab_review_module.reply_and_resolve", return_value=True) as reply_mock:
        rc = main(["review-loop", "--repo", "group/repo", "--execute"])

    assert rc == 0
    push_mock.assert_called_once_with("target", "group/repo", "tok", "fix/ai-VD-9-1")
    reply_mock.assert_called_once()
    assert reply_mock.call_args.args[-1] == "FIXED: Added validation."


def test_review_loop_execute_defense_skips_push(capsys, monkeypatch):
    monkeypatch.setenv("TARGET_REPO_TOKEN", "tok")
    thread = OpenThread(
        mr_iid=9, discussion_id="disc-1",
        comment=ReviewComment(body="hardcoded, not reachable by users"),
    )
    fake_result = type("R", (), {"stdout": (
        "===REVIEW_RESPONSE===\nPATH: FALSE_POSITIVE_DEFENSE\n"
        "MESSAGE: config.ts:5 shows this is a build-time constant.\n"
        "===END_REVIEW_RESPONSE==="
    ), "stderr": "", "returncode": 0})()
    fake_runner = type("Runner", (), {"name": "claude"})()

    with patch("orchestrator.cli.gitlab_review_module.list_all_unresolved_threads", return_value=[thread]), \
         patch("orchestrator.cli._checkout_mr_branch", return_value="fix/ai-VD-9-1"), \
         patch("orchestrator.cli.run_review", return_value=(fake_runner, fake_result, [(fake_runner, fake_result)])), \
         patch("orchestrator.cli._push_current_branch") as push_mock, \
         patch("orchestrator.cli.gitlab_review_module.reply_and_resolve", return_value=True) as reply_mock:
        rc = main(["review-loop", "--repo", "group/repo", "--execute"])

    assert rc == 0
    push_mock.assert_not_called()
    assert reply_mock.call_args.args[-1] == "FALSE POSITIVE DEFENSE: config.ts:5 shows this is a build-time constant."


def test_review_loop_execute_marks_failure_when_checkout_fails(monkeypatch):
    monkeypatch.setenv("TARGET_REPO_TOKEN", "tok")
    thread = OpenThread(
        mr_iid=9, discussion_id="disc-1",
        comment=ReviewComment(body="please validate this input"),
    )
    with patch("orchestrator.cli.gitlab_review_module.list_all_unresolved_threads", return_value=[thread]), \
         patch("orchestrator.cli._checkout_mr_branch", return_value=None):
        rc = main(["review-loop", "--repo", "group/repo", "--execute"])
    assert rc == 1
