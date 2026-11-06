import json
from pathlib import Path

from orchestrator.models import Decision, ReviewComment, VulnTicket
from orchestrator.prompt_builder import (
    build_fix_instruction,
    build_review_instruction,
    primary_category_keyword,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_build_fix_instruction_includes_ticket_key_and_cheatsheet():
    ticket = VulnTicket.from_jira_payload(_load("jira_sqli.json"))
    instruction = build_fix_instruction(ticket)

    assert "SEC-101" in instruction
    assert "injection.md" in instruction
    assert "===FIX_REPORT===" in instruction
    assert "CONFIDENCE:" in instruction
    assert "EXPLOITABILITY:" in instruction
    assert "EXPLOITABILITY_DETAILS:" in instruction


def test_build_fix_instruction_ssrf_points_to_ssrf_sheet():
    ticket = VulnTicket.from_jira_payload(_load("jira_ssrf.json"))
    instruction = build_fix_instruction(ticket)

    assert "ssrf.md" in instruction


def test_build_fix_instruction_without_context_says_not_gathered():
    ticket = VulnTicket.from_jira_payload(_load("jira_sqli.json"))
    instruction = build_fix_instruction(ticket)

    assert "not gathered for this run" in instruction


def test_build_fix_instruction_includes_provided_related_context():
    ticket = VulnTicket.from_jira_payload(_load("jira_sqli.json"))
    instruction = build_fix_instruction(
        ticket, related_context="- [jira] VD-3: old related SQLi fix"
    )

    assert "VD-3: old related SQLi fix" in instruction


def test_primary_category_keyword_uses_classification():
    ticket = VulnTicket.from_jira_payload(_load("jira_sqli.json"))
    assert primary_category_keyword(ticket.text) == "Injection"


def test_primary_category_keyword_falls_back_to_summary_words():
    assert primary_category_keyword("totally unrelated free text here") == (
        "totally unrelated free text"
    )


def test_build_review_instruction_defend_path_demands_evidence():
    comment = ReviewComment(body="any user could pass an arbitrary id (IDOR)")
    decision = Decision(
        path="defend",
        reason="test",
        candidate_fp_patterns=("not_attacker_reachable",),
    )
    instruction = build_review_instruction(comment, decision)

    assert "FALSE POSITIVE DEFENSE" in instruction
    assert "cite concrete evidence" in instruction


def test_build_review_instruction_fix_path_defaults_safely():
    comment = ReviewComment(body="missing input validation on the amount field")
    decision = Decision(path="fix", reason="no pattern matched")
    instruction = build_review_instruction(comment, decision)

    assert "default to fixing it" in instruction
