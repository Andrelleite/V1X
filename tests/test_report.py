from orchestrator.models import VulnTicket
from orchestrator.report import parse_fix_report, render_mr_description

TICKET = VulnTicket(
    key="VD-14",
    summary="SQL Injection in login",
    description="...",
    repo="mumbo-jumbo/juice-shop-revamped",
    priority="Highest",
)

SAMPLE_OUTPUT = """
Some agent chatter before the report.

===FIX_REPORT===
CONFIDENCE: 85
BLAST_RADIUS: MEDIUM
AFFECTED_FILES: routes/login.ts, test/api/loginApiSpec.ts
SUMMARY: Parameterized the login query in routes/login.ts:34 using named
replacements instead of raw string interpolation.
BLAST_RADIUS_DETAILS: Only called by the /rest/user/login handler.
Legitimate logins are unaffected; several SQLi-based challenge tests now
intentionally fail since they tested the vulnerability itself.
TESTS: Updated 5 tests in loginApiSpec.ts; did not run the suite (no
node_modules in this checkout).
===ARCHITECTURE_DIAGRAM===
flowchart TD
  A["routes/login.ts"] -->|parameterized query| B[(Users table)]
  C["test/api/loginApiSpec.ts"] -.verifies.-> A
===END_ARCHITECTURE_DIAGRAM===
===END_FIX_REPORT===

Trailing chatter after the report.
"""


def test_parse_fix_report_extracts_all_fields():
    report = parse_fix_report(SAMPLE_OUTPUT)
    assert report.found
    assert report.confidence == 85
    assert report.blast_radius == "MEDIUM"
    assert report.affected_files == "routes/login.ts, test/api/loginApiSpec.ts"
    assert "Parameterized the login query" in report.summary
    assert "SQLi-based challenge tests" in report.blast_radius_details
    assert "did not run the suite" in report.tests
    assert "flowchart TD" in report.architecture_diagram
    assert "Users table" in report.architecture_diagram


def test_parse_fix_report_missing_block_returns_not_found():
    report = parse_fix_report("No report here, just an error message.")
    assert not report.found
    assert report.confidence is None
    assert report.blast_radius is None


def test_parse_fix_report_clamps_confidence_to_0_100():
    text = "===FIX_REPORT===\nCONFIDENCE: 150\nBLAST_RADIUS: LOW\n===END_FIX_REPORT==="
    report = parse_fix_report(text)
    assert report.confidence == 100


def test_parse_fix_report_rejects_invalid_blast_radius():
    text = "===FIX_REPORT===\nCONFIDENCE: 50\nBLAST_RADIUS: WHO_KNOWS\n===END_FIX_REPORT==="
    report = parse_fix_report(text)
    assert report.blast_radius is None


def test_render_mr_description_includes_meter_badge_and_diagram():
    report = parse_fix_report(SAMPLE_OUTPUT)
    description = render_mr_description(
        TICKET,
        "A03 (Injection)",
        report,
        backend="claude",
        issue_url="https://vixai.atlassian.net/browse/VD-14",
    )
    assert "VD-14" in description
    assert "85%" in description
    assert "🟡 Medium" in description
    assert "claude" in description
    assert "🔴 Highest" in description  # ticket.priority severity badge
    assert "A03 (Injection)" in description
    assert "```mermaid" in description
    assert "flowchart TD" in description


def test_render_mr_description_falls_back_cleanly_when_not_found():
    report = parse_fix_report("nothing useful here")
    ticket = VulnTicket(key="VD-99", summary="x", description="y", priority="Medium")
    description = render_mr_description(
        ticket, "unclassified", report, issue_url="https://vixai.atlassian.net/browse/VD-99"
    )
    assert "No structured fix report" in description
    assert "VD-99" in description


def test_render_mr_description_uses_fallback_diagram_when_agent_omits_one():
    text = (
        "===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n"
        "AFFECTED_FILES: routes/search.ts\nSUMMARY: fixed it\n"
        "BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n"
        "===END_FIX_REPORT==="
    )
    report = parse_fix_report(text)
    description = render_mr_description(TICKET, "A03 (Injection)", report)
    assert "```mermaid" in description
    assert "routes/search.ts" in description
