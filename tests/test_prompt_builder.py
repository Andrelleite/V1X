import json
from pathlib import Path

from orchestrator.models import Decision, ReviewComment, VulnTicket
from orchestrator.prompt_builder import build_fix_instruction, build_review_instruction

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


def test_build_fix_instruction_ssrf_points_to_ssrf_sheet():
    ticket = VulnTicket.from_jira_payload(_load("jira_ssrf.json"))
    instruction = build_fix_instruction(ticket)

    assert "ssrf.md" in instruction


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
