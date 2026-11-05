import json
from pathlib import Path

from orchestrator.models import ReviewComment
from orchestrator.review_loop import candidate_patterns, route

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fix_comment_routes_to_fix():
    payload = _load("coderabbit_fix_comment.json")
    comment = ReviewComment(body=payload["body"], file_path=payload["file_path"])
    decision = route(comment)
    assert decision.path == "fix"
    assert not decision.candidate_fp_patterns


def test_false_positive_comment_without_evidence_defaults_to_fix():
    payload = _load("coderabbit_false_positive_comment.json")
    comment = ReviewComment(body=payload["body"], file_path=payload["file_path"])
    decision = route(comment)  # no evidence passed, and body alone names no pattern
    assert decision.path == "fix"
    assert decision.candidate_fp_patterns == ()


def test_false_positive_comment_with_evidence_routes_to_defend():
    payload = _load("coderabbit_false_positive_comment.json")
    comment = ReviewComment(body=payload["body"], file_path=payload["file_path"])
    decision = route(comment, evidence=payload["evidence"])
    assert decision.path == "defend"
    assert decision.requires_evidence


def test_candidate_patterns_detects_not_attacker_reachable():
    patterns = candidate_patterns("this value is hardcoded and not reachable by users")
    assert "not_attacker_reachable" in patterns


def test_candidate_patterns_empty_for_unrelated_text():
    assert candidate_patterns("please rename this variable") == ()
