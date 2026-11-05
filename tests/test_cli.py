from pathlib import Path

from orchestrator.cli import main

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
